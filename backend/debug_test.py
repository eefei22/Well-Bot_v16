#!/usr/bin/env python3
"""
Debug script to test the Well-Bot orchestrator step by step
"""

import os
import sys
import logging
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent
sys.path.append(str(backend_dir))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def test_orchestrator_initialization():
    """Test if the orchestrator initializes properly"""
    try:
        from main import WellBotOrchestrator
        
        logger.info("=== Testing Orchestrator Initialization ===")
        orchestrator = WellBotOrchestrator()
        
        # Test config validation
        logger.info("Testing config validation...")
        if not orchestrator._validate_config_files():
            logger.error("❌ Config validation failed")
            return False
        logger.info("✅ Config validation passed")
        
        # Test component initialization
        logger.info("Testing component initialization...")
        if not orchestrator._initialize_components():
            logger.error("❌ Component initialization failed")
            return False
        logger.info("✅ Component initialization passed")
        
        # Test SmallTalk activity specifically
        logger.info("Testing SmallTalk activity...")
        if orchestrator.smalltalk_activity:
            logger.info(f"✅ SmallTalk activity exists: {orchestrator.smalltalk_activity}")
            logger.info(f"✅ SmallTalk activity initialized: {orchestrator.smalltalk_activity._initialized}")
        else:
            logger.error("❌ SmallTalk activity is None")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Initialization test failed: {e}", exc_info=True)
        return False

def test_intent_routing():
    """Test the intent routing logic"""
    try:
        from main import WellBotOrchestrator
        
        logger.info("=== Testing Intent Routing ===")
        orchestrator = WellBotOrchestrator()
        
        # Test different intents
        test_intents = ["small_talk", "unknown", "todo_add", "journal_write"]
        
        for intent in test_intents:
            logger.info(f"Testing intent: {intent}")
            try:
                orchestrator._route_to_activity(intent, "test transcript")
                logger.info(f"✅ Intent '{intent}' routed successfully")
            except Exception as e:
                logger.error(f"❌ Intent '{intent}' routing failed: {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Intent routing test failed: {e}", exc_info=True)
        return False

def main():
    """Run all tests"""
    logger.info("=== Well-Bot Debug Tests ===")
    
    # Test 1: Initialization
    if not test_orchestrator_initialization():
        logger.error("Initialization test failed - stopping")
        return 1
    
    # Test 2: Intent routing
    if not test_intent_routing():
        logger.error("Intent routing test failed - stopping")
        return 1
    
    logger.info("=== All tests passed! ===")
    return 0

if __name__ == "__main__":
    exit(main())
