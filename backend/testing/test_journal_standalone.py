#!/usr/bin/env python3
"""
Standalone Journal Test Script
Test the journaling feature independently before integration.
"""

import os
import sys
import logging
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.activities.journal import JournalActivity

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Main entry point for standalone journal test"""
    
    logger.info("=" * 70)
    logger.info("STANDALONE JOURNAL FEATURE TEST")
    logger.info("=" * 70)
    logger.info("")
    logger.info("This script will test the journaling feature independently.")
    logger.info("")
    logger.info("Behavior:")
    logger.info("  - Starts recording when you speak")
    logger.info("  - Finalizes paragraphs after 2.5s pauses")
    logger.info("  - Can be stopped with termination phrases:")
    logger.info("    * stop journal")
    logger.info("    * save journal")
    logger.info("    * end entry")
    logger.info("    * that's all")
    logger.info("  - Auto-saves after 90s + 20s inactivity")
    logger.info("  - Can be interrupted with Ctrl+C")
    logger.info("")
    logger.info("Press Ctrl+C at any time to exit gracefully")
    logger.info("=" * 70)
    logger.info("")
    
    # Create and initialize journal activity
    journal = JournalActivity(backend_dir=backend_dir)
    
    if not journal.initialize():
        logger.error("Failed to initialize journal activity")
        sys.exit(1)
    
    # Start the journal session
    try:
        logger.info("Starting journal session...")
        logger.info("")
        journal.start()
        
    except KeyboardInterrupt:
        logger.info("")
        logger.info("Session interrupted by user (Ctrl+C)")
        logger.info("Auto-saving accumulated content...")
        
        # The save will happen in the finally block
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        logger.info("")
        logger.info("=" * 70)
        logger.info("Test completed")
        logger.info("=" * 70)
        
        # Display final status
        status = journal.get_status()
        logger.info(f"Status: {status}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

