"""
Microphone Audio Stream Service

This service provides a buffered stream of audio chunks from the microphone.
It handles low-level audio I/O, buffering, threading, and yields audio frames to consumers.
"""

import pyaudio
from queue import Queue, Empty
from typing import Generator, Optional
import logging
import threading

logger = logging.getLogger(__name__)


class MicStream:
    """
    A wrapper around microphone input that yields raw audio chunks.
    Handles buffering and threading for continuous audio capture.
    """
    
    def __init__(self, rate: int = 16000, chunk_size: int = 1600):
        """
        Initialize the microphone stream.
        
        Args:
            rate: Sample rate in Hz (default: 16000)
            chunk_size: Number of frames per chunk (default: 1600)
        """
        self.rate = rate
        self.chunk_size = chunk_size
        self._buff = Queue()
        self.closed = True
        self._pa = None
        self._stream = None
        self._lock = threading.Lock()
        
        logger.info(f"Microphone stream ready | Rate: {rate}Hz | Chunk: {chunk_size}")
    
    def start(self):
        """Open the mic and begin filling buffer."""
        with self._lock:
            if not self.closed:
                logger.warning("MicStream is already running")
                return
                
            try:
                self._pa = pyaudio.PyAudio()
                self._stream = self._pa.open(
                    format=pyaudio.paInt16,
                    channels=1,
                    rate=self.rate,
                    input=True,
                    frames_per_buffer=self.chunk_size,
                    stream_callback=self._fill_buffer
                )
                self.closed = False
                logger.info("Microphone active")
                
            except Exception as e:
                logger.error(f"Failed to start MicStream: {e}")
                self._cleanup()
                raise
    
    def _fill_buffer(self, in_data: bytes, frame_count: int, time_info, status):
        """
        Callback function for PyAudio stream to fill the buffer.
        
        Args:
            in_data: Raw audio data bytes
            frame_count: Number of frames in the data
            time_info: Timing information
            status: Stream status flags
            
        Returns:
            Tuple indicating no output data and continue status
        """
        try:
            if not self.closed:
                self._buff.put(in_data)
        except Exception as e:
            logger.error(f"Error in audio callback: {e}")
        
        return (None, pyaudio.paContinue)
    
    def generator(self) -> Generator[bytes, None, None]:
        """
        Generator that yields audio chunks. Ends when close is called.
        
        Yields:
            Raw audio data bytes
        """
        logger.info("Audio generator started")
        
        while not self.closed:
            try:
                chunk = self._buff.get(timeout=0.5)
                if chunk is None:
                    logger.info("Received termination signal in generator")
                    return
                yield chunk
                
            except Empty:
                # Timeout occurred, continue checking if we should still be running
                continue
            except Exception as e:
                logger.error(f"Error in audio generator: {e}")
                break
        
        logger.info("Audio generator ended")
    
    def stop(self):
        """Stop the stream and cleanup."""
        with self._lock:
            if self.closed:
                logger.warning("MicStream is already stopped")
                return
                
            logger.info("Stopping MicStream...")
            self.closed = True
            
            # Signal generator termination
            try:
                self._buff.put(None)
            except Exception as e:
                logger.error(f"Error signaling generator termination: {e}")
            
            self._cleanup()
            logger.info("Microphone stopped")
    
    def _cleanup(self):
        """Internal cleanup method."""
        # Stop and close audio stream
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
                self._stream = None
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
        
        # Terminate PyAudio
        if self._pa is not None:
            try:
                self._pa.terminate()
                self._pa = None
            except Exception as e:
                logger.error(f"Error terminating PyAudio: {e}")
    
    def is_running(self) -> bool:
        """Check if the microphone stream is currently running."""
        return not self.closed
    
    def get_sample_rate(self) -> int:
        """Get the sample rate."""
        return self.rate
    
    def get_chunk_size(self) -> int:
        """Get the chunk size."""
        return self.chunk_size
    
    def get_buffer_size(self) -> int:
        """Get the current buffer size."""
        return self._buff.qsize()


# Example usage and testing
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    def test_mic_stream():
        """Test the MicStream functionality."""
        mic = MicStream(rate=16000, chunk_size=1600)
        
        try:
            print("Starting microphone stream...")
            mic.start()
            
            print("Recording audio chunks (press Ctrl+C to stop)...")
            chunk_count = 0
            
            for audio_chunk in mic.generator():
                chunk_count += 1
                print(f"Received chunk {chunk_count}, size: {len(audio_chunk)} bytes")
                
                # Simulate processing time
                import time
                time.sleep(0.1)
                
                # Stop after 10 chunks for testing
                if chunk_count >= 10:
                    print("Test completed, stopping...")
                    break
                    
        except KeyboardInterrupt:
            print("\nInterrupted by user")
        except Exception as e:
            print(f"Error during test: {e}")
        finally:
            mic.stop()
            print("MicStream test finished")
    
    # Run the test
    test_mic_stream()
