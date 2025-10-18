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
from src.components.intent import IntentInference
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
        self.intent_model_path    = self.backend_dir / "config" / "intent_classifier"
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
                intent_model_path=str(self.intent_model_path)
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
            self._route_to_activity(intent, transcript)

    def _route_to_activity(self, intent: str, transcript: str):
        """Route the user to proper activity based on intent."""
        logger.info(f"🔄 Routing to activity: {intent}")

        if intent == "small_talk":
            self._start_smalltalk_activity()
        elif intent == "todo_add":
            logger.info("📝 Todo-Add intent detected – not implemented yet; falling back to smalltalk")
            self._fallback_to_smalltalk()
        elif intent == "journal_write":
            logger.info("📖 Journal-Write intent detected – not implemented yet; falling back to smalltalk")
            self._fallback_to_smalltalk()
        else:
            logger.info(f"❓ Unknown intent '{intent}' – falling back to smalltalk")
            self._fallback_to_smalltalk()

    def _start_smalltalk_activity(self):
        """Start the smalltalk activity thread."""
        logger.info("💬 Starting SmallTalk activity…")

        with self._lock:
            self.current_activity = "smalltalk"

        # Stop wake-word detection for the duration of the activity
        if self.voice_pipeline:
            self.voice_pipeline.stop()
            logger.info("🔇 Wake word detection paused for activity")

        def run_activity():
            try:
                logger.info("🚀 Running SmallTalk activity…")
                success = self.smalltalk_activity.run()
                if success:
                    logger.info("✅ SmallTalk activity completed successfully")
                else:
                    logger.error("❌ SmallTalk activity ended with failure or abnormal termination")
            except Exception as e:
                logger.error(f"Error in SmallTalk activity: {e}", exc_info=True)
            finally:
                # When activity ends, restart wake word detection
                self._restart_wakeword_detection()

        self._activity_thread = threading.Thread(target=run_activity, daemon=True)
        self._activity_thread.start()

    def _fallback_to_smalltalk(self):
        """Fallback to smalltalk in absence of specific activity."""
        logger.info("🔄 Falling back to SmallTalk…")
        self._start_smalltalk_activity()

    def _restart_wakeword_detection(self):
        """Restart wake word detection after an activity ends."""
        logger.info("🔄 Restarting wake word detection…")
        with self._lock:
            self.state = SystemState.LISTENING
            self.current_activity = None
        if self.voice_pipeline:
            try:
                self.voice_pipeline.start()
                logger.info("🎤 Wake word detection restarted – LISTENING for wake word")
            except Exception as e:
                logger.error(f"Failed to restart wake word pipeline: {e}", exc_info=True)
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
