#!/usr/bin/env python3
"""
Standalone Test Script for Wakeword Detection

This script tests wakeword detection using Porcupine.
It continuously listens for the wake word and logs all detection events.

Usage:
    python test_wakeword.py

Press Ctrl+C to stop.
"""

import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION - Tweak these variables as needed
# ============================================================================

# Path to .env file (relative to this script)
ENV_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')

# Wakeword model file path (relative to backend directory)
WAKEWORD_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'config', 'WakeWord', 'WellBot_WakeWordModel.ppn'
)

# Output directory for logs and results
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
DETECTION_LOG_FILE = os.path.join(OUTPUT_DIR, 'wakeword_detections.log')
LOG_FILE = os.path.join(OUTPUT_DIR, 'logs', 'test_wakeword.log')

# ============================================================================
# SETUP
# ============================================================================

# Load environment variables
load_dotenv(ENV_FILE_PATH)

# Get Porcupine access key from environment
PORCUPINE_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY")
if not PORCUPINE_ACCESS_KEY:
    # Try ARM key as fallback
    PORCUPINE_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY_ARM")

# Create output directories
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, 'logs'), exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Add backend directory to path for imports (needed for relative imports in components)
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

# Import wakeword component
try:
    from src.components.wakeword import WakeWordDetector
    logger.info("Successfully imported WakeWordDetector")
except ImportError as e:
    logger.error(f"Failed to import WakeWordDetector: {e}")
    logger.error(f"Python path: {sys.path}")
    sys.exit(1)

# ============================================================================
# MAIN TEST FUNCTION
# ============================================================================

def on_wake_word_detected():
    """Callback function called when wake word is detected."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    detection_msg = f"[{timestamp}] Wake word detected!"
    
    logger.info("=" * 60)
    logger.info(detection_msg)
    logger.info("=" * 60)
    
    # Write to detection log file
    try:
        with open(DETECTION_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{detection_msg}\n")
    except Exception as e:
        logger.error(f"Failed to write to detection log: {e}")

def main():
    """Main test function."""
    logger.info("=" * 60)
    logger.info("Wakeword Detection Test Script")
    logger.info("=" * 60)
    
    # Validate configuration
    if not PORCUPINE_ACCESS_KEY:
        logger.error("PORCUPINE_ACCESS_KEY not found in environment variables!")
        logger.error("Please set PORCUPINE_ACCESS_KEY in your .env file")
        return False
    
    if not os.path.exists(WAKEWORD_MODEL_PATH):
        logger.error(f"Wakeword model file not found: {WAKEWORD_MODEL_PATH}")
        logger.error("Please check the WAKEWORD_MODEL_PATH configuration")
        return False
    
    logger.info(f"Porcupine Access Key: {PORCUPINE_ACCESS_KEY[:10]}...")
    logger.info(f"Wakeword Model: {WAKEWORD_MODEL_PATH}")
    logger.info(f"Output Directory: {OUTPUT_DIR}")
    logger.info(f"Detection Log: {DETECTION_LOG_FILE}")
    logger.info(f"Debug Log: {LOG_FILE}")
    
    detector = None
    
    try:
        # Create wakeword detector
        logger.info("Creating WakeWordDetector...")
        detector = WakeWordDetector(
            access_key=PORCUPINE_ACCESS_KEY,
            custom_keyword_path=WAKEWORD_MODEL_PATH
        )
        logger.info("WakeWordDetector created successfully")
        
        # Initialize detector
        logger.info("Initializing wakeword detector...")
        if not detector.initialize():
            logger.error("Failed to initialize wakeword detector")
            return False
        
        logger.info("Wakeword detector initialized successfully!")
        logger.info(f"Frame length: {detector.get_frame_length()}")
        logger.info(f"Sample rate: {detector.get_sample_rate()} Hz")
        
        # Start continuous listening
        logger.info("=" * 60)
        logger.info("Starting continuous wake word detection...")
        logger.info("Say the wake word to test detection.")
        logger.info("Press Ctrl+C to stop.")
        logger.info("=" * 60)
        
        detector.start(on_wake_word_detected)
        
        # Keep the main thread alive
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("Interrupted by user (Ctrl+C)")
            logger.info("Stopping wake word detection...")
            logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Error during wakeword test: {e}", exc_info=True)
        return False
        
    finally:
        # Cleanup
        if detector:
            try:
                logger.info("Cleaning up wakeword detector...")
                detector.stop()
                detector.cleanup()
                logger.info("Cleanup completed")
            except Exception as e:
                logger.error(f"Error during cleanup: {e}", exc_info=True)
        
        logger.info("=" * 60)
        logger.info("Test completed")
        logger.info("=" * 60)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

