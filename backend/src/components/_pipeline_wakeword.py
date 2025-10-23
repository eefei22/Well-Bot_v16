"""
Wakeword Pipeline
"""

import os
import sys
import threading
import time
import logging
import json
from typing import Optional, Callable

# For playing wakeword audio - use pydub as primary, PowerShell as fallback
try:
    from pydub import AudioSegment
    from pydub.playback import play
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logging.warning("pydub not available - will use PowerShell fallback for audio")

try:
    from playsound import playsound
    PLAYSOUND_AVAILABLE = True
except ImportError:
    playsound = None
    PLAYSOUND_AVAILABLE = False
    logging.warning("playsound not available - using alternative audio methods")

# Add the backend directory to the path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Handle imports for both module and direct execution
try:
    from .wakeword import WakeWordDetector, create_wake_word_detector
    from .mic_stream import MicStream
    from .stt import GoogleSTTService
    from .intent_detection import IntentDetection
    from ..config_loader import PORCUPINE_ACCESS_KEY
except ImportError:
    from wakeword import WakeWordDetector, create_wake_word_detector
    from mic_stream import MicStream
    from stt import GoogleSTTService
    from intent_detection import IntentDetection
    from config_loader import PORCUPINE_ACCESS_KEY

logger = logging.getLogger(__name__)


