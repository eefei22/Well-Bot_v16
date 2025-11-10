"""
Wakeword Pipeline
"""

import os
import sys
import threading
import time
import logging
import json
from pathlib import Path
from typing import Optional, Callable

# For playing wakeword audio - use pydub as primary, PowerShell as fallback
try:
    from pydub import AudioSegment
    from pydub.playback import play
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logging.warning("pydub not available - will use PowerShell fallback for audio")


# Add the backend directory to the path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Handle imports for both module and direct execution
try:
    from .wakeword import WakeWordDetector, create_wake_word_detector
    from .mic_stream import MicStream
    from .tts import GoogleTTSClient
    from .stt import GoogleSTTService
    from .keyword_intent_matcher import KeywordIntentMatcher
    from ..utils.config_loader import PORCUPINE_ACCESS_KEY
except ImportError:
    from wakeword import WakeWordDetector, create_wake_word_detector
    from mic_stream import MicStream
    from tts import GoogleTTSClient
    from stt import GoogleSTTService
    from keyword_intent_matcher import KeywordIntentMatcher
    from utils.config_loader import PORCUPINE_ACCESS_KEY

logger = logging.getLogger(__name__)


class VoicePipeline:
    """
    Orchestrator that ties together wakeword detection and intent recognition.
    Manages the complete voice pipeline flow and state transitions.
    """

    def __init__(
        self,
        wakeword_detector: WakeWordDetector,
        lang: str = "en-US",
        user_id: Optional[str] = None,
        on_wake_callback: Optional[Callable[[], None]] = None,
        on_final_transcript: Optional[Callable[[str, Optional[dict]], None]] = None,
        intent_config_path: Optional[str] = None,
        preference_file_path: Optional[str] = None,
        stt_timeout_s: float = 8.0  # timeout for intent recognition after wakeword
    ):
        self.wakeword = wakeword_detector
        self.lang = lang
        self.on_wake_callback = on_wake_callback
        self.on_final_transcript = on_final_transcript
        
        # Resolve user ID
        from ..supabase.auth import get_current_user_id
        self.user_id = user_id if user_id is not None else get_current_user_id()
        logger.info(f"VoicePipeline initialized for user: {self.user_id}")
        
        # Load user-specific configurations
        from ..utils.config_resolver import get_global_config_for_user, get_language_config
        self.global_config = get_global_config_for_user(self.user_id)
        self.language_config = get_language_config(self.user_id)

        self.wakeword_audio_path = self.language_config["audio_paths"].get("wokeword_audio_path")
        logger.info(f"Wakeword audio path loaded: {self.wakeword_audio_path}")

        # Initialize TTS service for wakeword responses
        try:
            from google.cloud import texttospeech
            self.tts_service = GoogleTTSClient(
                voice_name=self.global_config["language_codes"]["tts_voice_name"],
                language_code=self.global_config["language_codes"]["tts_language_code"],
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                num_channels=1,
                sample_width_bytes=2
            )
            logger.info("TTS service initialized for wakeword")
        except Exception as e:
            logger.warning(f"Failed to initialize TTS service for wakeword: {e}")
            self.tts_service = None

        # Initialize STT service and keyword intent matcher
        backend_dir = Path(__file__).parent.parent.parent
        
        try:
            # Initialize STT service
            stt_language = self.global_config["language_codes"]["stt_language_code"]
            self.stt_service = GoogleSTTService(language=stt_language, sample_rate=16000)
            logger.info(f"STT service initialized for keyword matching (language: {stt_language})")
            
            # Initialize keyword intent matcher (uses user language preference)
            self.intent_matcher = KeywordIntentMatcher(backend_dir=backend_dir, user_id=self.user_id)
            logger.info(f"Keyword intent matcher initialized for user {self.user_id}")
        except Exception as e:
            logger.error(f"Failed to initialize STT service or keyword matcher: {e}", exc_info=True)
            self.stt_service = None
            self.intent_matcher = None

        self.active = False
        self.stt_active = False
        self._lock = threading.Lock()
        self._stt_thread: Optional[threading.Thread] = None

        self.stt_timeout_s = stt_timeout_s  # how many seconds to wait for speech

        logger.info(f"Pipeline initialized | Language: {lang} | Intent: {'Yes' if self.intent_matcher else 'No'} | Wakeword Audio: {'Yes' if self.wakeword_audio_path else 'No'}")

    def _play_audio_file(self, audio_path: str) -> bool:
        """
        Play an audio file using the best available method.
        Returns True if successful, False otherwise.
        """
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return False

        # Method 1: Try pydub (most reliable)
        if PYDUB_AVAILABLE:
            try:
                logger.debug(f"Playing audio with pydub: {audio_path}")
                audio = AudioSegment.from_wav(audio_path)
                play(audio)
                logger.debug("Audio played successfully with pydub")
                return True
            except Exception as e:
                logger.warning(f"pydub playback failed: {e}, trying fallback")

        # Method 2: Try PowerShell (Windows-specific fallback)
        if sys.platform == "win32":
            try:
                import subprocess
                logger.debug(f"Playing audio with PowerShell: {audio_path}")
                # Use PowerShell's Media.SoundPlayer - more reliable than playsound
                ps_cmd = f'powershell -c "(New-Object Media.SoundPlayer \'{audio_path}\').PlaySync()"'
                result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    logger.debug("Audio played successfully with PowerShell")
                    return True
                else:
                    logger.warning(f"PowerShell playback failed: {result.stderr}")
            except Exception as e:
                logger.warning(f"PowerShell playback error: {e}")

        logger.error(f"All audio playback methods failed for: {audio_path}")
        return False

    def _speak(self, text: str):
        """Speak text using TTS with microphone muting"""
        if not self.tts_service:
            logger.warning("TTS service not available")
            return
        
        # Note: We can't directly mute the mic here because it's in a separate thread
        # The mic will be stopped when the STT session ends, which happens before TTS
        # For wakeword responses, the mic is already stopped by the time we speak
        try:
            def text_gen():
                yield text
            
            # Generate PCM chunks
            pcm_chunks = self.tts_service.stream_synthesize(text_gen())
            
            # Play PCM chunks using PyAudio
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=24000,
                output=True
            )
            
            for chunk in pcm_chunks:
                stream.write(chunk)
            
            stream.stop_stream()
            stream.close()
            pa.terminate()
            
            logger.info(f"TTS played: {text[:50]}...")
        except Exception as e:
            logger.error(f"TTS error: {e}")


    def _on_wake(self):
        logger.info("Wake word detected")
        with self._lock:
            if self.stt_active:
                logger.warning("Intent recognition already active after wakeword – ignoring this wake event")
                return
            self.stt_active = True

        # Load wakeword response config
        wakeword_config = self.language_config.get("wakeword_responses", {})
        use_audio_files = self.global_config["wakeword"].get("use_audio_files", False)
        
        # Play feedback audio if enabled
        if use_audio_files and self.wakeword_audio_path:
            try:
                logger.info(f"Playing wakeword feedback audio: {self.wakeword_audio_path}")
                success = self._play_audio_file(self.wakeword_audio_path)
                if success:
                    logger.info("Wakeword feedback audio played successfully")
                else:
                    logger.error("Failed to play wakeword feedback audio")
            except Exception as e:
                logger.error(f"Error playing wakeword audio: {e}")
        else:
            logger.debug("No wakeword feedback audio configured or audio files disabled")

        # TTS prompt from config
        try:
            prompts = wakeword_config.get("prompts", {})
            wakeword_prompt = prompts.get("wakeword_detected", "Hey, I heard you called me. What can I help you with?")
        except Exception as e:
            logger.warning(f"Failed to load wakeword detected prompt from config: {e}")
            wakeword_prompt = "Hey, I heard you called me. What can I help you with?"
        
        # Callback to orchestrator first (for state management)
        if self.on_wake_callback:
            try:
                self.on_wake_callback()
            except Exception as e:
                logger.error(f"Error in wake callback: {e}")

        # Speak the prompt (this will block until TTS finishes)
        logger.info(f"Speaking wakeword prompt: {wakeword_prompt}")
        self._speak(wakeword_prompt)
        logger.info("Wakeword prompt finished, starting keyword intent recognition")

        # Launch STT-based keyword intent recognition thread AFTER TTS completes
        logger.info("Launching keyword intent recognition session")
        self._stt_thread = threading.Thread(target=self._run_keyword_intent, daemon=True)
        self._stt_thread.start()

    def _run_keyword_intent(self):
        """Process audio with STT and match against keywords for intent recognition."""
        if not self.stt_service or not self.intent_matcher:
            logger.error("STT service or keyword matcher not initialized, cannot process")
            with self._lock:
                self.stt_active = False
            return
        
        logger.info("Keyword intent recognition session started")
        
        # Use standard STT parameters (16kHz)
        mic = MicStream(rate=16000, chunk_size=1600)  # 100ms chunks at 16kHz
        
        intent_result: Optional[dict] = None
        transcript: Optional[str] = None
        start_time = time.time()

        try:
            mic.start()
            logger.info("Microphone active, awaiting speech for keyword matching")
            
            # Capture transcript using STT
            def on_transcript(text: str, is_final: bool):
                nonlocal transcript
                if is_final and text:
                    transcript = text
                    mic.stop()
            
            # Run STT with timeout
            try:
                self.stt_service.stream_recognize(
                    mic.generator(),
                    on_transcript,
                    interim_results=True,
                    single_utterance=True  # Stop after first final result
                )
            except Exception as e:
                logger.error(f"STT error during keyword matching: {e}")
            
            # Check timeout
            if time.time() - start_time > self.stt_timeout_s:
                logger.warning(f"No speech detected within {self.stt_timeout_s:.1f}s → timing out")
            
            # Match transcript against keywords
            if transcript:
                logger.info(f"[Pipeline] Transcript received: '{transcript}'")
                intent_result = self.intent_matcher.match_intent(transcript)
                if intent_result:
                    logger.info(f"[Pipeline] Intent detected: {intent_result.get('intent')}")
                else:
                    logger.info("[Pipeline] No intent matched from transcript")
            
            # If we didn't get an intent, set unknown
            if not intent_result:
                intent_result = {"intent": "unknown", "confidence": 0.0}
                logger.info("[Pipeline] No intent understood, defaulting to unknown")
            
            # Invoke callback with transcript and intent result
            if self.on_final_transcript:
                try:
                    self.on_final_transcript(transcript or "", intent_result)
                except Exception as e:
                    logger.error(f"Error invoking final transcript callback: {e}")
            
        except Exception as e:
            logger.error(f"Error during keyword intent recognition: {e}", exc_info=True)
        finally:
            mic.stop()
            with self._lock:
                self.stt_active = False
            logger.info("Keyword intent recognition session ended, returning to wakeword detection")

    def start(self):
        if self.active:
            logger.warning("Pipeline already active")
            return
        try:
            logger.info("Initializing wakeword detector if necessary")
            if not self.wakeword.is_initialized:
                if not self.wakeword.initialize():
                    raise RuntimeError("Failed to initialize wakeword detector")
            self.wakeword.start(self._on_wake)
            self.active = True
            logger.info("Pipeline active: listening for wake word")
        except Exception as e:
            logger.error(f"Failed to start pipeline: {e}")
            self.active = False
            raise

    def stop(self):
        if not self.active:
            logger.warning("Pipeline not active, cannot stop")
            return
        logger.info("Stopping voice pipeline")
        try:
            # Stop wakeword first
            self.wakeword.stop()
            
            # Wait for STT thread to complete if it's running
            with self._lock:
                if self.stt_active and self._stt_thread and self._stt_thread.is_alive():
                    logger.info("Waiting for intent recognition session to complete before fully stopping")
            
            # Wait for STT thread to finish (with timeout)
            if self._stt_thread and self._stt_thread.is_alive():
                self._stt_thread.join(timeout=2.0)
                if self._stt_thread.is_alive():
                    logger.warning("STT thread did not complete within timeout, continuing anyway")
            
            self.active = False
            logger.info("Voice pipeline stopped")
        except Exception as e:
            logger.error(f"Error when stopping pipeline: {e}")

    def cleanup(self):
        logger.info("Cleaning up pipeline resources")
        try:
            self.stop()
            self.wakeword.cleanup()
            # STT service and keyword matcher don't need explicit cleanup
            logger.info("Pipeline cleanup done")
        except Exception as e:
            logger.error(f"Error during pipeline cleanup: {e}")

    def is_active(self) -> bool:
        return self.active

    def is_stt_active(self) -> bool:
        with self._lock:
            return self.stt_active

    def get_status(self) -> dict:
        return {
            "active": self.active,
            "stt_active": self.stt_active,
            "language": self.lang,
            "wakeword_initialized": self.wakeword.is_initialized,
            "wakeword_running": getattr(self.wakeword, 'running', False)
        }


