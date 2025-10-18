#!/usr/bin/env python3
"""
Test script to verify the SmallTalk activity re-initialization fix.

This script tests the complete cycle:
1. Initialize activity
2. Run activity
3. Cleanup activity
4. Re-initialize activity
5. Run activity again
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

def test_activity_reinitialization():
    """Test the complete activity lifecycle with re-initialization."""
    logger.info("=== Testing SmallTalk Activity Re-initialization ===")
    
    try:
        from src.activities.smalltalk import SmallTalkActivity
        
        # Test 1: Initial setup
        logger.info("Test 1: Initial activity setup...")
        activity = SmallTalkActivity(backend_dir)
        
        if not activity.initialize():
            logger.error("❌ Initial initialization failed")
            return False
        
        logger.info("✅ Initial initialization successful")
        logger.info(f"Manager exists: {activity.manager is not None}")
        logger.info(f"Initialized: {activity._initialized}")
        
        # Test 2: First run simulation
        logger.info("Test 2: First activity run simulation...")
        if not activity.start():
            logger.error("❌ First start failed")
            return False
        
        logger.info("✅ First start successful")
        logger.info(f"Manager active: {activity.manager.is_active() if activity.manager else False}")
        
        # Simulate activity running
        time.sleep(1)
        
        # Stop the activity
        activity.stop()
        logger.info("✅ First activity stopped")
        
        # Test 3: Cleanup
        logger.info("Test 3: Activity cleanup...")
        activity.cleanup()
        logger.info("✅ Activity cleanup completed")
        logger.info(f"Manager after cleanup: {activity.manager is not None}")
        logger.info(f"Initialized after cleanup: {activity._initialized}")
        
        # Test 4: Re-initialization
        logger.info("Test 4: Activity re-initialization...")
        if not activity.reinitialize():
            logger.error("❌ Re-initialization failed")
            return False
        
        logger.info("✅ Re-initialization successful")
        logger.info(f"Manager after reinit: {activity.manager is not None}")
        logger.info(f"Initialized after reinit: {activity._initialized}")
        
        # Test 5: Second run
        logger.info("Test 5: Second activity run...")
        if not activity.start():
            logger.error("❌ Second start failed")
            return False
        
        logger.info("✅ Second start successful")
        logger.info(f"Manager active: {activity.manager.is_active() if activity.manager else False}")
        
        # Stop and cleanup
        activity.stop()
        activity.cleanup()
        
        logger.info("✅ Complete lifecycle test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Activity re-initialization test failed: {e}", exc_info=True)
        return False

def test_multiple_cycles():
    """Test multiple complete cycles."""
    logger.info("=== Testing Multiple Activity Cycles ===")
    
    try:
        from src.activities.smalltalk import SmallTalkActivity
        
        activity = SmallTalkActivity(backend_dir)
        
        for cycle in range(3):
            logger.info(f"Cycle {cycle + 1}:")
            
            # Initialize
            if not activity.initialize():
                logger.error(f"❌ Cycle {cycle + 1} initialization failed")
                return False
            
            # Start
            if not activity.start():
                logger.error(f"❌ Cycle {cycle + 1} start failed")
                return False
            
            logger.info(f"✅ Cycle {cycle + 1} started successfully")
            
            # Simulate running
            time.sleep(0.5)
            
            # Stop and cleanup
            activity.stop()
            activity.cleanup()
            
            logger.info(f"✅ Cycle {cycle + 1} completed")
        
        logger.info("✅ Multiple cycles test PASSED")
        return True
        
    except Exception as e:
        logger.error(f"Multiple cycles test failed: {e}", exc_info=True)
        return False

def main():
    """Run all tests."""
    logger.info("=== SmallTalk Activity Re-initialization Test Suite ===")
    
    tests = [
        ("Activity Re-initialization", test_activity_reinitialization),
        ("Multiple Cycles", test_multiple_cycles),
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
        logger.info("🎉 All tests passed! The re-initialization fix should work correctly.")
        logger.info("\nExpected behavior:")
        logger.info("1. First activity run works normally")
        logger.info("2. After cleanup, manager is properly reset")
        logger.info("3. Re-initialization recreates the manager")
        logger.info("4. Second activity run works without errors")
        logger.info("5. Multiple cycles work reliably")
    else:
        logger.warning("⚠️ Some tests failed. Check the logs above for details.")

if __name__ == "__main__":
    main()
