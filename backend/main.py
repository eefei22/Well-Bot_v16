# backend/main.py

"""
Main entry point for the Well-Bot backend.
Orchestrates the complete voice pipeline: Wake Word → Intent Recognition → Activity Execution
"""

import os
import sys
import logging
import threading
import time
import json
from pathlib import Path
from enum import Enum
from typing import Optional, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add the backend directory to the path (so we can import src.components etc.)
backend_dir = Path(__file__).parent
sys.path.append(str(backend_dir))

# Import pipeline / components
from src.components._pipeline_wakeword import create_voice_pipeline, VoicePipeline
from src.components.stt import GoogleSTTService
from src.components.tts import GoogleTTSClient
from src.components.mic_stream import MicStream
from src.activities.smalltalk import SmallTalkActivity
from src.activities.journal import JournalActivity
from src.activities.spiritual_quote import SpiritualQuoteActivity
from src.activities.meditation import MeditationActivity
from src.activities.gratitude import GratitudeActivity
from src.utils.config_resolver import get_global_config_for_user, resolve_language
from src.supabase.auth import get_current_user_id
from src.supabase.database import log_activity_start

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

class SystemState(Enum):
    """System states for the orchestration"""
    STARTING        = "starting"
    LISTENING       = "listening"        # Listening for wake word
    PROCESSING      = "processing"       # After wake word, processing speech/intent
    ACTIVITY_ACTIVE = "activity_active"  # Running an activity (e.g., smalltalk)
    SHUTTING_DOWN   = "shutting_down"

