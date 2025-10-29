"""
Speech-to-Text Service using Google Cloud Speech API

This service handles streaming speech recognition with interim and final results.
It accepts audio chunks and provides transcript callbacks.
"""

import os
import logging
from google.cloud import speech
from typing import Callable, Iterable, Optional, Dict, Any
from ..utils.config_loader import get_google_cloud_credentials_path

# Set up credentials from environment variables
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = get_google_cloud_credentials_path()

logger = logging.getLogger(__name__)


class GoogleSTTService:
    """
    Google Cloud Speech-to-Text service for streaming recognition.
    """
    
    def __init__(self, language: str = "en-US", sample_rate: int = 16000):
        """
        Initialize the STT service.
        
        Args:
            language: Language code for recognition (default: "en-US")
            sample_rate: Audio sample rate in Hz (default: 16000)
        """
        self.client = speech.SpeechClient()
        self.language = language
        self.sample_rate = sample_rate
        
        logger.info(f"STT service ready | Language: {language} | Rate: {sample_rate}Hz")
    
    def _build_streaming_config(self, **kwargs) -> speech.StreamingRecognitionConfig:
        """
        Build the streaming recognition configuration.
        
        Args:
            **kwargs: Additional configuration options
            
        Returns:
            Configured StreamingRecognitionConfig
        """
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=self.sample_rate,
            language_code=self.language,
            max_alternatives=kwargs.get('max_alternatives', 1),
            profanity_filter=kwargs.get('profanity_filter', False),
            enable_automatic_punctuation=kwargs.get('enable_automatic_punctuation', True),
            enable_word_time_offsets=kwargs.get('enable_word_time_offsets', False),
            enable_word_confidence=kwargs.get('enable_word_confidence', False),
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=kwargs.get('interim_results', True),
            single_utterance=kwargs.get('single_utterance', False),
        )
        
        return streaming_config
    
    def stream_recognize(
        self,
        audio_generator: Iterable[bytes],
        on_transcript: Callable[[str, bool], None],
        **config_kwargs
    ) -> None:
        """
        Send streaming requests and call on_transcript(text, is_final) for each result.
        
        This function is blocking — it will run until audio_generator drains or error.
        
        Args:
            audio_generator: Iterable of audio chunks (bytes)
            on_transcript: Callback function that receives (text, is_final)
            **config_kwargs: Additional configuration options
        """
        try:
            streaming_config = self._build_streaming_config(**config_kwargs)
            
            # Create streaming requests from audio generator
            requests = (
                speech.StreamingRecognizeRequest(audio_content=chunk)
                for chunk in audio_generator
            )
            
            logger.info("Speech recognition started")
            
            # Get streaming responses
            responses = self.client.streaming_recognize(streaming_config, requests)
            
            # Process responses
            for resp in responses:
                if not resp.results:
                    continue
                    
                result = resp.results[0]
                if not result.alternatives:
                    continue
                    
                transcript = result.alternatives[0].transcript
                is_final = result.is_final
                confidence = result.alternatives[0].confidence if hasattr(result.alternatives[0], 'confidence') else None
                
                logger.debug(f"Transcript: '{transcript}' (final: {is_final}, confidence: {confidence})")
                
                try:
                    on_transcript(transcript, is_final)
                except Exception as e:
                    import traceback
                    exception_name = type(e).__name__
                    
                    # Check if this is a termination signal that should propagate
                    # (e.g., TerminationPhraseDetected from journal/smalltalk activities)
                    is_termination_signal = "Termination" in exception_name or "termination" in str(e).lower()
                    
                    if is_termination_signal:
                        # Termination signals are expected - log at debug level
                        logger.debug(f"Termination signal in transcript callback: {exception_name}")
                        logger.debug(f"  Transcript: '{transcript}' (final: {is_final})")
                        # Re-raise termination signals so they can be caught by activity handlers
                        raise
                    else:
                        # Real errors - log with full details
                        logger.error(f"Error in transcript callback")
                        logger.error(f"  Exception type: {exception_name}")
                        logger.error(f"  Exception message: {str(e)}")
                        logger.error(f"  Transcript text: '{transcript}'")
                        logger.error(f"  Is final: {is_final}")
                        logger.error(f"  Full traceback:")
                        logger.error(traceback.format_exc())
                        # For other errors, log and continue processing
                    
        except Exception as e:
            # Check if this is a termination signal that should propagate silently
            exception_name = type(e).__name__
            is_termination_signal = "Termination" in exception_name or "termination" in str(e).lower()
            
            if is_termination_signal:
                # Termination signals are expected and should propagate without error logging
                logger.debug(f"Termination signal propagated from transcript callback: {exception_name}")
                raise
            else:
                logger.error(f"Error in streaming recognition: {e}")
                raise
    
    def recognize_file(self, audio_file_path: str) -> Optional[str]:
        """
        Recognize speech from an audio file (non-streaming).
        
        Args:
            audio_file_path: Path to the audio file
            
        Returns:
            Final transcript text or None if error
        """
        try:
            with open(audio_file_path, 'rb') as audio_file:
                content = audio_file.read()
            
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self.sample_rate,
                language_code=self.language,
            )
            
            audio = speech.RecognitionAudio(content=content)
            response = self.client.recognize(config=config, audio=audio)
            
            if response.results:
                return response.results[0].alternatives[0].transcript
            
            return None
            
        except Exception as e:
            logger.error(f"Error recognizing file {audio_file_path}: {e}")
            return None
    
    def get_language(self) -> str:
        """Get the configured language code."""
        return self.language
    
    def get_sample_rate(self) -> int:
        """Get the configured sample rate."""
        return self.sample_rate


# Example usage and testing
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(level=logging.INFO)
    
    def test_stt_service():
        """Test the STT service with a simple audio generator."""
        stt_service = GoogleSTTService(language="en-US", sample_rate=16000)
        
        def on_transcript(text: str, is_final: bool):
            """Callback function for transcript results."""
            if is_final:
                print(f"🎯 Final: {text}")
            else:
                print(f"⏳ Interim: {text}", end="\r")
        
        # Mock audio generator (in real usage, this would come from MicStream)
        def mock_audio_generator():
            """Generate mock audio chunks for testing."""
            import time
            for i in range(10):  # Generate 10 chunks
                # In real usage, this would be actual audio data
                mock_chunk = b'\x00' * 1600  # 100ms of silence at 16kHz
                yield mock_chunk
                time.sleep(0.1)  # Simulate real-time audio
        
        try:
            print("Testing STT service...")
            print("Note: This test uses mock audio data (silence)")
            print("In real usage, audio would come from MicStream")
            
            # Test streaming recognition
            stt_service.stream_recognize(
                audio_generator=mock_audio_generator(),
                on_transcript=on_transcript,
                interim_results=True,
                single_utterance=False
            )
            
        except Exception as e:
            print(f"Error during STT test: {e}")
    
    # Run the test
    test_stt_service()
