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
from src.components.mic_stream import MicStream
# Lazy import activities (only import when needed to reduce memory footprint)
# from src.activities.smalltalk import SmallTalkActivity
# from src.activities.journal import JournalActivity
# from src.activities.spiritual_quote import SpiritualQuoteActivity
# from src.activities.meditation import MeditationActivity
# from src.activities.gratitude import GratitudeActivity
# from src.activities.activity_suggestion import ActivitySuggestionActivity
from src.activities.idle_mode import IdleModeActivity
from src.activities.wake_mode import WakeModeActivity
from src.utils.config_resolver import get_global_config_for_user, resolve_language, get_language_config
from src.supabase.auth import get_current_user_id, resolve_user_from_device_id
from src.supabase.database import log_activity_start, save_user_context_to_local, update_mood_rating
from src.components.activity_logger import prompt_mood_rating_before_activity, prompt_mood_rating_after_activity

# GUI imports
from src.components.ui_interface import UIInterface, NoOpUIInterface
from src.gui import start_gui
from src.utils.config_loader import DEVICE_ID, load_language_config
from src.components.tts import GoogleTTSClient
from google.cloud import texttospeech
import pyaudio

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
        
        # Resolve user from device_id at startup
        if not DEVICE_ID:
            # Load English config for error message (default)
            try:
                en_config = load_language_config('en')
                error_message = en_config.get('startup', {}).get('device_not_associated', 
                    "This device is not associated to any user. Please contact Well-Bot customer service for assistance.")
                
                # Speak error message via TTS
                logger.error("DEVICE_ID environment variable is not set")
                self._speak_startup_message(error_message, language='en')
                logger.error(error_message)
            except Exception as tts_error:
                logger.warning(f"Failed to speak error message: {tts_error}")
            
            raise ValueError(
                "DEVICE_ID environment variable is not set. "
                "Please set DEVICE_ID in your .env file to identify this device."
            )
        
        logger.info(f"Resolving user for device_id: {DEVICE_ID}")
        try:
            user_info = resolve_user_from_device_id(DEVICE_ID)
            self.user_id = user_info['user_id']
            self.prefer_name = user_info.get('prefer_name')
            self.full_name = user_info.get('full_name')
            
            # Save user info to user_persona.json
            save_user_context_to_local(
                user_id=self.user_id,
                prefer_name=self.prefer_name,
                full_name=self.full_name,
                backend_dir=self.backend_dir
            )
            logger.info(f"✓ User resolved and saved: user_id={self.user_id}, prefer_name={self.prefer_name}, full_name={self.full_name}")
        except ValueError as e:
            # Load English config for error message (default)
            try:
                en_config = load_language_config('en')
                error_message = en_config.get('startup', {}).get('device_not_associated',
                    "This device is not associated to any user. Please contact Well-Bot customer service for assistance.")
                
                # Speak error message via TTS
                logger.error(f"Failed to resolve user from device_id {DEVICE_ID}: {e}")
                self._speak_startup_message(error_message, language='en')
                logger.error(error_message)
            except Exception as tts_error:
                logger.warning(f"Failed to speak error message: {tts_error}")
            
            raise RuntimeError(
                f"Cannot start Well-Bot: {e}. "
                "Please ensure the device is registered in the database."
            ) from e
        
        # Load user-specific config (will be loaded in _initialize_components)
        self.global_config = None

        # Components
        self.idle_mode_activity: Optional[IdleModeActivity] = None
        self.wake_mode_activity: Optional[WakeModeActivity] = None
        # Activities are lazy-loaded (imported when needed)
        self.smalltalk_activity = None
        self.journal_activity = None
        self.spiritual_quote_activity = None
        self.meditation_activity = None
        self.gratitude_activity = None
        self.activity_suggestion_activity = None

        self.current_activity: Optional[str] = None
        self._activity_thread: Optional[threading.Thread] = None
        self._idle_mode_thread: Optional[threading.Thread] = None  # Track idle mode thread
        self._wake_mode_thread: Optional[threading.Thread] = None  # Track wake mode thread
        self._transitioning_to_activity = False  # Flag to prevent idle mode restart during activity transition
        self._restarting_idle_mode = False  # Flag to prevent multiple concurrent idle mode restarts
        self._current_activity_log_id: Optional[str] = None  # Track log ID for completion
        self._pre_activity_mood_rating: Optional[int] = None  # Store pre-activity mood rating
        
        # UI interface (for GUI updates)
        self.ui_interface = None
        self._gui_window = None

        logger.info("WellBotOrchestrator initialized")

    def _speak_startup_message(self, text: str, language: str = 'en') -> bool:
        """
        Speak a startup message using TTS.
        
        Args:
            text: Text to speak
            language: Language code ('en', 'cn', 'bm') - defaults to 'en'
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get language codes for TTS
            from src.utils.config_resolver import LANGUAGE_CODES
            lang_config = LANGUAGE_CODES.get(language, LANGUAGE_CODES['en'])
            
            # Initialize TTS service
            tts_service = GoogleTTSClient(
                voice_name=lang_config['tts_voice_name'],
                language_code=lang_config['tts_language_code'],
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                num_channels=1,
                sample_width_bytes=2
            )
            
            # Generate PCM chunks
            def text_gen():
                yield text
            
            pcm_chunks = tts_service.stream_synthesize(text_gen())
            
            # Play PCM chunks using PyAudio
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
            
            logger.info(f"TTS startup message played: {text[:50]}...")
            return True
            
        except Exception as e:
            logger.warning(f"Failed to speak startup message: {e}", exc_info=True)
            return False

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

    def _is_activity_running(self) -> bool:
        """
        Atomically check if any activity is currently running.
        
        Returns:
            True if an activity is active (state is ACTIVITY_ACTIVE and thread is alive), False otherwise
        """
        with self._lock:
            is_active = (
                self.state == SystemState.ACTIVITY_ACTIVE and
                self._activity_thread is not None and
                self._activity_thread.is_alive()
            )
            return is_active

    def _stop_idle_mode_for_activity(self):
        """Stop idle mode activity before starting another activity"""
        logger.info("🔇 Stopping idle mode activity before starting new activity…")
        
        # Set flag to prevent idle mode from restarting during transition
        self._transitioning_to_activity = True
        
        # Stop the activity object
        if self.idle_mode_activity:
            try:
                self.idle_mode_activity.stop()
                logger.info("✅ Idle mode activity stopped successfully")
            except Exception as e:
                logger.warning(f"Ignoring error while stopping idle mode: {e}")
                logger.info("⚠️ Continuing despite stop error...")
        
        # Wait for the idle mode thread to finish (if it's running)
        # Don't try to join if we're in the idle mode thread itself (would cause "cannot join current thread" error)
        if self._idle_mode_thread and self._idle_mode_thread.is_alive():
            current_thread = threading.current_thread()
            if self._idle_mode_thread is not current_thread:
                logger.info("Waiting for idle mode thread to finish...")
                # Set a timeout to avoid blocking indefinitely
                self._idle_mode_thread.join(timeout=2.0)
                # Check again after join (thread might have been cleared by another thread)
                if self._idle_mode_thread and self._idle_mode_thread.is_alive():
                    logger.warning("Idle mode thread did not finish within timeout, continuing anyway")
                else:
                    logger.info("✅ Idle mode thread finished")
            else:
                logger.debug("Idle mode thread is current thread - skipping join to avoid deadlock")
            self._idle_mode_thread = None
        
        # Add a tiny guard delay (Windows USB audio sometimes needs this)
        logger.info("⏱️ Adding guard delay for Windows audio device release...")
        time.sleep(0.15)

    def _initialize_components(self) -> bool:
        """Initialize STT, voice pipeline, activities."""
        try:
            # Resolve user language and load configs
            user_lang = resolve_language(self.user_id)
            logger.info(f"Resolved language '{user_lang}' for user {self.user_id}")
            
            self.global_config = get_global_config_for_user(self.user_id)
            logger.info(f"Loaded global config for user")

            logger.info("Initializing Idle Mode activity (wakeword detection)…")
            self.idle_mode_activity = IdleModeActivity(
                backend_dir=self.backend_dir,
                user_id=self.user_id,
                on_wake_detected=self._on_wake_detected,
                on_intervention_triggered=self._on_intervention_triggered
            )
            if not self.idle_mode_activity.initialize():
                raise RuntimeError("Failed to initialize Idle Mode activity")
            logger.info("✓ Idle Mode activity initialized")

            # Initialize Wake Mode activity
            logger.info("Initializing Wake Mode activity (intent recognition)…")
            self.wake_mode_activity = WakeModeActivity(
                backend_dir=self.backend_dir,
                user_id=self.user_id,
                on_intent_detected=self._handle_intent_detected
            )
            if not self.wake_mode_activity.initialize():
                raise RuntimeError("Failed to initialize Wake Mode activity")
            logger.info("✓ Wake Mode activity initialized")

            # Initialize UI interface
            self._initialize_ui()
            
            # Activities are lazy-loaded - only initialize when needed
            # This reduces memory footprint when idle_mode is running
            
            return True
        except Exception as e:
            logger.error(f"Component initialization failed: {e}", exc_info=True)
            return False

    def _initialize_ui(self):
        """Initialize UI interface based on configuration."""
        try:
            gui_config = self.global_config.get("gui", {})
            gui_enabled = gui_config.get("enabled", False)
            
            if gui_enabled:
                logger.info("Initializing UI interface for GUI...")
                self.ui_interface = UIInterface()
                logger.info("✓ UI interface initialized")
            else:
                logger.info("GUI disabled - using NoOp UI interface")
                self.ui_interface = NoOpUIInterface()
        except Exception as e:
            logger.warning(f"Failed to initialize UI interface: {e}")
            logger.warning("Falling back to NoOp UI interface")
            self.ui_interface = NoOpUIInterface()

    def _start_gui_if_enabled(self):
        """Start GUI window if enabled in configuration."""
        try:
            gui_config = self.global_config.get("gui", {})
            gui_enabled = gui_config.get("enabled", False)
            update_interval_ms = gui_config.get("update_interval_ms", 100)
            
            if gui_enabled and self.ui_interface and not isinstance(self.ui_interface, NoOpUIInterface):
                logger.info("Starting GUI window...")
                self._gui_window = start_gui(self.ui_interface, update_interval_ms)
                if self._gui_window:
                    logger.info("✓ GUI window started")
                else:
                    logger.warning("GUI window failed to start, continuing without GUI")
            else:
                logger.debug("GUI not enabled or NoOp interface in use")
        except Exception as e:
            logger.warning(f"Failed to start GUI: {e}")
            logger.warning("Continuing without GUI")

    def _handle_intent_detected(self, transcript: str, intent_result: Dict[str, Any]):
        """
        Callback when intent is detected by idle_mode activity.
        
        Args:
            transcript: The user's speech transcript
            intent_result: Dictionary with 'intent' and 'confidence' keys
        """
        logger.info(f"📝 Intent detected - Transcript: '{transcript}'")
        
        with self._lock:
            if self.state != SystemState.LISTENING:
                logger.warning(f"Intent detected but system in state {self.state.value}, ignoring")
                # Clear intent flags if we're ignoring this intent
                if self.idle_mode_activity:
                    try:
                        self.idle_mode_activity._intent_detected.clear()
                        self.idle_mode_activity._detected_intent = None
                        self.idle_mode_activity._detected_transcript = None
                    except:
                        pass
                return
            
            # Transition to processing state
            self.state = SystemState.PROCESSING
            logger.info("🎯 Transitioning to PROCESSING state")

        # Extract intent
        intent = intent_result.get('intent', 'unknown')
        confidence = intent_result.get('confidence', 0.0)
        logger.info(f"🎯 Intent: {intent} (confidence: {confidence:.3f})")

        # Transition to activity state
        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
        
        # Release lock before calling _route_to_activity to avoid deadlock
        self._route_to_activity(intent, transcript)

    def _prompt_pre_activity_mood_rating(self, intent: str) -> Optional[int]:
        """
        Prompt user for pre-activity mood rating.
        
        Args:
            intent: Activity intent name
            
        Returns:
            Mood rating (1-10) or None if skipped/timed out/error
        """
        try:
            # Get activity instance and initialize if needed
            activity = None
            if intent == "smalltalk":
                if self.smalltalk_activity is None:
                    from src.activities.smalltalk import SmallTalkActivity
                    self.smalltalk_activity = SmallTalkActivity(
                        backend_dir=self.backend_dir,
                        user_id=self.user_id,
                        ui_interface=self.ui_interface
                    )
                    if not self.smalltalk_activity.initialize():
                        logger.error("Failed to initialize SmallTalk activity for mood rating")
                        return None
                activity = self.smalltalk_activity
            elif intent == "journaling":
                if self.journal_activity is None:
                    from src.activities.journal import JournalActivity
                    self.journal_activity = JournalActivity(
                        backend_dir=self.backend_dir,
                        user_id=self.user_id
                    )
                    if not self.journal_activity.initialize():
                        logger.error("Failed to initialize Journal activity for mood rating")
                        return None
                activity = self.journal_activity
            elif intent == "meditation":
                if self.meditation_activity is None:
                    from src.activities.meditation import MeditationActivity
                    self.meditation_activity = MeditationActivity(
                        backend_dir=self.backend_dir,
                        user_id=self.user_id
                    )
                    if not self.meditation_activity.initialize():
                        logger.error("Failed to initialize Meditation activity for mood rating")
                        return None
                activity = self.meditation_activity
            elif intent == "quote":
                if self.spiritual_quote_activity is None:
                    from src.activities.spiritual_quote import SpiritualQuoteActivity
                    self.spiritual_quote_activity = SpiritualQuoteActivity(
                        backend_dir=self.backend_dir,
                        user_id=self.user_id
                    )
                    if not self.spiritual_quote_activity.initialize():
                        logger.error("Failed to initialize SpiritualQuote activity for mood rating")
                        return None
                activity = self.spiritual_quote_activity
            elif intent == "gratitude":
                if self.gratitude_activity is None:
                    from src.activities.gratitude import GratitudeActivity
                    self.gratitude_activity = GratitudeActivity(
                        backend_dir=self.backend_dir,
                        user_id=self.user_id
                    )
                    if not self.gratitude_activity.initialize():
                        logger.error("Failed to initialize Gratitude activity for mood rating")
                        return None
                activity = self.gratitude_activity
            
            if not activity:
                logger.warning(f"No activity found for intent: {intent}")
                return None
            
            # Get configs
            language_config = get_language_config(self.user_id)
            global_config = get_global_config_for_user(self.user_id)
            timeout_seconds = global_config.get("mood_rating", {}).get("timeout_seconds", 10.0)
            
            # Get TTS, STT, and audio_manager from activity
            tts_service = getattr(activity, 'tts_service', None)
            stt_service = getattr(activity, 'stt_service', None)
            audio_manager = getattr(activity, 'audio_manager', None)
            
            if not (tts_service and stt_service and audio_manager):
                logger.warning(f"Activity {intent} missing required services for mood rating")
                return None
            
            # Prompt for mood rating
            return prompt_mood_rating_before_activity(
                tts_service=tts_service,
                stt_service=stt_service,
                audio_manager=audio_manager,
                language_config=language_config,
                global_config=global_config,
                timeout_seconds=timeout_seconds
            )
        except Exception as e:
            logger.error(f"Error in _prompt_pre_activity_mood_rating: {e}", exc_info=True)
            return None

    def _prompt_post_activity_mood_rating(self, activity) -> Optional[int]:
        """
        Prompt user for post-activity mood rating.
        
        Args:
            activity: Activity instance
            
        Returns:
            Mood rating (1-10) or None if skipped/timed out/error
        """
        try:
            if not activity:
                return None
            
            # Get configs
            language_config = get_language_config(self.user_id)
            global_config = get_global_config_for_user(self.user_id)
            
            # Check if mood rating is enabled
            mood_rating_enabled = global_config.get("mood_rating", {}).get("enabled", True)
            if not mood_rating_enabled:
                logger.debug("Mood rating is disabled, skipping post-activity prompt")
                return None
            
            timeout_seconds = global_config.get("mood_rating", {}).get("timeout_seconds", 10.0)
            
            # Get TTS, STT, and audio_manager from activity
            tts_service = getattr(activity, 'tts_service', None)
            stt_service = getattr(activity, 'stt_service', None)
            audio_manager = getattr(activity, 'audio_manager', None)
            
            if not (tts_service and stt_service and audio_manager):
                logger.warning("Activity missing required services for mood rating")
                return None
            
            # Prompt for mood rating
            return prompt_mood_rating_after_activity(
                tts_service=tts_service,
                stt_service=stt_service,
                audio_manager=audio_manager,
                language_config=language_config,
                global_config=global_config,
                timeout_seconds=timeout_seconds
            )
        except Exception as e:
            logger.error(f"Error in _prompt_post_activity_mood_rating: {e}", exc_info=True)
            return None

    def _route_to_activity(self, intent: str, transcript: str, allow_nested_routing: bool = False):
        """Route the user to proper activity based on intent.
        
        Args:
            intent: The intent to route to
            transcript: The transcript associated with the intent
            allow_nested_routing: If True, allows routing when already in an activity (for activity_suggestion → other activity)
        """
        logger.info(f"🔄 Routing to activity: {intent}")
        
        # Check if an activity is already running
        # Store thread reference and activity name atomically to avoid race conditions
        with self._lock:
            is_running = (
                self.state == SystemState.ACTIVITY_ACTIVE and
                self._activity_thread is not None and
                self._activity_thread.is_alive()
            )
            current_activity_name = self.current_activity
            activity_thread_ref = self._activity_thread  # Store reference while holding lock
        
        if is_running:
            # Allow nested routing if explicitly requested (e.g., activity_suggestion routing to another activity)
            if allow_nested_routing:
                current_thread = threading.current_thread()
                if activity_thread_ref is current_thread:
                    logger.info(f"✅ Allowing nested routing from activity thread: {intent}")
                    # Clear current activity state before starting new activity to prevent guard from blocking
                    # The finally block of the old activity will skip cleanup due to nested_routing_occurred flag
                    with self._lock:
                        self._activity_thread = None
                        # Keep state as ACTIVITY_ACTIVE since new activity will set it
                else:
                    logger.warning(f"⚠️ Activity already running ({current_activity_name}), but allow_nested_routing=True requested from different thread - allowing anyway")
            else:
                logger.warning(f"⚠️ Cannot route to '{intent}': activity '{current_activity_name}' is already running. Ignoring routing request.")
                return

        # Map intent to activity type for logging
        intent_to_activity_type = {
            "smalltalk": "Support Chat",  # Smalltalk is logged as "Support Chat"
            "journaling": "Journaling",
            "meditation": "Meditation with Music",
            "quote": "Daily Quote",
            "gratitude": "Gratitude",
            "activity_suggestion": None,  # activity_suggestion routes to activities but doesn't log itself
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
            
            # Prompt for pre-activity mood rating (if enabled)
            try:
                global_config = get_global_config_for_user(self.user_id)
                mood_rating_enabled = global_config.get("mood_rating", {}).get("enabled", True)
                if mood_rating_enabled:
                    pre_rating = self._prompt_pre_activity_mood_rating(intent)
                    self._pre_activity_mood_rating = pre_rating
                    # Update database with pre-rating if provided
                    if pre_rating is not None:
                        update_mood_rating(public_id, pre_rating=pre_rating)
                else:
                    logger.debug("Mood rating is disabled, skipping pre-activity prompt")
                    self._pre_activity_mood_rating = None
            except Exception as e:
                logger.error(f"Error prompting for pre-activity mood rating: {e}", exc_info=True)
                # Non-blocking: continue even if mood rating fails
        else:
            self._current_activity_log_id = None
            self._pre_activity_mood_rating = None

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
        elif intent == "activity_suggestion":
            logger.info("Activity suggestion intent detected - launching activity suggestion")
            self._start_activity_suggestion_activity()
        elif intent == "termination":
            logger.info("👋 Termination intent detected – ending session")
            self._handle_termination()
        else:
            logger.info(f"❓ Unknown intent '{intent}' – prompting to repeat")
            self._handle_unknown_intent(transcript)

    def _start_smalltalk_activity(self):
        """Start the smalltalk activity thread."""
        logger.info("💬 Starting SmallTalk activity…")
        
        # Check if another activity is already running
        if self._is_activity_running():
            with self._lock:
                current_activity = self.current_activity
            logger.warning(f"⚠️ Cannot start SmallTalk activity: activity '{current_activity}' is already running. Ignoring start request.")
            with self._lock:
                self.state = SystemState.LISTENING
                self.current_activity = None
            return
        
        # Lazy import and initialize if needed
        if self.smalltalk_activity is None:
            from src.activities.smalltalk import SmallTalkActivity
            logger.info("Lazy loading SmallTalk activity...")
            self.smalltalk_activity = SmallTalkActivity(
                backend_dir=self.backend_dir, 
                user_id=self.user_id,
                ui_interface=self.ui_interface
            )
            if not self.smalltalk_activity.initialize():
                logger.error("❌ Failed to initialize SmallTalk activity")
                # Notify user that activity is unavailable
                from src.components.activity_error_handler import handle_activity_error
                handle_activity_error(self.backend_dir, self.user_id, activity_name="smalltalk")
                # Reset state back to LISTENING since activity failed
                with self._lock:
                    self.state = SystemState.LISTENING
                    self.current_activity = None
                # Restart idle mode since activity failed
                self._restart_idle_mode()
                return
        
        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "smalltalk"

        # Stop idle mode activity before starting SmallTalk
        self._stop_idle_mode_for_activity()

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
                # Prompt for post-activity mood rating before cleanup
                try:
                    if self._current_activity_log_id:
                        post_rating = self._prompt_post_activity_mood_rating(self.smalltalk_activity)
                        if post_rating is not None or self._pre_activity_mood_rating is not None:
                            # Update database with both pre and post ratings
                            update_mood_rating(
                                self._current_activity_log_id,
                                pre_rating=self._pre_activity_mood_rating,
                                post_rating=post_rating
                            )
                except Exception as e:
                    logger.error(f"Error prompting for post-activity mood rating: {e}", exc_info=True)
                    # Non-blocking: continue even if mood rating fails
                
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
                
                # Clear log ID and mood rating
                self._current_activity_log_id = None
                self._pre_activity_mood_rating = None
                
                # Clear activity thread reference to allow new activities to start
                with self._lock:
                    self._activity_thread = None
                
                # When activity ends, restart wake word detection
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()
        # Clear transition flag now that activity thread has started
        self._transitioning_to_activity = False

    def _handle_termination(self):
        """Handle termination intent by shutting down the system."""
        logger.info("👋 Termination intent received – shutting down system")
        with self._lock:
            self.state = SystemState.SHUTTING_DOWN
        self.stop()


    def _handle_unknown_intent(self, transcript: str):
        """Handle unknown/unrecognized intent by prompting user to repeat and looping back"""
        logger.info(f"Handling unknown intent for transcript: '{transcript}' - prompting to repeat")
        
        # Prompt user to repeat using TTS
        try:
            if self.idle_mode_activity and self.idle_mode_activity.tts_service:
                # Load prompt from config
                language_code = resolve_language(self.user_id)
                language_config = get_language_config(language_code)
                wakeword_responses_config = language_config.get("wakeword_responses", {})
                unknown_intent_prompt = wakeword_responses_config.get(
                    "unknown_intent",
                    "I didn't quite catch that. Could you call my name again and repeat please?"
                )
                logger.info(f"Speaking unknown intent prompt: {unknown_intent_prompt}")
                self.idle_mode_activity._speak(unknown_intent_prompt)
        except Exception as e:
            logger.warning(f"Failed to speak unknown intent prompt: {e}")
            # Fallback prompt
            try:
                if self.idle_mode_activity:
                    self.idle_mode_activity._speak("I didn't quite catch that. Could you call my name again and repeat please?")
            except Exception as e2:
                logger.error(f"Failed to speak fallback prompt: {e2}")
        
        # Clear any stale intent flags before restarting to prevent immediate re-detection
        if self.idle_mode_activity:
            try:
                self.idle_mode_activity._intent_detected.clear()
                self.idle_mode_activity._detected_intent = None
                self.idle_mode_activity._detected_transcript = None
                logger.debug("Cleared stale intent flags before restarting idle mode")
            except Exception as e:
                logger.warning(f"Error clearing intent flags: {e}")
        
        # Reset system state to LISTENING before restarting
        with self._lock:
            self.state = SystemState.LISTENING
        
        # Restart idle_mode to listen again
        logger.info("Restarting idle mode to listen for command again")
        self._restart_idle_mode()

    def _start_journal_activity(self):
        """Start the journal activity thread."""
        logger.info("📖 Starting Journal activity…")
        
        # Check if another activity is already running
        if self._is_activity_running():
            with self._lock:
                current_activity = self.current_activity
            logger.warning(f"⚠️ Cannot start Journal activity: activity '{current_activity}' is already running. Ignoring start request.")
            with self._lock:
                self.state = SystemState.LISTENING
                self.current_activity = None
            return
        
        # Lazy import and initialize if needed
        if self.journal_activity is None:
            from src.activities.journal import JournalActivity
            logger.info("Lazy loading Journal activity...")
            self.journal_activity = JournalActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.journal_activity.initialize():
                logger.error("❌ Failed to initialize Journal activity")
                # Notify user that activity is unavailable
                from src.components.activity_error_handler import handle_activity_error
                handle_activity_error(self.backend_dir, self.user_id, activity_name="journaling")
                # Reset state back to LISTENING since activity failed
                with self._lock:
                    self.state = SystemState.LISTENING
                    self.current_activity = None
                # Restart idle mode since activity failed
                self._restart_idle_mode()
                return
        
        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "journaling"

        # Stop idle mode activity before starting Journal
        self._stop_idle_mode_for_activity()

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
                # Prompt for post-activity mood rating before cleanup
                try:
                    if self._current_activity_log_id:
                        post_rating = self._prompt_post_activity_mood_rating(self.journal_activity)
                        if post_rating is not None or self._pre_activity_mood_rating is not None:
                            # Update database with both pre and post ratings
                            update_mood_rating(
                                self._current_activity_log_id,
                                pre_rating=self._pre_activity_mood_rating,
                                post_rating=post_rating
                            )
                except Exception as e:
                    logger.error(f"Error prompting for post-activity mood rating: {e}", exc_info=True)
                    # Non-blocking: continue even if mood rating fails
                
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
                
                # Clear log ID and mood rating
                self._current_activity_log_id = None
                self._pre_activity_mood_rating = None
                
                # Clear activity thread reference to allow new activities to start
                with self._lock:
                    self._activity_thread = None
                
                # When activity ends, restart wake word detection
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()
        # Clear transition flag now that activity thread has started
        self._transitioning_to_activity = False

    def _start_spiritual_quote_activity(self):
        """Start the spiritual quote activity thread."""
        logger.info("📜 Starting Spiritual Quote activity…")
        
        # Check if another activity is already running
        if self._is_activity_running():
            with self._lock:
                current_activity = self.current_activity
            logger.warning(f"⚠️ Cannot start Spiritual Quote activity: activity '{current_activity}' is already running. Ignoring start request.")
            with self._lock:
                self.state = SystemState.LISTENING
                self.current_activity = None
            return
        
        # Lazy import and initialize if needed
        if self.spiritual_quote_activity is None:
            from src.activities.spiritual_quote import SpiritualQuoteActivity
            logger.info("Lazy loading Spiritual Quote activity...")
            self.spiritual_quote_activity = SpiritualQuoteActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.spiritual_quote_activity.initialize():
                logger.error("❌ Failed to initialize Spiritual Quote activity")
                # Notify user that activity is unavailable
                from src.components.activity_error_handler import handle_activity_error
                handle_activity_error(self.backend_dir, self.user_id, activity_name="quote")
                # Reset state back to LISTENING since activity failed
                with self._lock:
                    self.state = SystemState.LISTENING
                    self.current_activity = None
                # Restart idle mode since activity failed
                self._restart_idle_mode()
                return

        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "spiritual_quote"

        # Stop idle mode activity before starting Spiritual Quote
        self._stop_idle_mode_for_activity()

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
                # Prompt for post-activity mood rating before cleanup
                try:
                    if self._current_activity_log_id:
                        post_rating = self._prompt_post_activity_mood_rating(self.spiritual_quote_activity)
                        if post_rating is not None or self._pre_activity_mood_rating is not None:
                            # Update database with both pre and post ratings
                            update_mood_rating(
                                self._current_activity_log_id,
                                pre_rating=self._pre_activity_mood_rating,
                                post_rating=post_rating
                            )
                except Exception as e:
                    logger.error(f"Error prompting for post-activity mood rating: {e}", exc_info=True)
                    # Non-blocking: continue even if mood rating fails
                
                # Clear log ID and mood rating
                self._current_activity_log_id = None
                self._pre_activity_mood_rating = None
                
                # Re-initialize for next run
                try:
                    self.spiritual_quote_activity = SpiritualQuoteActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.spiritual_quote_activity.initialize()
                except Exception:
                    pass
                
                # Clear activity thread reference to allow new activities to start
                with self._lock:
                    self._activity_thread = None
                
                # Restart wakeword
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()
        # Clear transition flag now that activity thread has started
        self._transitioning_to_activity = False

    def _start_gratitude_activity(self):
        """Start the gratitude activity thread."""
        logger.info("🙏 Starting Gratitude activity…")
        
        # Check if another activity is already running
        if self._is_activity_running():
            with self._lock:
                current_activity = self.current_activity
            logger.warning(f"⚠️ Cannot start Gratitude activity: activity '{current_activity}' is already running. Ignoring start request.")
            with self._lock:
                self.state = SystemState.LISTENING
                self.current_activity = None
            return
        
        # Lazy import and initialize if needed
        if self.gratitude_activity is None:
            from src.activities.gratitude import GratitudeActivity
            logger.info("Lazy loading Gratitude activity...")
            self.gratitude_activity = GratitudeActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.gratitude_activity.initialize():
                logger.error("❌ Failed to initialize Gratitude activity")
                # Notify user that activity is unavailable
                from src.components.activity_error_handler import handle_activity_error
                handle_activity_error(self.backend_dir, self.user_id, activity_name="gratitude")
                # Reset state back to LISTENING since activity failed
                with self._lock:
                    self.state = SystemState.LISTENING
                    self.current_activity = None
                # Restart idle mode since activity failed
                self._restart_idle_mode()
                return

        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "gratitude"

        # Stop idle mode activity before starting Gratitude
        self._stop_idle_mode_for_activity()

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
                # Prompt for post-activity mood rating before cleanup
                try:
                    if self._current_activity_log_id:
                        post_rating = self._prompt_post_activity_mood_rating(self.gratitude_activity)
                        if post_rating is not None or self._pre_activity_mood_rating is not None:
                            # Update database with both pre and post ratings
                            update_mood_rating(
                                self._current_activity_log_id,
                                pre_rating=self._pre_activity_mood_rating,
                                post_rating=post_rating
                            )
                except Exception as e:
                    logger.error(f"Error prompting for post-activity mood rating: {e}", exc_info=True)
                    # Non-blocking: continue even if mood rating fails
                
                # Clear log ID and mood rating
                self._current_activity_log_id = None
                self._pre_activity_mood_rating = None
                
                # Re-initialize for next run
                try:
                    self.gratitude_activity = GratitudeActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.gratitude_activity.initialize()
                except Exception:
                    pass
                
                # Clear activity thread reference to allow new activities to start
                with self._lock:
                    self._activity_thread = None
                
                # Restart wakeword
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()
        # Clear transition flag now that activity thread has started
        self._transitioning_to_activity = False

    def _start_meditation_activity(self):
        """Start the meditation activity thread."""
        logger.info("🧘 Starting Meditation activity…")
        
        # Check if another activity is already running
        if self._is_activity_running():
            with self._lock:
                current_activity = self.current_activity
            logger.warning(f"⚠️ Cannot start Meditation activity: activity '{current_activity}' is already running. Ignoring start request.")
            with self._lock:
                self.state = SystemState.LISTENING
                self.current_activity = None
            return
        
        # Lazy import and initialize if needed
        if self.meditation_activity is None:
            from src.activities.meditation import MeditationActivity
            logger.info("Lazy loading Meditation activity...")
            self.meditation_activity = MeditationActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.meditation_activity.initialize():
                logger.error("❌ Failed to initialize Meditation activity")
                # Notify user that activity is unavailable
                from src.components.activity_error_handler import handle_activity_error
                handle_activity_error(self.backend_dir, self.user_id, activity_name="meditation")
                # Reset state back to LISTENING since activity failed
                with self._lock:
                    self.state = SystemState.LISTENING
                    self.current_activity = None
                # Restart idle mode since activity failed
                self._restart_idle_mode()
                return

        # Set state first, then stop idle mode (consistent with other activities)
        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "meditation"

        # Stop idle mode activity after setting state to ensure STT sessions are stopped
        self._stop_idle_mode_for_activity()

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
                # Prompt for post-activity mood rating before cleanup
                try:
                    if self._current_activity_log_id:
                        post_rating = self._prompt_post_activity_mood_rating(self.meditation_activity)
                        if post_rating is not None or self._pre_activity_mood_rating is not None:
                            # Update database with both pre and post ratings
                            update_mood_rating(
                                self._current_activity_log_id,
                                pre_rating=self._pre_activity_mood_rating,
                                post_rating=post_rating
                            )
                except Exception as e:
                    logger.error(f"Error prompting for post-activity mood rating: {e}", exc_info=True)
                    # Non-blocking: continue even if mood rating fails
                
                # Clear log ID and mood rating
                self._current_activity_log_id = None
                self._pre_activity_mood_rating = None
                
                # Re-initialize for next run
                try:
                    self.meditation_activity = MeditationActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.meditation_activity.initialize()
                except Exception:
                    pass
                
                # Clear activity thread reference to allow new activities to start
                with self._lock:
                    self._activity_thread = None
                
                # Restart wakeword
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()
        # Clear transition flag now that activity thread has started
        self._transitioning_to_activity = False

    def _start_activity_suggestion_activity(self):
        """Start the activity suggestion activity thread."""
        logger.info("💡 Starting Activity Suggestion activity…")
        
        # Check if another activity is already running
        if self._is_activity_running():
            with self._lock:
                current_activity = self.current_activity
            logger.warning(f"⚠️ Cannot start Activity Suggestion activity: activity '{current_activity}' is already running. Ignoring start request.")
            with self._lock:
                self.state = SystemState.LISTENING
                self.current_activity = None
            return
        
        # Lazy import and initialize if needed
        if self.activity_suggestion_activity is None:
            from src.activities.activity_suggestion import ActivitySuggestionActivity
            logger.info("Lazy loading Activity Suggestion activity...")
            self.activity_suggestion_activity = ActivitySuggestionActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.activity_suggestion_activity.initialize():
                logger.error("❌ Failed to initialize Activity Suggestion activity")
                return
        
        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "activity_suggestion"

        # Stop idle mode activity before starting Activity Suggestion
        self._stop_idle_mode_for_activity()

        def run_activity():
            nested_routing_occurred = False  # Track if we routed to another activity
            try:
                if self.activity_suggestion_activity is None:
                    logger.error("❌ Activity Suggestion activity is None - cannot run")
                    return
                
                success = self.activity_suggestion_activity.run()
                
                # Store selected activity and context before cleanup
                selected_activity = None
                conversation_context = []
                if self.activity_suggestion_activity:
                    selected_activity = self.activity_suggestion_activity.get_selected_activity()
                    conversation_context = self.activity_suggestion_activity.get_conversation_context()
                
                if success:
                    logger.info("✅ Activity Suggestion activity completed successfully")
                    
                    # Check for termination first
                    if self.activity_suggestion_activity and self.activity_suggestion_activity.is_termination_detected():
                        logger.info("👋 Termination phrase detected in activity suggestion - returning to idle mode")
                        # Cleanup and restart idle mode
                        if self.activity_suggestion_activity:
                            try:
                                self.activity_suggestion_activity.cleanup()
                                self.activity_suggestion_activity.reinitialize()
                            except Exception as e:
                                logger.warning(f"Error during cleanup: {e}")
                        
                        # Reset state and restart wakeword detection
                        with self._lock:
                            self.state = SystemState.LISTENING
                        
                        logger.info("🔄 Restarting idle mode after termination")
                        self._restart_idle_mode()
                        return  # Exit early - don't route to any activity
                    
                    # Check if timeout occurred (special sentinel value)
                    if selected_activity == "__timeout__":
                        logger.info("Timeout occurred - skipping routing, will return to wakeword")
                        # Don't route anywhere, just let finally block restart wakeword
                        return
                    
                    if selected_activity:
                        # Route to selected activity
                        logger.info(f"🎯 Routing to selected activity: {selected_activity}")
                        # Use transcript from context if available, otherwise empty
                        transcript = ""
                        if conversation_context:
                            # Get last user message
                            for msg in reversed(conversation_context):
                                if msg.get("role") == "user":
                                    transcript = msg.get("content", "")
                                    break
                        
                        # Cleanup before routing (routing will handle state)
                        if self.activity_suggestion_activity:
                            try:
                                self.activity_suggestion_activity.cleanup()
                                self.activity_suggestion_activity.reinitialize()
                            except Exception as e:
                                logger.warning(f"Error during cleanup before routing: {e}")
                        
                        # Route to the selected activity (this will handle state management)
                        # Allow nested routing since we're routing from within activity_suggestion
                        nested_routing_occurred = True
                        self._route_to_activity(selected_activity, transcript, allow_nested_routing=True)
                        return  # Don't restart wakeword - routing handles it
                    else:
                        # No match - route to smalltalk with context
                        logger.info("No activity selected - routing to smalltalk with context")
                        if conversation_context and self.smalltalk_activity:
                            # Seed smalltalk with conversation context
                            context_text = "\n".join([
                                f"{msg.get('role', 'unknown')}: {msg.get('content', '')}"
                                for msg in conversation_context
                                if msg.get("role") in ["user", "assistant"]
                            ])
                            seed_prompt = f"Continue the conversation from activity suggestion. Previous context:\n{context_text}"
                            self.smalltalk_activity.add_system_message(seed_prompt)
                        
                        # Cleanup before routing
                        if self.activity_suggestion_activity:
                            try:
                                self.activity_suggestion_activity.cleanup()
                                self.activity_suggestion_activity.reinitialize()
                            except Exception as e:
                                logger.warning(f"Error during cleanup before routing: {e}")
                        
                        # Route to smalltalk (this will handle state management)
                        # Allow nested routing since we're routing from within activity_suggestion
                        nested_routing_occurred = True
                        self._route_to_activity("smalltalk", "", allow_nested_routing=True)
                        return  # Don't restart wakeword - routing handles it
                else:
                    logger.error("❌ Activity Suggestion activity ended with failure")
            except Exception as e:
                logger.error(f"Error in Activity Suggestion activity: {e}", exc_info=True)
            finally:
                # Cleanup activity resources (only if we didn't route to another activity)
                logger.info("🧹 Cleaning up Activity Suggestion activity resources...")
                if self.activity_suggestion_activity:
                    try:
                        self.activity_suggestion_activity.cleanup()
                        logger.info("✅ Activity Suggestion activity cleanup completed")
                        
                        # Re-initialize for next run
                        logger.info("🔄 Re-initializing Activity Suggestion activity for next run...")
                        if not self.activity_suggestion_activity.reinitialize():
                            logger.error("❌ Failed to re-initialize Activity Suggestion activity")
                        else:
                            logger.info("✅ Activity Suggestion activity re-initialized successfully")
                            
                    except Exception as e:
                        logger.warning(f"Error during activity cleanup/reinit: {e}")
                
                # Only clear thread reference and reset state if we didn't route to another activity
                # When nested routing occurs, the new activity manages its own state and thread
                if not nested_routing_occurred:
                    # Clear activity thread reference to allow new activities to start
                    with self._lock:
                        self._activity_thread = None
                    
                    # Reset state and restart wakeword detection
                    with self._lock:
                        self.state = SystemState.LISTENING
                    
                    logger.info("🔄 Restarting wake word detection after activity suggestion completion")
                    self._restart_idle_mode()
                else:
                    logger.info("⏭️ Skipping state reset and idle mode restart - nested routing occurred, new activity manages state")

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()
        # Clear transition flag now that activity thread has started
        self._transitioning_to_activity = False

    def _start_idle_mode_activity(self):
        """Start the idle mode activity in a thread with error handling"""
        logger.info("🎬 Starting idle mode activity...")
        
        # Check if an activity is already running - idle mode should not start if an activity is active
        if self._is_activity_running():
            with self._lock:
                current_activity = self.current_activity
            logger.warning(f"⚠️ Cannot start idle mode: activity '{current_activity}' is already running. Idle mode will start after activity completes.")
            return
        
        # Check if there's already a running idle mode thread
        if self._idle_mode_thread and self._idle_mode_thread.is_alive():
            current_thread = threading.current_thread()
            if self._idle_mode_thread is current_thread:
                logger.warning("⚠️ Cannot start idle mode from within idle mode thread - skipping")
                return
            logger.warning("⚠️ Idle mode thread is already running - stopping it first")
            try:
                if self.idle_mode_activity:
                    self.idle_mode_activity.stop()
                # Check if thread is still valid before joining
                if self._idle_mode_thread:
                    self._idle_mode_thread.join(timeout=1.0)
                    # Check again after join (thread might have been cleared)
                    if self._idle_mode_thread and self._idle_mode_thread.is_alive():
                        logger.warning("Previous idle mode thread did not finish within timeout")
            except Exception as e:
                logger.warning(f"Error stopping previous idle mode thread: {e}")
            finally:
                self._idle_mode_thread = None
        
        def run_idle_mode():
            try:
                if not self.idle_mode_activity:
                    logger.error("Idle mode activity is None - cannot start")
                    return
                
                # Run the idle mode activity (this will block until wake word/intervention detected)
                success = self.idle_mode_activity.run()
                
                if success:
                    logger.info("✅ Idle mode completed (wake word/intervention detected)")
                    # Note: wake_mode should already be started by callback, but check if it wasn't
                    # This is a fallback in case callback didn't fire
                    with self._lock:
                        if self._wake_mode_thread is None or not self._wake_mode_thread.is_alive():
                            logger.warning("Wake mode not started by callback - starting now as fallback")
                            intervention_mode = False
                            if hasattr(self.idle_mode_activity, 'was_last_trigger_intervention'):
                                intervention_mode = self.idle_mode_activity.was_last_trigger_intervention()
                            self._start_wake_mode(intervention_mode=intervention_mode)
                else:
                    logger.info("⏰ Idle mode exited without wake word/intervention (stopped)")
                    # Restart idle mode if needed
                    self._restart_idle_mode_if_needed()
                    
            except Exception as e:
                logger.error(f"Error running idle mode activity: {e}", exc_info=True)
                # Attempt to restart idle mode on error
                try:
                    logger.info("Attempting to restart idle mode after error...")
                    time.sleep(1.0)  # Brief delay before retry
                    if self.idle_mode_activity:
                        if self.idle_mode_activity.reinitialize():
                            self._start_idle_mode_activity()
                        else:
                            logger.error("Failed to reinitialize idle mode after error")
                except Exception as retry_error:
                    logger.error(f"Failed to restart idle mode: {retry_error}")
            finally:
                # Clear thread reference when thread exits
                with self._lock:
                    if self._idle_mode_thread == threading.current_thread():
                        self._idle_mode_thread = None
        
        # Start idle mode in a daemon thread and track it
        self._idle_mode_thread = threading.Thread(target=run_idle_mode, daemon=True)
        self._idle_mode_thread.start()
        logger.info("✅ Idle mode activity thread started")

    def _on_wake_detected(self):
        """Callback when wake word is detected by idle_mode - start wake_mode immediately"""
        logger.info("🔔 Wake word detected callback - starting wake_mode immediately")
        
        # Check system state
        with self._lock:
            current_state = self.state
        
        if current_state != SystemState.LISTENING:
            logger.info(f"System state is {current_state.value}, not LISTENING - skipping wake_mode start")
            return
        
        # Start wake_mode immediately (non-blocking)
        intervention_mode = False
        if self.idle_mode_activity and hasattr(self.idle_mode_activity, 'was_last_trigger_intervention'):
            intervention_mode = self.idle_mode_activity.was_last_trigger_intervention()
        
        # Start wake_mode in a separate thread to avoid blocking
        def start_wake_mode_async():
            time.sleep(0.05)  # Tiny delay to ensure idle_mode flag is set
            self._start_wake_mode(intervention_mode=intervention_mode)
        
        threading.Thread(target=start_wake_mode_async, daemon=True).start()
    
    def _on_intervention_triggered(self):
        """Callback when intervention is triggered by idle_mode - start wake_mode immediately"""
        logger.info("🔔 Intervention triggered callback - starting wake_mode immediately")
        
        # Check system state
        with self._lock:
            current_state = self.state
        
        if current_state != SystemState.LISTENING:
            logger.info(f"System state is {current_state.value}, not LISTENING - skipping wake_mode start")
            return
        
        # Start wake_mode immediately in intervention mode (non-blocking)
        def start_wake_mode_async():
            time.sleep(0.05)  # Tiny delay to ensure idle_mode flag is set
            self._start_wake_mode(intervention_mode=True)
        
        threading.Thread(target=start_wake_mode_async, daemon=True).start()
    
    def _start_wake_mode(self, intervention_mode: bool = False):
        """Start the wake mode activity in a thread with error handling"""
        logger.info("🎬 Starting wake mode activity...")
        
        # Check if there's already a running wake mode thread
        if self._wake_mode_thread and self._wake_mode_thread.is_alive():
            current_thread = threading.current_thread()
            if self._wake_mode_thread is current_thread:
                logger.warning("⚠️ Cannot start wake mode from within wake mode thread - skipping")
                return
            logger.warning("⚠️ Wake mode thread is already running - stopping it first")
            try:
                if self.wake_mode_activity:
                    self.wake_mode_activity.stop()
                # Check if thread is still valid before joining
                if self._wake_mode_thread:
                    self._wake_mode_thread.join(timeout=1.0)
                    if self._wake_mode_thread and self._wake_mode_thread.is_alive():
                        logger.warning("Previous wake mode thread did not finish within timeout")
            except Exception as e:
                logger.warning(f"Error stopping previous wake mode thread: {e}")
            finally:
                self._wake_mode_thread = None
        
        def run_wake_mode():
            try:
                if not self.wake_mode_activity:
                    logger.error("Wake mode activity is None - cannot start")
                    return
                
                # Start wake mode
                if not self.wake_mode_activity.start(intervention_mode=intervention_mode):
                    logger.error("Failed to start wake mode activity")
                    return
                
                # Run the wake mode activity (this will block until intent detected or timeout)
                success = self.wake_mode_activity.run()
                
                if success:
                    logger.info("✅ Wake mode completed successfully (intent detected)")
                    # Get detected intent and transcript
                    detected_intent = self.wake_mode_activity.get_detected_intent()
                    detected_transcript = self.wake_mode_activity.get_detected_transcript()
                    
                    # Check system state
                    with self._lock:
                        current_state = self.state
                    
                    if current_state != SystemState.LISTENING:
                        logger.info(f"System state is {current_state.value}, not LISTENING - skipping intent routing")
                        return
                    
                    if detected_intent:
                        # Update state before routing
                        with self._lock:
                            if self.state == SystemState.LISTENING:
                                self.state = SystemState.PROCESSING
                                logger.info("🎯 Transitioning to PROCESSING state")
                            self.state = SystemState.ACTIVITY_ACTIVE
                        
                        # Route to activity based on detected intent
                        intent = detected_intent.get('intent', 'unknown')
                        transcript = detected_transcript or ""
                        logger.info(f"🎯 Routing to activity based on detected intent: {intent}")
                        
                        self._route_to_activity(intent, transcript)
                    else:
                        logger.warning("Wake mode completed but no intent detected")
                        # Restart idle mode
                        self._restart_idle_mode_if_needed()
                else:
                    logger.info("⏰ Wake mode exited without intent detection (timeout)")
                    # Restart idle mode
                    self._restart_idle_mode_if_needed()
                    
            except Exception as e:
                logger.error(f"Error running wake mode activity: {e}", exc_info=True)
                # Restart idle mode on error
                self._restart_idle_mode_if_needed()
            finally:
                # Clear thread reference when thread exits
                with self._lock:
                    if self._wake_mode_thread == threading.current_thread():
                        self._wake_mode_thread = None
        
        # Start wake mode in a daemon thread and track it
        self._wake_mode_thread = threading.Thread(target=run_wake_mode, daemon=True)
        self._wake_mode_thread.start()
        logger.info("✅ Wake mode activity thread started")

    def _stop_wake_mode(self):
        """Stop the wake mode activity"""
        logger.info("Stopping wake mode activity...")
        
        current_thread = threading.current_thread()
        if self._wake_mode_thread and self._wake_mode_thread.is_alive():
            if self._wake_mode_thread is current_thread:
                logger.warning("Cannot stop wake mode from within wake mode thread")
                return
            
            try:
                if self.wake_mode_activity:
                    self.wake_mode_activity.stop()
                # Check if thread is still valid before joining
                if self._wake_mode_thread:
                    self._wake_mode_thread.join(timeout=2.0)
                    if self._wake_mode_thread and self._wake_mode_thread.is_alive():
                        logger.warning("Wake mode thread did not finish within timeout during stop")
                    else:
                        logger.info("✅ Wake mode thread finished")
            except Exception as e:
                logger.warning(f"Error waiting for wake mode thread: {e}")
            finally:
                self._wake_mode_thread = None
        
        logger.info("✅ Wake mode stopped")
    
    def _restart_idle_mode_if_needed(self):
        """Helper to restart idle mode if needed (checks state and flags)"""
        # Check if we're transitioning to an activity
        if self._transitioning_to_activity:
            logger.info("System is transitioning to activity - skipping idle mode restart")
            return
        
        # Check if restart is already in progress
        with self._lock:
            if self._restarting_idle_mode:
                logger.info("Idle mode restart already in progress - skipping duplicate restart")
                return
            current_state = self.state
        
        if current_state in [SystemState.PROCESSING, SystemState.ACTIVITY_ACTIVE]:
            logger.info("System state indicates activity transition - skipping idle mode restart")
            return
        
        # Restart idle mode
        logger.info("🔄 Restarting idle mode...")
        current_thread = threading.current_thread()
        if self._idle_mode_thread is current_thread:
            # We're in the idle mode thread - schedule restart from a different thread
            logger.info("Scheduling idle mode restart from outside thread...")
            def restart_from_outside():
                time.sleep(0.1)  # Brief delay to ensure thread cleanup
                self._restart_idle_mode()
            threading.Thread(target=restart_from_outside, daemon=True).start()
        else:
            # We're not in the idle mode thread - safe to restart directly
            self._restart_idle_mode()

    def _restart_idle_mode(self):
        """Restart idle mode activity after an activity ends."""
        logger.info("🔄 Restarting idle mode activity…")
        
        # Prevent concurrent restart attempts
        with self._lock:
            if self._restarting_idle_mode:
                logger.warning("Idle mode restart already in progress - skipping duplicate restart")
                return
            self._restarting_idle_mode = True
        
        # Prevent calling from within idle mode thread
        current_thread = threading.current_thread()
        if self._idle_mode_thread and self._idle_mode_thread.is_alive():
            if self._idle_mode_thread is current_thread:
                logger.warning("Cannot restart idle mode from within idle mode thread - skipping")
                with self._lock:
                    self._restarting_idle_mode = False
                return
        
        try:
            # 1) Wait for any existing idle mode thread to finish first
            if self._idle_mode_thread and self._idle_mode_thread.is_alive():
                logger.info("Waiting for existing idle mode thread to finish...")
                try:
                    if self.idle_mode_activity:
                        self.idle_mode_activity.stop()
                    # Check if thread is still valid before joining
                    if self._idle_mode_thread:
                        self._idle_mode_thread.join(timeout=2.0)
                        if self._idle_mode_thread and self._idle_mode_thread.is_alive():
                            logger.warning("Idle mode thread did not finish within timeout during restart")
                        else:
                            logger.info("✅ Existing idle mode thread finished")
                except Exception as e:
                    logger.warning(f"Error waiting for idle mode thread: {e}")
                finally:
                    self._idle_mode_thread = None
            
            # 2) Ensure complete cleanup of previous idle mode
            if self.idle_mode_activity:
                logger.info("🧹 Performing complete idle mode cleanup...")
                try:
                    # Stop the activity completely
                    self.idle_mode_activity.stop()
                    
                    # Cleanup resources
                    self.idle_mode_activity.cleanup()
                    logger.info("✅ Idle mode cleanup completed")
                    
                    # Re-initialize for next run
                    logger.info("🔄 Re-initializing idle mode activity...")
                    if not self.idle_mode_activity.reinitialize():
                        logger.error("❌ Failed to re-initialize idle mode activity")
                        with self._lock:
                            self._restarting_idle_mode = False
                        raise RuntimeError("Failed to re-initialize idle mode")
                    
                    logger.info("✅ Idle mode re-initialized successfully")
                except Exception as e:
                    logger.error(f"Error during idle mode cleanup/reinit: {e}", exc_info=True)
                    # Try to recreate the activity if reinit failed
                    try:
                        logger.info("Attempting to recreate idle mode activity...")
                        self.idle_mode_activity = IdleModeActivity(
                            backend_dir=self.backend_dir,
                            user_id=self.user_id,
                            on_wake_detected=self._on_wake_detected,
                            on_intervention_triggered=self._on_intervention_triggered
                        )
                        if not self.idle_mode_activity.initialize():
                            raise RuntimeError("Failed to recreate idle mode activity")
                    except Exception as recreate_error:
                        logger.error(f"Failed to recreate idle mode activity: {recreate_error}", exc_info=True)
                        with self._lock:
                            self.state = SystemState.SHUTTING_DOWN
                        with self._lock:
                            self._restarting_idle_mode = False
                        return
            # 3) Reset state and clear transition flag
            with self._lock:
                self.state = SystemState.LISTENING
                self.current_activity = None
            
            # Clear any stale intent flags to prevent immediate re-detection
            # This is critical when restarting after activity failures
            if self.idle_mode_activity:
                try:
                    self.idle_mode_activity._intent_detected.clear()
                    self.idle_mode_activity._detected_intent = None
                    self.idle_mode_activity._detected_transcript = None
                    logger.debug("Cleared stale intent flags in _restart_idle_mode")
                except Exception as e:
                    logger.warning(f"Error clearing intent flags in _restart_idle_mode: {e}")
            
            self._transitioning_to_activity = False  # Clear flag when restarting idle mode
            
            # 4) Start the idle mode activity (will check for existing thread)
            self._start_idle_mode_activity()
            logger.info("🎤 Idle mode restarted – LISTENING for wake word")
        except Exception as e:
            logger.error(f"Failed to restart idle mode: {e}", exc_info=True)
            with self._lock:
                self.state = SystemState.SHUTTING_DOWN
        finally:
            # Clear restart flag when done (only if not already cleared)
            with self._lock:
                if self._restarting_idle_mode:
                    self._restarting_idle_mode = False
            
            # Add guard delay for Windows audio device release
            time.sleep(0.2)

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

        # Speak startup success message before starting idle mode
        try:
            # Get user's language preference
            user_language = resolve_language(self.user_id)
            
            # Load language config for user's language
            language_config = get_language_config(self.user_id)
            
            # Get success message template
            success_template = language_config.get('startup', {}).get('startup_completed',
                "Startup completed. Hi {name}, call me Well-Bot to wake me up!")
            
            # Format message with user's name (prefer prefer_name, fallback to full_name, then "there")
            user_name = self.prefer_name or self.full_name or "there"
            success_message = success_template.format(name=user_name)
            
            # Speak success message via TTS
            logger.info("Speaking startup completion message...")
            self._speak_startup_message(success_message, language=user_language)
            logger.info(f"✓ Startup success message: {success_message}")
        except Exception as e:
            logger.warning(f"Failed to speak startup success message: {e}", exc_info=True)
            # Continue startup even if TTS fails

        try:
            # Start idle mode activity (emotion monitoring is managed internally by idle_mode)
            if self.idle_mode_activity:
                self._start_idle_mode_activity()
            else:
                logger.error("Idle mode activity not initialized")
                return False
            
            with self._lock:
                self.state = SystemState.LISTENING
            
            # Start GUI if enabled
            self._start_gui_if_enabled()
            
            logger.info("🎤 Idle mode started – system ready")
            logger.info("Say the wake word to activate the system")
            return True
        except Exception as e:
            logger.error(f"Failed to start idle mode: {e}", exc_info=True)
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

        # Stop wake mode activity
        self._stop_wake_mode()

        # Stop idle mode activity (emotion monitoring is stopped internally)
        if self.idle_mode_activity:
            logger.info("Stopping idle mode activity…")
            self.idle_mode_activity.stop()
            try:
                self.idle_mode_activity.cleanup()
            except Exception:
                pass

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
                "wakeword_active": bool(self.idle_mode_activity and self.idle_mode_activity.is_active()),
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

        # On Windows, update GUI periodically in main thread
        import sys
        gui_update_interval = 0.05  # 50ms for smooth GUI updates
        last_gui_update = time.time()
        
        while orchestrator.is_active():
            # Update GUI if on Windows and GUI exists
            if sys.platform == "win32" and orchestrator._gui_window:
                current_time = time.time()
                if current_time - last_gui_update >= gui_update_interval:
                    try:
                        orchestrator._gui_window.update_non_blocking()
                        last_gui_update = current_time
                    except Exception as e:
                        # GUI might be closed
                        if "application has been destroyed" not in str(e).lower():
                            logger.debug(f"GUI update error: {e}")
                        orchestrator._gui_window = None
            
            time.sleep(0.1)  # Smaller sleep for more responsive GUI updates
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
