"""
Standalone test script for GoogleTTSClient.

This script demonstrates both streaming and non-streaming TTS functionality.
"""

import os
import sys
import logging
from pathlib import Path

# Add the backend/src directory to the Python path
backend_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(backend_src))

from components.tts import GoogleTTSClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_non_streaming():
    """Test non-streaming TTS synthesis."""
    logger.info("Testing non-streaming TTS synthesis...")
    
    try:
        # Initialize client (credentials set via environment variable)
        client = GoogleTTSClient()
        
        # Test synthesis with WAV file output
        test_text = "Well-bot is a friendly assistant. It can help you with your questions and tasks."
        audio_bytes = client.synthesize_to_wav(test_text, "test_output.wav")
        
        logger.info(f"Non-streaming test completed. Audio saved to test_output.wav")
        logger.info(f"Generated {len(audio_bytes)} bytes of PCM audio")
        
        return True
        
    except Exception as e:
        logger.error(f"Non-streaming test failed: {e}")
        return False


def test_streaming():
    """Test streaming TTS synthesis."""
    logger.info("Testing streaming TTS synthesis...")
    
    try:
        # Initialize client (credentials set via environment variable)
        client = GoogleTTSClient()
        
        # Test streaming synthesis with WAV file output
        text_chunks = ["Hello, ", "this is a ", "streaming test. ", "It should work ", "incrementally."]
        
        audio_bytes = client.stream_synthesize_to_wav(iter(text_chunks), "test_streaming_output.wav")
        
        logger.info(f"Streaming test completed. Audio saved to test_streaming_output.wav")
        logger.info(f"Generated {len(audio_bytes)} bytes of PCM audio")
        
        return True
        
    except Exception as e:
        logger.error(f"Streaming test failed: {e}")
        return False


def test_safe_streaming():
    """Test safe streaming TTS synthesis with fallback."""
    logger.info("Testing safe streaming TTS synthesis...")
    
    try:
        # Initialize client (credentials set via environment variable)
        client = GoogleTTSClient()
        
        # Test safe streaming synthesis with WAV file output
        text_chunks = ["Safe streaming ", "test with ", "fallback capability."]
        
        audio_bytes = client.synthesize_safe_to_wav(iter(text_chunks), "test_safe_streaming_output.wav")
        
        logger.info(f"Safe streaming test completed. Audio saved to test_safe_streaming_output.wav")
        logger.info(f"Generated {len(audio_bytes)} bytes of PCM audio")
        
        return True
        
    except Exception as e:
        logger.error(f"Safe streaming test failed: {e}")
        return False


def test_voice_listing():
    """Test getting available voices."""
    logger.info("Testing voice listing...")
    
    try:
        # Initialize client (credentials set via environment variable)
        client = GoogleTTSClient()
        
        # Get available voices
        voices = client.get_available_voices()
        logger.info(f"Found {len(voices)} available voices")
        
        # Show first few voices
        for i, voice in enumerate(voices[:5]):
            logger.info(f"Voice {i+1}: {voice.name} ({voice.language_codes[0]})")
        
        return True
        
    except Exception as e:
        logger.error(f"Voice listing test failed: {e}")
        return False


def main():
    """Run all tests."""
    logger.info("Starting TTS client tests...")
    
    tests = [
        ("Non-streaming synthesis", test_non_streaming),
        ("Streaming synthesis", test_streaming),
        ("Safe streaming synthesis", test_safe_streaming),
        ("Voice listing", test_voice_listing),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n{'='*50}")
        logger.info(f"Running: {test_name}")
        logger.info(f"{'='*50}")
        
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            logger.error(f"Test {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info(f"\n{'='*50}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*50}")
    
    passed = 0
    for test_name, success in results:
        status = "PASSED" if success else "FAILED"
        logger.info(f"{test_name}: {status}")
        if success:
            passed += 1
    
    logger.info(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        logger.info("All tests passed! 🎉")
    else:
        logger.warning("Some tests failed. Check the logs above for details.")


if __name__ == "__main__":
    main()
