#!/usr/bin/env python3
"""
Intent Recognition Component using Picovoice Rhino

Audio-based intent recognition that processes raw audio frames directly,
bypassing the need for speech-to-text transcription for intent detection.
"""

import logging
import struct
from pathlib import Path
from typing import Optional, Dict, Any, List
import pvrhino

logger = logging.getLogger(__name__)


class IntentRecognition:
    """
    Rhino-based intent recognition system.
    
    Processes audio frames directly and returns intent classifications
    without requiring text transcription.
    """
    
    def __init__(
        self,
        access_key: str,
        context_path: Path,
        sensitivity: float = 0.5,
        require_endpoint: bool = True
    ):
        """
        Initialize Rhino intent recognition engine.
        
        Args:
            access_key: Picovoice access key (from RHINO_ACCESS_KEY)
            context_path: Path to Rhino context file (.rhn)
            sensitivity: Detection sensitivity [0.0-1.0], default 0.5
            require_endpoint: Whether to require silence after command (default True)
        """
        self.access_key = access_key
        self.context_path = Path(context_path)
        self.sensitivity = sensitivity
        self.require_endpoint = require_endpoint
        self.rhino = None
        self.is_initialized = False
        
        # Audio format properties (set after initialization)
        self.sample_rate = None
        self.frame_length = None
        
        if not self.context_path.exists():
            raise FileNotFoundError(f"Rhino context file not found: {self.context_path}")
        
        self._initialize()
    
    def _initialize(self):
        """Initialize the Rhino engine."""
        try:
            logger.info(f"Initializing Rhino intent recognition with context: {self.context_path}")
            
            self.rhino = pvrhino.create(
                access_key=self.access_key,
                context_path=str(self.context_path),
                sensitivity=self.sensitivity,
                require_endpoint=self.require_endpoint
            )
            
            # Get audio format requirements
            self.sample_rate = self.rhino.sample_rate
            self.frame_length = self.rhino.frame_length
            self.is_initialized = True
            
            logger.info(
                f"Rhino initialized successfully | "
                f"Sample rate: {self.sample_rate}Hz | "
                f"Frame length: {self.frame_length} | "
                f"Sensitivity: {self.sensitivity}"
            )
            
        except Exception as e:
            logger.error(f"Failed to initialize Rhino: {e}", exc_info=True)
            self.is_initialized = False
            raise
    
    def process_frame(self, pcm_frame: List[int]) -> bool:
        """
        Process a single audio frame through Rhino.
        
        Args:
            pcm_frame: List of 16-bit PCM audio samples (length must match frame_length)
            
        Returns:
            True if inference is ready, False otherwise
        """
        if not self.is_initialized or not self.rhino:
            logger.warning("Rhino not initialized, cannot process frame")
            return False
        
        if len(pcm_frame) != self.frame_length:
            logger.warning(
                f"Frame length mismatch: expected {self.frame_length}, got {len(pcm_frame)}"
            )
            return False
        
        try:
            return self.rhino.process(pcm_frame)
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
            return False
    
    def process_bytes(self, pcm_bytes: bytes) -> bool:
        """
        Process raw audio bytes (16-bit PCM).
        
        Args:
            pcm_bytes: Raw audio bytes (must be 2 * frame_length bytes)
            
        Returns:
            True if inference is ready, False otherwise
        """
        if len(pcm_bytes) != self.frame_length * 2:
            logger.warning(
                f"Byte length mismatch: expected {self.frame_length * 2}, got {len(pcm_bytes)}"
            )
            return False
        
        # Convert bytes to PCM samples (16-bit signed integers)
        pcm_frame = struct.unpack_from("h" * self.frame_length, pcm_bytes)
        return self.process_frame(list(pcm_frame))
    
    def get_inference(self) -> Optional[Dict[str, Any]]:
        """
        Get the current inference result.
        
        Returns:
            Dict with "intent" and "confidence" keys if understood, None otherwise.
            Format: {"intent": str, "confidence": float}
        """
        if not self.is_initialized or not self.rhino:
            return None
        
        try:
            inference = self.rhino.get_inference()
            
            if inference.is_understood:
                intent_name = inference.intent
                # Rhino doesn't provide confidence, but we can infer from is_understood
                # For now, set confidence to 1.0 when understood (similar to text-based system)
                confidence = 1.0
                
                logger.info(f"Intent recognized: '{intent_name}' (confidence: {confidence:.3f})")
                
                return {
                    "intent": intent_name,
                    "confidence": confidence
                }
            else:
                logger.debug("Rhino inference: not understood")
                return None
                
        except Exception as e:
            logger.error(f"Error getting inference: {e}")
            return None
    
    def reset(self):
        """Reset the Rhino engine for a new command session."""
        if self.rhino:
            try:
                self.rhino.reset()
                logger.debug("Rhino engine reset")
            except Exception as e:
                logger.warning(f"Error resetting Rhino: {e}")
    
    def delete(self):
        """Clean up and delete the Rhino engine."""
        if self.rhino:
            try:
                self.rhino.delete()
                self.rhino = None
                self.is_initialized = False
                logger.info("Rhino engine deleted")
            except Exception as e:
                logger.error(f"Error deleting Rhino: {e}")
    
    def get_sample_rate(self) -> int:
        """Get the required sample rate for audio input."""
        return self.sample_rate if self.sample_rate else 16000
    
    def get_frame_length(self) -> int:
        """Get the required frame length for audio processing."""
        return self.frame_length if self.frame_length else 512
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup."""
        self.delete()
        return False

