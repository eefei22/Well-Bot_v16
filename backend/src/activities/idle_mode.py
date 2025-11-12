"""
Idle Mode Activity

This activity handles wakeword detection and intent recognition when the system is idle.
It continuously listens for wake words, processes user speech, and routes to appropriate activities.
"""

import os
import sys
import threading
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional, Callable, Dict, Any

# For playing wakeword audio - use pydub as primary, PowerShell as fallback
try:
    from pydub import AudioSegment
    from pydub.playback import play
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logging.warning("pydub not available - will use PowerShell fallback for audio")

# Add the backend directory to the path to import modules
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

# Import components (use absolute imports like other activities)
from src.components.wakeword import WakeWordDetector, create_wake_word_detector
from src.components.mic_stream import MicStream
from src.components.tts import GoogleTTSClient
from src.components.stt import GoogleSTTService
from src.components.keyword_intent_matcher import KeywordIntentMatcher
from src.utils.config_loader import PORCUPINE_ACCESS_KEY
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.utils.intervention_record import InterventionRecordManager
from src.supabase.auth import get_current_user_id

logger = logging.getLogger(__name__)


class IdleModeActivity:
    """
    Idle Mode Activity
    
    Handles wakeword detection and intent recognition when the system is idle.
    This is the default activity that runs continuously until a wake word is detected
    and an intent is recognized, at which point it exits to allow main.py to route
    to the appropriate activity.
    """
    
    def __init__(
        self,
        backend_dir: Path,
        user_id: Optional[str] = None,
        on_intent_detected: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ):
        """
        Initialize the Idle Mode Activity
        
        Args:
            backend_dir: Path to the backend directory
            user_id: User ID (optional, will be resolved if not provided)
            on_intent_detected: Callback function called when intent is detected
                                Signature: (transcript: str, intent_result: dict) -> None
        """
        self.backend_dir = backend_dir
        self.user_id = user_id if user_id is not None else get_current_user_id()
        self.on_intent_detected = on_intent_detected
        
        # Components (initialized in initialize())
        self.wakeword_detector: Optional[WakeWordDetector] = None
        self.stt_service: Optional[GoogleSTTService] = None
        self.tts_service: Optional[GoogleTTSClient] = None
        self.intent_matcher: Optional[KeywordIntentMatcher] = None
        
        # Configs (loaded in initialize())
        self.global_config: Optional[dict] = None
        self.language_config: Optional[dict] = None
        self.wakeword_audio_path: Optional[str] = None
        
        # Activity state
        self._active = False
        self._initialized = False
        
        # Wakeword detection state
        self.stt_active = False
        self._lock = threading.Lock()
        self._stt_thread: Optional[threading.Thread] = None
        self._current_mic: Optional[MicStream] = None
        
        # Silence monitoring
        self._silence_timer: Optional[threading.Timer] = None
        self._silence_lock = threading.Lock()
        
        # Intent detection flag (to exit run() after intent detected)
        self._intent_detected = threading.Event()
        self._timeout_occurred = threading.Event()  # Flag for timeout (no intent)
        self._detected_transcript: Optional[str] = None
        self._detected_intent: Optional[Dict[str, Any]] = None
        
        logger.info(f"IdleModeActivity initialized for user {self.user_id}")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            logger.info("Initializing Idle Mode activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            
            # Load user-specific configurations
            logger.info(f"Loading configs for user {self.user_id}")
            self.global_config = get_global_config_for_user(self.user_id)
            self.language_config = get_language_config(self.user_id)
            
            # Get wakeword audio path
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
                logger.info("✓ TTS service initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize TTS service: {e}")
                self.tts_service = None
            
            # Initialize STT service and keyword intent matcher
            try:
                # Initialize STT service
                stt_language = self.global_config["language_codes"]["stt_language_code"]
                self.stt_service = GoogleSTTService(language=stt_language, sample_rate=16000)
                logger.info(f"✓ STT service initialized (language: {stt_language})")
                
                # Initialize keyword intent matcher (uses user language preference)
                self.intent_matcher = KeywordIntentMatcher(backend_dir=self.backend_dir, user_id=self.user_id)
                logger.info(f"✓ Keyword intent matcher initialized")
            except Exception as e:
                logger.error(f"Failed to initialize STT service or keyword matcher: {e}", exc_info=True)
                self.stt_service = None
                self.intent_matcher = None
                return False
            
            # Initialize wakeword detector
            try:
                wakeword_model_path = self.backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel.ppn"
                self.wakeword_detector = create_wake_word_detector(PORCUPINE_ACCESS_KEY, str(wakeword_model_path))
                logger.info("✓ Wakeword detector created")
            except Exception as e:
                logger.error(f"Failed to create wakeword detector: {e}", exc_info=True)
                return False
            
            self._initialized = True
            logger.info("✅ Idle Mode activity initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Idle Mode activity: {e}", exc_info=True)
            return False
    
    def start(self) -> bool:
        """Start the idle mode activity (wakeword detection)"""
        if not self._initialized:
            logger.error("Cannot start: activity not initialized")
            return False
        
        if self._active:
            logger.warning("Idle mode already active")
            return True
        
        try:
            logger.info("Starting wakeword detector...")
            if not self.wakeword_detector.is_initialized:
                if not self.wakeword_detector.initialize():
                    raise RuntimeError("Failed to initialize wakeword detector")
            
            self.wakeword_detector.start(self._on_wake)
            self._active = True
            logger.info("✅ Idle mode active: listening for wake word")
            return True
        except Exception as e:
            logger.error(f"Failed to start idle mode: {e}", exc_info=True)
            self._active = False
            return False
    
    def stop(self):
        """Stop the idle mode activity"""
        if not self._active:
            logger.warning("Idle mode not active, cannot stop")
            return
        
        logger.info("Stopping idle mode activity...")
        
        # Stop silence monitoring
        self._stop_silence_monitoring()
        
        # Stop wakeword detector
        if self.wakeword_detector:
            try:
                self.wakeword_detector.stop()
            except Exception as e:
                logger.warning(f"Error stopping wakeword detector: {e}")
        
        # Stop mic immediately
        with self._lock:
            if self._current_mic and self._current_mic.is_running():
                logger.debug("Stopping mic during idle mode stop")
                self._current_mic.stop()
                self._current_mic = None
        
        # Wait for STT thread to complete if it's running
        if self._stt_thread and self._stt_thread.is_alive():
            logger.info("Waiting for intent recognition session to complete...")
            self._stt_thread.join(timeout=2.0)
            if self._stt_thread.is_alive():
                logger.warning("STT thread did not complete within timeout, continuing anyway")
        
        # Ensure mic is cleared
        with self._lock:
            if self._current_mic:
                try:
                    if self._current_mic.is_running():
                        self._current_mic.stop()
                except:
                    pass
                self._current_mic = None
        
        self._active = False
        logger.info("✅ Idle mode stopped")
    
    def run(self) -> bool:
        """
        Run the idle mode activity
        
        Returns:
            True if intent was detected (activity should exit to allow routing)
            False on error or if activity was stopped
        """
        logger.info("🎬 IdleModeActivity.run() - Starting idle mode execution")
        
        try:
            # Start the activity
            if not self.start():
                logger.error("❌ Failed to start idle mode")
                return False
            
            # Wait for intent to be detected or activity to be stopped
            logger.info("Waiting for wake word detection and intent recognition...")
            
            # Wait for intent detection event or timeout (with timeout check for activity state)
            while self._active and not self._intent_detected.is_set() and not self._timeout_occurred.is_set():
                time.sleep(0.1)  # Small sleep to avoid busy waiting
            
            # Check if intent was detected
            if self._intent_detected.is_set():
                logger.info("✅ Intent detected - exiting idle mode to allow routing")
                # Stop the activity
                self.stop()
                return True
            elif self._timeout_occurred.is_set():
                # Timeout occurred - no intent detected, just clean up and restart
                logger.info("⏰ Timeout occurred - no intent detected, cleaning up to restart idle mode")
                # Stop the activity
                self.stop()
                return False
            else:
                # Activity was stopped externally
                logger.info("Idle mode stopped externally")
                return False
                
        except Exception as e:
            logger.error(f"Error running idle mode activity: {e}", exc_info=True)
            self.stop()
            return False
    
    def cleanup(self):
        """Clean up all resources"""
        logger.info("Cleaning up idle mode resources...")
        try:
            self.stop()
            
            if self.wakeword_detector:
                try:
                    self.wakeword_detector.cleanup()
                except Exception as e:
                    logger.warning(f"Error cleaning up wakeword detector: {e}")
            
            # STT service, TTS service, and keyword matcher don't need explicit cleanup
            logger.info("✅ Idle mode cleanup completed")
        except Exception as e:
            logger.error(f"Error during idle mode cleanup: {e}", exc_info=True)
    
    def reinitialize(self) -> bool:
        """Re-initialize the activity for subsequent runs"""
        logger.info("🔄 Re-initializing Idle Mode activity...")
        
        # Reset state
        self._active = False
        self._initialized = False
        self._intent_detected.clear()
        self._timeout_occurred.clear()
        self._detected_transcript = None
        self._detected_intent = None
        
        # Re-initialize components
        return self.initialize()
    
    def is_active(self) -> bool:
        """Check if the activity is currently active"""
        return self._active and self._initialized
    
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
                logger.debug(f"Playing audio with PowerShell: {audio_path}")
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
        
        # Mute the mic before speaking to prevent TTS feedback
        with self._lock:
            if self._current_mic and self._current_mic.is_running():
                logger.debug("Muting microphone before TTS")
                self._current_mic.mute()
        
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
        finally:
            # Unmute the mic after speaking (if it's still running)
            with self._lock:
                if self._current_mic and self._current_mic.is_running():
                    logger.debug("Unmuting microphone after TTS")
                    self._current_mic.unmute()

    def _on_wake(self):
        """Callback when wake word is detected"""
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
        
        # Speak the prompt (this will block until TTS finishes)
        logger.info(f"Speaking wakeword prompt: {wakeword_prompt}")
        self._speak(wakeword_prompt)
        logger.info("Wakeword prompt finished, starting keyword intent recognition")

        # Start silence monitoring after wake word detection
        self._start_silence_monitoring()

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
        
        # Store mic reference for muting during TTS
        with self._lock:
            self._current_mic = mic
        
        intent_result: Optional[dict] = None
        transcript: Optional[str] = None

        try:
            mic.start()
            logger.info("Microphone active, awaiting speech for keyword matching")
            
            # Capture transcript using STT
            def on_transcript(text: str, is_final: bool):
                nonlocal transcript
                if is_final and text:
                    transcript = text
                    # Stop mic immediately when we get final transcript
                    mic.stop()
                    # Reset silence timer on transcript
                    self._stop_silence_monitoring()
            
            # Run STT - no timeout check here since silence monitoring handles it
            try:
                self.stt_service.stream_recognize(
                    mic.generator(),
                    on_transcript,
                    interim_results=True,
                    single_utterance=True  # Stop after first final result
                )
            except Exception as e:
                logger.error(f"STT error during keyword matching: {e}")
            
            # Ensure mic is stopped
            if mic.is_running():
                logger.debug("Stopping mic before processing transcript")
                mic.stop()
            
            # Only proceed with intent recognition if transcript has at least one word
            if transcript and transcript.strip():
                # Check if transcript has at least one word (not just whitespace)
                words = transcript.strip().split()
                if len(words) > 0:
                    logger.info(f"[IdleMode] Transcript received: '{transcript}'")
                    intent_result = self.intent_matcher.match_intent(transcript)
                    if intent_result:
                        logger.info(f"[IdleMode] Intent detected: {intent_result.get('intent')}")
                    else:
                        logger.info("[IdleMode] No intent matched from transcript")
                        # If no intent matched, set unknown
                        intent_result = {"intent": "unknown", "confidence": 0.0}
                        logger.info("[IdleMode] No intent understood, defaulting to unknown")
                    
                    # Store results and signal intent detection
                    self._detected_transcript = transcript
                    self._detected_intent = intent_result
                    
                    # If intent is unknown, check if we should trigger intervention and speak prompt
                    if intent_result.get("intent") == "unknown":
                        try:
                            record_path = self.backend_dir / "config" / "intervention_record.json"
                            record_manager = InterventionRecordManager(record_path)
                            record = record_manager.load_record()
                            
                            decision = record.get("latest_decision", {}) if record else {}
                            trigger_intervention = decision.get("trigger_intervention", False)
                            
                            if trigger_intervention:
                                # Load and speak the unknown intent prompt
                                activity_suggestion_config = self.language_config.get("activity_suggestion", {})
                                unknown_intent_prompt = activity_suggestion_config.get(
                                    "unknown_intent_prompt",
                                    "I didn't quite catch that, but let me suggest something for you"
                                )
                                logger.info(f"Speaking unknown intent prompt: {unknown_intent_prompt}")
                                self._speak(unknown_intent_prompt)
                        except Exception as e:
                            logger.warning(f"Failed to check trigger_intervention or speak prompt: {e}")
                    
                    # Invoke callback if provided
                    if self.on_intent_detected:
                        try:
                            self.on_intent_detected(self._detected_transcript, self._detected_intent)
                        except Exception as e:
                            logger.error(f"Error invoking intent detected callback: {e}")
                    
                    # Signal that intent was detected (this will cause run() to exit)
                    self._intent_detected.set()
                else:
                    logger.info("[IdleMode] Transcript is empty or whitespace only - skipping intent recognition")
            else:
                logger.info("[IdleMode] No transcript received - skipping intent recognition")
            
        except Exception as e:
            logger.error(f"Error during keyword intent recognition: {e}", exc_info=True)
        finally:
            # Ensure mic is stopped and cleared
            if mic.is_running():
                mic.stop()
            with self._lock:
                self._current_mic = None
                self.stt_active = False
            logger.info("Keyword intent recognition session ended")

    def _start_silence_monitoring(self):
        """Start monitoring silence after wake word detection"""
        with self._silence_lock:
            if self._silence_timer:
                self._silence_timer.cancel()
            
            # Use silence_timeout_seconds for the initial nudge timer
            silence_timeout = self.global_config["wakeword"]["silence_timeout_seconds"]
            self._silence_timer = threading.Timer(silence_timeout, self._handle_nudge)
            self._silence_timer.daemon = True
            self._silence_timer.start()
            logger.info(f"Started silence monitoring - nudge in {silence_timeout}s")

    def _handle_nudge(self):
        """Handle nudge when user is silent after wake word"""
        logger.info("User silent after wake word, playing nudge")
        
        # Stop STT session to mute microphone before playing audio
        self._stop_stt_session()
        
        # Load user-specific config
        wakeword_config = self.language_config.get("wakeword_responses", {})
        use_audio_files = self.global_config["wakeword"].get("use_audio_files", False)
        
        # Play nudge audio if enabled
        if use_audio_files:
            nudge_audio_path = self.backend_dir / self.language_config["audio_paths"]["nudge_audio_path"]
            if nudge_audio_path.exists():
                self._play_audio_file(str(nudge_audio_path))
        
        # TTS prompt from config
        try:
            prompts = wakeword_config.get("prompts", {})
            nudge_prompt = prompts.get("nudge", "I'm listening. What would you like to do?")
        except Exception as e:
            logger.warning(f"Failed to load nudge prompt from config: {e}")
            nudge_prompt = "I'm listening. What would you like to do?"
        
        self._speak(nudge_prompt)
        
        # After nudge TTS finishes, restart STT session to continue listening for speech
        # This replicates the same flow as after wake word detection
        logger.info("Restarting STT session after nudge to continue listening for speech")
        
        # Check if STT thread is still running (it should have been stopped by _stop_stt_session)
        # If it's still running, wait for it to finish
        if self._stt_thread and self._stt_thread.is_alive():
            logger.info("Waiting for previous STT thread to finish...")
            self._stt_thread.join(timeout=1.0)
            if self._stt_thread.is_alive():
                logger.warning("Previous STT thread did not finish within timeout")
        
        # Reset stt_active flag
        with self._lock:
            self.stt_active = True
        
        # Launch new STT-based keyword intent recognition thread
        logger.info("Launching keyword intent recognition session after nudge")
        self._stt_thread = threading.Thread(target=self._run_keyword_intent, daemon=True)
        self._stt_thread.start()
        
        # Start final timeout timer
        # This timer runs AFTER the nudge, so use nudge_timeout_seconds directly
        with self._silence_lock:
            nudge_timeout = self.global_config["wakeword"]["nudge_timeout_seconds"]
            self._silence_timer = threading.Timer(nudge_timeout, self._handle_timeout)
            self._silence_timer.daemon = True
            self._silence_timer.start()
            logger.info(f"Started final timeout timer - timeout in {nudge_timeout}s")

    def _handle_timeout(self):
        """Handle final timeout after wake word with no user speech"""
        logger.info("User timeout after wake word, playing termination and restarting")
        
        # Stop STT session to mute microphone before playing audio
        self._stop_stt_session()
        
        # Load user-specific config
        wakeword_config = self.language_config.get("wakeword_responses", {})
        use_audio_files = self.global_config["wakeword"].get("use_audio_files", False)
        
        # Play termination audio if enabled
        if use_audio_files:
            termination_audio_path = self.backend_dir / self.language_config["audio_paths"]["termination_audio_path"]
            if termination_audio_path.exists():
                self._play_audio_file(str(termination_audio_path))
        
        # TTS prompt from config
        try:
            prompts = wakeword_config.get("prompts", {})
            timeout_prompt = prompts.get("timeout", "I'll be here when you need me. Just say my name.")
        except Exception as e:
            logger.warning(f"Failed to load timeout prompt from config: {e}")
            timeout_prompt = "I'll be here when you need me. Just say my name."
        
        self._speak(timeout_prompt)
        
        # Signal timeout occurred (no intent detected) - this will cause run() to return False
        # and main.py will restart idle_mode to return to wakeword listening
        self._timeout_occurred.set()
        logger.info("Timeout detected - no intent detected, will restart idle mode")

    def _stop_silence_monitoring(self):
        """Stop silence monitoring"""
        with self._silence_lock:
            if self._silence_timer:
                self._silence_timer.cancel()
                self._silence_timer = None
                logger.info("Stopped silence monitoring")

    def _stop_stt_session(self):
        """Stop the current STT session and microphone to prevent TTS pickup"""
        try:
            # Stop the mic immediately to prevent picking up TTS
            with self._lock:
                if self._current_mic and self._current_mic.is_running():
                    logger.debug("Stopping mic in STT session to prevent TTS pickup")
                    self._current_mic.stop()
                    self._current_mic = None
        except Exception as e:
            logger.warning(f"Failed to stop STT session: {e}")
