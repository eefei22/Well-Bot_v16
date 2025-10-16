#!/usr/bin/env python3
"""
Test script for SmallTalkManager
Demonstrates how to use the manager with the existing pipeline components.
"""

import os
import sys
import logging
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.managers.smalltalk_manager import SmallTalkManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def create_mic_factory():
    """Factory function to create MicStream instances"""
    def mic_factory():
        return MicStream()
    return mic_factory

def main():
    """Main test function"""
    try:
        # Paths
        backend_dir = Path(__file__).parent.parent
        stt_config_path = backend_dir / "config" / "STT" / "GoogleCloud.json"
        deepseek_config_path = backend_dir / "config" / "LLM" / "deepseek.json"
        llm_config_path = backend_dir / "config" / "LLM" / "smalltalk_instructions.json"
        nudge_audio_path = backend_dir / "assets" / "inactivity_nudge_EN.mp3"
        intent_model_path = backend_dir / "config" / "intent_classifier"

        # Check if all required files exist
        required_files = [stt_config_path, deepseek_config_path, llm_config_path, nudge_audio_path]
        for file_path in required_files:
            if not file_path.exists():
                logger.error(f"Required file not found: {file_path}")
                return

        # Initialize STT service
        logger.info("Initializing STT service...")
        stt = GoogleSTTService(stt_config_path)

        # Create mic factory
        mic_factory = create_mic_factory()

        # Initialize SmallTalkManager
        logger.info("Initializing SmallTalkManager...")
        manager = SmallTalkManager(
            stt=stt,
            mic_factory=mic_factory,
            deepseek_config_path=str(deepseek_config_path),
            llm_config_path=str(llm_config_path),
            nudge_audio_path=str(nudge_audio_path),
            intent_model_path=str(intent_model_path) if intent_model_path.exists() else None,
            language_code="en-US"
        )

        logger.info("Starting SmallTalkManager session...")
        logger.info("The manager will:")
        logger.info("- Monitor for silence and play nudge audio")
        logger.info("- Detect termination phrases")
        logger.info("- Strip emojis from assistant responses")
        logger.info("- Limit conversation turns")
        logger.info("- Press Ctrl+C to stop")

        # Start the manager
        manager.start()

        # Keep the main thread alive
        try:
            while manager.is_active():
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, stopping manager...")
            manager.stop()

        logger.info("Test completed successfully!")

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)

if __name__ == "__main__":
    main()
