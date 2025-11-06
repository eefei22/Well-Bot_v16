"""
Speech Pipeline Package

This package provides a complete voice pipeline implementation including:
- Wake word detection using Porcupine
- Microphone audio streaming
- Speech-to-text using Google Cloud Speech API
- Pipeline orchestration and state management
- Conversation management components
"""

from .wakeword import WakeWordDetector, create_wake_word_detector
from .mic_stream import MicStream
from .stt import GoogleSTTService
from .intent_recognition import IntentRecognition
from ._pipeline_wakeword import VoicePipeline, create_voice_pipeline
from .conversation_audio_manager import ConversationAudioManager
from .conversation_session import ConversationSession

__all__ = [
    'WakeWordDetector',
    'create_wake_word_detector', 
    'MicStream',
    'GoogleSTTService',
    'IntentRecognition',
    'VoicePipeline',
    'create_voice_pipeline',
    'ConversationAudioManager',
    'ConversationSession'
]

__version__ = "1.0.0"
