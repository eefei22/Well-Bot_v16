#!/usr/bin/env python3
"""
OpenWakeWord Feasibility Test

This script tests OpenWakeWord as a potential replacement for Porcupine.
It uses built-in pre-trained models to verify:
- Audio capture works correctly
- OpenWakeWord runs in real-time on the hardware
- Detection accuracy and performance

Usage:
    python test_openwakeword.py

Press Ctrl+C to stop.
"""

import os
import sys
import time
import logging
import struct
from datetime import datetime
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Try importing required libraries
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    logger.error("pyaudio not available. Install with: pip install pyaudio")

try:
    import openwakeword
    from openwakeword.model import Model
    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False
    logger.error("openwakeword not available. Install with: pip install openwakeword")

import numpy as np


def download_models_if_needed():
    """Download OpenWakeWord models if not already present."""
    try:
        logger.info("Checking for OpenWakeWord models...")
        openwakeword.utils.download_models()
        logger.info("✓ Models ready")
    except Exception as e:
        logger.warning(f"Error downloading models: {e}")
        logger.info("Models may already be downloaded, continuing...")


def test_openwakeword():
    """Test OpenWakeWord with built-in models."""
    
    if not PYAUDIO_AVAILABLE:
        logger.error("Cannot run test: pyaudio not available")
        return False
    
    if not OPENWAKEWORD_AVAILABLE:
        logger.error("Cannot run test: openwakeword not available")
        return False
    
    # Download models
    download_models_if_needed()
    
    # Initialize OpenWakeWord model
    logger.info("Initializing OpenWakeWord model...")
    try:
        model = Model()
        logger.info(f"✓ Model initialized with {len(model.models)} built-in models")
        logger.info(f"Available models: {list(model.models.keys())}")
    except Exception as e:
        logger.error(f"Failed to initialize model: {e}", exc_info=True)
        return False
    
    # Audio configuration (matching your existing setup)
    SAMPLE_RATE = 16000
    CHANNELS = 1
    FORMAT = pyaudio.paInt16
    CHUNK_SIZE = 1280  # OpenWakeWord typically uses 1280 samples per frame (80ms at 16kHz)
    
    # Detection threshold (adjust as needed)
    DETECTION_THRESHOLD = 0.5
    
    # Initialize PyAudio
    pa = pyaudio.PyAudio()
    
    # Print available audio devices
    logger.info("\nAvailable audio input devices:")
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if info['maxInputChannels'] > 0:
            logger.info(f"  [{i}] {info['name']} - {info['maxInputChannels']} channels")
    
    try:
        # Open audio stream
        logger.info(f"\nOpening audio stream: {SAMPLE_RATE}Hz, {CHANNELS} channel(s), chunk={CHUNK_SIZE}")
        stream = pa.open(
            rate=SAMPLE_RATE,
            channels=CHANNELS,
            format=FORMAT,
            input=True,
            frames_per_buffer=CHUNK_SIZE
        )
        
        logger.info("✓ Audio stream opened")
        logger.info("\n" + "="*60)
        logger.info("Listening for wake words...")
        logger.info(f"Detection threshold: {DETECTION_THRESHOLD}")
        logger.info("Say wake words like 'hey jarvis', 'alexa', etc.")
        logger.info("Press Ctrl+C to stop")
        logger.info("="*60 + "\n")
        
        detection_count = 0
        frame_count = 0
        start_time = time.time()
        
        try:
            while True:
                # Read audio frame
                audio_bytes = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                
                # Convert bytes to numpy array (int16)
                audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                
                # OpenWakeWord expects int16 array
                # Get predictions for all models
                prediction = model.predict(audio_data)
                
                frame_count += 1
                
                # Check each model's prediction
                for model_name, score in prediction.items():
                    if score > DETECTION_THRESHOLD:
                        detection_count += 1
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        logger.info(
                            f"[{timestamp}] 🔔 WAKE WORD DETECTED: '{model_name}' "
                            f"(score: {score:.3f})"
                        )
                
                # Log stats every 5 seconds
                if frame_count % 250 == 0:  # ~5 seconds at 16kHz
                    elapsed = time.time() - start_time
                    fps = frame_count / elapsed if elapsed > 0 else 0
                    logger.debug(f"Stats: {frame_count} frames processed, {fps:.1f} fps, {detection_count} detections")
        
        except KeyboardInterrupt:
            logger.info("\n\nStopping...")
        
        finally:
            # Cleanup
            stream.stop_stream()
            stream.close()
            
            elapsed = time.time() - start_time
            logger.info("\n" + "="*60)
            logger.info("Test Summary:")
            logger.info(f"  Total frames processed: {frame_count}")
            logger.info(f"  Total detections: {detection_count}")
            logger.info(f"  Test duration: {elapsed:.1f} seconds")
            logger.info(f"  Average FPS: {frame_count / elapsed:.1f}" if elapsed > 0 else "  Average FPS: N/A")
            logger.info("="*60)
    
    except Exception as e:
        logger.error(f"Error during audio capture: {e}", exc_info=True)
        return False
    
    finally:
        pa.terminate()
        # Cleanup model
        try:
            model.__del__()
        except:
            pass
    
    return True


if __name__ == "__main__":
    logger.info("="*60)
    logger.info("OpenWakeWord Feasibility Test")
    logger.info("="*60)
    
    success = test_openwakeword()
    
    if success:
        logger.info("\n✓ Test completed successfully")
        logger.info("\nNext steps:")
        logger.info("  1. Verify detections work correctly")
        logger.info("  2. Check CPU/memory usage")
        logger.info("  3. Test with custom wake word model (if needed)")
    else:
        logger.error("\n✗ Test failed - check errors above")
        sys.exit(1)

