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
from pathlib import Path
from enum import Enum
from typing import Optional, Dict, Any

# Add the backend directory to the path (so we can import src.components etc.)
backend_dir = Path(__file__).parent
sys.path.append(str(backend_dir))

# Import pipeline / components
from src.components._pipeline_wakeword import create_voice_pipeline, VoicePipeline
from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.activities.smalltalk import SmallTalkActivity

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
        self.access_key_path      = self.backend_dir / "config" / "WakeWord" / "PorcupineAccessKey.txt"
        self.wakeword_model_path  = self.backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel.ppn"
        self.intent_model_path    = self.backend_dir / "config" / "WakeWord" / "intents.json"
        self.deepseek_config_path = self.backend_dir / "config" / "LLM" / "deepseek.json"
        self.llm_config_path      = self.backend_dir / "config" / "LLM" / "smalltalk_instructions.json"

        # Components
        self.voice_pipeline: Optional[VoicePipeline] = None
        self.smalltalk_activity: Optional[SmallTalkActivity] = None
        self.stt_service: Optional[GoogleSTTService] = None

        self.current_activity: Optional[str] = None
        self._activity_thread: Optional[threading.Thread] = None

        logger.info("WellBotOrchestrator initialized")

    def _validate_config_files(self) -> bool:
        """Validate that all required config files exist."""
        required = [
            self.access_key_path,
            self.wakeword_model_path,
            self.intent_model_path,
            self.deepseek_config_path,
            self.llm_config_path
        ]
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
            logger.info("Initializing STT service…")
            self.stt_service = GoogleSTTService(language="en-US", sample_rate=16000)
            logger.info("✓ STT service initialized")

            logger.info("Initializing voice pipeline (wake word)…")
            self.voice_pipeline = create_voice_pipeline(
                access_key_file=str(self.access_key_path),
                custom_keyword_file=str(self.wakeword_model_path),
                language="en-US",
                on_wake_callback=self._on_wake_detected,
                on_final_transcript=self._on_transcript_received,
                intent_config_path=str(self.intent_model_path),
                preference_file_path=str(self.backend_dir / "config" / "user_preference" / "preference.json"),
            )

            logger.info("✓ Voice pipeline initialized")

            logger.info("Initializing SmallTalk activity…")
            self.smalltalk_activity = SmallTalkActivity(backend_dir=self.backend_dir)
            if not self.smalltalk_activity.initialize():
                raise RuntimeError("Failed to initialize SmallTalk activity")
            logger.info("✓ SmallTalk activity initialized")

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

    def _on_transcript_received(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Callback when final transcript and intent are available."""
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

        if intent == "smalltalk":
            self._start_smalltalk_activity()
        elif intent == "journaling":
            logger.info("📖 Journaling intent detected – not implemented yet; falling back to smalltalk")
            self._fallback_to_smalltalk()
        elif intent == "meditation":
            logger.info("🧘 Meditation intent detected – not implemented yet; falling back to smalltalk")
            self._fallback_to_smalltalk()
        elif intent == "quote":
            logger.info("💭 Quote intent detected – not implemented yet; falling back to smalltalk")
            self._fallback_to_smalltalk()
        elif intent == "gratitude":
            logger.info("🙏 Gratitude intent detected – not implemented yet; falling back to smalltalk")
            self._fallback_to_smalltalk()
        elif intent == "termination":
            logger.info("👋 Termination intent detected – ending session")
            self._handle_termination()
        else:
            logger.info(f"❓ Unknown intent '{intent}' – falling back to smalltalk")
            self._fallback_to_smalltalk()

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
                access_key_file=str(self.access_key_path),
                custom_keyword_file=str(self.wakeword_model_path),
                language="en-US",
                on_wake_callback=self._on_wake_detected,
                on_final_transcript=self._on_transcript_received,
                intent_config_path=str(self.intent_model_path),
                preference_file_path=str(self.backend_dir / "config" / "user_preference" / "preference.json"),
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

        # Stop voice pipeline
        if self.voice_pipeline:
            logger.info("Stopping voice pipeline…")
            self.voice_pipeline.stop()
            try:
                self.voice_pipeline.cleanup()
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
                "wakeword_active": bool(self.voice_pipeline and self.voice_pipeline.is_active()),
                "smalltalk_active": bool(self.smalltalk_activity and self.smalltalk_activity.is_active())
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
