#!/usr/bin/env python3
"""
Activity Error Handler Component

Reusable component for handling activity failures (initialization and runtime errors).
Speaks a user-friendly error message via TTS when activities fail to start or encounter errors.
"""

import logging
import pyaudio
from pathlib import Path
from typing import Optional

from src.components.tts import GoogleTTSClient
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from google.cloud import texttospeech

logger = logging.getLogger(__name__)


def handle_activity_error(
    backend_dir: Path,
    user_id: str,
    activity_name: Optional[str] = None,
    error_context: Optional[str] = None
) -> bool:
    """
    Handle activity errors by speaking a user-friendly error message.
    
    Args:
        backend_dir: Path to backend directory
        user_id: User ID for loading user-specific config
        activity_name: Optional name of the activity that failed (for logging)
        error_context: Optional error context/details (for logging)
    
    Returns:
        True if error message was spoken successfully, False otherwise
    """
    try:
        logger.info(f"Handling activity error for user {user_id}" + 
                   (f", activity: {activity_name}" if activity_name else "") +
                   (f", context: {error_context}" if error_context else ""))
        
        # Load user-specific configurations
        try:
            global_config = get_global_config_for_user(user_id)
            language_config = get_language_config(user_id)
        except Exception as e:
            logger.error(f"Failed to load configs for error handler: {e}")
            return False
        
        # Get error message from config
        wakeword_responses = language_config.get("wakeword_responses", {})
        prompts = wakeword_responses.get("prompts", {})
        error_message = prompts.get(
            "activity_unavailable",
            "That activity isn't available right now. Can we try something else?"
        )
        
        logger.info(f"Speaking error message: {error_message}")
        
        # Initialize TTS client
        try:
            audio_settings = global_config.get("audio_settings", {})
            tts_client = GoogleTTSClient(
                voice_name=global_config["language_codes"]["tts_voice_name"],
                language_code=global_config["language_codes"]["tts_language_code"],
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=audio_settings.get("tts_sample_rate_hertz", 24000),
                num_channels=audio_settings.get("tts_num_channels", 1),
                sample_width_bytes=audio_settings.get("tts_sample_width_bytes", 2),
            )
        except Exception as e:
            logger.error(f"Failed to initialize TTS client for error handler: {e}")
            return False
        
        # Speak the error message using PyAudio
        try:
            def text_gen():
                yield error_message
            
            # Generate PCM chunks
            pcm_chunks = tts_client.stream_synthesize(text_gen())
            
            # Play PCM chunks using PyAudio
            pa = pyaudio.PyAudio()
            stream = pa.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=24000,
                output=True
            )
            
            for chunk in pcm_chunks:
                stream.write(chunk)
            
            stream.stop_stream()
            stream.close()
            pa.terminate()
            
            logger.info("Error message spoken successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to speak error message: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Unexpected error in activity error handler: {e}", exc_info=True)
        return False


