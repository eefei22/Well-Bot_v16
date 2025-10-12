"""
Speech Pipeline Package

This package provides a complete voice pipeline implementation including:
- Wake word detection using Porcupine
- Microphone audio streaming
- Speech-to-text using Google Cloud Speech API
- Pipeline orchestration and state management
"""

from .wakeword import WakeWordDetector, create_wake_word_detector
from .mic_stream import MicStream
from .stt import GoogleSTTService
from .pipeline import VoicePipeline, create_voice_pipeline

__all__ = [
    'WakeWordDetector',
    'create_wake_word_detector', 
    'MicStream',
    'GoogleSTTService',
    'VoicePipeline',
    'create_voice_pipeline'
]

__version__ = "1.0.0"