class VoicePipeline:
    """
    Orchestrator that ties together wakeword detection, microphone streaming, and STT.
    Manages the complete voice pipeline flow and state transitions.
    """

    def __init__(
        self,
        wakeword_detector: WakeWordDetector,
        stt_service: GoogleSTTService,
        lang: str = "en-US",
        on_wake_callback: Optional[Callable[[], None]] = None,
        on_final_transcript: Optional[Callable[[str, Optional[dict]], None]] = None,
        intent_config_path: Optional[str] = None,
        preference_file_path: Optional[str] = None,
        stt_timeout_s: float = 8.0  # new: timeout for speech after wakeword
    ):
        self.wakeword = wakeword_detector
        self.stt = stt_service
        self.lang = lang
        self.on_wake_callback = on_wake_callback
        self.on_final_transcript = on_final_transcript

        self.wakeword_audio_path = None
        if preference_file_path:
            try:
                self.wakeword_audio_path = self._load_wakeword_audio_path(preference_file_path)
                logger.info(f"Wakeword audio path loaded: {self.wakeword_audio_path}")
            except Exception as e:
                logger.warning(f"Failed to load wakeword audio path: {e}")
                self.wakeword_audio_path = None

        self.intent_detection = None
        if intent_config_path:
            try:
                self.intent_detection = IntentDetection(intent_config_path)
                logger.info("Intent detection initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize intent detection: {e}")
                self.intent_detection = None

        self.active = False
        self.stt_active = False
        self._lock = threading.Lock()
        self._stt_thread: Optional[threading.Thread] = None

        self.stt_timeout_s = stt_timeout_s  # how many seconds to wait for speech

        logger.info(f"Pipeline initialized | Language: {lang} | Intent: {'Yes' if self.intent_detection else 'No'} | Wakeword Audio: {'Yes' if self.wakeword_audio_path else 'No'}")

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

        # Method 3: Try playsound as last resort (with path normalization)
        if PLAYSOUND_AVAILABLE:
            try:
                logger.debug(f"Playing audio with playsound: {audio_path}")
                # Normalize the path to use consistent separators
                normalized_path = os.path.normpath(audio_path)
                playsound(normalized_path)
                logger.debug("Audio played successfully with playsound")
                return True
            except Exception as e:
                logger.warning(f"playsound playback failed: {e}")

        logger.error(f"All audio playback methods failed for: {audio_path}")
        return False

    def _load_wakeword_audio_path(self, preference_file_path: str) -> Optional[str]:
        try:
            with open(preference_file_path, 'r') as f:
                preferences = json.load(f)
            wakeword_path = preferences.get('wokeword_audio_path')
            if wakeword_path:
                backend_dir = os.path.join(os.path.dirname(__file__), '..', '..')
                absolute_path = os.path.join(backend_dir, wakeword_path)
                if os.path.exists(absolute_path):
                    return absolute_path
                else:
                    logger.warning(f"Wakeword audio file not found: {absolute_path}")
            else:
                logger.warning("No 'wokeword_audio_path' key in preferences")
        except Exception as e:
            logger.error(f"Error loading wakeword preferences: {e}")
        return None

    def _on_wake(self):
        logger.info("Wake word detected")
        with self._lock:
            if self.stt_active:
                logger.warning("STT already active after wakeword – ignoring this wake event")
                return
            self.stt_active = True

        # Play feedback (blocking) if configured
        if self.wakeword_audio_path:
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
            logger.debug("No wakeword feedback audio configured")

        # Callback to orchestrator
        if self.on_wake_callback:
            try:
                self.on_wake_callback()
            except Exception as e:
                logger.error(f"Error in wake callback: {e}")

        # Launch STT thread
        logger.info("Launching STT session")
        self._stt_thread = threading.Thread(target=self._run_stt, daemon=True)
        self._stt_thread.start()

    def _run_stt(self):
        logger.info("STT session started")
        mic = MicStream(
            rate=self.stt.get_sample_rate(),
            chunk_size=int(self.stt.get_sample_rate() / 10)
        )

        final_transcript: Optional[str] = None
        intent_result: Optional[dict] = None
        transcript_received_event = threading.Event()

        def on_transcript_cb(text: str, is_final: bool):
            nonlocal final_transcript
            if not is_final:
                logger.debug(f"[Pipeline] Interim transcript: {text}")
                return
            logger.info(f"[Pipeline] Final transcript: '{text}'")
            final_transcript = text
            transcript_received_event.set()
            try:
                mic.stop()
            except Exception as e:
                logger.error(f"Error stopping mic after final: {e}")

        try:
            mic.start()
            logger.info("Microphone active, awaiting speech")
            # Start recognition with single_utterance = True so stream ends when user stops speaking
            self.stt.stream_recognize(
                audio_generator=mic.generator(),
                on_transcript=on_transcript_cb,
                interim_results=True,
                single_utterance=True
            )

            # Wait for final transcript or timeout
            logger.debug(f"Waiting up to {self.stt_timeout_s:.1f}s for user speech")
            transcript_received = transcript_received_event.wait(timeout=self.stt_timeout_s)
            if not transcript_received:
                logger.warning(f"No user transcript received within {self.stt_timeout_s:.1f}s → timing out STT session")
            else:
                # We got a transcript
                if self.intent_detection and final_transcript:
                    try:
                        intent_result = self.intent_detection.detect_intent(final_transcript)
                        if intent_result:
                            intent_name, matched_phrase = intent_result
                            logger.info(f"Detected intent: {intent_name} (matched phrase: '{matched_phrase}')")
                            intent_result = {"intent": intent_name, "matched_phrase": matched_phrase, "confidence": 1.0}
                        else:
                            logger.info("No intent detected")
                            intent_result = {"intent": "unknown", "confidence": 0.0}
                    except Exception as e:
                        logger.error(f"Intent detection error: {e}")
                        intent_result = {"intent": "unknown", "confidence": 0.0}

                # Invoke callback 
                if self.on_final_transcript:
                    try:
                        self.on_final_transcript(final_transcript, intent_result)
                    except Exception as e:
                        logger.error(f"Error invoking final transcript callback: {e}")
            # Ensure mic is stopped
            mic.stop()

        except Exception as e:
            logger.error(f"Error during STT streaming: {e}")
        finally:
            with self._lock:
                self.stt_active = False
            logger.info("STT session ended, returning to wakeword detection")

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
            self.wakeword.stop()
            with self._lock:
                if self.stt_active:
                    logger.info("Waiting for STT session to complete before fully stopping")
            self.active = False
            logger.info("Voice pipeline stopped")
        except Exception as e:
            logger.error(f"Error when stopping pipeline: {e}")

    def cleanup(self):
        logger.info("Cleaning up pipeline resources")
        try:
            self.stop()
            self.wakeword.cleanup()
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
    on_wake_callback: Optional[Callable[[], None]] = None,
    on_final_transcript: Optional[Callable[[str, Optional[dict]], None]] = None,
    intent_config_path: Optional[str] = None,
    preference_file_path: Optional[str] = None,
    stt_timeout_s: float = 8.0
) -> VoicePipeline:
    wakeword_detector = create_wake_word_detector(PORCUPINE_ACCESS_KEY, custom_keyword_file)
    stt_service = GoogleSTTService(language=language)
    pipeline = VoicePipeline(
        wakeword_detector=wakeword_detector,
        stt_service=stt_service,
        lang=language,
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
