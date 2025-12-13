"""
Wake Mode Activity

This activity handles intent recognition after wake word detection or intervention trigger.
It processes user speech, matches intents, and handles silence monitoring and timeouts.
"""

import os
import sys
import threading
import time
import logging
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any

# For playing audio files - use pydub as primary, PowerShell as fallback
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

# Import components
from src.components.mic_stream import MicStream
from src.components.tts import GoogleTTSClient
from src.components.stt import GoogleSTTService
from src.components.keyword_intent_matcher import KeywordIntentMatcher
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.utils.intervention_record import InterventionRecordManager
from src.supabase.auth import get_current_user_id

logger = logging.getLogger(__name__)


class WakeModeActivity:
    """
    Wake Mode Activity
    
    Handles intent recognition after wake word detection or intervention trigger.
    Processes user speech, matches intents, and handles silence monitoring and timeouts.
    """
    
    def __init__(
        self,
        backend_dir: Path,
        user_id: Optional[str] = None,
        on_intent_detected: Optional[callable] = None
    ):
        """
        Initialize the Wake Mode Activity
        
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
        
        # STT session state
        self.stt_active = False
        self._lock = threading.Lock()
        self._stt_thread: Optional[threading.Thread] = None
        self._mic_stream: Optional[MicStream] = None
        
        # Silence monitoring
        self._silence_timer: Optional[threading.Timer] = None
        self._silence_lock = threading.Lock()
        
        # Intent detection flags
        self._intent_detected = threading.Event()
        self._timeout_occurred = threading.Event()
        self._detected_transcript: Optional[str] = None
        self._detected_intent: Optional[Dict[str, Any]] = None
        
        # Intervention mode flag
        self._intervention_mode = False
        
        logger.info(f"WakeModeActivity initialized for user {self.user_id}")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            logger.info("Initializing Wake Mode activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            
            # Load user-specific configurations
            logger.info(f"Loading configs for user {self.user_id}")
            self.global_config = get_global_config_for_user(self.user_id)
            self.language_config = get_language_config(self.user_id)
            
            # Get wakeword audio path
            self.wakeword_audio_path = self.language_config["audio_paths"].get("wokeword_audio_path")
            logger.info(f"Wakeword audio path loaded: {self.wakeword_audio_path}")
            
            # Initialize TTS service
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
            
            self._initialized = True
            logger.info("✅ Wake Mode activity initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Wake Mode activity: {e}", exc_info=True)
            return False
    
    def start(self, intervention_mode: bool = False) -> bool:
        """Start the wake mode activity"""
        if not self._initialized:
            logger.error("Cannot start: activity not initialized")
            return False
        
        if self._active:
            logger.warning("Wake mode already active")
            return True
        
        self._intervention_mode = intervention_mode
        self._active = True
        logger.info(f"✅ Wake mode active (intervention_mode={intervention_mode})")
        return True
    
    def stop(self):
        """Stop the wake mode activity"""
        if not self._active:
            logger.warning("Wake mode not active, cannot stop")
            return
        
        logger.info("Stopping wake mode activity...")
        
        # Mark as inactive FIRST
        self._active = False
        
        # Stop silence monitoring
        self._stop_silence_monitoring()
        
        # Stop STT session
        self._stop_stt_session()
        
        # Wait for STT thread to complete if it's running
        if self._stt_thread and self._stt_thread.is_alive():
            current_thread = threading.current_thread()
            if self._stt_thread is not current_thread:
                logger.info("Waiting for intent recognition session to complete...")
                self._stt_thread.join(timeout=1.0)
                if self._stt_thread.is_alive():
                    logger.warning("STT thread did not complete within timeout, continuing anyway")
            else:
                logger.debug("STT thread is current thread - skipping join to avoid deadlock")
        
        # Clear flags
        self._intent_detected.clear()
        self._timeout_occurred.clear()
        self._detected_intent = None
        self._detected_transcript = None
        
        logger.info("✅ Wake mode stopped")
    
    def run(self) -> bool:
        """
        Run the wake mode activity
        
        Returns:
            True if intent was detected, False on timeout or error
        """
        logger.info("🎬 WakeModeActivity.run() - Starting wake mode execution")
        
        try:
            # Clear any stale state
            self._intent_detected.clear()
            self._timeout_occurred.clear()
            self._detected_intent = None
            self._detected_transcript = None
            
            # Handle intervention mode vs wake word mode
            if self._intervention_mode:
                # Intervention mode: play intervention prompt first
                self._handle_intervention_prompt()
            else:
                # Wake word mode: play wake word response
                self._handle_wake_word_response()
            
            # Start STT session for intent recognition
            self._start_intent_recognition()
            
            # Wait for intent detection or timeout
            logger.info("Waiting for intent detection or timeout...")
            
            while self._active and not self._intent_detected.is_set() and not self._timeout_occurred.is_set():
                time.sleep(0.1)  # Small sleep to avoid busy waiting
            
            # Check if intent was detected
            if self._intent_detected.is_set():
                logger.info("✅ Intent detected - exiting wake mode")
                self.stop()
                return True
            elif self._timeout_occurred.is_set():
                logger.info("⏰ Timeout occurred - no intent detected")
                self.stop()
                return False
            else:
                # Activity was stopped externally
                logger.info("Wake mode stopped externally")
                return False
                
        except Exception as e:
            logger.error(f"Error running wake mode activity: {e}", exc_info=True)
            self.stop()
            return False
    
    def get_detected_intent(self) -> Optional[Dict[str, Any]]:
        """
        Get the detected intent and transcript.
        
        Returns:
            Dictionary with 'intent' and 'confidence' keys, or None if no intent detected
        """
        return self._detected_intent
    
    def get_detected_transcript(self) -> Optional[str]:
        """
        Get the detected transcript.
        
        Returns:
            Transcript string, or None if no transcript available
        """
        return self._detected_transcript
    
    def cleanup(self):
        """Clean up all resources"""
        logger.info("Cleaning up wake mode resources...")
        try:
            self.stop()
            logger.info("✅ Wake mode cleanup completed")
        except Exception as e:
            logger.error(f"Error during wake mode cleanup: {e}", exc_info=True)
    
    def is_active(self) -> bool:
        """Check if the activity is currently active"""
        return self._active and self._initialized
    
    def _handle_wake_word_response(self):
        """Handle wake word response (play audio/TTS)"""
        logger.info("Handling wake word response...")
        
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
        
        # Speak the prompt
        logger.info(f"Speaking wakeword prompt: {wakeword_prompt}")
        self._speak(wakeword_prompt)
        logger.info("Wakeword prompt finished")
    
    def _handle_intervention_prompt(self):
        """Handle intervention prompt"""
        logger.info("Handling intervention prompt...")
        
        # Load intervention prompt from language config
        try:
            activity_suggestion_config = self.language_config.get("activity_suggestion", {})
            intervention_prompt = activity_suggestion_config.get(
                "intervention_trigger_prompt",
                "I'm seeing that you're having a good day would you like to do an activity with me?"
            )
        except Exception as e:
            logger.warning(f"Failed to load intervention prompt from config: {e}")
            intervention_prompt = "I'm seeing that you're having a good day would you like to do an activity with me?"
        
        logger.info(f"Speaking intervention prompt: {intervention_prompt}")
        self._speak(intervention_prompt)
        logger.info("Intervention prompt finished")
    
    def _start_intent_recognition(self):
        """Start intent recognition session"""
        # Start silence monitoring
        self._start_silence_monitoring()
        
        # Launch STT-based keyword intent recognition thread
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
        
        # Check if activity is still active before starting
        if not self._active:
            logger.debug("Wake mode no longer active, aborting STT session")
            with self._lock:
                self.stt_active = False
            return
        
        # Create direct MicStream instance (NOT SharedAudioManager)
        mic = MicStream(rate=16000, chunk_size=1600)  # 100ms chunks at 16kHz
        
        # Store mic reference
        with self._lock:
            self._mic_stream = mic
            self.stt_active = True
        
        intent_result: Optional[dict] = None
        transcript: Optional[str] = None
        
        try:
            mic.start()
            logger.info("Microphone active (direct MicStream), awaiting speech for keyword matching")
            
            # Capture transcript using STT with timeout
            def on_transcript(text: str, is_final: bool):
                nonlocal transcript
                if is_final and text:
                    transcript = text
                    # Reset silence timer on transcript
                    self._stop_silence_monitoring()
            
            # Run STT in a thread with timeout to prevent 5-minute hangs
            stt_completed = threading.Event()
            stt_error = {'error': None}
            
            def run_stt():
                try:
                    self.stt_service.stream_recognize(
                        mic.generator(),
                        on_transcript,
                        interim_results=True,
                        single_utterance=True  # Stop after first final result
                    )
                except Exception as e:
                    stt_error['error'] = e
                    logger.error(f"STT error during keyword matching: {e}")
                finally:
                    stt_completed.set()
            
            # Start STT in thread
            stt_thread = threading.Thread(target=run_stt, daemon=True)
            stt_thread.start()
            
            # Wait for STT with timeout (max 30 seconds to prevent 5-minute hangs)
            stt_timeout = 30.0
            if stt_completed.wait(timeout=stt_timeout):
                # STT completed
                if stt_error['error']:
                    logger.error(f"STT failed: {stt_error['error']}")
            else:
                # STT timeout - stop mic and continue
                logger.warning(f"STT timeout after {stt_timeout}s - stopping microphone and continuing")
                if mic.is_running():
                    mic.stop()
                # Wait a bit for thread to finish
                stt_thread.join(timeout=2.0)
            
            # Only proceed with intent recognition if transcript has at least one word
            if transcript and transcript.strip() and self._active:
                # Check if transcript has at least one word
                words = transcript.strip().split()
                if len(words) > 0:
                    logger.info(f"[WakeMode] Transcript received: '{transcript}'")
                    intent_result = self.intent_matcher.match_intent(transcript)
                    if intent_result:
                        logger.info(f"[WakeMode] Intent detected: {intent_result.get('intent')}")
                    else:
                        logger.info("[WakeMode] No intent matched from transcript")
                        # If no intent matched, set unknown
                        intent_result = {"intent": "unknown", "confidence": 0.0}
                        logger.info("[WakeMode] No intent understood, defaulting to unknown")
                    
                    # Double-check activity is still active
                    if not self._active:
                        logger.debug("Wake mode stopped during intent processing, aborting")
                        return
                    
                    # Store results
                    self._detected_transcript = transcript
                    self._detected_intent = intent_result
                    
                    # In intervention mode, always route to activity_suggestion (per plan)
                    if self._intervention_mode:
                        self._detected_intent = {"intent": "activity_suggestion", "confidence": 1.0}
                        logger.info("[WakeMode] Intervention mode - routing to activity_suggestion")
                    # If intent is unknown (and not intervention mode), check if we should trigger intervention
                    elif intent_result.get("intent") == "unknown":
                            # Check if we should trigger intervention
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
                                    # Route to activity_suggestion
                                    self._detected_intent = {"intent": "activity_suggestion", "confidence": 1.0}
                            except Exception as e:
                                logger.warning(f"Failed to check trigger_intervention or speak prompt: {e}")
                    
                    # Final check: ensure activity is still active
                    if not self._active:
                        logger.debug("Wake mode stopped before signaling intent, aborting")
                        return
                    
                    # Signal that intent was detected
                    self._intent_detected.set()
                    
                    # Invoke callback if provided
                    if self.on_intent_detected and self._active:
                        try:
                            self.on_intent_detected(self._detected_transcript, self._detected_intent)
                        except Exception as e:
                            logger.error(f"Error invoking intent detected callback: {e}")
                else:
                    logger.info("[WakeMode] Transcript is empty or whitespace only - skipping intent recognition")
            elif transcript and transcript.strip() and not self._active:
                logger.debug("Transcript received but wake mode is no longer active, ignoring")
            else:
                logger.info("[WakeMode] No transcript received - skipping intent recognition")
            
        except Exception as e:
            logger.error(f"Error during keyword intent recognition: {e}", exc_info=True)
        finally:
            # Stop mic
            if mic.is_running():
                mic.stop()
            
            # Mark STT as inactive
            with self._lock:
                self._mic_stream = None
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
        
        # After nudge TTS finishes, restart STT session
        logger.info("Restarting STT session after nudge to continue listening for speech")
        
        # Check if STT thread is still running
        if self._stt_thread and self._stt_thread.is_alive():
            current_thread = threading.current_thread()
            if self._stt_thread is not current_thread:
                logger.info("Waiting for previous STT thread to finish...")
                self._stt_thread.join(timeout=1.0)
                if self._stt_thread.is_alive():
                    logger.warning("Previous STT thread did not finish within timeout")
            else:
                logger.debug("STT thread is current thread - skipping join to avoid deadlock")
        
        # Reset stt_active flag
        with self._lock:
            self.stt_active = True
        
        # Launch new STT-based keyword intent recognition thread
        logger.info("Launching keyword intent recognition session after nudge")
        self._stt_thread = threading.Thread(target=self._run_keyword_intent, daemon=True)
        self._stt_thread.start()
        
        # Start final timeout timer
        with self._silence_lock:
            nudge_timeout = self.global_config["wakeword"]["nudge_timeout_seconds"]
            self._silence_timer = threading.Timer(nudge_timeout, self._handle_timeout)
            self._silence_timer.daemon = True
            self._silence_timer.start()
            logger.info(f"Started final timeout timer - timeout in {nudge_timeout}s")
    
    def _handle_timeout(self):
        """Handle final timeout after wake word with no user speech"""
        logger.info("User timeout after wake word, playing termination and exiting")
        
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
        
        # Signal timeout occurred
        self._timeout_occurred.set()
        logger.info("Timeout detected - no intent detected")
    
    def _stop_silence_monitoring(self):
        """Stop silence monitoring"""
        with self._silence_lock:
            if self._silence_timer:
                self._silence_timer.cancel()
                self._silence_timer = None
                logger.info("Stopped silence monitoring")
    
    def _stop_stt_session(self):
        """Stop the current STT session and microphone"""
        try:
            with self._lock:
                if self._mic_stream and self._mic_stream.is_running():
                    logger.debug("Stopping mic in STT session")
                    self._mic_stream.stop()
                    self._mic_stream = None
        except Exception as e:
            logger.warning(f"Failed to stop STT session: {e}")
    
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
            if self._mic_stream and self._mic_stream.is_running():
                logger.debug("Muting microphone before TTS")
                self._mic_stream.mute()
        
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
                if self._mic_stream and self._mic_stream.is_running():
                    logger.debug("Unmuting microphone after TTS")
                    self._mic_stream.unmute()