class WellBotOrchestrator:
    """
    Main orchestrator that coordinates the complete voice pipeline flow:
    Wake Word Detection → Speech Recognition → Intent Classification → Activity Execution
    """
    def __init__(self):
        self.state = SystemState.STARTING
        self._lock = threading.Lock()

        # Paths to configuration
        self.backend_dir = backend_dir
        self.wakeword_model_path  = self.backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel.ppn"
        
        # Get current user at startup
        self.user_id = get_current_user_id()
        logger.info(f"Orchestrator initialized for user: {self.user_id}")
        
        # Load user-specific config (will be loaded in _initialize_components)
        self.global_config = None

        # Components
        self.voice_pipeline: Optional[VoicePipeline] = None
        self.smalltalk_activity: Optional[SmallTalkActivity] = None
        self.journal_activity: Optional[JournalActivity] = None
        self.spiritual_quote_activity: Optional[SpiritualQuoteActivity] = None
        self.meditation_activity: Optional[MeditationActivity] = None
        self.gratitude_activity: Optional[GratitudeActivity] = None
        self.stt_service: Optional[GoogleSTTService] = None
        self.tts_service: Optional[GoogleTTSClient] = None

        # Silence monitoring for wakeword
        self._silence_timer: Optional[threading.Timer] = None
        self._silence_lock = threading.Lock()
        
        # Mic management for audio playback
        self._current_mic = None
        self._mic_lock = threading.Lock()

        self.current_activity: Optional[str] = None
        self._activity_thread: Optional[threading.Thread] = None
        self._current_activity_log_id: Optional[str] = None  # Track log ID for completion

        logger.info("WellBotOrchestrator initialized")

    def _validate_config_files(self) -> bool:
        """Validate that all required config files exist."""
        required = [self.wakeword_model_path]
        missing = []
        for f in required:
            if not f.exists():
                missing.append(str(f))
            else:
                logger.info(f"✓ Found: {f}")
        if missing:
            logger.error(f"Missing required files: {missing}")
            return False
        return True

    def _wait_for_stt_teardown(self, timeout_s: float = 3.0) -> bool:
        """Wait briefly for the voice pipeline's STT session and wakeword engine to fully stop."""
        start = time.time()
        while time.time() - start < timeout_s:
            stt_active = self.voice_pipeline.is_stt_active() if self.voice_pipeline else False
            wake_active = self.voice_pipeline.is_active() if self.voice_pipeline else False
            if not stt_active and not wake_active:
                return True
            time.sleep(0.05)
        return False

    def _initialize_components(self) -> bool:
        """Initialize STT, voice pipeline, activities."""
        try:
            # Resolve user language and load configs
            user_lang = resolve_language(self.user_id)
            logger.info(f"Resolved language '{user_lang}' for user {self.user_id}")
            
            self.global_config = get_global_config_for_user(self.user_id)
            logger.info(f"Loaded global config for user")
            
            logger.info("Initializing STT service…")
            stt_language = self.global_config["language_codes"]["stt_language_code"]
            self.stt_service = GoogleSTTService(language=stt_language, sample_rate=16000)
            logger.info(f"✓ STT service initialized with language: {stt_language}")

            logger.info("Initializing TTS service for wakeword responses…")
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

            logger.info("Initializing voice pipeline (wake word)…")
            self.voice_pipeline = create_voice_pipeline(
                access_key_file="",  # Deprecated - now uses environment variable
                custom_keyword_file=str(self.wakeword_model_path),
                language=self.global_config["language_codes"]["stt_language_code"],
                user_id=self.user_id,  # Pass user_id
                on_wake_callback=self._on_wake_detected,
                on_final_transcript=self._on_transcript_received,
                intent_config_path=None,  # Now loaded from language_config
                preference_file_path=None,  # Now loaded from language_config
                stt_timeout_s=self.global_config["wakeword"]["stt_timeout_s"]
            )

            logger.info("✓ Voice pipeline initialized")

            logger.info("Initializing SmallTalk activity…")
            self.smalltalk_activity = SmallTalkActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.smalltalk_activity.initialize():
                raise RuntimeError("Failed to initialize SmallTalk activity")
            logger.info("✓ SmallTalk activity initialized")

            logger.info("Initializing Journal activity…")
            self.journal_activity = JournalActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.journal_activity.initialize():
                raise RuntimeError("Failed to initialize Journal activity")
            logger.info("✓ Journal activity initialized")

            logger.info("Initializing Spiritual Quote activity…")
            self.spiritual_quote_activity = SpiritualQuoteActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.spiritual_quote_activity.initialize():
                raise RuntimeError("Failed to initialize Spiritual Quote activity")
            logger.info("✓ Spiritual Quote activity initialized")

            logger.info("Initializing Meditation activity…")
            self.meditation_activity = MeditationActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.meditation_activity.initialize():
                raise RuntimeError("Failed to initialize Meditation activity")
            logger.info("✓ Meditation activity initialized")

            logger.info("Initializing Gratitude activity…")
            self.gratitude_activity = GratitudeActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.gratitude_activity.initialize():
                raise RuntimeError("Failed to initialize Gratitude activity")
            logger.info("✓ Gratitude activity initialized")
            
            return True
        except Exception as e:
            logger.error(f"Component initialization failed: {e}", exc_info=True)
            return False

    def _on_wake_detected(self):
        """Callback when wake word is detected."""
        with self._lock:
            if self.state != SystemState.LISTENING:
                logger.warning(f"Wake word detected but system in state {self.state.value}, ignoring")
                return
            logger.info("🎤 Wake word detected – transitioning to PROCESSING state")
            self.state = SystemState.PROCESSING
        
        # Track current microphone for muting during audio playback
        if self.voice_pipeline and hasattr(self.voice_pipeline, '_stt_thread'):
            # The microphone is managed by the voice pipeline's STT thread
            # We'll get access to it through the pipeline's internal state
            pass
        
        # Start silence monitoring after wake word detection
        self._start_wakeword_silence_monitoring()

    def _on_transcript_received(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Callback when final transcript and intent are available."""
        # Stop silence monitoring since we received a transcript
        self._stop_wakeword_silence_monitoring()
        
        with self._lock:
            if self.state != SystemState.PROCESSING:
                logger.warning(f"Transcript received but system in state {self.state.value}, ignoring")
                return

            logger.info(f"📝 Transcript: '{transcript}'")

            intent = "unknown"
            confidence = 0.0
            if intent_result:
                intent = intent_result.get('intent', 'unknown')
                confidence = intent_result.get('confidence', 0.0)
                logger.info(f"🎯 Intent: {intent} (confidence: {confidence:.3f})")
            else:
                logger.warning("No intent classification available; defaulting to smalltalk")

            # Transition to activity
            self.state = SystemState.ACTIVITY_ACTIVE
        
        # Release lock before calling _route_to_activity to avoid deadlock
        self._route_to_activity(intent, transcript)

    def _route_to_activity(self, intent: str, transcript: str):
        """Route the user to proper activity based on intent."""
        logger.info(f"🔄 Routing to activity: {intent}")

        # Map intent to activity type for logging
        intent_to_activity_type = {
            "smalltalk": None,  # Smalltalk is not logged as an activity
            "journaling": "journal",
            "meditation": "meditation",
            "quote": "quote",
            "gratitude": "gratitude",
            "termination": None,
        }
        
        activity_type = intent_to_activity_type.get(intent)
        
        # Log activity start if it's a trackable activity
        # Command-triggered interventions have emotional_log_id=None
        if activity_type:
            public_id = log_activity_start(
                user_id=self.user_id,
                activity_type=activity_type,
                emotional_log_id=None  # Command-triggered, not emotion-triggered
            )
            self._current_activity_log_id = public_id  # Keep variable name for backward compatibility
        else:
            self._current_activity_log_id = None

        if intent == "smalltalk":
            self._start_smalltalk_activity()
        elif intent == "journaling":
            self._start_journal_activity()
        elif intent == "meditation":
            self._start_meditation_activity()
        elif intent == "quote":
            self._start_spiritual_quote_activity()
        elif intent == "gratitude":
            self._start_gratitude_activity()
        elif intent == "termination":
            logger.info("👋 Termination intent detected – ending session")
            self._handle_termination()
        else:
            logger.info(f"❓ Unknown intent '{intent}' – prompting user to repeat")
            self._handle_unknown_intent(transcript)

    def _start_smalltalk_activity(self):
        """Start the smalltalk activity thread."""
        logger.info("💬 Starting SmallTalk activity…")
        
        # Safety check - ensure smalltalk_activity is initialized
        if self.smalltalk_activity is None:
            logger.error("❌ SmallTalk activity is None - cannot start")
            return
        
        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "smalltalk"

        # 1) Stop wake word pipeline first (this triggers Picovoice/Porcupine cleanup)
        if self.voice_pipeline:
            logger.info("🔇 Pausing wake word pipeline before SmallTalk…")
            try:
                logger.info("🔍 Calling voice_pipeline.stop()...")
                
                # Force stop with timeout
                import threading
                stop_success = threading.Event()
                
                def force_stop():
                    try:
                        self.voice_pipeline.stop()
                        stop_success.set()
                    except Exception as e:
                        logger.error(f"Error in stop thread: {e}")
                        stop_success.set()
                
                stop_thread = threading.Thread(target=force_stop, daemon=True)
                stop_thread.start()
                
                # Wait for stop to complete with timeout
                if stop_success.wait(timeout=5.0):
                    logger.info("✅ voice_pipeline.stop() completed successfully")
                else:
                    logger.warning("⚠️ voice_pipeline.stop() timed out after 5s - forcing continuation")
                    
            except Exception as e:
                logger.warning(f"Ignoring error while stopping voice pipeline: {e}")
                logger.info("⚠️ Continuing despite stop error...")

        # 2) Wait until STT/wakeword fully release audio devices
        if self.voice_pipeline:
            logger.info("⏳ Waiting for STT teardown (mic/device release)…")
            ok = self._wait_for_stt_teardown(timeout_s=3.0)
            if not ok:
                logger.warning("⚠️ STT teardown wait timed out; proceeding anyway")

        # 3) Add a tiny guard delay (Windows USB audio sometimes needs this)
        logger.info("⏱️ Adding guard delay for Windows audio device release...")
        time.sleep(0.15)

        # 4) Sanity check - verify device state before activity starts
        logger.info(f"🔍 Device state check - Wake active: {self.voice_pipeline.is_active() if self.voice_pipeline else None} | "
                   f"STT active: {self.voice_pipeline.is_stt_active() if self.voice_pipeline else None}")

        def run_activity():
            try:
                # Extra visibility
                logger.info("🚀 Launching SmallTalkActivity.run()…")
                
                # Safety check - ensure smalltalk_activity exists
                if self.smalltalk_activity is None:
                    logger.error("❌ SmallTalk activity is None - cannot run")
                    return
                
                # Pass log_id to activity for completion tracking
                if hasattr(self.smalltalk_activity, 'set_activity_log_id'):
                    self.smalltalk_activity.set_activity_log_id(self._current_activity_log_id)
                
                success = self.smalltalk_activity.run()
                if success:
                    logger.info("✅ SmallTalk activity completed successfully")
                else:
                    logger.error("❌ SmallTalk activity ended with failure or abnormal termination")
            except Exception as e:
                logger.error(f"Error in SmallTalk activity: {e}", exc_info=True)
            finally:
                # Cleanup activity resources before restarting wakeword
                logger.info("🧹 Cleaning up SmallTalk activity resources...")
                if self.smalltalk_activity:
                    try:
                        self.smalltalk_activity.cleanup()
                        logger.info("✅ SmallTalk activity cleanup completed")
                        
                        # Re-initialize for next run
                        logger.info("🔄 Re-initializing SmallTalk activity for next run...")
                        if not self.smalltalk_activity.reinitialize():
                            logger.error("❌ Failed to re-initialize SmallTalk activity")
                        else:
                            logger.info("✅ SmallTalk activity re-initialized successfully")
                            
                    except Exception as e:
                        logger.warning(f"Error during activity cleanup/reinit: {e}")
                
                # Clear log ID
                self._current_activity_log_id = None
                
                # When activity ends, restart wake word detection
                self._restart_wakeword_detection()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _fallback_to_smalltalk(self):
        """Fallback to smalltalk in absence of specific activity."""
        logger.info("🔄 Falling back to SmallTalk…")
        self._start_smalltalk_activity()
    
    def _handle_termination(self):
        """Handle termination intent by shutting down the system."""
        logger.info("👋 Termination intent received – shutting down system")
        with self._lock:
            self.state = SystemState.SHUTTING_DOWN
        self.stop()

    def _start_wakeword_silence_monitoring(self):
        """Start monitoring silence after wake word detection"""
        with self._silence_lock:
            if self._silence_timer:
                self._silence_timer.cancel()
            
            nudge_timeout = self.global_config["wakeword"]["nudge_timeout_seconds"]
            self._silence_timer = threading.Timer(nudge_timeout, self._handle_wakeword_nudge)
            self._silence_timer.daemon = True
            self._silence_timer.start()
            logger.info(f"Started silence monitoring - nudge in {nudge_timeout}s")

    def _handle_wakeword_nudge(self):
        """Handle nudge when user is silent after wake word"""
        logger.info("User silent after wake word, playing nudge")
        
        # Stop STT session to mute microphone before playing audio
        self._stop_stt_session()
        
        # Load user-specific config
        from src.utils.config_resolver import get_language_config
        language_config = get_language_config(self.user_id)
        wakeword_config = language_config.get("wakeword_responses", {})
        use_audio_files = self.global_config["wakeword"].get("use_audio_files", False)
        
        # Play nudge audio if enabled
        if use_audio_files:
            nudge_audio_path = self.backend_dir / language_config["audio_paths"]["nudge_audio_path"]
            if nudge_audio_path.exists():
                self._play_audio_blocking(nudge_audio_path)
        
        # TTS prompt from config
        try:
            prompts = wakeword_config.get("prompts", {})
            nudge_prompt = prompts.get("nudge", "I'm listening. What would you like to do?")
        except Exception as e:
            logger.warning(f"Failed to load nudge prompt from config: {e}")
            nudge_prompt = "I'm listening. What would you like to do?"
        
        self._speak(nudge_prompt)
        
        # Start final timeout timer
        with self._silence_lock:
            silence_timeout = self.global_config["wakeword"]["silence_timeout_seconds"]
            nudge_timeout = self.global_config["wakeword"]["nudge_timeout_seconds"]
            remaining_time = silence_timeout - nudge_timeout
            self._silence_timer = threading.Timer(remaining_time, self._handle_wakeword_timeout)
            self._silence_timer.daemon = True
            self._silence_timer.start()
            logger.info(f"Started final timeout timer - timeout in {remaining_time}s")

    def _handle_wakeword_timeout(self):
        """Handle final timeout after wake word with no user speech"""
        logger.info("User timeout after wake word, playing termination and restarting")
        
        # Stop STT session to mute microphone before playing audio
        self._stop_stt_session()
        
        # Load user-specific config
        from src.utils.config_resolver import get_language_config
        language_config = get_language_config(self.user_id)
        wakeword_config = language_config.get("wakeword_responses", {})
        use_audio_files = self.global_config["wakeword"].get("use_audio_files", False)
        
        # Play termination audio if enabled
        if use_audio_files:
            termination_audio_path = self.backend_dir / language_config["audio_paths"]["termination_audio_path"]
            if termination_audio_path.exists():
                self._play_audio_blocking(termination_audio_path)
        
        # TTS prompt from config
        try:
            prompts = wakeword_config.get("prompts", {})
            timeout_prompt = prompts.get("timeout", "I'll be here when you need me. Just say my name.")
        except Exception as e:
            logger.warning(f"Failed to load timeout prompt from config: {e}")
            timeout_prompt = "I'll be here when you need me. Just say my name."
        
        self._speak(timeout_prompt)
        
        # Reset state and restart wake word detection
        with self._lock:
            self.state = SystemState.LISTENING
        
        logger.info("Restarting wake word detection after timeout")
        self._restart_wakeword_detection()

    def _stop_wakeword_silence_monitoring(self):
        """Stop silence monitoring"""
        with self._silence_lock:
            if self._silence_timer:
                self._silence_timer.cancel()
                self._silence_timer = None
                logger.info("Stopped silence monitoring")

    def _play_audio_blocking(self, audio_path: Path):
        """Play audio file synchronously"""
        try:
            if audio_path.exists():
                # Use same audio playback method as wakeword pipeline
                import subprocess
                if sys.platform == "win32":
                    ps_cmd = f'powershell -c "(New-Object Media.SoundPlayer \'{audio_path}\').PlaySync()"'
                    subprocess.run(ps_cmd, shell=True, capture_output=True, timeout=10)
                    logger.info(f"Played audio: {audio_path}")
                else:
                    logger.warning("Audio playback only supported on Windows")
            else:
                logger.error(f"Audio file not found: {audio_path}")
        except Exception as e:
            logger.error(f"Failed to play audio: {e}")

    def _speak(self, text: str):
        """Speak text using TTS (for wakeword responses)"""
        if not self.tts_service:
            logger.warning("TTS service not available")
            return
        
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

    def _stop_stt_session(self):
        """Stop the current STT session to mute microphone"""
        try:
            if self.voice_pipeline and hasattr(self.voice_pipeline, '_stt_thread'):
                # The STT session is running in a separate thread
                # We can't directly stop it, but we can wait for it to complete
                # The STT session will timeout naturally after stt_timeout_s
                logger.debug("STT session will timeout naturally, microphone will be muted")
        except Exception as e:
            logger.warning(f"Failed to stop STT session: {e}")

    def _handle_unknown_intent(self, transcript: str):
        """Handle unknown/unrecognized intent with audio feedback"""
        logger.info(f"Handling unknown intent for transcript: '{transcript}'")
        
        # Stop any ongoing STT session
        self._stop_stt_session()
        
        # Load user-specific config
        from src.utils.config_resolver import get_language_config
        language_config = get_language_config(self.user_id)
        wakeword_config = language_config.get("wakeword_responses", {})
        use_audio_files = self.global_config["wakeword"].get("use_audio_files", False)
        
        # Play prompt repeat audio if enabled
        if use_audio_files:
            prompt_repeat_path = self.backend_dir / language_config["audio_paths"]["prompt_repeat_path"]
            if prompt_repeat_path.exists():
                self._play_audio_blocking(prompt_repeat_path)
        
        # TTS prompt from config
        try:
            prompts = wakeword_config.get("prompts", {})
            unknown_prompt = prompts.get("unknown_intent", "I didn't quite catch that. Could you please repeat?")
        except Exception as e:
            logger.warning(f"Failed to load unknown intent prompt from config: {e}")
            unknown_prompt = "I didn't quite catch that. Could you please repeat?"
        
        self._speak(unknown_prompt)
        
        # Reset state and restart wakeword detection (clean restart)
        with self._lock:
            self.state = SystemState.LISTENING
        
        logger.info("Restarting wakeword detection after unknown intent")
        self._restart_wakeword_detection()

    def _handle_activity_unavailable(self, activity_name: str):
        """Handle unavailable activity with audio feedback"""
        logger.info(f"Handling unavailable activity: {activity_name}")
        
        # Stop any ongoing STT session
        self._stop_stt_session()
        
        # Load user-specific config
        from src.utils.config_resolver import get_language_config
        language_config = get_language_config(self.user_id)
        wakeword_config = language_config.get("wakeword_responses", {})
        use_audio_files = self.global_config["wakeword"].get("use_audio_files", False)
        
        # Play activity unavailable audio if enabled
        if use_audio_files:
            unavailable_path = self.backend_dir / language_config["audio_paths"]["activity_unavailable_path"]
            if unavailable_path.exists():
                self._play_audio_blocking(unavailable_path)
        
        # TTS prompt from config
        try:
            prompts = wakeword_config.get("prompts", {})
            unavailable_prompt = prompts.get("activity_unavailable", "That feature isn't available yet. What else can I help you with?")
        except Exception as e:
            logger.warning(f"Failed to load activity unavailable prompt from config: {e}")
            unavailable_prompt = "That feature isn't available yet. What else can I help you with?"
        
        self._speak(unavailable_prompt)
        
        # Reset state and restart wakeword detection (clean restart)
        with self._lock:
            self.state = SystemState.LISTENING
        
        logger.info("Restarting wakeword detection after unavailable activity")
        self._restart_wakeword_detection()

    def _start_journal_activity(self):
        """Start the journal activity thread."""
        logger.info("📖 Starting Journal activity…")
        
        # Safety check - ensure journal_activity is initialized
        if self.journal_activity is None:
            logger.error("❌ Journal activity is None - cannot start")
            return
        
        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "journaling"

        # 1) Stop wake word pipeline first (this triggers Picovoice/Porcupine cleanup)
        if self.voice_pipeline:
            logger.info("🔇 Pausing wake word pipeline before Journal…")
            try:
                logger.info("🔍 Calling voice_pipeline.stop()...")
                
                # Force stop with timeout
                import threading
                stop_success = threading.Event()
                
                def force_stop():
                    try:
                        self.voice_pipeline.stop()
                        stop_success.set()
                    except Exception as e:
                        logger.error(f"Error in stop thread: {e}")
                        stop_success.set()
                
                stop_thread = threading.Thread(target=force_stop, daemon=True)
                stop_thread.start()
                
                # Wait for stop to complete with timeout
                if stop_success.wait(timeout=5.0):
                    logger.info("✅ voice_pipeline.stop() completed successfully")
                else:
                    logger.warning("⚠️ voice_pipeline.stop() timed out after 5s - forcing continuation")
                    
            except Exception as e:
                logger.warning(f"Ignoring error while stopping voice pipeline: {e}")
                logger.info("⚠️ Continuing despite stop error...")

        # 2) Wait until STT/wakeword fully release audio devices
        if self.voice_pipeline:
            logger.info("⏳ Waiting for STT teardown (mic/device release)…")
            ok = self._wait_for_stt_teardown(timeout_s=3.0)
            if not ok:
                logger.warning("⚠️ STT teardown wait timed out; proceeding anyway")

        # 3) Add a tiny guard delay (Windows USB audio sometimes needs this)
        logger.info("⏱️ Adding guard delay for Windows audio device release...")
        time.sleep(0.15)

        # 4) Sanity check - verify device state before activity starts
        logger.info(f"🔍 Device state check - Wake active: {self.voice_pipeline.is_active() if self.voice_pipeline else None} | "
                   f"STT active: {self.voice_pipeline.is_stt_active() if self.voice_pipeline else None}")

        def run_activity():
            try:
                # Extra visibility
                logger.info("🚀 Launching JournalActivity.run()…")
                
                # Safety check - ensure journal_activity exists
                if self.journal_activity is None:
                    logger.error("❌ Journal activity is None - cannot run")
                    return
                
                # Pass log_id to activity for completion tracking
                if hasattr(self.journal_activity, 'set_activity_log_id'):
                    self.journal_activity.set_activity_log_id(self._current_activity_log_id)
                
                success = self.journal_activity.run()
                if success:
                    logger.info("✅ Journal activity completed successfully")
                else:
                    logger.error("❌ Journal activity ended with failure or abnormal termination")
            except Exception as e:
                logger.error(f"Error in Journal activity: {e}", exc_info=True)
            finally:
                # Cleanup activity resources before restarting wakeword
                logger.info("🧹 Cleaning up Journal activity resources...")
                if self.journal_activity:
                    try:
                        self.journal_activity.cleanup()
                        logger.info("✅ Journal activity cleanup completed")
                        
                        # Re-initialize for next run
                        logger.info("🔄 Re-initializing Journal activity for next run...")
                        if not self.journal_activity.reinitialize():
                            logger.error("❌ Failed to re-initialize Journal activity")
                        else:
                            logger.info("✅ Journal activity re-initialized successfully")
                            
                    except Exception as e:
                        logger.warning(f"Error during activity cleanup/reinit: {e}")
                
                # Clear log ID
                self._current_activity_log_id = None
                
                # When activity ends, restart wake word detection
                self._restart_wakeword_detection()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_spiritual_quote_activity(self):
        """Start the spiritual quote activity thread."""
        logger.info("🧘 Starting Spiritual Quote activity…")

        if self.spiritual_quote_activity is None:
            logger.error("❌ Spiritual Quote activity is None - cannot start")
            return

        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "spiritual_quote"

        # Stop wake word pipeline first
        if self.voice_pipeline:
            logger.info("🔇 Pausing wake word pipeline before Spiritual Quote…")
            try:
                import threading
                stop_success = threading.Event()
                def force_stop():
                    try:
                        self.voice_pipeline.stop()
                        stop_success.set()
                    except Exception:
                        stop_success.set()
                threading.Thread(target=force_stop, daemon=True).start()
                stop_success.wait(timeout=5.0)
            except Exception as e:
                logger.warning(f"Ignoring error while stopping voice pipeline: {e}")

        def run_activity():
            try:
                if self.spiritual_quote_activity is None:
                    logger.error("❌ Spiritual Quote activity is None - cannot run")
                    return
                
                # Pass log_id to activity for completion tracking
                if hasattr(self.spiritual_quote_activity, 'set_activity_log_id'):
                    self.spiritual_quote_activity.set_activity_log_id(self._current_activity_log_id)
                
                ok = self.spiritual_quote_activity.run()
                if ok:
                    logger.info("✅ Spiritual Quote activity completed")
                else:
                    logger.error("❌ Spiritual Quote activity ended with failure")
            except Exception as e:
                logger.error(f"Error in Spiritual Quote activity: {e}", exc_info=True)
            finally:
                # Clear log ID
                self._current_activity_log_id = None
                
                # Re-initialize for next run
                try:
                    self.spiritual_quote_activity = SpiritualQuoteActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.spiritual_quote_activity.initialize()
                except Exception:
                    pass
                # Restart wakeword
                self._restart_wakeword_detection()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_gratitude_activity(self):
        """Start the gratitude activity thread."""
        logger.info("🙏 Starting Gratitude activity…")

        if self.gratitude_activity is None:
            logger.error("❌ Gratitude activity is None - cannot start")
            return

        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "gratitude"

        # Stop wake word pipeline first
        if self.voice_pipeline:
            logger.info("🔇 Pausing wake word pipeline before Gratitude…")
            try:
                import threading
                stop_success = threading.Event()
                def force_stop():
                    try:
                        self.voice_pipeline.stop()
                        stop_success.set()
                    except Exception:
                        stop_success.set()
                threading.Thread(target=force_stop, daemon=True).start()
                stop_success.wait(timeout=5.0)
            except Exception as e:
                logger.warning(f"Ignoring error while stopping voice pipeline: {e}")

        def run_activity():
            try:
                if self.gratitude_activity is None:
                    logger.error("❌ Gratitude activity is None - cannot run")
                    return
                
                # Pass log_id to activity for completion tracking
                if hasattr(self.gratitude_activity, 'set_activity_log_id'):
                    self.gratitude_activity.set_activity_log_id(self._current_activity_log_id)
                
                ok = self.gratitude_activity.run()
                if ok:
                    logger.info("✅ Gratitude activity completed")
                else:
                    logger.error("❌ Gratitude activity ended with failure")
            except Exception as e:
                logger.error(f"Error in Gratitude activity: {e}", exc_info=True)
            finally:
                # Clear log ID
                self._current_activity_log_id = None
                
                # Re-initialize for next run
                try:
                    self.gratitude_activity = GratitudeActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.gratitude_activity.initialize()
                except Exception:
                    pass
                # Restart wakeword
                self._restart_wakeword_detection()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_meditation_activity(self):
        """Start the meditation activity thread."""
        logger.info("🧘 Starting Meditation activity…")

        if self.meditation_activity is None:
            logger.error("❌ Meditation activity is None - cannot start")
            return

        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "meditation"

        # Stop wake word pipeline first
        if self.voice_pipeline:
            logger.info("🔇 Pausing wake word pipeline before Meditation…")
            try:
                import threading
                stop_success = threading.Event()
                def force_stop():
                    try:
                        self.voice_pipeline.stop()
                        stop_success.set()
                    except Exception:
                        stop_success.set()
                threading.Thread(target=force_stop, daemon=True).start()
                stop_success.wait(timeout=5.0)
            except Exception as e:
                logger.warning(f"Ignoring error while stopping voice pipeline: {e}")

        def run_activity():
            try:
                if self.meditation_activity is None:
                    logger.error("❌ Meditation activity is None - cannot run")
                    return
                
                # Pass log_id to activity for completion tracking
                if hasattr(self.meditation_activity, 'set_activity_log_id'):
                    self.meditation_activity.set_activity_log_id(self._current_activity_log_id)
                
                ok = self.meditation_activity.run()
                if ok:
                    logger.info("✅ Meditation activity completed")
                else:
                    logger.error("❌ Meditation activity ended with failure")
            except Exception as e:
                logger.error(f"Error in Meditation activity: {e}", exc_info=True)
            finally:
                # Clear log ID
                self._current_activity_log_id = None
                
                # Re-initialize for next run
                try:
                    self.meditation_activity = MeditationActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.meditation_activity.initialize()
                except Exception:
                    pass
                # Restart wakeword
                self._restart_wakeword_detection()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _restart_wakeword_detection(self):
        """Restart wake word detection after an activity ends."""
        logger.info("🔄 Restarting wake word detection…")
        
        # 1) Ensure complete cleanup of previous pipeline
        if self.voice_pipeline:
            logger.info("🧹 Performing complete pipeline cleanup...")
            try:
                # Stop the pipeline completely
                self.voice_pipeline.stop()
                
                # Wait for complete teardown
                logger.info("⏳ Waiting for complete pipeline teardown...")
                ok = self._wait_for_stt_teardown(timeout_s=5.0)
                if not ok:
                    logger.warning("⚠️ Pipeline teardown wait timed out")
                
                # Cleanup resources
                self.voice_pipeline.cleanup()
                logger.info("✅ Pipeline cleanup completed")
                
                # Add guard delay for Windows audio device release
                time.sleep(0.2)
                
            except Exception as e:
                logger.warning(f"Error during pipeline cleanup: {e}")
        
        # 2) Recreate the pipeline fresh to avoid resource conflicts
        logger.info("🔄 Recreating voice pipeline fresh...")
        try:
            self.voice_pipeline = create_voice_pipeline(
                access_key_file="",  # Deprecated - now uses environment variable
                custom_keyword_file=str(self.wakeword_model_path),
                language=self.global_config["language_codes"]["stt_language_code"],
                user_id=self.user_id,  # Pass user_id for user-specific config
                on_wake_callback=self._on_wake_detected,
                on_final_transcript=self._on_transcript_received,
                intent_config_path=None,  # Now loaded from language_config
                preference_file_path=None,  # Now loaded from language_config
                stt_timeout_s=self.global_config["wakeword"]["stt_timeout_s"]
            )
            logger.info("✅ Fresh voice pipeline created")
        except Exception as e:
            logger.error(f"Failed to recreate voice pipeline: {e}", exc_info=True)
            with self._lock:
                self.state = SystemState.SHUTTING_DOWN
            return
        
        # 3) Start the fresh pipeline
        with self._lock:
            self.state = SystemState.LISTENING
            self.current_activity = None
            
        try:
            self.voice_pipeline.start()
            logger.info("🎤 Wake word detection restarted – LISTENING for wake word")
        except Exception as e:
            logger.error(f"Failed to start fresh wake word pipeline: {e}", exc_info=True)
            with self._lock:
                self.state = SystemState.SHUTTING_DOWN

    def start(self) -> bool:
        """Start the entire orchestration system."""
        logger.info("=== Well-Bot Orchestrator Starting ===")

        if not self._validate_config_files():
            logger.error("Configuration validation failed")
            return False

        logger.info("✓ Global and language configurations loaded")

        if not self._initialize_components():
            logger.error("Component initialization failed")
            return False

        try:
            if self.voice_pipeline:
                self.voice_pipeline.start()
            with self._lock:
                self.state = SystemState.LISTENING
            logger.info("🎤 Wake word detection started – system ready")
            logger.info("Say the wake word to activate the system")
            return True
        except Exception as e:
            logger.error(f"Failed to start voice pipeline: {e}", exc_info=True)
            return False

    def stop(self):
        """Stop the orchestration system and all components."""
        logger.info("=== Well-Bot Orchestrator Shutting Down ===")

        with self._lock:
            self.state = SystemState.SHUTTING_DOWN

        # Stop activity if active
        if self.current_activity == "smalltalk" and self.smalltalk_activity:
            logger.info("Stopping SmallTalk activity…")
            self.smalltalk_activity.stop()
        elif self.current_activity == "journaling" and self.journal_activity:
            logger.info("Stopping Journal activity…")
            if self.journal_activity.is_active():
                # Journal activity's _cleanup will be called automatically when start() completes
                # But we can trigger cleanup if needed
                self.journal_activity.cleanup()
        elif self.current_activity == "quote" and self.spiritual_quote_activity:
            logger.info("Stopping Spiritual Quote activity…")
            if self.spiritual_quote_activity.is_active():
                self.spiritual_quote_activity.cleanup()
        elif self.current_activity == "meditation" and self.meditation_activity:
            logger.info("Stopping Meditation activity…")
            if self.meditation_activity.is_active():
                self.meditation_activity.cleanup()

        # Stop voice pipeline
        if self.voice_pipeline:
            logger.info("Stopping voice pipeline…")
            self.voice_pipeline.stop()
            try:
                self.voice_pipeline.cleanup()
            except Exception:
                pass

        # Cleanup TTS service
        if self.tts_service:
            logger.info("Cleaning up TTS service…")
            self.tts_service = None

        logger.info("✅ Well-Bot Orchestrator stopped")

    def is_active(self) -> bool:
        """Check if the orchestrator is still active (not shutting down)."""
        with self._lock:
            return self.state not in [SystemState.SHUTTING_DOWN]

    def get_status(self) -> Dict[str, Any]:
        """Return current system status snapshot."""
        with self._lock:
            return {
                "state": self.state.value,
                "current_activity": self.current_activity,
                "wakeword_active": bool(self.voice_pipeline and self.voice_pipeline.is_active()),
                "smalltalk_active": bool(self.smalltalk_activity and self.smalltalk_activity.is_active()),
                "journal_active": bool(self.journal_activity and self.journal_activity.is_active()),
                "quote_active": bool(self.spiritual_quote_activity and self.spiritual_quote_activity.is_active()),
                "meditation_active": bool(self.meditation_activity and self.meditation_activity.is_active())
            }

def main():
    orchestrator = WellBotOrchestrator()
    try:
        if not orchestrator.start():
            logger.error("Failed to start orchestrator")
            return 1

        logger.info("Well-Bot is now running!")
        logger.info("System flow:")
        logger.info("  1. Listen for wake word")
        logger.info("  2. Detect wake word → process speech/intent")
        logger.info("  3. Classify intent → route to activity")
        logger.info("  4. Run activity (e.g., SmallTalk)")
        logger.info("  5. Activity ends → restart wake word detection")
        logger.info("Press Ctrl+C to stop")

        while orchestrator.is_active():
            time.sleep(1)
            status = orchestrator.get_status()
            # optionally log debugging info
            # logger.debug(f"Status: {status}")
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received; shutting down…")
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        return 1
    finally:
        orchestrator.stop()
    logger.info("=== Well-Bot Backend Shutdown ===")
    return 0

if __name__ == "__main__":
    exit(main())
