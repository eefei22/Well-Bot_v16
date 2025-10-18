#!/usr/bin/env python3
"""
Test script to verify the complete audio and resource cleanup fixes.

This script tests:
1. Wakeword audio playback with robust method
2. Resource cleanup between activity cycles
3. Fresh pipeline recreation
"""

import os
import sys
import logging
import time
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def test_wakeword_audio_fix():
    """Test the wakeword audio playback fix."""
    logger.info("=== Testing Wakeword Audio Fix ===")
    
    try:
        from src.components._pipeline_wakeword import VoicePipeline, create_voice_pipeline
        
        # Create a test pipeline
        access_key_path = backend_dir / "config" / "WakeWord" / "PorcupineAccessKey.txt"
        wakeword_model_path = backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel.ppn"
        intent_model_path = backend_dir / "config" / "intent_classifier"
        preference_file_path = backend_dir / "config" / "user_preference" / "preference.json"
        
        logger.info("Creating test voice pipeline...")
        pipeline = create_voice_pipeline(
            access_key_file=str(access_key_path),
            custom_keyword_file=str(wakeword_model_path),
            language="en-US",
            intent_model_path=str(intent_model_path),
            preference_file_path=str(preference_file_path),
        )
        
        # Test the audio playback method directly
        if pipeline.wakeword_audio_path:
            logger.info(f"Testing wakeword audio playback: {pipeline.wakeword_audio_path}")
            success = pipeline._play_audio_file(pipeline.wakeword_audio_path)
            if success:
                logger.info("✅ Wakeword audio playback test PASSED")
                return True
            else:
                logger.error("✗ Wakeword audio playback test FAILED")
                return False
        else:
            logger.warning("No wakeword audio path configured")
            return True
            
    except Exception as e:
        logger.error(f"Wakeword audio test failed: {e}", exc_info=True)
        return False

def test_resource_cleanup():
    """Test resource cleanup and pipeline recreation."""
    logger.info("=== Testing Resource Cleanup ===")
    
    try:
        from src.components._pipeline_wakeword import create_voice_pipeline
        from src.activities.smalltalk import SmallTalkActivity
        
        # Test 1: Create and cleanup pipeline
        logger.info("Test 1: Pipeline creation and cleanup...")
        access_key_path = backend_dir / "config" / "WakeWord" / "PorcupineAccessKey.txt"
        wakeword_model_path = backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel.ppn"
        intent_model_path = backend_dir / "config" / "intent_classifier"
        preference_file_path = backend_dir / "config" / "user_preference" / "preference.json"
        
        # Create first pipeline
        pipeline1 = create_voice_pipeline(
            access_key_file=str(access_key_path),
            custom_keyword_file=str(wakeword_model_path),
            language="en-US",
            intent_model_path=str(intent_model_path),
            preference_file_path=str(preference_file_path),
        )
        logger.info("✅ First pipeline created")
        
        # Cleanup first pipeline
        pipeline1.cleanup()
        logger.info("✅ First pipeline cleaned up")
        
        # Wait a bit for resources to be released
        time.sleep(0.5)
        
        # Create second pipeline (should work without conflicts)
        pipeline2 = create_voice_pipeline(
            access_key_file=str(access_key_path),
            custom_keyword_file=str(wakeword_model_path),
            language="en-US",
            intent_model_path=str(intent_model_path),
            preference_file_path=str(preference_file_path),
        )
        logger.info("✅ Second pipeline created successfully")
        
        # Cleanup second pipeline
        pipeline2.cleanup()
        logger.info("✅ Second pipeline cleaned up")
        
        # Test 2: SmallTalk activity cleanup
        logger.info("Test 2: SmallTalk activity cleanup...")
        activity = SmallTalkActivity(backend_dir)
        
        if activity.initialize():
            logger.info("✅ SmallTalk activity initialized")
            activity.cleanup()
            logger.info("✅ SmallTalk activity cleaned up")
        else:
            logger.error("✗ SmallTalk activity initialization failed")
            return False
        
        logger.info("✅ Resource cleanup test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Resource cleanup test failed: {e}", exc_info=True)
        return False

def test_integration():
    """Test the complete integration of fixes."""
    logger.info("=== Testing Complete Integration ===")
    
    try:
        from src.components._pipeline_wakeword import create_voice_pipeline
        from src.activities.smalltalk import SmallTalkActivity
        
        # Simulate the orchestrator's restart process
        logger.info("Simulating orchestrator restart process...")
        
        # 1. Create initial pipeline
        access_key_path = backend_dir / "config" / "WakeWord" / "PorcupineAccessKey.txt"
        wakeword_model_path = backend_dir / "config" / "WakeWord" / "WellBot_WakeWordModel.ppn"
        intent_model_path = backend_dir / "config" / "intent_classifier"
        preference_file_path = backend_dir / "config" / "user_preference" / "preference.json"
        
        pipeline = create_voice_pipeline(
            access_key_file=str(access_key_path),
            custom_keyword_file=str(wakeword_model_path),
            language="en-US",
            intent_model_path=str(intent_model_path),
            preference_file_path=str(preference_file_path),
        )
        logger.info("✅ Initial pipeline created")
        
        # 2. Simulate activity cleanup
        activity = SmallTalkActivity(backend_dir)
        if activity.initialize():
            logger.info("✅ Activity initialized")
            activity.cleanup()
            logger.info("✅ Activity cleaned up")
        
        # 3. Simulate pipeline restart (cleanup + recreate)
        logger.info("Simulating pipeline restart...")
        pipeline.cleanup()
        time.sleep(0.2)  # Guard delay
        
        # Recreate pipeline fresh
        fresh_pipeline = create_voice_pipeline(
            access_key_file=str(access_key_path),
            custom_keyword_file=str(wakeword_model_path),
            language="en-US",
            intent_model_path=str(intent_model_path),
            preference_file_path=str(preference_file_path),
        )
        logger.info("✅ Fresh pipeline created")
        
        # Test audio playback on fresh pipeline
        if fresh_pipeline.wakeword_audio_path:
            success = fresh_pipeline._play_audio_file(fresh_pipeline.wakeword_audio_path)
            if success:
                logger.info("✅ Fresh pipeline audio playback works")
            else:
                logger.error("✗ Fresh pipeline audio playback failed")
                return False
        
        # Cleanup
        fresh_pipeline.cleanup()
        logger.info("✅ Integration test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Integration test failed: {e}", exc_info=True)
        return False

def main():
    """Run all tests."""
    logger.info("=== Complete Audio and Resource Cleanup Test Suite ===")
    
    tests = [
        ("Wakeword Audio Fix", test_wakeword_audio_fix),
        ("Resource Cleanup", test_resource_cleanup),
        ("Complete Integration", test_integration),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n{'='*60}")
        logger.info(f"Running: {test_name}")
        logger.info(f"{'='*60}")
        
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            logger.error(f"Test {test_name} crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*60}")
    
    passed = 0
    for test_name, success in results:
        status = "PASSED" if success else "FAILED"
        logger.info(f"{test_name}: {status}")
        if success:
            passed += 1
    
    logger.info(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        logger.info("🎉 All tests passed! The fixes should work correctly.")
        logger.info("\nExpected behavior:")
        logger.info("1. Wakeword audio will play without Windows MCI errors")
        logger.info("2. Resources will be properly cleaned up between activity cycles")
        logger.info("3. Fresh pipeline recreation will work without conflicts")
        logger.info("4. Multiple wakeword detections should work reliably")
    else:
        logger.warning("⚠️ Some tests failed. Check the logs above for details.")

if __name__ == "__main__":
    main()
