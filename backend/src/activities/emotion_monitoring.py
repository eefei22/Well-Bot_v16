"""
Emotion Monitoring Activity

This activity continuously captures audio and images, sending them to SER/FER services
for emotion recognition. Runs in parallel with idle_mode activity.
"""

import os
import sys
import threading
import time
import logging
import tempfile
import wave
from pathlib import Path
from typing import Optional
from datetime import datetime

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

from src.components.mic_stream import MicStream
from src.utils.emotion_service_clients import SERServiceClient, FERServiceClient
from src.supabase.auth import get_current_user_id

logger = logging.getLogger(__name__)


class EmotionMonitoringActivity:
    """
    Emotion Monitoring Activity
    
    Continuously captures 10-second audio chunks and images, sending them to
    SER and FER services for emotion recognition.
    """
    
    def __init__(
        self,
        backend_dir: Path,
        user_id: Optional[str] = None,
        ser_service_url: Optional[str] = None,
        fer_service_url: Optional[str] = None,
        audio_chunk_duration_seconds: float = 10.0
    ):
        """
        Initialize the Emotion Monitoring Activity
        
        Args:
            backend_dir: Path to the backend directory
            user_id: User ID (optional, will be resolved if not provided)
            ser_service_url: Optional SER service URL override
            fer_service_url: Optional FER service URL override
            audio_chunk_duration_seconds: Duration of each audio chunk (default: 10.0)
        """
        self.backend_dir = backend_dir
        self.user_id = user_id if user_id is not None else get_current_user_id()
        self.audio_chunk_duration_seconds = audio_chunk_duration_seconds
        
        # Service clients (initialized in initialize())
        self.ser_client: Optional[SERServiceClient] = None
        self.fer_client: Optional[FERServiceClient] = None
        
        # Activity state
        self._active = False
        self._initialized = False
        self._running = False
        self._lock = threading.Lock()
        
        # Camera availability (will be checked on first use)
        self._camera_available: Optional[bool] = None
        
        logger.info(f"EmotionMonitoringActivity initialized for user {self.user_id}")
        logger.info(f"Audio chunk duration: {self.audio_chunk_duration_seconds}s")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            logger.info("Initializing Emotion Monitoring activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            
            # Initialize service clients
            self.ser_client = SERServiceClient(service_url=os.getenv("SER_SERVICE_URL"))
            self.fer_client = FERServiceClient(service_url=os.getenv("FER_SERVICE_URL"))
            
            logger.info("✓ Service clients initialized")
            
            self._initialized = True
            logger.info("✅ Emotion Monitoring activity initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Emotion Monitoring activity: {e}", exc_info=True)
            return False
    
    def start(self) -> bool:
        """Start the emotion monitoring activity"""
        if not self._initialized:
            logger.error("Cannot start: activity not initialized")
            return False
        
        with self._lock:
            if self._active:
                logger.warning("Emotion monitoring already active")
                return True
            
            self._active = True
            self._running = True
            logger.info("✅ Emotion monitoring active")
            return True
    
    def stop(self):
        """Stop the emotion monitoring activity"""
        with self._lock:
            if not self._active:
                logger.warning("Emotion monitoring not active, cannot stop")
                return
            
            logger.info("Stopping emotion monitoring activity...")
            self._running = False
            self._active = False
            logger.info("✅ Emotion monitoring stopped")
    
    def run(self) -> bool:
        """
        Run the emotion monitoring activity in continuous loop
        
        Returns:
            True if activity completed normally, False if stopped or error
        """
        logger.info("🎬 EmotionMonitoringActivity.run() - Starting emotion monitoring execution")
        
        if not self._initialized:
            logger.error("Cannot run: activity not initialized")
            return False
        
        if not self.start():
            logger.error("Failed to start emotion monitoring")
            return False
        
        try:
            # Continuous capture loop
            while self._running:
                try:
                    # Perform one capture cycle
                    self._capture_cycle()
                    
                    # Small delay before next cycle to avoid tight loop
                    time.sleep(0.1)
                    
                except Exception as e:
                    logger.error(f"Error in capture cycle: {e}", exc_info=True)
                    # Continue loop even on error
                    time.sleep(1.0)
            
            logger.info("Emotion monitoring loop ended")
            return True
            
        except Exception as e:
            logger.error(f"Error running emotion monitoring: {e}", exc_info=True)
            return False
        finally:
            self.stop()
    
    def _capture_cycle(self):
        """Perform one capture cycle: 10s audio + 1 image, then send to services"""
        logger.debug("Starting capture cycle...")
        
        # Generate timestamp for this cycle
        timestamp = datetime.now().isoformat()
        
        audio_sent = False
        image_sent = False
        
        # Capture and send audio
        try:
            audio_file = self._capture_audio_chunk()
            if audio_file:
                logger.debug(f"Sending audio to SER service (timestamp: {timestamp})")
                result = self.ser_client.send_audio(audio_file, self.user_id)
                audio_sent = result is not None
                
                if audio_sent:
                    logger.info(f"✅ Audio sent to SER service successfully")
                else:
                    logger.warning("Failed to send audio to SER service")
                
                # Clean up temp file
                try:
                    audio_file.unlink()
                except Exception as e:
                    logger.debug(f"Failed to delete temp audio file: {e}")
        except Exception as e:
            logger.error(f"Error capturing/sending audio: {e}", exc_info=True)
        
        # Capture and send image (if camera available)
        if self._check_camera_available():
            try:
                image_file = self._capture_image()
                if image_file:
                    logger.debug(f"Sending image to FER service (timestamp: {timestamp})")
                    success = self.fer_client.send_image(image_file, self.user_id)
                    image_sent = success
                    
                    if image_sent:
                        logger.info(f"✅ Image sent to FER service successfully")
                    else:
                        logger.warning("Failed to send image to FER service")
                    
                    # Clean up temp file
                    try:
                        image_file.unlink()
                    except Exception as e:
                        logger.debug(f"Failed to delete temp image file: {e}")
            except Exception as e:
                logger.error(f"Error capturing/sending image: {e}", exc_info=True)
        else:
            # Camera not available, but FER client handles placeholder mode
            logger.debug("Camera not available, skipping image capture")
            image_sent = True  # Consider it "sent" for placeholder mode
        
        logger.debug(f"Capture cycle completed - Audio: {audio_sent}, Image: {image_sent}")
    
    def _capture_audio_chunk(self) -> Optional[Path]:
        """
        Capture audio chunk from microphone (exactly 10 seconds).
        
        Returns:
            Path to temporary WAV file if successful, None if failed
        """
        mic = None
        try:
            logger.debug(f"Capturing audio for {self.audio_chunk_duration_seconds}s...")
            
            # Create separate MicStream instance (doesn't interfere with idle_mode's mic)
            sample_rate = 16000
            chunk_size = 1600  # 100ms chunks
            mic = MicStream(rate=sample_rate, chunk_size=chunk_size)
            mic.start()
            
            # Calculate number of chunks needed
            chunks_per_second = sample_rate // chunk_size
            total_chunks = int(self.audio_chunk_duration_seconds * chunks_per_second)
            
            # Collect audio chunks
            audio_chunks = []
            for i in range(total_chunks):
                if not self._running:
                    break
                try:
                    chunk = next(mic.generator())
                    audio_chunks.append(chunk)
                except StopIteration:
                    break
                except Exception as e:
                    logger.warning(f"Error capturing audio chunk: {e}")
                    break
            
            if not audio_chunks:
                logger.warning("No audio chunks captured")
                return None
            
            # Save to temporary WAV file
            temp_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix='.wav',
                prefix='emotion_monitoring_audio_'
            )
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Write WAV file
            with wave.open(str(temp_path), 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                
                # Convert chunks to bytes and write
                for chunk in audio_chunks:
                    wav_file.writeframes(chunk)
            
            logger.debug(f"Audio captured and saved to {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.error(f"Error capturing audio: {e}", exc_info=True)
            return None
        finally:
            if mic:
                try:
                    mic.stop()
                except Exception as e:
                    logger.debug(f"Error stopping mic: {e}")
    
    def _capture_image(self) -> Optional[Path]:
        """
        Capture image from camera.
        
        Returns:
            Path to temporary image file if successful, None if failed
        """
        try:
            # Try to import cv2 (OpenCV)
            try:
                import cv2
            except ImportError:
                logger.debug("OpenCV not available, cannot capture images")
                return None
            
            logger.debug("Capturing image from camera...")
            
            # Open camera
            camera = cv2.VideoCapture(0)
            if not camera.isOpened():
                logger.debug("Camera not available")
                camera.release()
                return None
            
            # Capture frame
            ret, frame = camera.read()
            camera.release()
            
            if not ret or frame is None:
                logger.debug("Failed to capture frame from camera")
                return None
            
            # Save to temporary JPEG file
            temp_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix='.jpg',
                prefix='emotion_monitoring_image_'
            )
            temp_path = Path(temp_file.name)
            temp_file.close()
            
            # Write image file
            cv2.imwrite(str(temp_path), frame)
            
            logger.debug(f"Image captured and saved to {temp_path}")
            return temp_path
            
        except Exception as e:
            logger.debug(f"Error capturing image: {e}")
            return None
    
    def _check_camera_available(self) -> bool:
        """
        Check if camera is available.
        
        Returns:
            True if camera is available, False otherwise
        """
        if self._camera_available is not None:
            return self._camera_available
        
        try:
            import cv2
            camera = cv2.VideoCapture(0)
            if camera.isOpened():
                camera.release()
                self._camera_available = True
                logger.info("Camera is available")
            else:
                self._camera_available = False
                logger.info("Camera is not available")
        except ImportError:
            self._camera_available = False
            logger.info("OpenCV not installed, camera not available")
        except Exception as e:
            self._camera_available = False
            logger.debug(f"Error checking camera: {e}")
        
        return self._camera_available
    
    def is_active(self) -> bool:
        """Check if emotion monitoring is currently active"""
        with self._lock:
            return self._active
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop()
        logger.info("Emotion monitoring cleanup completed")
