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
        deepseek_config_path = backend_dir / "config" / "LLM" / "deepseek.json"
        llm_config_path = backend_dir / "config" / "LLM" / "smalltalk_instructions.json"
        intent_model_path = backend_dir / "config" / "intent_classifier"

        logger.info("=== SmallTalk Manager Test ===")
        logger.info(f"Backend directory: {backend_dir}")
        logger.info(f"DeepSeek config: {deepseek_config_path}")
        logger.info(f"LLM config: {llm_config_path}")

        # Check if all required files exist
        required_files = [deepseek_config_path, llm_config_path]
        for file_path in required_files:
            if not file_path.exists():
                logger.error(f"Required file not found: {file_path}")
                return
            else:
                logger.info(f"✓ Found: {file_path}")

        # Initialize STT service
        logger.info("Initializing STT service...")
        stt = GoogleSTTService(language="en-US", sample_rate=16000)
        logger.info("✓ STT service initialized")

        # Create mic factory
        mic_factory = create_mic_factory()
        logger.info("✓ Microphone factory created")

        # Initialize SmallTalkManager
        logger.info("Initializing SmallTalkManager...")
        manager = SmallTalkManager(
            stt=stt,
            mic_factory=mic_factory,
            deepseek_config_path=str(deepseek_config_path),
            llm_config_path=str(llm_config_path)
        )
        logger.info("✓ SmallTalkManager initialized")
        logger.info(f"✓ TTS Voice: {manager.tts_voice_name}")
        logger.info(f"✓ TTS Language: {manager.tts_language_code}")
        logger.info(f"✓ STT Language: {manager.language_code}")
        logger.info(f"✓ Nudge Audio: {manager.nudge_audio_path}")
        logger.info(f"✓ Termination Audio: {manager.termination_audio_path}")

        logger.info("Starting SmallTalkManager session...")
        logger.info("The manager will:")
        logger.info("- Stream TTS responses and play them through speakers")
        logger.info("- Monitor for silence and play nudge audio")
        logger.info("- Play termination audio when nudge timeout expires")
        logger.info("- Detect termination phrases")
        logger.info("- Strip emojis from assistant responses")
        logger.info("- Limit conversation turns")
        logger.info("- Mute microphone during playback to prevent feedback")
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

        logger.info("=== Test completed successfully! ===")
        logger.info("The SmallTalk session has ended.")

    except Exception as e:
        logger.error(f"=== Test failed: {e} ===", exc_info=True)

if __name__ == "__main__":
    main()