def create_voice_pipeline(
    access_key_file: str,
    custom_keyword_file: Optional[str] = None,
    language: str = "en-US",
    user_id: Optional[str] = None,
    on_wake_callback: Optional[Callable[[], None]] = None,
    on_final_transcript: Optional[Callable[[str, Optional[dict]], None]] = None,
    intent_config_path: Optional[str] = None,
    preference_file_path: Optional[str] = None,
    stt_timeout_s: float = 8.0
) -> VoicePipeline:
    wakeword_detector = create_wake_word_detector(PORCUPINE_ACCESS_KEY, custom_keyword_file)
    pipeline = VoicePipeline(
        wakeword_detector=wakeword_detector,
        lang=language,
        user_id=user_id,
        on_wake_callback=on_wake_callback,
        on_final_transcript=on_final_transcript,
        intent_config_path=intent_config_path,
        preference_file_path=preference_file_path,
        stt_timeout_s=stt_timeout_s
    )
    logger.info("Voice pipeline created successfully")
    return pipeline


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )

    def dummy_callback(text: str, intent: Optional[dict]):
        print(f"Final transcript: '{text}'  Intent: {intent}")

    current_dir = os.path.dirname(__file__)
    access_key_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'PorcupineAccessKey.txt')
    custom_keyword_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'WellBot_WakeWordModel.ppn')
    intent_config_path = os.path.join(current_dir, '..', '..', 'config', 'intents.json')
    preference_file_path = os.path.join(current_dir, '..', '..', 'config', 'preference.json')

    pipeline = create_voice_pipeline(
        access_key_file=access_key_path,
        custom_keyword_file=custom_keyword_path,
        language="en-US",
        on_wake_callback=lambda: print("Wake detected"),
        on_final_transcript=dummy_callback,
        intent_config_path=intent_config_path,
        preference_file_path=preference_file_path,
        stt_timeout_s=8.0
    )

    pipeline.start()
    print("Voice pipeline started. Say wake word.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pipeline.stop()
        pipeline.cleanup()
        print("Pipeline stopped.")
