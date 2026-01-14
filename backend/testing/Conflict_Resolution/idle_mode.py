"""
Idle Mode Activity

This activity handles wakeword detection and emotion monitoring when the system is idle.
It continuously listens for wake words and manages emotion monitoring lifecycle.
When wake word is detected, it signals the orchestrator to start wake_mode for intent recognition.
"""

import os
import sys
import threading
import time
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any, Union

# Add the backend directory to the path to import modules
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

# Import components (use absolute imports like other activities)
from src.components.wakeword import WakeWordDetector, OpenWakeWordDetector, create_wake_word_detector
from src.components.shared_audio_manager import SharedAudioManager
from src.utils.config_loader import PORCUPINE_ACCESS_KEY
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.utils.intervention_poller import InterventionPoller
from src.activities.emotion_monitoring import EmotionMonitoringActivity
from src.supabase.auth import get_current_user_id

logger = logging.getLogger(__name__)


class IdleModeActivity:
    """
    Idle Mode Activity
    
    Handles wakeword detection and emotion monitoring coordination when the system is idle.
    This is the default activity that runs continuously until a wake word is detected,
    at which point it stops emotion monitoring and signals the orchestrator to start wake_mode.
    """
    
    def __init__(
        self,
        backend_dir: Path,
        user_id: Optional[str] = None,
        on_wake_detected: Optional[Callable[[], None]] = None,
        on_intervention_triggered: Optional[Callable[[], None]] = None,
        ui_interface=None,
        servo_controller=None,
    ):
        """
        Initialize the Idle Mode Activity
        
        Args:
            backend_dir: Path to the backend directory
            user_id: User ID (optional, will be resolved if not provided)
            on_wake_detected: Callback function called when wake word is detected
            on_intervention_triggered: Callback function called when intervention is triggered
            ui_interface: UI interface for visual feedback (optional)
            servo_controller: Servo controller for gesture feedback (optional)
        """
        self.backend_dir = backend_dir
        self.user_id = user_id if user_id is not None else get_current_user_id()
        self.on_wake_detected = on_wake_detected
        self.on_intervention_triggered = on_intervention_triggered
        self.ui_interface = ui_interface
        self.servo_controller = servo_controller
        
        # Components (initialized in initialize())
        self.wakeword_detector: Optional[Union[WakeWordDetector, OpenWakeWordDetector]] = None
        self.intervention_poller: Optional[InterventionPoller] = None
        self.emotion_monitoring_activity: Optional[EmotionMonitoringActivity] = None
        self._emotion_monitoring_thread: Optional[threading.Thread] = None
        
        # Configs (loaded in initialize())
        self.global_config: Optional[dict] = None
        self.language_config: Optional[dict] = None
        
        # Activity state
        self._active = False
        self._initialized = False
        
        # Wakeword detection state
        self._lock = threading.Lock()
        self._wakeword_audio_generator = None
        
        # Wake word debouncing to prevent rapid multiple triggers
        self._last_wake_time = 0.0
        self._wake_debounce_seconds = 2.0  # Ignore wake words within 2 seconds of last detection
        
        # Wake word/intervention detection flags
        self._wake_detected = threading.Event()
        self._intervention_triggered_flag = threading.Event()
        self._last_was_intervention = False  # Track if last trigger was intervention
        
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
            
            # Initialize wakeword detector (with automatic fallback to OpenWakeWord)
            try:
                wakeword_model_path = self.backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel_ARM2.ppn"
                self.wakeword_detector = create_wake_word_detector(
                    PORCUPINE_ACCESS_KEY, 
                    str(wakeword_model_path),
                    backend_dir=self.backend_dir
                )
                logger.info("✓ Wakeword detector created")
            except Exception as e:
                logger.error(f"Failed to create wakeword detector: {e}", exc_info=True)
                return False
            
            # Initialize intervention poller
            try:
                import os
                from dotenv import load_dotenv
                load_dotenv()
                service_url = os.getenv("CLOUD_SERVICE_URL")
                
                record_file_path = self.backend_dir / "config" / "intervention_record.json"
                poll_interval_minutes = self.global_config.get("intervention", {}).get("poll_interval_minutes", 15)
                
                self.intervention_poller = InterventionPoller(
                    user_id=self.user_id,
                    record_file_path=record_file_path,
                    poll_interval_minutes=poll_interval_minutes,
                    service_url=service_url,
                    on_intervention_triggered=self._on_intervention_triggered
                )
                logger.info(f"✓ Intervention poller initialized (interval: {poll_interval_minutes} minutes)")
            except Exception as e:
                logger.warning(f"Failed to initialize intervention poller: {e}", exc_info=True)
                self.intervention_poller = None
            
            # Initialize emotion monitoring activity
            try:
                self.emotion_monitoring_activity = EmotionMonitoringActivity(
                    backend_dir=self.backend_dir,
                    user_id=self.user_id
                )
                if not self.emotion_monitoring_activity.initialize():
                    logger.error("Failed to initialize emotion monitoring activity")
                    return False
                logger.info("✓ Emotion monitoring activity initialized")
            except Exception as e:
                logger.error(f"Failed to initialize emotion monitoring activity: {e}", exc_info=True)
                return False
            
            self._initialized = True
            logger.info("Idle Mode activity initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Idle Mode activity: {e}", exc_info=True)
            return False
    
    def start(self) -> bool:
        """Start the idle mode activity (wakeword detection and emotion monitoring)"""
        if not self._initialized:
            logger.error("Cannot start: activity not initialized")
            return False
        
        if self._active:
            logger.warning("Idle mode already active")
            return True
        
        try:
            logger.info("Starting wakeword detector...")
            # Detector should already be initialized by create_wake_word_detector()
            # Verify initialization status
            if not self.wakeword_detector.is_initialized:
                logger.error("Wakeword detector was not initialized during creation - this should not happen")
                raise RuntimeError("Wakeword detector not initialized")
            
            # Subscribe to SharedAudioManager for wake word detection
            audio_manager = SharedAudioManager.get_instance()
            self._wakeword_audio_generator = audio_manager.subscribe(
                subscriber_id="idle_mode_wakeword",
                sample_rate=16000,
                chunk_size=1600
            )
            
            # Start wake word detector with subscription
            self.wakeword_detector.start_with_subscription(
                self._wakeword_audio_generator,
                self._on_wake
            )
            
            # Start intervention poller
            if self.intervention_poller:
                try:
                    self.intervention_poller.start()
                    logger.info("✓ Intervention poller started")
                except Exception as e:
                    logger.warning(f"Failed to start intervention poller: {e}")
            
            # Start emotion monitoring activity
            if self.emotion_monitoring_activity:
                try:
                    if self.emotion_monitoring_activity.start():
                        # Start emotion monitoring in a thread
                        def run_emotion_monitoring():
                            try:
                                self.emotion_monitoring_activity.run()
                            except Exception as e:
                                logger.error(f"Error running emotion monitoring: {e}", exc_info=True)
                        
                        self._emotion_monitoring_thread = threading.Thread(
                            target=run_emotion_monitoring,
                            daemon=True,
                            name="EmotionMonitoring"
                        )
                        self._emotion_monitoring_thread.start()
                        logger.info("✓ Emotion monitoring started")
                    else:
                        logger.warning("Failed to start emotion monitoring")
                except Exception as e:
                    logger.warning(f"Error starting emotion monitoring: {e}", exc_info=True)
            
            self._active = True
            logger.info("Idle mode active: listening for wake word and monitoring emotions")
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
        
        # Mark as inactive FIRST
        self._active = False
        
        # Stop emotion monitoring
        if self.emotion_monitoring_activity:
            try:
                self.emotion_monitoring_activity.stop()
                logger.info("✓ Emotion monitoring stopped")
            except Exception as e:
                logger.warning(f"Error stopping emotion monitoring: {e}")
        
        # Wait for emotion monitoring thread to finish
        if self._emotion_monitoring_thread and self._emotion_monitoring_thread.is_alive():
            current_thread = threading.current_thread()
            if self._emotion_monitoring_thread is not current_thread:
                logger.info("Waiting for emotion monitoring thread to finish...")
                self._emotion_monitoring_thread.join(timeout=2.0)
                if self._emotion_monitoring_thread.is_alive():
                    logger.warning("Emotion monitoring thread did not finish within timeout")
            else:
                logger.debug("Emotion monitoring thread is current thread - skipping join")
        
        self._emotion_monitoring_thread = None
        
        # Stop intervention poller
        if self.intervention_poller:
            try:
                self.intervention_poller.stop()
                logger.info("✓ Intervention poller stopped")
            except Exception as e:
                logger.warning(f"Error stopping intervention poller: {e}")
        
        # Stop wakeword detector
        if self.wakeword_detector:
            try:
                self.wakeword_detector.stop()
            except Exception as e:
                logger.warning(f"Error stopping wakeword detector: {e}")
        
        # Unsubscribe from SharedAudioManager
        if self._wakeword_audio_generator:
            try:
                audio_manager = SharedAudioManager.get_instance()
                audio_manager.unsubscribe("idle_mode_wakeword")
                self._wakeword_audio_generator = None
            except Exception as e:
                logger.warning(f"Error unsubscribing from SharedAudioManager: {e}")
        
        # Clear flags
        self._wake_detected.clear()
        self._intervention_triggered_flag.clear()
        self._last_was_intervention = False
        
        logger.info("Idle mode stopped")
    
    def _on_intervention_triggered(self):
        """Callback when intervention trigger is detected from poller"""
        logger.info("Intervention trigger detected")
        
        # Stop emotion monitoring immediately (non-blocking - don't wait for it to finish)
        if self.emotion_monitoring_activity:
            try:
                # Set running flag to False immediately to interrupt ongoing operations
                self.emotion_monitoring_activity._running = False
                # Call stop() in background thread so we don't block
                def stop_emotion_monitoring():
                    try:
                        self.emotion_monitoring_activity.stop()
                        logger.info("✓ Emotion monitoring stopped (intervention triggered)")
                    except Exception as e:
                        logger.warning(f"Error stopping emotion monitoring: {e}")
                threading.Thread(target=stop_emotion_monitoring, daemon=True).start()
            except Exception as e:
                logger.warning(f"Error stopping emotion monitoring: {e}")
        
        # Set flag to signal orchestrator IMMEDIATELY (don't wait for emotion monitoring)
        self._intervention_triggered_flag.set()
        self._last_was_intervention = True  # Mark that this was intervention
        
        # Call callback if provided (this will trigger wake_mode start immediately)
        if self.on_intervention_triggered:
            try:
                self.on_intervention_triggered()
            except Exception as e:
                logger.error(f"Error invoking intervention callback: {e}")
        
        logger.info("Intervention trigger flag set - orchestrator will start wake_mode immediately")
    
    def run(self) -> bool:
        """
        Run the idle mode activity
        
        Returns:
            True if wake word detected or intervention triggered (activity should exit to allow wake_mode)
            False on error or if activity was stopped
        """
        logger.info("IdleModeActivity.run() - Starting idle mode execution")
        
        try:
            # Clear any stale state before starting
            self._wake_detected.clear()
            self._intervention_triggered_flag.clear()
            
            # Start the activity
            if not self.start():
                logger.error("Failed to start idle mode")
                return False
            
            # Check if intervention was already triggered before we entered the wait loop
            if self._intervention_triggered_flag.is_set():
                logger.info("Intervention already triggered (detected before wait loop)")
                self._intervention_triggered_flag.clear()
                self.stop()
                return True
            
            # Wait for wake word detection or intervention trigger
            logger.info("Waiting for wake word detection or intervention trigger...")
            
            while self._active and not self._wake_detected.is_set() and not self._intervention_triggered_flag.is_set():
                time.sleep(0.01)  # Very small sleep for minimal latency (10ms)
            
            # Check if wake word was detected
            if self._wake_detected.is_set():
                logger.info("Wake word detected - exiting idle mode to allow wake_mode")
                self.stop()
                return True
            
            # Check if intervention was triggered
            if self._intervention_triggered_flag.is_set():
                logger.info("Intervention triggered - exiting idle mode to allow wake_mode")
                self._intervention_triggered_flag.clear()
                self.stop()
                return True
            
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
            
            if self.emotion_monitoring_activity:
                try:
                    self.emotion_monitoring_activity.cleanup()
                except Exception as e:
                    logger.warning(f"Error cleaning up emotion monitoring: {e}")
            
            logger.info("Idle mode cleanup completed")
        except Exception as e:
            logger.error(f"Error during idle mode cleanup: {e}", exc_info=True)
    
    def reinitialize(self) -> bool:
        """Re-initialize the activity for subsequent runs"""
        logger.info("Re-initializing Idle Mode activity...")
        
        # Cleanup existing wakeword detector before resetting state
        if self.wakeword_detector:
            try:
                logger.debug("Cleaning up existing wakeword detector before reinitialize")
                self.wakeword_detector.cleanup()
            except Exception as e:
                logger.warning(f"Error cleaning up wakeword detector during reinitialize: {e}")
            finally:
                self.wakeword_detector = None
        
        # Cleanup emotion monitoring
        if self.emotion_monitoring_activity:
            try:
                self.emotion_monitoring_activity.cleanup()
            except Exception as e:
                logger.warning(f"Error cleaning up emotion monitoring during reinitialize: {e}")
            finally:
                self.emotion_monitoring_activity = None
        
        # Reset state
        self._active = False
        self._initialized = False
        self._wake_detected.clear()
        self._intervention_triggered_flag.clear()
        self._last_was_intervention = False
        self._last_wake_time = 0.0
        
        # Re-initialize components
        return self.initialize()
    
    def is_active(self) -> bool:
        """Check if the activity is currently active"""
        return self._active and self._initialized
    
    def was_last_trigger_intervention(self) -> bool:
        """Check if the last trigger was intervention (vs wake word)"""
        return self._last_was_intervention
    
    def _on_wake(self):
        """Callback when wake word is detected"""
        current_time = time.time()
        
        # Atomic debounce check to prevent race conditions
        with self._lock:
            if current_time - self._last_wake_time < self._wake_debounce_seconds:
                logger.debug(f"Ignoring wake word detected too soon (debounce: {self._wake_debounce_seconds}s)")
                return
            
            # Update last wake time
            self._last_wake_time = current_time
        
        logger.info("Wake word detected")

        # Minimal wake reaction before handoff to wake mode
        if self.ui_interface:
            try:
                self.ui_interface.update_mic_status("listening")
            except Exception:
                pass
        if self.servo_controller:
            try:
                self.servo_controller.trigger_wave()
            except Exception as e:
                logger.warning(f"Failed to trigger servo gesture: {e}")
        
        # Stop emotion monitoring immediately (non-blocking - don't wait for it to finish)
        if self.emotion_monitoring_activity:
            try:
                # Set running flag to False immediately to interrupt ongoing operations
                self.emotion_monitoring_activity._running = False
                # Call stop() in background thread so we don't block
                def stop_emotion_monitoring():
                    try:
                        self.emotion_monitoring_activity.stop()
                        logger.info("✓ Emotion monitoring stopped (wake word detected)")
                    except Exception as e:
                        logger.warning(f"Error stopping emotion monitoring: {e}")
                threading.Thread(target=stop_emotion_monitoring, daemon=True).start()
            except Exception as e:
                logger.warning(f"Error stopping emotion monitoring: {e}")
        
        # Set flag to signal orchestrator IMMEDIATELY (don't wait for emotion monitoring)
        self._wake_detected.set()
        self._last_was_intervention = False  # Mark that this was wake word, not intervention
        
        # Call callback if provided (this will trigger wake_mode start immediately)
        if self.on_wake_detected:
            try:
                self.on_wake_detected()
            except Exception as e:
                logger.error(f"Error invoking wake detected callback: {e}")
        
        logger.info("Wake word flag set - orchestrator will start wake_mode immediately")
