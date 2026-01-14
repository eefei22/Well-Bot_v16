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

# Try to import Picamera2 (Hardware specific)
try:
    from picamera2 import Picamera2
    PICAMERA_AVAILABLE = True
except ImportError:
    PICAMERA_AVAILABLE = False

# Try to import OpenCV (needed for saving the array to image)
try:
    import cv2
except ImportError:
    cv2 = None

# Add backend directory to path for imports
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

from src.components.shared_audio_manager import SharedAudioManager
from src.utils.emotion_service_clients import SERServiceClient, FERServiceClient
from src.supabase.auth import get_current_user_id
from src.supabase.database import get_current_time_utc8_naive

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
        
        # SharedAudioManager subscription
        self._audio_generator = None

        # Camera Object (Picamera2)
        self.picam2 = None
        self._camera_available = False
        
        # Activity state
        self._active = False
        self._initialized = False
        self._running = False
        self._lock = threading.Lock()
        
        # Track active HTTP request threads for cancellation
        self._active_request_threads = set()
        self._request_threads_lock = threading.Lock()
        
        # Camera availability (will be checked on first use)
        self._camera_available: Optional[bool] = None
        
        logger.info(f"EmotionMonitoringActivity initialized for user {self.user_id}")
        logger.info(f"Audio chunk duration: {self.audio_chunk_duration_seconds}s")

    def _ensure_audio_subscription(self) -> bool:
        """Ensure we have an active SharedAudioManager subscription."""
        if self._audio_generator is not None:
            return True

        try:
            audio_manager = SharedAudioManager.get_instance()
            self._audio_generator = audio_manager.subscribe(
                subscriber_id="emotion_monitoring",
                sample_rate=16000,
                chunk_size=1600,
            )
            logger.info("event=emotion.audio.subscribe user_id=%s", self.user_id)
            return True
        except Exception as e:
            logger.warning("event=emotion.audio.subscribe_failed user_id=%s error=%s", self.user_id, e)
            self._audio_generator = None
            return False
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            logger.info("Initializing Emotion Monitoring activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            
            # Initialize service clients
            self.ser_client = SERServiceClient(service_url=os.getenv("SER_SERVICE_URL"))
            self.fer_client = FERServiceClient(service_url=os.getenv("FER_SERVICE_URL"))
            
            logger.info("Service clients initialized")
            
            # Subscribe to SharedAudioManager
            audio_manager = SharedAudioManager.get_instance()
            self._audio_generator = audio_manager.subscribe(
                subscriber_id="emotion_monitoring",
                sample_rate=16000,
                chunk_size=1600
            )
            
            logger.info("✓ Subscribed to SharedAudioManager")

            # Initialize & Start Camera (Picamera2)
            if PICAMERA_AVAILABLE and cv2 is not None:
                try:
                    logger.info("Starting Picamera2...")
                    self.picam2 = Picamera2()
                    # Configure for 640x480 still capture (matches send_image.py)
                    config = self.picam2.create_still_configuration(main={"size": (640, 480)})
                    self.picam2.configure(config)
                    self.picam2.start()
                    
                    self._camera_available = True
                    logger.info("✓ Picamera2 started successfully")
                except Exception as e:
                    logger.error(f"Failed to start Picamera2: {e}")
                    self._camera_available = False
            else:
                logger.warning("Picamera2 or OpenCV not installed. Image capture disabled.")
                self._camera_available = False
            
            self._initialized = True
            logger.info("Emotion Monitoring activity initialized successfully")
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
                logger.debug(
                    "event=emotion.start.noop user_id=%s reason=already_active",
                    self.user_id,
                )
                return True
            
            self._active = True
            self._running = True
            # Re-subscribe if we were previously stopped (stop() unsubscribes and clears generator).
            self._ensure_audio_subscription()
            logger.info(
                "event=emotion.start user_id=%s audio_chunk_seconds=%s",
                self.user_id,
                self.audio_chunk_duration_seconds,
            )
            return True
    
    def stop(self):
        """Stop the emotion monitoring activity immediately (non-blocking)"""
        with self._lock:
            if not self._active:
                logger.debug(
                    "event=emotion.stop.noop user_id=%s reason=not_active",
                    self.user_id,
                )
                return
            
            logger.info(
                "event=emotion.stop.begin user_id=%s",
                self.user_id,
            )
            # Set flags immediately to interrupt ongoing operations
            self._running = False
            self._active = False
            
            # Cancel any active HTTP request threads
            with self._request_threads_lock:
                active_threads = list(self._active_request_threads)
                self._active_request_threads.clear()
            
            if active_threads:
                logger.info(f"Cancelling {len(active_threads)} active HTTP request thread(s)")
                # Note: We can't actually cancel HTTP requests, but we've set _running=False
                # so they'll know to abort. The threads will finish but won't process results.
            
            # Unsubscribe from SharedAudioManager (non-blocking)
            if self._audio_generator:
                try:
                    audio_manager = SharedAudioManager.get_instance()
                    audio_manager.unsubscribe("emotion_monitoring")
                    self._audio_generator = None
                except Exception as e:
                    logger.warning(f"Error unsubscribing from SharedAudioManager: {e}")
            
            logger.info(
                "event=emotion.stop.end user_id=%s",
                self.user_id,
            )
    
    def run(self) -> bool:
        """
        Run the emotion monitoring activity in continuous loop
        
        Returns:
            True if activity completed normally, False if stopped or error
        """
        logger.info(
            "event=emotion.run.begin user_id=%s",
            self.user_id,
        )
        
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
                    # Check if we should abort before starting capture cycle
                    if not self._running:
                        break
                    
                    # Perform one capture cycle
                    self._capture_cycle()
                    
                    # Small delay before next cycle to avoid tight loop (check flag during sleep)
                    if self._running:
                        # Sleep in small chunks so we can respond quickly to stop signal
                        for _ in range(10):  # 10 * 0.01 = 0.1s total
                            if not self._running:
                                break
                            time.sleep(0.01)
                    
                except Exception as e:
                    if self._running:  # Only log if we're still supposed to be running
                        logger.error(f"Error in capture cycle: {e}", exc_info=True)
                    # Continue loop even on error (but check flag)
                    if self._running:
                        time.sleep(1.0)
            
            logger.info(
                "event=emotion.run.end user_id=%s",
                self.user_id,
            )
            return True
            
        except Exception as e:
            logger.error(f"Error running emotion monitoring: {e}", exc_info=True)
            return False
        finally:
            self.stop()
    
    def _capture_cycle(self):
        """Perform one capture cycle: 10s audio + 1 image, then send to services"""
        # Check if we should abort immediately
        if not self._running:
            logger.debug("Capture cycle aborted - emotion monitoring stopped")
            return
        
        logger.debug("Starting capture cycle...")

        # Generate timestamp for this cycle (Malaysia time UTC+8)
        timestamp = get_current_time_utc8_naive().isoformat()

        audio_sent = False
        image_sent = False
        
        # Capture and send audio (only if still running)
        if self._running:
            try:
                audio_file = self._capture_audio_chunk()
                if audio_file and self._running:  # Check again before HTTP request
                    logger.debug(f"Sending audio to SER service (timestamp: {timestamp})")
                    # Run HTTP request in thread so it can be interrupted
                    result = self._send_audio_interruptible(audio_file, self.user_id)
                    audio_sent = result is not None
                    
                    if audio_sent:
                        logger.info(f"Audio sent to SER service successfully")
                        # Only delete file if send was successful and completed
                        try:
                            audio_file.unlink()
                            logger.debug(f"Cleaned up audio file: {audio_file}")
                        except Exception as e:
                            logger.debug(f"Failed to delete temp audio file: {e}")
                    else:
                        # If send failed or was interrupted, file cleanup is handled by _send_audio_interruptible
                        logger.warning("Failed to send audio to SER service (file cleanup handled separately)")
            except Exception as e:
                logger.error(f"Error capturing/sending audio: {e}", exc_info=True)
        
        # Capture and send image (if camera available and still running)
        if self._running and self._check_camera_available():
            try:
                # Refresh user_id before sending image (in case pairing changed)
                try:
                    from src.supabase.auth import get_current_user_id
                    current_user_id = get_current_user_id()
                    if current_user_id:
                        self.user_id = current_user_id
                except Exception:
                    pass

                image_file = self._capture_image()
                if image_file and self._running:  # Check again before HTTP request
                    logger.debug(f"Sending image to FER service (timestamp: {timestamp})")
                    try:
                        send_user_id = self.user_id or ""
                        success = False
                        if self.fer_client:
                            success = self.fer_client.send_image(image_file, send_user_id)
                        image_sent = bool(success)

                        if image_sent:
                            logger.info("Image sent to FER service successfully")
                        else:
                            logger.warning("Failed to send image to FER service")
                    except Exception as e:
                        logger.error(f"Error sending image to FER service: {e}", exc_info=True)

                    # Clean up temp file
                    try:
                        image_file.unlink()
                    except Exception as e:
                        logger.debug(f"Failed to delete temp image file: {e}")
            except Exception as e:
                logger.error(f"Error capturing/sending image: {e}", exc_info=True)
        elif not self._running:
            logger.debug("Skipping image capture - emotion monitoring stopped")
        else:
            # Camera not available, but FER client handles placeholder mode
            logger.debug("Camera not available, skipping image capture")
            image_sent = True  # Consider it "sent" for placeholder mode
        
        logger.debug(f"Capture cycle completed - Audio: {audio_sent}, Image: {image_sent}")
    
    def _send_audio_interruptible(self, audio_file: Path, user_id: str):
        """
        Send audio in a way that can be interrupted when stopped.
        
        Uses ser_client.send_audio (which matches test script approach) but allows
        early return if stopped. Returns the result if completed, None if interrupted.
        """
        result_container = {'result': None, 'done': False, 'error': None}
        
        def send_request():
            """Send request using ser_client (matches test script approach)"""
            try:
                if not self._running:  # Check before starting request
                    logger.debug("Skipping HTTP request - emotion monitoring stopped")
                    return
                # Use ser_client which has the same implementation as test script
                result_container['result'] = self.ser_client.send_audio(audio_file, user_id)
                # Check again after request completes
                if not self._running:
                    logger.debug("HTTP request completed but emotion monitoring stopped - discarding result")
                    result_container['result'] = None
            except Exception as e:
                if self._running:  # Only log if we're still supposed to be running
                    result_container['error'] = str(e)
                    logger.error(f"Error in send_request thread: {e}", exc_info=True)
            finally:
                result_container['done'] = True
                # Remove from active threads
                with self._request_threads_lock:
                    self._active_request_threads.discard(threading.current_thread())
        
        # Start request in thread
        request_thread = threading.Thread(target=send_request, daemon=True)
        with self._request_threads_lock:
            self._active_request_threads.add(request_thread)
        request_thread.start()
        
        # Wait for completion or stop signal
        # SER requests tyddlly take 5-15 seconds, so we wait up to 15 seconds
        # But we check frequently (every 100ms) to respond quickly to stop signals
        timeout = 15.0  # Allow enough time for SER requests to complete
        check_interval = 0.1  # Check every 100ms
        elapsed = 0.0
        
        while not result_container['done'] and self._running and elapsed < timeout:
            time.sleep(check_interval)
            elapsed += check_interval
        
        # If stopped, return immediately (request continues in background but we don't wait)
        if not self._running:
            logger.debug("Audio send interrupted - emotion monitoring stopped, continuing immediately")
            # Schedule file cleanup after request completes (don't delete while request is active)
            def cleanup_file_after_request():
                request_thread.join(timeout=30.0)  # Wait up to 30s for request to finish
                try:
                    if audio_file.exists():
                        audio_file.unlink()
                        logger.debug(f"Cleaned up audio file after interrupt: {audio_file}")
                except Exception as e:
                    logger.debug(f"Error cleaning up audio file: {e}")
            threading.Thread(target=cleanup_file_after_request, daemon=True).start()
            return None
        
        # If timeout and still running, wait a bit more (SER might be slow)
        if not result_container['done']:
            logger.debug(f"Audio send not completed after {timeout}s, waiting a bit more...")
            # Give it a bit more time
            request_thread.join(timeout=5.0)
            if not result_container['done']:
                logger.warning("Audio send still not completed - continuing without result")
                # Schedule cleanup
                def cleanup_file_after_timeout():
                    request_thread.join(timeout=30.0)
                    try:
                        if audio_file.exists():
                            audio_file.unlink()
                    except Exception as e:
                        logger.debug(f"Error cleaning up audio file: {e}")
                threading.Thread(target=cleanup_file_after_timeout, daemon=True).start()
                return None
        
        # Request completed - check for errors
        if result_container['error']:
            logger.error(f"Error sending audio: {result_container['error']}")
            return None
        
        return result_container['result']
    
    def _capture_audio_chunk(self) -> Optional[Path]:
        """
        Capture audio chunk from microphone (exactly 10 seconds).
        
        Uses SharedAudioManager generator to collect chunks.
        
        Returns:
            Path to temporary WAV file if successful, None if failed
        """
        try:
            if not self._audio_generator:
                if not self._running:
                    logger.debug("Audio generator not available (stopped)")
                    return None

                # Recover if possible (e.g., idle-mode restart without reinitialize()).
                if not self._ensure_audio_subscription():
                    logger.warning("Audio generator not available")
                    return None
            
            logger.debug(f"Capturing audio for {self.audio_chunk_duration_seconds}s...")
            
            sample_rate = 16000
            chunk_size = 1600  # 100ms chunks
            
            # Calculate number of chunks needed
            chunks_per_second = sample_rate // chunk_size
            total_chunks = int(self.audio_chunk_duration_seconds * chunks_per_second)
            
            # Collect audio chunks from SharedAudioManager generator
            audio_chunks = []
            for i in range(total_chunks):
                if not self._running:
                    break
                try:
                    chunk = next(self._audio_generator)
                    audio_chunks.append(chunk)
                except StopIteration:
                    if not self._running:
                        logger.debug("Audio generator ended during shutdown")
                    else:
                        logger.warning("Audio generator ended unexpectedly")
                    break
                except Exception as e:
                    logger.warning(f"Error capturing audio chunk: {e}")
                    break
            
            if not audio_chunks:
                if not self._running:
                    logger.debug("No audio chunks captured (stopped during capture)")
                else:
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
    
    def _capture_image(self) -> Optional[Path]:
        """
        Capture image using Picamera2.
        Matches logic from send_image.py: capture_array -> imwrite
        """
        try:
            if not self.picam2 or not self._camera_available:
                return None

            logger.debug("Capturing image with Picamera2...")

            # 1. Capture Raw Array (like send_image.py)
            frame = self.picam2.capture_array()
            
            # 2. Save to Temp File
            # We use tempfile instead of /tmp/frame.jpg to avoid thread conflicts
            temp_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix='.jpg',
                prefix='emotion_monitoring_image_'
            )
            temp_path = Path(temp_file.name)
            temp_file.close()

            # 3. Write using OpenCV
            success = cv2.imwrite(str(temp_path), frame)
            
            if not success:
                logger.warning("cv2.imwrite failed to save image")
                return None

            logger.debug(f"Image saved to {temp_path}")
            return temp_path

        except Exception as e:
            logger.error(f"Error capturing image with Picamera2: {e}")
            return None
    
    def _check_camera_available(self) -> bool:
        """
        Check if camera is available.
        
        Returns:
            True if camera is available, False otherwise
        """
        return self._camera_available and self.picam2 is not None
    
    def is_active(self) -> bool:
        """Check if emotion monitoring is currently active"""
        with self._lock:
            return self._active
    
    def cleanup(self):
        """Cleanup resources"""
        self.stop()

        # Stop the camera explicitly
        if self.picam2:
            try:
                logger.info("Stopping Picamera2...")
                self.picam2.stop()
                # self.picam2.close() # Note: Picamera2 usually just needs stop(), close() depends on version
                self.picam2 = None
                logger.info("Picamera2 stopped.")
            except Exception as e:
                logger.warning(f"Error cleaning up camera: {e}")

        # Ensure unsubscribe (in case stop() didn't handle it)
        if self._audio_generator:
            try:
                audio_manager = SharedAudioManager.get_instance()
                audio_manager.unsubscribe("emotion_monitoring")
                self._audio_generator = None
            except Exception as e:
                logger.warning(f"Error unsubscribing during cleanup: {e}")
        
        logger.info("Emotion monitoring cleanup completed")
