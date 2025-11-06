#!/usr/bin/env python3
"""
Standalone Test Script for Intent Recognition

This script tests Rhino intent recognition.
It captures audio from the microphone and processes it through Rhino to detect intents.

Usage:
    python test_intent_recognition.py

Speak a command when prompted, or press Ctrl+C to stop.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

# ============================================================================
# CONFIGURATION - Tweak these variables as needed
# ============================================================================

# Path to .env file (relative to this script)
ENV_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')

# Rhino context file path (relative to backend directory)
RHINO_CONTEXT_PATH = os.path.join(
    os.path.dirname(__file__), '..', 'config', 'Intent', 'Well-Bot-Commands_en_windows_v3_0_0.rhn'
)

# Rhino settings
RHINO_SENSITIVITY = 0.5  # Detection sensitivity [0.0-1.0]
RHINO_REQUIRE_ENDPOINT = True  # Require silence after command

# Audio capture settings
CAPTURE_TIMEOUT_SECONDS = 10.0  # Maximum time to wait for intent detection

# Output directory for logs and results
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
RESULTS_FILE = os.path.join(OUTPUT_DIR, 'intent_results.json')
LOG_FILE = os.path.join(OUTPUT_DIR, 'logs', 'test_intent_recognition.log')

# ============================================================================
# SETUP
# ============================================================================

# Load environment variables
load_dotenv(ENV_FILE_PATH)

# Get Rhino access key from environment (fallback to Porcupine key)
RHINO_ACCESS_KEY = os.getenv("RHINO_ACCESS_KEY")
if not RHINO_ACCESS_KEY:
    RHINO_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY")
    if not RHINO_ACCESS_KEY:
        # Try ARM key as fallback
        RHINO_ACCESS_KEY = os.getenv("PORCUPINE_ACCESS_KEY_ARM")

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

# Add backend/src to path for imports
backend_src_path = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, backend_src_path)

# Import components
try:
    from components.intent_recognition import IntentRecognition
    from components.mic_stream import MicStream
    logger.info("Successfully imported IntentRecognition and MicStream")
except ImportError as e:
    logger.error(f"Failed to import components: {e}")
    logger.error(f"Python path: {sys.path}")
    sys.exit(1)

# ============================================================================
# MAIN TEST FUNCTION
# ============================================================================

def save_result(intent_result: dict, timestamp: str):
    """Save intent result to JSON file."""
    result_entry = {
        "timestamp": timestamp,
        "intent": intent_result.get("intent"),
        "confidence": intent_result.get("confidence"),
        "raw_result": intent_result
    }
    
    # Load existing results
    results = []
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
                results = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load existing results: {e}")
    
    # Append new result
    results.append(result_entry)
    
    # Save updated results
    try:
        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info(f"Result saved to {RESULTS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save result: {e}")

def test_single_intent(intent_recognition: IntentRecognition) -> dict:
    """Test intent recognition with a single audio capture."""
    logger.info("=" * 60)
    logger.info("Starting audio capture for intent recognition...")
    logger.info(f"Speak a command now. Timeout: {CAPTURE_TIMEOUT_SECONDS}s")
    logger.info("=" * 60)
    
    mic = None
    intent_result = None
    
    try:
        # Create and start microphone stream
        sample_rate = intent_recognition.get_sample_rate()
        frame_length = intent_recognition.get_frame_length()
        
        logger.info(f"Initializing microphone (rate: {sample_rate}Hz, frame: {frame_length})...")
        mic = MicStream(rate=sample_rate, chunk_size=frame_length)
        mic.start()
        logger.info("Microphone active")
        
        # Reset Rhino for new session
        intent_recognition.reset()
        logger.debug("Rhino engine reset")
        
        # Process audio frames
        start_time = time.time()
        frame_count = 0
        
        for audio_chunk in mic.generator():
            # Check timeout
            elapsed = time.time() - start_time
            if elapsed > CAPTURE_TIMEOUT_SECONDS:
                logger.warning(f"Timeout reached ({CAPTURE_TIMEOUT_SECONDS}s)")
                break
            
            # Process frame with Rhino
            if intent_recognition.process_bytes(audio_chunk):
                # Inference is ready
                intent_result = intent_recognition.get_inference()
                frame_count += 1
                
                if intent_result:
                    logger.info(f"Intent detected after {frame_count} frames ({elapsed:.2f}s)")
                    break
                else:
                    # Not understood, reset and continue
                    logger.debug("Rhino inference: not understood, resetting...")
                    intent_recognition.reset()
        
        # If no intent detected, set unknown
        if not intent_result:
            intent_result = {"intent": "unknown", "confidence": 0.0}
            logger.info("No intent understood, defaulting to unknown")
        
        return intent_result
        
    except Exception as e:
        logger.error(f"Error during intent recognition: {e}", exc_info=True)
        return {"intent": "error", "confidence": 0.0, "error": str(e)}
        
    finally:
        if mic:
            try:
                mic.stop()
                logger.debug("Microphone stopped")
            except Exception as e:
                logger.error(f"Error stopping microphone: {e}")

def main():
    """Main test function."""
    logger.info("=" * 60)
    logger.info("Intent Recognition Test Script")
    logger.info("=" * 60)
    
    # Validate configuration
    if not RHINO_ACCESS_KEY:
        logger.error("RHINO_ACCESS_KEY or PORCUPINE_ACCESS_KEY not found in environment variables!")
        logger.error("Please set RHINO_ACCESS_KEY or PORCUPINE_ACCESS_KEY in your .env file")
        return False
    
    if not os.path.exists(RHINO_CONTEXT_PATH):
        logger.error(f"Rhino context file not found: {RHINO_CONTEXT_PATH}")
        logger.error("Please check the RHINO_CONTEXT_PATH configuration")
        return False
    
    logger.info(f"Rhino Access Key: {RHINO_ACCESS_KEY[:10]}...")
    logger.info(f"Rhino Context: {RHINO_CONTEXT_PATH}")
    logger.info(f"Sensitivity: {RHINO_SENSITIVITY}")
    logger.info(f"Require Endpoint: {RHINO_REQUIRE_ENDPOINT}")
    logger.info(f"Output Directory: {OUTPUT_DIR}")
    logger.info(f"Results File: {RESULTS_FILE}")
    logger.info(f"Debug Log: {LOG_FILE}")
    
    intent_recognition = None
    
    try:
        # Initialize intent recognition
        logger.info("Initializing Rhino intent recognition...")
        intent_recognition = IntentRecognition(
            access_key=RHINO_ACCESS_KEY,
            context_path=Path(RHINO_CONTEXT_PATH),
            sensitivity=RHINO_SENSITIVITY,
            require_endpoint=RHINO_REQUIRE_ENDPOINT
        )
        
        logger.info("Rhino initialized successfully!")
        logger.info(f"Sample rate: {intent_recognition.get_sample_rate()} Hz")
        logger.info(f"Frame length: {intent_recognition.get_frame_length()}")
        
        # Test loop
        logger.info("=" * 60)
        logger.info("Ready for intent recognition testing")
        logger.info("Press Enter to start a test, or type 'quit' to exit")
        logger.info("=" * 60)
        
        while True:
            try:
                user_input = input("\nPress Enter to test (or 'quit' to exit): ").strip().lower()
                if user_input == 'quit':
                    break
                
                # Run single intent test
                result = test_single_intent(intent_recognition)
                
                # Display result
                timestamp = datetime.now().isoformat()
                logger.info("=" * 60)
                logger.info("INTENT RECOGNITION RESULT")
                logger.info(f"Timestamp: {timestamp}")
                logger.info(f"Intent: {result.get('intent', 'N/A')}")
                logger.info(f"Confidence: {result.get('confidence', 0.0):.3f}")
                logger.info("=" * 60)
                
                # Save result
                save_result(result, timestamp)
                
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Error in test loop: {e}", exc_info=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Error during intent recognition test: {e}", exc_info=True)
        return False
        
    finally:
        # Cleanup
        if intent_recognition:
            try:
                logger.info("Cleaning up Rhino engine...")
                intent_recognition.delete()
                logger.info("Cleanup completed")
            except Exception as e:
                logger.error(f"Error during cleanup: {e}", exc_info=True)
        
        logger.info("=" * 60)
        logger.info("Test completed")
        logger.info("=" * 60)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

