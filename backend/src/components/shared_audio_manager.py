"""
Shared Audio Manager

Centralized audio management system that allows multiple activities to access
microphone audio concurrently through a single hardware stream.

Uses a multi-buffer approach where each subscriber gets its own buffer queue,
enabling independent consumption rates and preventing blocking between subscribers.
"""

import threading
import logging
from typing import Dict, Optional, Generator
from queue import Queue, Empty
from collections import defaultdict

from src.components.mic_stream import MicStream

logger = logging.getLogger(__name__)


class SharedAudioManager:
    """
    Singleton manager that distributes audio chunks from a single MicStream
    to multiple subscribers via per-subscriber buffers.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        """Initialize the SharedAudioManager (private, use get_instance())."""
        # MicStream configuration (fixed for all subscribers)
        self.sample_rate = 16000
        self.chunk_size = 1600  # 100ms chunks at 16kHz
        
        # Single MicStream instance
        self.mic_stream: Optional[MicStream] = None
        
        # Subscriber management
        self.subscriber_buffers: Dict[str, Queue] = {}
        self.subscriber_configs: Dict[str, dict] = {}
        self._subscriber_lock = threading.Lock()
        
        # Distribution thread
        self.distribution_thread: Optional[threading.Thread] = None
        self.running = False
        self._running_lock = threading.Lock()
        
        logger.info("SharedAudioManager initialized")
    
    @classmethod
    def get_instance(cls):
        """
        Get the singleton instance of SharedAudioManager.
        
        Returns:
            SharedAudioManager instance
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    def subscribe(
        self,
        subscriber_id: str,
        sample_rate: int = 16000,
        chunk_size: int = 1600,
        buffer_size: int = 100
    ) -> Generator[bytes, None, None]:
        """
        Subscribe to receive audio chunks.
        
        Args:
            subscriber_id: Unique identifier for subscriber
            sample_rate: Required sample rate (must match MicStream, default: 16000)
            chunk_size: Required chunk size (must match MicStream, default: 1600)
            buffer_size: Maximum buffer size for this subscriber (default: 100)
        
        Returns:
            Generator that yields audio chunks from subscriber's buffer
        
        Raises:
            ValueError: If sample_rate or chunk_size don't match MicStream configuration
        """
        with self._subscriber_lock:
            # Validate sample rate and chunk size
            if sample_rate != self.sample_rate:
                raise ValueError(
                    f"Sample rate mismatch: requested {sample_rate}Hz, "
                    f"but MicStream uses {self.sample_rate}Hz"
                )
            if chunk_size != self.chunk_size:
                raise ValueError(
                    f"Chunk size mismatch: requested {chunk_size}, "
                    f"but MicStream uses {self.chunk_size}"
                )
            
            # Check if already subscribed
            if subscriber_id in self.subscriber_buffers:
                logger.warning(f"Subscriber '{subscriber_id}' is already subscribed")
                # Return existing generator
                return self._subscriber_generator(subscriber_id)
            
            # Create buffer for this subscriber
            subscriber_buffer = Queue(maxsize=buffer_size)
            self.subscriber_buffers[subscriber_id] = subscriber_buffer
            self.subscriber_configs[subscriber_id] = {
                'sample_rate': sample_rate,
                'chunk_size': chunk_size,
                'buffer_size': buffer_size
            }
            
            logger.info(f"Subscriber '{subscriber_id}' registered (buffer_size: {buffer_size})")
            
            # Start MicStream if this is the first subscriber
            if len(self.subscriber_buffers) == 1:
                self._start_mic_stream()
            
            # Start distribution thread if not running
            if not self.running:
                self._start_distribution()
        
        # Return generator for this subscriber
        return self._subscriber_generator(subscriber_id)
    
    def unsubscribe(self, subscriber_id: str):
        """
        Unsubscribe from audio stream.
        
        Args:
            subscriber_id: Subscriber identifier
        """
        with self._subscriber_lock:
            if subscriber_id not in self.subscriber_buffers:
                logger.warning(f"Subscriber '{subscriber_id}' is not subscribed")
                return
            
            # Remove subscriber
            buffer = self.subscriber_buffers.pop(subscriber_id)
            self.subscriber_configs.pop(subscriber_id)
            
            # Signal termination to buffer (for generator)
            try:
                buffer.put(None)  # None signals end of stream
            except Exception as e:
                logger.debug(f"Error signaling termination to subscriber '{subscriber_id}': {e}")
            
            logger.info(f"Subscriber '{subscriber_id}' unsubscribed")
            
            # Stop MicStream if this was the last subscriber
            if len(self.subscriber_buffers) == 0:
                self._stop_mic_stream()
                self._stop_distribution()
    
    def _subscriber_generator(self, subscriber_id: str) -> Generator[bytes, None, None]:
        """
        Generator that yields audio chunks for a specific subscriber.
        
        Args:
            subscriber_id: Subscriber identifier
        
        Yields:
            Audio chunk bytes
        """
        buffer = self.subscriber_buffers.get(subscriber_id)
        if buffer is None:
            logger.error(f"Subscriber '{subscriber_id}' buffer not found")
            return
        
        logger.debug(f"Generator started for subscriber '{subscriber_id}'")
        
        while True:
            try:
                chunk = buffer.get(timeout=0.5)
                
                # None signals end of stream
                if chunk is None:
                    logger.debug(f"Generator terminated for subscriber '{subscriber_id}'")
                    break
                
                yield chunk
                
            except Empty:
                # Timeout - check if subscriber still exists
                with self._subscriber_lock:
                    if subscriber_id not in self.subscriber_buffers:
                        logger.debug(f"Subscriber '{subscriber_id}' unsubscribed, generator ending")
                        break
                continue
            except Exception as e:
                logger.error(f"Error in generator for subscriber '{subscriber_id}': {e}")
                break
        
        logger.debug(f"Generator ended for subscriber '{subscriber_id}'")
    
    def _start_mic_stream(self):
        """Start the MicStream instance."""
        if self.mic_stream is not None:
            logger.warning("MicStream already exists")
            return
        
        try:
            logger.info("Starting MicStream for SharedAudioManager...")
            self.mic_stream = MicStream(rate=self.sample_rate, chunk_size=self.chunk_size)
            self.mic_stream.start()
            logger.info("MicStream started successfully")
        except Exception as e:
            logger.error(f"Failed to start MicStream: {e}", exc_info=True)
            self.mic_stream = None
            raise
    
    def _stop_mic_stream(self):
        """Stop the MicStream instance."""
        if self.mic_stream is None:
            return
        
        try:
            logger.info("Stopping MicStream...")
            self.mic_stream.stop()
            self.mic_stream = None
            logger.info("MicStream stopped successfully")
        except Exception as e:
            logger.error(f"Error stopping MicStream: {e}", exc_info=True)
            self.mic_stream = None
    
    def _start_distribution(self):
        """Start the distribution thread."""
        with self._running_lock:
            if self.running:
                logger.warning("Distribution thread already running")
                return
            
            self.running = True
            self.distribution_thread = threading.Thread(
                target=self._distribution_loop,
                daemon=True,
                name="SharedAudioManager-Distribution"
            )
            self.distribution_thread.start()
            logger.info("Distribution thread started")
    
    def _stop_distribution(self):
        """Stop the distribution thread."""
        with self._running_lock:
            if not self.running:
                return
            
            self.running = False
        
        # Wait for thread to finish
        if self.distribution_thread and self.distribution_thread.is_alive():
            logger.info("Waiting for distribution thread to finish...")
            self.distribution_thread.join(timeout=2.0)
            if self.distribution_thread.is_alive():
                logger.warning("Distribution thread did not finish within timeout")
            else:
                logger.info("Distribution thread finished")
        
        self.distribution_thread = None
    
    def _distribution_loop(self):
        """
        Main loop that reads from MicStream and distributes to all subscribers.
        Runs in separate thread.
        """
        logger.info("Distribution loop started")
        
        if self.mic_stream is None:
            logger.error("MicStream is None, cannot start distribution")
            return
        
        try:
            # Read chunks from MicStream generator
            for chunk in self.mic_stream.generator():
                if not self.running:
                    break
                
                # Distribute chunk to all subscribers
                self._distribute_chunk(chunk)
                
        except StopIteration:
            logger.info("MicStream generator ended")
        except Exception as e:
            logger.error(f"Error in distribution loop: {e}", exc_info=True)
        finally:
            logger.info("Distribution loop ended")
            with self._running_lock:
                self.running = False
    
    def _distribute_chunk(self, chunk: bytes):
        """
        Distribute a single chunk to all subscriber buffers.
        
        Args:
            chunk: Audio chunk bytes to distribute
        """
        with self._subscriber_lock:
            # Get list of subscribers (snapshot to avoid lock during iteration)
            subscribers = list(self.subscriber_buffers.keys())
        
        # Distribute to each subscriber
        for subscriber_id in subscribers:
            buffer = self.subscriber_buffers.get(subscriber_id)
            if buffer is None:
                continue
            
            try:
                # Try to put chunk in buffer (non-blocking)
                buffer.put_nowait(chunk)
            except Exception as e:
                # Buffer is full or other error
                # Drop oldest chunk and add new one (prevents blocking)
                try:
                    buffer.get_nowait()  # Remove oldest
                    buffer.put_nowait(chunk)  # Add new
                    logger.debug(f"Buffer full for '{subscriber_id}', dropped oldest chunk")
                except Exception as e2:
                    logger.warning(f"Error distributing chunk to '{subscriber_id}': {e2}")
    
    def is_running(self) -> bool:
        """
        Check if the manager is currently running.
        
        Returns:
            True if distribution is active, False otherwise
        """
        with self._running_lock:
            return self.running
    
    def get_subscriber_count(self) -> int:
        """
        Get the number of active subscribers.
        
        Returns:
            Number of active subscribers
        """
        with self._subscriber_lock:
            return len(self.subscriber_buffers)
    
    def get_subscriber_ids(self) -> list:
        """
        Get list of active subscriber IDs.
        
        Returns:
            List of subscriber IDs
        """
        with self._subscriber_lock:
            return list(self.subscriber_buffers.keys())
    
    def mute(self):
        """Mute the microphone (discard incoming audio)."""
        if self.mic_stream:
            self.mic_stream.mute()
            logger.info("SharedAudioManager microphone muted")
    
    def unmute(self):
        """Unmute the microphone (resume capturing audio)."""
        if self.mic_stream:
            self.mic_stream.unmute()
            logger.info("SharedAudioManager microphone unmuted")
    
    def is_muted(self) -> bool:
        """Check if microphone is muted."""
        if self.mic_stream:
            return self.mic_stream.is_muted()
        return False
    
    def stop(self):
        """
        Stop the SharedAudioManager (stops MicStream and distribution).
        Use with caution - this will affect all subscribers.
        """
        logger.info("Stopping SharedAudioManager...")
        
        # Unsubscribe all subscribers
        with self._subscriber_lock:
            subscriber_ids = list(self.subscriber_buffers.keys())
        
        for subscriber_id in subscriber_ids:
            self.unsubscribe(subscriber_id)
        
        logger.info("SharedAudioManager stopped")




