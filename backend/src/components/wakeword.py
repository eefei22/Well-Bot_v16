"""
Wake Word Detection Service using Porcupine

This service handles continuous wake word detection using Picovoice's Porcupine engine.
It runs in the background and triggers callbacks when wake words are detected.
"""

import os
import sys
import pvporcupine
import pyaudio
import struct
import threading
from typing import Optional, List, Callable
import logging

# Add the backend directory to the path to import config
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from ..config_loader import PORCUPINE_ACCESS_KEY
except ImportError:
    from config_loader import PORCUPINE_ACCESS_KEY

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Continuous wake word detection service using Porcupine engine.
    Runs in the background and triggers callbacks when wake words are detected.
    """
    
    def __init__(self, access_key: str, custom_keyword_path: Optional[str] = None):
        """
        Initialize the wake word detector.
        
        Args:
            access_key: Picovoice access key
            custom_keyword_path: Path to custom wake word model (.ppn file)
        """
        self.access_key = access_key
        self.custom_keyword_path = custom_keyword_path
        self.porcupine = None
        self._pa = None
        self._stream = None
        self.running = False
        self._thread = None
        self.is_initialized = False
        
    def initialize(self, built_in_keywords: Optional[List[str]] = None) -> bool:
        """
        Initialize the Porcupine engine and PyAudio.
        
        Args:
            built_in_keywords: List of built-in keywords to detect (e.g., ['picovoice', 'bumblebee'])
            
        Returns:
            True if initialization successful, False otherwise
        """
        try:
            keyword_paths = []
            keywords = []
            
            # Add custom keyword if provided
            if self.custom_keyword_path and os.path.exists(self.custom_keyword_path):
                keyword_paths.append(self.custom_keyword_path)
                keywords.append("custom")
                logger.info(f"Custom wake word: Well-Bot")
            
            # Add built-in keywords if provided
            if built_in_keywords:
                keywords.extend(built_in_keywords)
                logger.info(f"Added built-in keywords: {built_in_keywords}")
            
            if not keyword_paths and not built_in_keywords:
                logger.error("No keywords or keyword paths provided")
                return False
            
            # Create Porcupine instance
            self.porcupine = pvporcupine.create(
                access_key=self.access_key,
                keywords=keywords if not keyword_paths else None,
                keyword_paths=keyword_paths if keyword_paths else None
            )
            
            # Initialize PyAudio
            self._pa = pyaudio.PyAudio()
            
            self.is_initialized = True
            logger.info(f"Wake word detector ready | Frame: {self.porcupine.frame_length} | Rate: {self.porcupine.sample_rate}Hz")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize wake word detector: {e}")
            return False
    
    def start(self, on_detected: Callable[[], None]):
        """
        Start listening for wake words in the background.
        
        Args:
            on_detected: Callback function to call when wake word is detected
        """
        if not self.is_initialized:
            logger.error("Wake word detector not initialized. Call initialize() first.")
            return
            
        if self.running:
            logger.warning("Wake word detector is already running")
            return
            
        self.running = True
        
        def _run_loop():
            """Background thread loop for continuous wake word detection."""
            try:
                # Open audio stream
                self._stream = self._pa.open(
                    rate=self.porcupine.sample_rate,
                    channels=1,
                    format=pyaudio.paInt16,
                    input=True,
                    frames_per_buffer=self.porcupine.frame_length
                )
                
                logger.info("Wake word detection active")
                
                while self.running:
                    try:
                        # Read audio frame
                        pcm_bytes = self._stream.read(
                            self.porcupine.frame_length, 
                            exception_on_overflow=False
                        )
                        
                        # Convert bytes to PCM samples
                        pcm = struct.unpack_from("h" * self.porcupine.frame_length, pcm_bytes)
                        
                        # Process frame for wake word detection
                        result = self.porcupine.process(pcm)
                        
                        if result >= 0:
                            logger.info("Wake word detected")
                            try:
                                on_detected()
                            except Exception as e:
                                logger.error(f"Exception in wake word callback: {e}")
                                
                    except Exception as e:
                        if self.running:  # Only log if we're still supposed to be running
                            logger.error(f"Error in wake word detection loop: {e}")
                            
            except Exception as e:
                logger.error(f"Failed to start audio stream: {e}")
            finally:
                # Cleanup audio stream
                if self._stream is not None:
                    try:
                        self._stream.stop_stream()
                        self._stream.close()
                        self._stream = None
                    except Exception as e:
                        logger.error(f"Error closing audio stream: {e}")
                        
                logger.info("Wake word detection loop ended")
        
        # Start background thread
        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
        
    def stop(self):
        """Stop the continuous wake word detection."""
        if not self.running:
            logger.warning("Wake word detector is not running")
            return
            
        logger.info("Stopping wake word detection...")
        self.running = False
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            
        logger.info("Wake word detection stopped")
    
    def get_frame_length(self) -> Optional[int]:
        """Get the required frame length for audio processing."""
        if self.porcupine:
            return self.porcupine.frame_length
        return None
    
    def get_sample_rate(self) -> Optional[int]:
        """Get the required sample rate for audio processing."""
        if self.porcupine:
            return self.porcupine.sample_rate
        return None
    
    def cleanup(self):
        """Clean up resources."""
        # Stop detection if running
        if self.running:
            self.stop()
            
        # Cleanup audio stream
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None
            except Exception as e:
                logger.error(f"Error closing audio stream during cleanup: {e}")
        
        # Cleanup PyAudio
        if self._pa is not None:
            try:
                self._pa.terminate()
                self._pa = None
            except Exception as e:
                logger.error(f"Error terminating PyAudio during cleanup: {e}")
        
        # Cleanup Porcupine
        if self.porcupine:
            try:
                self.porcupine.delete()
                logger.info("Wake word detector cleaned up")
            except Exception as e:
                logger.error(f"Error during Porcupine cleanup: {e}")
            finally:
                self.porcupine = None
                self.is_initialized = False


def create_wake_word_detector(access_key_file: str, custom_keyword_file: Optional[str] = None) -> WakeWordDetector:
    """
    Factory function to create a wake word detector.
    
    Args:
        access_key_file: Path to file containing Picovoice access key (deprecated, now uses env var)
        custom_keyword_file: Path to custom wake word model file
        
    Returns:
        WakeWordDetector instance
    """
    try:
        # Use access key from environment variables
        return WakeWordDetector(PORCUPINE_ACCESS_KEY, custom_keyword_file)
        
    except Exception as e:
        logger.error(f"Failed to create wake word detector: {e}")
        raise


# Example usage and testing
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Paths relative to this file
    current_dir = os.path.dirname(__file__)
    access_key_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'PorcupineAccessKey.txt')
    custom_keyword_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'Well-Bot_en_raspberry-pi_v3_0_0.ppn')
    
    def on_wake_word_detected():
        """Callback function called when wake word is detected."""
        print("🎤 Wake word detected! Starting STT pipeline...")
        # Here you would trigger the STT pipeline
        # For example: stt_pipeline.start()
    
    try:
        # Create detector
        detector = create_wake_word_detector(access_key_path, custom_keyword_path)
        
        # Initialize with custom wake word
        if detector.initialize():
            print(f"Wake word detector initialized successfully!")
            print(f"Frame length: {detector.get_frame_length()}")
            print(f"Sample rate: {detector.get_sample_rate()}")
            
            # Start continuous listening
            print("Starting continuous wake word detection...")
            print("Say the wake word to test detection. Press Ctrl+C to stop.")
            detector.start(on_wake_word_detected)
            
            # Keep the main thread alive
            try:
                while True:
                    import time
                    time.sleep(0.1)
            except KeyboardInterrupt:
                print("\nStopping wake word detection...")
                detector.stop()
        else:
            print("Failed to initialize wake word detector")
            
        # Cleanup
        detector.cleanup()
        
    except Exception as e:
        print(f"Error: {e}")
