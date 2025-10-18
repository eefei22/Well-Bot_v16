"""
Simple usage example for GoogleTTSClient.

This demonstrates basic usage patterns for both streaming and non-streaming TTS.
"""

import sys
from pathlib import Path

# Add the backend/src directory to the Python path
backend_src = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(backend_src))

from components.tts import GoogleTTSClient


def example_non_streaming():
    """Example of non-streaming TTS usage."""
    print("=== Non-Streaming TTS Example ===")
    
    # Initialize client
    client = GoogleTTSClient()
    
    # Synthesize complete text with proper WAV header
    text = "Why is there two different test files for TTS?"
    audio_bytes = client.synthesize_to_wav(text, "test_output2.wav")
    
    print(f"Generated {len(audio_bytes)} bytes of PCM audio")
    print("Audio saved to 'test_output2.wav' with proper WAV header")


def example_streaming():
    """Example of streaming TTS usage."""
    print("\n=== Streaming TTS Example ===")
    
    # Initialize client
    client = GoogleTTSClient()
    
    # Prepare text chunks (simulating incremental text generation)
    text_chunks = [
        "Hello there! ",
        "This is a streaming ",
        "text-to-speech example. ",
        "Each chunk is processed ",
        "as it becomes available."
    ]
    
    # Stream synthesis with proper WAV output
    audio_bytes = client.stream_synthesize_to_wav(iter(text_chunks), "example_streaming_output.wav")
    
    print(f"Generated {len(audio_bytes)} bytes of PCM audio from streaming")
    print("Audio saved to 'example_streaming_output.wav' with proper WAV header")


def example_with_custom_voice():
    """Example using custom voice settings."""
    print("\n=== Custom Voice Example ===")
    
    # Initialize with custom voice
    client = GoogleTTSClient(
        voice_name="en-US-Neural2-A",  # Different voice
        language_code="en-US"
    )
    
    text = "This is using a different neural voice."
    audio_bytes = client.synthesize_to_wav(text, "example_custom_voice.wav")
    
    print(f"Generated {len(audio_bytes)} bytes with custom voice")
    print("Audio saved to 'example_custom_voice.wav' with proper WAV header")


if __name__ == "__main__":
    try:
        example_non_streaming()
        example_streaming()
        example_with_custom_voice()
        print("\nAll examples completed successfully!")
        
    except Exception as e:
        print(f"Error running examples: {e}")
        print("Make sure you have:")
        print("1. Google Cloud credentials file at backend/config/STT/GoogleCloud.json")
        print("2. google-cloud-texttospeech installed")
        print("3. Proper permissions for TTS API")
