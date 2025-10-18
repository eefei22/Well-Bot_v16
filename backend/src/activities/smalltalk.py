#!/usr/bin/env python3
"""
SmallTalk Activity Class
A proper activity class that wraps the SmallTalkManager for use in the orchestration system.
"""

import os
import sys
import logging
import threading
import time
from pathlib import Path
from typing import Optional

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.managers.smalltalk_manager import SmallTalkManager

logger = logging.getLogger(__name__)


class SmallTalkActivity:
    """
    SmallTalk Activity Class
    
    Wraps the SmallTalkManager to provide a clean activity interface
    for the orchestration system.
    """
    
    def __init__(self, backend_dir: Path):
        """Initialize the SmallTalk activity"""
        self.backend_dir = backend_dir
        self.manager: Optional[SmallTalkManager] = None
        self.stt_service: Optional[GoogleSTTService] = None
        self._active = False
        self._initialized = False
        
        logger.info("SmallTalkActivity initialized")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            # Paths
            deepseek_config_path = self.backend_dir / "config" / "LLM" / "deepseek.json"
            llm_config_path = self.backend_dir / "config" / "LLM" / "smalltalk_instructions.json"
            
            logger.info(f"Initializing SmallTalk activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            logger.info(f"DeepSeek config: {deepseek_config_path}")
            logger.info(f"LLM config: {llm_config_path}")
            
            # Check if all required files exist
            required_files = [deepseek_config_path, llm_config_path]
            for file_path in required_files:
                if not file_path.exists():
                    logger.error(f"Required file not found: {file_path}")
                    return False
                else:
                    logger.info(f"✓ Found: {file_path}")
            
            # Initialize STT service
            logger.info("Initializing STT service...")
            self.stt_service = GoogleSTTService(language="en-US", sample_rate=16000)
            logger.info("✓ STT service initialized")
            
            # Create mic factory
            def mic_factory():
                return MicStream()
            
            # Initialize SmallTalkManager
            logger.info("Initializing SmallTalkManager...")
            self.manager = SmallTalkManager(
                stt=self.stt_service,
                mic_factory=mic_factory,
                deepseek_config_path=str(deepseek_config_path),
                llm_config_path=str(llm_config_path)
            )
            logger.info("✓ SmallTalkManager initialized")
            logger.info(f"✓ TTS Voice: {self.manager.tts_voice_name}")
            logger.info(f"✓ TTS Language: {self.manager.tts_language_code}")
            logger.info(f"✓ STT Language: {self.manager.language_code}")
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize SmallTalk activity: {e}", exc_info=True)
            return False
    
    def start(self) -> bool:
        """Start the SmallTalk activity"""
        if not self._initialized:
            logger.error("Activity not initialized")
            return False
        
        if self._active:
            logger.warning("Activity already active")
            return False
        
        try:
            logger.info("🚀 Starting SmallTalk activity...")
            self._active = True
            
            # Start the manager
            self.manager.start()
            
            logger.info("✅ SmallTalk activity started successfully")
            logger.info(f"🔍 Manager active status: {self.manager.is_active()}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start SmallTalk activity: {e}", exc_info=True)
            self._active = False
            return False
    
    def stop(self):
        """Stop the SmallTalk activity"""
        if not self._active:
            logger.warning("Activity not active")
            return
        
        logger.info("🛑 Stopping SmallTalk activity...")
        self._active = False
        
        if self.manager:
            self.manager.stop()
        
        logger.info("✅ SmallTalk activity stopped")
    
    def is_active(self) -> bool:
        """Check if the activity is currently active"""
        return self._active and self.manager and self.manager.is_active()
    
    def wait_for_completion(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for the activity to complete naturally
        
        Args:
            timeout: Maximum time to wait in seconds (None for no timeout)
            
        Returns:
            True if activity completed naturally, False if timeout or error
        """
        if not self._active:
            logger.warning("Activity not active")
            return False
        
        logger.info("⏳ Waiting for SmallTalk activity to complete...")
        
        start_time = time.time()
        try:
            while self.is_active():
                time.sleep(0.5)
                
                if timeout and (time.time() - start_time) > timeout:
                    logger.warning(f"Activity timeout after {timeout}s")
                    return False
            
            logger.info("✅ SmallTalk activity completed naturally")
            return True
            
        except Exception as e:
            logger.error(f"Error waiting for activity completion: {e}")
            return False
    
    def run(self) -> bool:
        """
        Run the complete activity: start, wait for completion, and stop
        
        Returns:
            True if activity completed successfully, False otherwise
        """
        logger.info("🎬 SmallTalkActivity.run() - Starting activity execution")
        try:
            # Start the activity
            if not self.start():
                logger.error("❌ SmallTalkActivity.run() - Failed to start activity")
                return False
            
            # Wait for completion
            success = self.wait_for_completion()
            
            # Stop the activity
            self.stop()
            
            return success
            
        except Exception as e:
            logger.error(f"Error running SmallTalk activity: {e}", exc_info=True)
            self.stop()
            return False
    
    def get_status(self) -> dict:
        """Get current activity status"""
        return {
            "initialized": self._initialized,
            "active": self._active,
            "manager_active": self.manager.is_active() if self.manager else False,
            "activity_type": "smalltalk"
        }


# For testing when run directly
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def main():
        """Test the SmallTalk activity"""
        try:
            # Get backend directory
            backend_dir = Path(__file__).parent.parent.parent
            
            # Create and initialize activity
            activity = SmallTalkActivity(backend_dir)
            
            if not activity.initialize():
                logger.error("Failed to initialize activity")
                return 1
            
            logger.info("=== SmallTalk Activity Test ===")
            logger.info("The activity will:")
            logger.info("- Start SmallTalk session")
            logger.info("- Handle conversation with user")
            logger.info("- Play TTS responses")
            logger.info("- Monitor for termination phrases")
            logger.info("- End when user says goodbye or timeout occurs")
            logger.info("- Press Ctrl+C to stop")
            
            # Run the activity
            success = activity.run()
            
            if success:
                logger.info("=== SmallTalk Activity Test Completed Successfully! ===")
            else:
                logger.error("=== SmallTalk Activity Test Failed! ===")
                return 1
            
            return 0
            
        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            return 0
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            return 1
    
    exit(main())
