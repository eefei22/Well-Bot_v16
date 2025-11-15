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
from src.utils.config_resolver import get_global_config_for_user, resolve_language
from src.supabase.auth import get_current_user_id
from src.supabase.database import log_activity_start

# GUI imports
from src.components.ui_interface import UIInterface, NoOpUIInterface
from src.gui import start_gui

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
        self.idle_mode_activity: Optional[IdleModeActivity] = None
        # Activities are lazy-loaded (imported when needed)
        self.smalltalk_activity = None
        self.journal_activity = None
        self.spiritual_quote_activity = None
        self.meditation_activity = None
        self.gratitude_activity = None
        self.activity_suggestion_activity = None

        self.current_activity: Optional[str] = None
        self._activity_thread: Optional[threading.Thread] = None
        self._current_activity_log_id: Optional[str] = None  # Track log ID for completion
        
        # UI interface (for GUI updates)
        self.ui_interface = None
        self._gui_window = None

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

    def _stop_idle_mode_for_activity(self):
        """Stop idle mode activity before starting another activity"""
        if self.idle_mode_activity:
            logger.info("🔇 Stopping idle mode activity before starting new activity…")
            try:
                self.idle_mode_activity.stop()
                logger.info("✅ Idle mode activity stopped successfully")
            except Exception as e:
                logger.warning(f"Ignoring error while stopping idle mode: {e}")
                logger.info("⚠️ Continuing despite stop error...")
        
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
                on_intent_detected=self._handle_intent_detected
            )
            if not self.idle_mode_activity.initialize():
                raise RuntimeError("Failed to initialize Idle Mode activity")
            logger.info("✓ Idle Mode activity initialized")

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
            "activity_suggestion": "activity_suggestion",
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
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _handle_termination(self):
        """Handle termination intent by shutting down the system."""
        logger.info("👋 Termination intent received – shutting down system")
        with self._lock:
            self.state = SystemState.SHUTTING_DOWN
        self.stop()


    def _handle_unknown_intent(self, transcript: str):
        """Handle unknown/unrecognized intent by prompting user to repeat and looping back"""
        logger.info(f"Handling unknown intent for transcript: '{transcript}' - prompting to repeat")
        
        # Note: TTS and audio playback are now handled by idle_mode activity
        # We just need to restart idle_mode to listen again
        logger.info("Restarting idle mode to listen for command again")
        self._restart_idle_mode()

    def _start_journal_activity(self):
        """Start the journal activity thread."""
        logger.info("📖 Starting Journal activity…")
        
        # Lazy import and initialize if needed
        if self.journal_activity is None:
            from src.activities.journal import JournalActivity
            logger.info("Lazy loading Journal activity...")
            self.journal_activity = JournalActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.journal_activity.initialize():
                logger.error("❌ Failed to initialize Journal activity")
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
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_spiritual_quote_activity(self):
        """Start the spiritual quote activity thread."""
        logger.info("📜 Starting Spiritual Quote activity…")
        
        # Lazy import and initialize if needed
        if self.spiritual_quote_activity is None:
            from src.activities.spiritual_quote import SpiritualQuoteActivity
            logger.info("Lazy loading Spiritual Quote activity...")
            self.spiritual_quote_activity = SpiritualQuoteActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.spiritual_quote_activity.initialize():
                logger.error("❌ Failed to initialize Spiritual Quote activity")
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
                # Clear log ID
                self._current_activity_log_id = None
                
                # Re-initialize for next run
                try:
                    self.spiritual_quote_activity = SpiritualQuoteActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.spiritual_quote_activity.initialize()
                except Exception:
                    pass
                # Restart wakeword
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_gratitude_activity(self):
        """Start the gratitude activity thread."""
        logger.info("🙏 Starting Gratitude activity…")
        
        # Lazy import and initialize if needed
        if self.gratitude_activity is None:
            from src.activities.gratitude import GratitudeActivity
            logger.info("Lazy loading Gratitude activity...")
            self.gratitude_activity = GratitudeActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.gratitude_activity.initialize():
                logger.error("❌ Failed to initialize Gratitude activity")
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
                # Clear log ID
                self._current_activity_log_id = None
                
                # Re-initialize for next run
                try:
                    self.gratitude_activity = GratitudeActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.gratitude_activity.initialize()
                except Exception:
                    pass
                # Restart wakeword
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_meditation_activity(self):
        """Start the meditation activity thread."""
        logger.info("🧘 Starting Meditation activity…")
        
        # Lazy import and initialize if needed
        if self.meditation_activity is None:
            from src.activities.meditation import MeditationActivity
            logger.info("Lazy loading Meditation activity...")
            self.meditation_activity = MeditationActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not self.meditation_activity.initialize():
                logger.error("❌ Failed to initialize Meditation activity")
                return

        with self._lock:
            self.state = SystemState.ACTIVITY_ACTIVE
            self.current_activity = "meditation"

        # Stop idle mode activity before starting Meditation
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
                # Clear log ID
                self._current_activity_log_id = None
                
                # Re-initialize for next run
                try:
                    self.meditation_activity = MeditationActivity(backend_dir=self.backend_dir, user_id=self.user_id)
                    self.meditation_activity.initialize()
                except Exception:
                    pass
                # Restart wakeword
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_activity_suggestion_activity(self):
        """Start the activity suggestion activity thread."""
        logger.info("💡 Starting Activity Suggestion activity…")
        
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
                        self._route_to_activity(selected_activity, transcript)
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
                        self._route_to_activity("smalltalk", "")
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
                
                # Reset state and restart wakeword detection
                with self._lock:
                    self.state = SystemState.LISTENING
                
                logger.info("🔄 Restarting wake word detection after activity suggestion completion")
                self._restart_idle_mode()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _start_idle_mode_activity(self):
        """Start the idle mode activity in a thread with error handling"""
        logger.info("🎬 Starting idle mode activity...")
        
        def run_idle_mode():
            try:
                if not self.idle_mode_activity:
                    logger.error("Idle mode activity is None - cannot start")
                    return
                
                # Run the idle mode activity (this will block until intent detected or timeout)
                success = self.idle_mode_activity.run()
                
                if success:
                    logger.info("✅ Idle mode completed successfully (intent detected)")
                    # Check if intent was detected (either from wakeword or intervention trigger)
                    detected_intent = self.idle_mode_activity.get_detected_intent()
                    detected_transcript = self.idle_mode_activity.get_detected_transcript()
                    
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
                        
                        # Clear detected intent to prevent duplicate routing
                        # This is safe because we're about to route, and reinitialize() will clear it anyway
                        if hasattr(self.idle_mode_activity, '_detected_intent'):
                            self.idle_mode_activity._detected_intent = None
                            self.idle_mode_activity._detected_transcript = None
                        
                        self._route_to_activity(intent, transcript)
                    else:
                        # Intent was detected via callback, routing already handled
                        logger.info("Intent routing handled by callback")
                else:
                    logger.info("⏰ Idle mode exited without intent detection (timeout or stopped)")
                    # No intent detected (timeout) - restart idle mode to return to wakeword listening
                    logger.info("🔄 Restarting idle mode after timeout...")
                    self._restart_idle_mode()
                    
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
        
        # Start idle mode in a daemon thread
        idle_thread = threading.Thread(target=run_idle_mode, daemon=True)
        idle_thread.start()
        logger.info("✅ Idle mode activity thread started")

    def _restart_idle_mode(self):
        """Restart idle mode activity after an activity ends."""
        logger.info("🔄 Restarting idle mode activity…")
        
        # 1) Ensure complete cleanup of previous idle mode
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
                    raise RuntimeError("Failed to re-initialize idle mode")
                
                logger.info("✅ Idle mode re-initialized successfully")
                
                # Add guard delay for Windows audio device release
                time.sleep(0.2)
                
            except Exception as e:
                logger.error(f"Error during idle mode cleanup/reinit: {e}", exc_info=True)
                # Try to recreate the activity if reinit failed
                try:
                    logger.info("Attempting to recreate idle mode activity...")
                    self.idle_mode_activity = IdleModeActivity(
                        backend_dir=self.backend_dir,
                        user_id=self.user_id,
                        on_intent_detected=self._handle_intent_detected
                    )
                    if not self.idle_mode_activity.initialize():
                        raise RuntimeError("Failed to recreate idle mode activity")
                except Exception as recreate_error:
                    logger.error(f"Failed to recreate idle mode activity: {recreate_error}", exc_info=True)
                    with self._lock:
                        self.state = SystemState.SHUTTING_DOWN
                    return
        
        # 2) Reset state
        with self._lock:
            self.state = SystemState.LISTENING
            self.current_activity = None
        
        # 3) Start the idle mode activity
        try:
            self._start_idle_mode_activity()
            logger.info("🎤 Idle mode restarted – LISTENING for wake word")
        except Exception as e:
            logger.error(f"Failed to restart idle mode: {e}", exc_info=True)
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
            # Start idle mode activity
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

        # Stop idle mode activity
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
