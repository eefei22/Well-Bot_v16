"""
Wake Word Detection Service using Porcupine

This service handles continuous wake word detection using Picovoice's Porcupine engine.
It runs in the background and triggers callbacks when wake words are detected.
"""

import os
import sys
import logging

try:
    import pvporcupine
    PORCUPINE_AVAILABLE = True
except ImportError:
    PORCUPINE_AVAILABLE = False
    pvporcupine = None

import pyaudio
import struct
import threading
import time
from typing import Optional, List, Callable, Union, Generator
from pathlib import Path

logger = logging.getLogger(__name__)

# Try importing OpenWakeWord
try:
    import openwakeword
    from openwakeword.model import Model
    import numpy as np
    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False
    Model = None
    np = None
    logger.warning("openwakeword not available - fallback will not work")

if not PORCUPINE_AVAILABLE:
    logger.warning("pvporcupine not available - wake word detection will not work")

# Add the backend directory to the path to import config
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from ..utils.config_loader import PORCUPINE_ACCESS_KEY
except ImportError:
    from utils.config_loader import PORCUPINE_ACCESS_KEY

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Continuous wake word detection service using Porcupine engine.
    Runs in the background and triggers callbacks when wake words are detected.
    """
    
    def __init__(self, access_key: str, custom_keyword_path: Optional[str] = None, ui_interface=None):
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
        self.ui_interface = ui_interface
        
        # For subscription-based mode
        self._audio_generator = None
        self._subscription_mode = False
        self._frame_buffer = bytearray()  # Buffer for frame alignment
        
    def initialize(self, built_in_keywords: Optional[List[str]] = None) -> bool:
        """
        Initialize the Porcupine engine and PyAudio.
        
        Args:
            built_in_keywords: List of built-in keywords to detect (e.g., ['picovoice', 'bumblebee'])
            
        Returns:
            True if initialization successful, False otherwise
        """
        if not PORCUPINE_AVAILABLE:
            logger.error("pvporcupine is not available - cannot initialize wake word detector")
            return False
            
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
                # Notify UI that mic is active/listening
                try:
                    if self.ui_interface:
                        self.ui_interface.update_mic_status("idle")
                except Exception:
                    pass
                
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
                # Ensure UI mic status reset
                try:
                    if self.ui_interface:
                        self.ui_interface.update_mic_status("idle")
                except Exception:
                    pass
                        
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
        
        # If in subscription mode, generator will end naturally
        # If in direct mode, stop audio stream
        if not self._subscription_mode and self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        
        # Clear subscription state
        self._subscription_mode = False
        self._audio_generator = None
        self._frame_buffer = bytearray()
            
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
    
    def process_audio_chunk(self, audio_chunk: bytes) -> Optional[int]:
        """
        Process audio chunk for wake word detection.
        
        This method handles chunk size mismatch by buffering and splitting
        chunks into Porcupine frame_length sized frames.
        
        Args:
            audio_chunk: Audio chunk bytes (16-bit PCM)
        
        Returns:
            Keyword index if detected (>= 0), None otherwise
        """
        if not self.is_initialized or not self.porcupine:
            logger.error("Wake word detector not initialized")
            return None
        
        frame_length = self.porcupine.frame_length
        bytes_per_frame = frame_length * 2  # 16-bit = 2 bytes per sample
        
        # Add chunk to buffer
        self._frame_buffer.extend(audio_chunk)
        
        # Process complete frames
        while len(self._frame_buffer) >= bytes_per_frame:
            # Extract one frame
            frame_bytes = bytes(self._frame_buffer[:bytes_per_frame])
            self._frame_buffer = self._frame_buffer[bytes_per_frame:]
            
            # Convert bytes to PCM samples
            pcm = struct.unpack_from("h" * frame_length, frame_bytes)
            
            # Process frame with Porcupine
            try:
                result = self.porcupine.process(pcm)
                if result >= 0:
                    logger.info(f"Wake word detected (keyword index: {result})")
                    return result
            except Exception as e:
                logger.error(f"Error processing frame: {e}")
        
        return None
    
    def start_with_subscription(self, audio_generator: Generator[bytes, None, None], on_detected: Callable[[], None]):
        """
        Start wake word detection using audio from SharedAudioManager.
        
        Args:
            audio_generator: Generator yielding audio chunks from SharedAudioManager
            on_detected: Callback function to call when wake word is detected
        """
        if not self.is_initialized:
            logger.error("Wake word detector not initialized. Call initialize() first.")
            return
        
        if self.running:
            logger.warning("Wake word detector is already running")
            return
        
        self.running = True
        self._subscription_mode = True
        self._audio_generator = audio_generator
        self._frame_buffer = bytearray()  # Reset buffer
        
        def _run_loop():
            """Background thread loop for subscription-based wake word detection."""
            logger.info("Wake word detection active (subscription mode)")
            # Notify UI that mic is active when subscription mode starts
            try:
                if self.ui_interface:
                    self.ui_interface.update_mic_status("idle")
            except Exception:
                pass
            
            try:
                for audio_chunk in audio_generator:
                    if not self.running:
                        break
                    
                    # Process chunk
                    result = self.process_audio_chunk(audio_chunk)
                    
                    if result is not None and result >= 0:
                        logger.info("Wake word detected")
                        try:
                            on_detected()
                        except Exception as e:
                            logger.error(f"Exception in wake word callback: {e}")
                            
            except StopIteration:
                logger.info("Audio generator ended")
            except Exception as e:
                if self.running:
                    logger.error(f"Error in wake word detection loop: {e}", exc_info=True)
            finally:
                logger.info("Wake word detection loop ended")
                self._subscription_mode = False
                self._audio_generator = None
                # Ensure UI mic status reset
                try:
                    if self.ui_interface:
                        self.ui_interface.update_mic_status("idle")
                except Exception:
                    pass
        
        # Start background thread
        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
    
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


class OpenWakeWordDetector:
    """
    Continuous wake word detection service using OpenWakeWord engine.
    Runs in the background and triggers callbacks when wake words are detected.
    This is used as a fallback when Porcupine fails to initialize.
    """
    
    def __init__(self, backend_dir: Optional[Path] = None, ui_interface=None):
        """
        Initialize the OpenWakeWord detector.
        
        Args:
            backend_dir: Path to backend directory (for finding model files)
        """
        self.backend_dir = backend_dir
        self.model = None
        self._pa = None
        self._stream = None
        self.running = False
        self._thread = None
        self.is_initialized = False
        
        # For subscription-based mode
        self._audio_generator = None
        self._subscription_mode = False
        
        # Model paths
        if backend_dir:
            self.model_dir = backend_dir / "config" / "WakeWord"
            self.model_onnx = self.model_dir / "well_bot.onnx"
            self.model_tflite = self.model_dir / "well_bot.tflite"
        else:
            # Fallback: try to determine backend_dir from current file location
            current_file = Path(__file__)
            self.model_dir = current_file.parent.parent.parent / "config" / "WakeWord"
            self.model_onnx = self.model_dir / "well_bot.onnx"
            self.model_tflite = self.model_dir / "well_bot.tflite"
        
        # Detection threshold
        self.detection_threshold = 0.5

        # Optional UI interface to update mic/speaker state
        self.ui_interface = ui_interface
        
        # Audio configuration
        self.sample_rate = 16000
        self.chunk_size = 1280  # 80ms at 16kHz
        
        # Internal debouncing (handled by idle_mode's _on_wake, but add extra safety)
        self._last_detection_time = 0.0
        self._detection_debounce_seconds = 0.5  # 500ms debounce within detector
        
    def initialize(self, built_in_keywords: Optional[List[str]] = None) -> bool:
        """
        Initialize the OpenWakeWord model and PyAudio.
        
        Args:
            built_in_keywords: Not used for OpenWakeWord (kept for interface compatibility)
            
        Returns:
            True if initialization successful, False otherwise
        """
        if not OPENWAKEWORD_AVAILABLE:
            logger.error("openwakeword is not available - cannot initialize OpenWakeWord detector")
            return False
        
        try:
            # Determine which model file to use (prefer ONNX, fallback to TFLite)
            model_path = None
            inference_framework = None
            
            if self.model_onnx.exists():
                model_path = self.model_onnx
                inference_framework = 'onnx'
                logger.info(f"Found ONNX model: {model_path}")
            elif self.model_tflite.exists():
                model_path = self.model_tflite
                inference_framework = 'tflite'
                logger.info(f"Found TFLite model: {model_path}")
            else:
                logger.error(f"Custom wake word model not found!")
                logger.error(f"Expected ONNX model at: {self.model_onnx}")
                logger.error(f"Or TFLite model at: {self.model_tflite}")
                return False
            
            # Initialize OpenWakeWord model
            self.model = Model(
                wakeword_models=[str(model_path)],
                inference_framework=inference_framework
            )
            
            # Initialize PyAudio
            self._pa = pyaudio.PyAudio()
            
            self.is_initialized = True
            logger.info(f"OpenWakeWord detector ready | Chunk: {self.chunk_size} | Rate: {self.sample_rate}Hz | Threshold: {self.detection_threshold}")
            logger.info(f"Using model: {model_path.name} ({inference_framework})")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize OpenWakeWord detector: {e}", exc_info=True)
            return False
    
    def start(self, on_detected: Callable[[], None]):
        """
        Start listening for wake words in the background.
        
        Args:
            on_detected: Callback function to call when wake word is detected
        """
        if not self.is_initialized:
            logger.error("OpenWakeWord detector not initialized. Call initialize() first.")
            return
            
        if self.running:
            logger.warning("OpenWakeWord detector is already running")
            return
            
        self.running = True
        
        def _run_loop():
            """Background thread loop for continuous wake word detection."""
            try:
                # Open audio stream
                self._stream = self._pa.open(
                    rate=self.sample_rate,
                    channels=1,
                    format=pyaudio.paInt16,
                    input=True,
                    frames_per_buffer=self.chunk_size
                )
                # Notify UI that mic is active/listening
                try:
                    if self.ui_interface:
                        self.ui_interface.update_mic_status("idle")
                except Exception:
                    pass
                
                logger.info("OpenWakeWord detection active")
                
                while self.running:
                    try:
                        # Read audio frame
                        audio_bytes = self._stream.read(
                            self.chunk_size,
                            exception_on_overflow=False
                        )
                        
                        # Convert bytes to numpy array (int16)
                        audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                        
                        # Get predictions for all models
                        prediction = self.model.predict(audio_data)
                        
                        # Check each model's prediction
                        for model_name, score in prediction.items():
                            if score > self.detection_threshold:
                                # Internal debouncing to prevent rapid multiple triggers
                                current_time = time.time()
                                if current_time - self._last_detection_time < self._detection_debounce_seconds:
                                    continue  # Skip this detection, too soon after last one
                                
                                self._last_detection_time = current_time
                                logger.info(f"Wake word detected: '{model_name}' (score: {score:.3f})")
                                try:
                                    on_detected()
                                    # Break after first detection to avoid multiple triggers
                                    break
                                except Exception as e:
                                    logger.error(f"Exception in wake word callback: {e}")
                                
                    except Exception as e:
                        if self.running:  # Only log if we're still supposed to be running
                            logger.error(f"Error in OpenWakeWord detection loop: {e}")
                            
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
                # Ensure UI mic status reset
                try:
                    if self.ui_interface:
                        self.ui_interface.update_mic_status("idle")
                except Exception:
                    pass
                        
                logger.info("OpenWakeWord detection loop ended")
        
        # Start background thread
        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
    
    def stop(self):
        """Stop the continuous wake word detection."""
        if not self.running:
            logger.warning("OpenWakeWord detector is not running")
            return
            
        logger.info("Stopping OpenWakeWord detection...")
        self.running = False
        
        # If in subscription mode, generator will end naturally
        # If in direct mode, stop audio stream
        if not self._subscription_mode and self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
        
        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        
        # Clear subscription state
        self._subscription_mode = False
        self._audio_generator = None
            
        logger.info("OpenWakeWord detection stopped")
    
    def get_frame_length(self) -> Optional[int]:
        """Get the required frame length for audio processing."""
        return self.chunk_size
    
    def get_sample_rate(self) -> Optional[int]:
        """Get the required sample rate for audio processing."""
        return self.sample_rate
    
    def process_audio_chunk(self, audio_chunk: bytes) -> bool:
        """
        Process audio chunk for wake word detection.
        
        Args:
            audio_chunk: Audio chunk bytes (16-bit PCM)
        
        Returns:
            True if wake word detected, False otherwise
        """
        if not self.is_initialized or not self.model:
            logger.error("OpenWakeWord detector not initialized")
            return False
        
        try:
            # Convert bytes to numpy array (int16)
            audio_data = np.frombuffer(audio_chunk, dtype=np.int16)
            
            # Get predictions for all models
            prediction = self.model.predict(audio_data)
            
            # Check each model's prediction
            for model_name, score in prediction.items():
                if score > self.detection_threshold:
                    # Internal debouncing
                    current_time = time.time()
                    if current_time - self._last_detection_time < self._detection_debounce_seconds:
                        continue  # Skip, too soon after last detection
                    
                    self._last_detection_time = current_time
                    logger.info(f"Wake word detected: '{model_name}' (score: {score:.3f})")
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error processing audio chunk: {e}")
            return False
    
    def start_with_subscription(self, audio_generator: Generator[bytes, None, None], on_detected: Callable[[], None]):
        """
        Start wake word detection using audio from SharedAudioManager.
        
        Args:
            audio_generator: Generator yielding audio chunks from SharedAudioManager
            on_detected: Callback function to call when wake word is detected
        """
        if not self.is_initialized:
            logger.error("OpenWakeWord detector not initialized. Call initialize() first.")
            return
        
        if self.running:
            logger.warning("OpenWakeWord detector is already running")
            return
        
        self.running = True
        self._subscription_mode = True
        self._audio_generator = audio_generator
        
        def _run_loop():
            """Background thread loop for subscription-based wake word detection."""
            logger.info("OpenWakeWord detection active (subscription mode)")
            # Notify UI that mic is active when subscription mode starts
            try:
                if self.ui_interface:
                    self.ui_interface.update_mic_status("listening")
            except Exception:
                pass
            
            try:
                for audio_chunk in audio_generator:
                    if not self.running:
                        break
                    
                    # Process chunk
                    if self.process_audio_chunk(audio_chunk):
                        logger.info("Wake word detected")
                        try:
                            on_detected()
                        except Exception as e:
                            logger.error(f"Exception in wake word callback: {e}")
                            
            except StopIteration:
                logger.info("Audio generator ended")
            except Exception as e:
                if self.running:
                    logger.error(f"Error in OpenWakeWord detection loop: {e}", exc_info=True)
            finally:
                logger.info("OpenWakeWord detection loop ended")
                self._subscription_mode = False
                self._audio_generator = None
                # Ensure UI mic status reset
                try:
                    if self.ui_interface:
                        self.ui_interface.update_mic_status("idle")
                except Exception:
                    pass
        
        # Start background thread
        self._thread = threading.Thread(target=_run_loop, daemon=True)
        self._thread.start()
    
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
        
        # Cleanup OpenWakeWord model
        if self.model:
            try:
                # OpenWakeWord Model doesn't have __del__, just set to None
                # The model will be garbage collected by Python
                self.model = None
                logger.info("OpenWakeWord detector cleaned up")
            except Exception as e:
                logger.warning(f"Error during OpenWakeWord cleanup: {e}")
            finally:
                self.model = None
                self.is_initialized = False


def create_wake_word_detector(access_key_file: str, custom_keyword_file: Optional[str] = None, backend_dir: Optional[Path] = None, ui_interface=None) -> Union[WakeWordDetector, 'OpenWakeWordDetector']:
    """
    Factory function to create a wake word detector.
    Tries Porcupine first, falls back to OpenWakeWord if Porcupine initialization fails.
    
    Args:
        access_key_file: Path to file containing Picovoice access key (deprecated, now uses env var)
        custom_keyword_file: Path to custom wake word model file
        backend_dir: Path to backend directory (for OpenWakeWord fallback)
        
    Returns:
        WakeWordDetector or OpenWakeWordDetector instance
    """
    # Try Porcupine first
    try:
        detector = WakeWordDetector(PORCUPINE_ACCESS_KEY, custom_keyword_file, ui_interface=ui_interface)
        
        # Try to initialize Porcupine
        if detector.initialize():
            logger.info("✓ Using Porcupine for wake word detection")
            return detector
        else:
            logger.warning("Porcupine initialization failed, falling back to OpenWakeWord")
            # Cleanup failed Porcupine detector
            try:
                detector.cleanup()
            except:
                pass
    
    except Exception as e:
        logger.warning(f"Porcupine initialization failed: {e}")
        logger.info("Falling back to OpenWakeWord")
    
    # Fallback to OpenWakeWord
    if not OPENWAKEWORD_AVAILABLE:
        logger.error("OpenWakeWord not available - cannot create fallback detector")
        raise RuntimeError("Both Porcupine and OpenWakeWord are unavailable")
    
    # Determine backend_dir if not provided
    if backend_dir is None:
        # Try to infer from custom_keyword_file path
        if custom_keyword_file:
            backend_dir = Path(custom_keyword_file).parent.parent.parent
        else:
            # Fallback: use current file location
            current_file = Path(__file__)
            backend_dir = current_file.parent.parent.parent
    
    logger.info("Initializing OpenWakeWord as fallback detector...")
    detector = OpenWakeWordDetector(backend_dir=backend_dir, ui_interface=ui_interface)
    
    if detector.initialize():
        logger.info("✓ Using OpenWakeWord for wake word detection (fallback mode)")
        return detector
    else:
        logger.error("OpenWakeWord initialization also failed")
        raise RuntimeError("Both Porcupine and OpenWakeWord failed to initialize")


# Example usage and testing
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    # Paths relative to this file
    current_dir = os.path.dirname(__file__)
    access_key_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'PorcupineAccessKey.txt')
    custom_keyword_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'WellBot_WakeWordModel_ARM.ppn')
    
    def on_wake_word_detected():
        """Callback function called when wake word is detected."""
        print("Wake word detected! Starting STT pipeline...")
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
