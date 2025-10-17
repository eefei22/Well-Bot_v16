# backend/main.py

"""
Main entry point for the Well-Bot backend.
This file orchestrates the complete voice interaction flow:
Wake Word Detection → Intent Recognition → Activity Execution → Return to Wake Word
"""

import os
import sys
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum

# Add the backend directory to the path
backend_dir = Path(__file__).parent
sys.path.append(str(backend_dir))

# Import pipeline components
from src.components._pipeline_wakeword import create_voice_pipeline, VoicePipeline
from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.components.intent import IntentInference
from src.managers.smalltalk_manager import SmallTalkManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class SystemState(Enum):
    """System states for the orchestrator"""
    WAKE_WORD_LISTENING = "wake_word_listening"
    ACTIVITY_RUNNING = "activity_running"
    SHUTTING_DOWN = "shutting_down"


class WellBotOrchestrator:
    """
    Main orchestrator that coordinates the complete voice interaction flow.
    
    Flow:
    1. Start in WAKE_WORD_LISTENING state
    2. Wake word detected → transition to ACTIVITY_RUNNING
    3. Intent recognized → start appropriate activity (e.g., SmallTalk)
    4. Activity completes → return to WAKE_WORD_LISTENING
    """
    
    def __init__(self):
        """Initialize the orchestrator with all required components"""
        self.state = SystemState.WAKE_WORD_LISTENING
        self._lock = threading.Lock()
        self._active = False
        
        # Component paths
        self.backend_dir = backend_dir
        self.access_key_path = self.backend_dir / "config" / "WakeWord" / "PorcupineAccessKey.txt"
        self.wakeword_model_path = self.backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel.ppn"
        self.intent_model_path = self.backend_dir / "config" / "intent_classifier"
        self.deepseek_config_path = self.backend_dir / "config" / "LLM" / "deepseek.json"
        self.smalltalk_config_path = self.backend_dir / "config" / "LLM" / "smalltalk_instructions.json"
        
        # Components
        self.voice_pipeline: Optional[VoicePipeline] = None
        self.smalltalk_manager: Optional[SmallTalkManager] = None
        self.stt_service: Optional[GoogleSTTService] = None
        
        # Activity tracking
        self.current_activity = None
        self.activity_thread: Optional[threading.Thread] = None
        
        logger.info("WellBot Orchestrator initialized")
    
    def _validate_config_files(self) -> bool:
        """Validate that all required configuration files exist"""
        required_files = [
            self.access_key_path,
            self.wakeword_model_path,
            self.intent_model_path,
            self.deepseek_config_path,
            self.smalltalk_config_path
        ]
        
        missing_files = []
        for file_path in required_files:
            if not file_path.exists():
                missing_files.append(str(file_path))
            else:
                logger.info(f"✓ Found: {file_path}")
        
        if missing_files:
            logger.error("Missing required configuration files:")
            for file_path in missing_files:
                logger.error(f"  - {file_path}")
            return False
        
        return True
    
    def _create_mic_factory(self):
        """Factory function to create MicStream instances"""
        def mic_factory():
            return MicStream()
        return mic_factory
    
    def _initialize_components(self) -> bool:
        """Initialize all pipeline components"""
        try:
            logger.info("Initializing STT service...")
            self.stt_service = GoogleSTTService(language="en-US", sample_rate=16000)
            logger.info("✓ STT service initialized")
            
            logger.info("Creating voice pipeline...")
            self.voice_pipeline = create_voice_pipeline(
                access_key_file=str(self.access_key_path),
                custom_keyword_file=str(self.wakeword_model_path),
                language="en-US",
                on_wake_callback=self._on_wake_word_detected,
                on_final_transcript=self._on_transcript_received,
                intent_model_path=str(self.intent_model_path)
            )
            logger.info("✓ Voice pipeline created")
            
            logger.info("Creating SmallTalk manager...")
            mic_factory = self._create_mic_factory()
            self.smalltalk_manager = SmallTalkManager(
                stt=self.stt_service,
                mic_factory=mic_factory,
                deepseek_config_path=str(self.deepseek_config_path),
                llm_config_path=str(self.smalltalk_config_path)
            )
            logger.info("✓ SmallTalk manager created")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}", exc_info=True)
            return False
    
    def _on_wake_word_detected(self):
        """Callback triggered when wake word is detected"""
        with self._lock:
            if self.state != SystemState.WAKE_WORD_LISTENING:
                logger.warning(f"Wake word detected but system is in {self.state.value} state - ignoring")
                return
            
            logger.info("Wake word detected - transitioning to activity mode")
            self.state = SystemState.ACTIVITY_RUNNING
    
    def _on_transcript_received(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Callback triggered when final transcript is received"""
        logger.info(f"Transcript received: '{transcript}'")
        
        if intent_result:
            intent = intent_result.get('intent', 'unknown')
            confidence = intent_result.get('confidence', 0.0)
            logger.info(f"Intent detected: {intent} (confidence: {confidence:.3f})")
            
            # Route to appropriate activity based on intent
            self._route_to_activity(intent, transcript, intent_result)
        else:
            logger.warning("No intent classification available - defaulting to small talk")
            self._route_to_activity("small_talk", transcript, None)
    
    def _route_to_activity(self, intent: str, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Route the user to the appropriate activity based on intent"""
        logger.info(f"Routing to activity: {intent}")
        
        # Activity routing logic - easily extensible for new activities
        activity_handlers = {
            "small_talk": self._start_smalltalk_activity,
            "todo_add": self._start_todo_activity,
            "journal_write": self._start_journal_activity,
            "weather_query": self._start_weather_activity,
            "news_query": self._start_news_activity,
            "music_control": self._start_music_activity,
            "calendar_query": self._start_calendar_activity
        }
        
        # Get the appropriate handler for the intent
        handler = activity_handlers.get(intent)
        
        if handler:
            logger.info(f"Starting {intent} activity")
            handler(transcript, intent_result)
        else:
            logger.warning(f"Unknown intent '{intent}' - defaulting to small talk")
            self._start_smalltalk_activity(transcript, intent_result)
    
    def _start_smalltalk_activity(self, transcript: str = "", intent_result: Optional[Dict[str, Any]] = None):
        """Start the SmallTalk activity"""
        logger.info("Starting SmallTalk activity...")
        
        # Stop the voice pipeline (wake word detection)
        if self.voice_pipeline and self.voice_pipeline.is_active():
            logger.info("Stopping wake word detection for activity")
            self.voice_pipeline.stop()
        
        # Start SmallTalk manager in a separate thread
        def run_activity():
            try:
                self.current_activity = "smalltalk"
                self.smalltalk_manager.start()
                
                # Wait for activity to complete
                while self.smalltalk_manager.is_active():
                    time.sleep(0.5)
                
                logger.info("SmallTalk activity completed")
                
            except Exception as e:
                logger.error(f"Error in SmallTalk activity: {e}", exc_info=True)
            finally:
                self._on_activity_completed()
        
        self.activity_thread = threading.Thread(target=run_activity, daemon=True)
        self.activity_thread.start()
    
    def _start_todo_activity(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Start the Todo activity (placeholder for future implementation)"""
        logger.info("Todo activity not yet implemented - defaulting to small talk")
        self._start_smalltalk_activity(transcript, intent_result)
    
    def _start_journal_activity(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Start the Journal activity (placeholder for future implementation)"""
        logger.info("Journal activity not yet implemented - defaulting to small talk")
        self._start_smalltalk_activity(transcript, intent_result)
    
    def _start_weather_activity(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Start the Weather activity (placeholder for future implementation)"""
        logger.info("Weather activity not yet implemented - defaulting to small talk")
        self._start_smalltalk_activity(transcript, intent_result)
    
    def _start_news_activity(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Start the News activity (placeholder for future implementation)"""
        logger.info("News activity not yet implemented - defaulting to small talk")
        self._start_smalltalk_activity(transcript, intent_result)
    
    def _start_music_activity(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Start the Music activity (placeholder for future implementation)"""
        logger.info("Music activity not yet implemented - defaulting to small talk")
        self._start_smalltalk_activity(transcript, intent_result)
    
    def _start_calendar_activity(self, transcript: str, intent_result: Optional[Dict[str, Any]]):
        """Start the Calendar activity (placeholder for future implementation)"""
        logger.info("Calendar activity not yet implemented - defaulting to small talk")
        self._start_smalltalk_activity(transcript, intent_result)
    
    def _on_activity_completed(self):
        """Called when an activity completes - return to wake word listening"""
        with self._lock:
            logger.info("Activity completed - returning to wake word listening")
            self.current_activity = None
            self.state = SystemState.WAKE_WORD_LISTENING
            
            # Restart wake word detection
            if self.voice_pipeline:
                try:
                    logger.info("Restarting wake word detection")
                    self.voice_pipeline.start()
                    logger.info("Wake word detection restarted")
                except Exception as e:
                    logger.error(f"Failed to restart wake word detection: {e}")
    
    def start(self) -> bool:
        """Start the orchestrator"""
        logger.info("=== Well-Bot Orchestrator Starting ===")
        
        # Validate configuration files
        if not self._validate_config_files():
            logger.error("Configuration validation failed")
            return False
        
        # Initialize components
        if not self._initialize_components():
            logger.error("Component initialization failed")
            return False
        
        # Start the voice pipeline (wake word detection)
        try:
            logger.info("Starting voice pipeline...")
            self.voice_pipeline.start()
            self._active = True
            
            logger.info("Well-Bot Orchestrator started successfully!")
            logger.info("Listening for wake word...")
            logger.info("Say the wake word to start an interaction")
            logger.info("Press Ctrl+C to stop")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start orchestrator: {e}", exc_info=True)
            return False
    
    def stop(self):
        """Stop the orchestrator"""
        logger.info("Stopping Well-Bot Orchestrator...")
        
        with self._lock:
            self._active = False
            self.state = SystemState.SHUTTING_DOWN
        
        # Stop current activity
        if self.current_activity == "smalltalk" and self.smalltalk_manager:
            logger.info("Stopping SmallTalk activity...")
            self.smalltalk_manager.stop()
        
        # Stop voice pipeline
        if self.voice_pipeline:
            logger.info("Stopping voice pipeline...")
            self.voice_pipeline.stop()
        
        logger.info("Well-Bot Orchestrator stopped")
    
    def cleanup(self):
        """Clean up all resources"""
        logger.info("Cleaning up orchestrator resources...")
        
        self.stop()
        
        if self.voice_pipeline:
            self.voice_pipeline.cleanup()
        
        logger.info("Cleanup completed")
    
    def get_status(self) -> Dict[str, Any]:
        """Get current orchestrator status"""
        with self._lock:
            return {
                "active": self._active,
                "state": self.state.value,
                "current_activity": self.current_activity,
                "voice_pipeline_active": self.voice_pipeline.is_active() if self.voice_pipeline else False,
                "voice_pipeline_stt_active": self.voice_pipeline.is_stt_active() if self.voice_pipeline else False,
                "smalltalk_active": self.smalltalk_manager.is_active() if self.smalltalk_manager else False
            }


def main():
    """Main function to run the Well-Bot orchestrator"""
    orchestrator = WellBotOrchestrator()
    
    try:
        # Start the orchestrator
        if not orchestrator.start():
            logger.error("Failed to start orchestrator")
            return 1
        
        # Keep running until interrupted
        try:
            while orchestrator._active:
                time.sleep(1)
                
                # Optional: Print status periodically
                # status = orchestrator.get_status()
                # logger.debug(f"Status: {status}")
                
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
            
    except Exception as e:
        logger.error(f"Application error: {e}", exc_info=True)
        return 1
    finally:
        orchestrator.cleanup()
    
    logger.info("=== Well-Bot Backend Shutdown ===")
    return 0


if __name__ == "__main__":
    exit(main())