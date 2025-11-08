"""
Speech Pipeline Package - Lazy Imports

This package provides a complete voice pipeline implementation including:
- Wake word detection using Porcupine
- Microphone audio streaming
- Speech-to-text using Google Cloud Speech API
- Pipeline orchestration and state management
- Conversation management components

Uses lazy imports to prevent cascade import issues on Raspberry Pi.
"""

# Lazy import pattern - modules are loaded on-demand via __getattr__
# This prevents cascade imports when the package is loaded

__all__ = [
    # Core components (originally exported)
    'WakeWordDetector',
    'create_wake_word_detector', 
    'MicStream',
    'GoogleSTTService',
    'IntentRecognition',
    'VoicePipeline',
    'create_voice_pipeline',
    'ConversationAudioManager',
    'ConversationSession',
    # Additional components used by activities (newly added)
    'GoogleTTSClient',
    'SmallTalkSession',
    'TerminationPhraseDetector',
    'TerminationPhraseDetected',
    'normalize_text',
    'DeepSeekClient',
    'UserContextInjector',
]

__version__ = "1.0.0"


def __getattr__(name):
    """
    Lazy import handler for components.
    
    Modules are loaded on-demand when accessed, preventing cascade imports.
    This allows the package to work on both Windows and Raspberry Pi without
    triggering unnecessary dependency loads.
    """
    # Core wakeword components
    if name == 'WakeWordDetector':
        from .wakeword import WakeWordDetector
        return WakeWordDetector
    elif name == 'create_wake_word_detector':
        from .wakeword import create_wake_word_detector
        return create_wake_word_detector
    
    # Audio streaming
    elif name == 'MicStream':
        from .mic_stream import MicStream
        return MicStream
    
    # Speech-to-text
    elif name == 'GoogleSTTService':
        from .stt import GoogleSTTService
        return GoogleSTTService
    
    # Intent recognition
    elif name == 'IntentRecognition':
        from .intent_recognition import IntentRecognition
        return IntentRecognition
    
    # Voice pipeline
    elif name == 'VoicePipeline':
        from ._pipeline_wakeword import VoicePipeline
        return VoicePipeline
    elif name == 'create_voice_pipeline':
        from ._pipeline_wakeword import create_voice_pipeline
        return create_voice_pipeline
    
    # Conversation management
    elif name == 'ConversationAudioManager':
        from .conversation_audio_manager import ConversationAudioManager
        return ConversationAudioManager
    elif name == 'ConversationSession':
        from .conversation_session import ConversationSession
        return ConversationSession
    
    # Text-to-speech (used by activities but not originally exported)
    elif name == 'GoogleTTSClient':
        from .tts import GoogleTTSClient
        return GoogleTTSClient
    
    # SmallTalk pipeline (used by smalltalk activity)
    elif name == 'SmallTalkSession':
        from ._pipeline_smalltalk import SmallTalkSession
        return SmallTalkSession
    
    # Termination phrase detection (used by multiple activities)
    elif name == 'TerminationPhraseDetector':
        from .termination_phrase import TerminationPhraseDetector
        return TerminationPhraseDetector
    elif name == 'TerminationPhraseDetected':
        from .termination_phrase import TerminationPhraseDetected
        return TerminationPhraseDetected
    elif name == 'normalize_text':
        from .termination_phrase import normalize_text
        return normalize_text
    
    # LLM client (used by _pipeline_smalltalk)
    elif name == 'DeepSeekClient':
        from .llm import DeepSeekClient
        return DeepSeekClient
    
    # User context injector (used by activities)
    elif name == 'UserContextInjector':
        from .user_context_injector import UserContextInjector
        return UserContextInjector
    
    # Unknown attribute
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
