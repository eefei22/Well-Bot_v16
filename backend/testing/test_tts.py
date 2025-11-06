#!/usr/bin/env python3
"""
Standalone Test Script for Text-to-Speech

This script tests Google Cloud Text-to-Speech.
It accepts text input and synthesizes speech, playing it back and saving to file.

Usage:
    python test_tts.py

Type text to synthesize, or press Ctrl+C to stop.
"""

import os
import sys
import json
import tempfile
import logging
import pyaudio
from datetime import datetime
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION - Tweak these variables as needed
# ============================================================================

# Path to .env file (relative to this script)
ENV_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')

# TTS settings
TTS_VOICE_NAME = "en-US-Chirp3-HD-Charon"  # Voice name
TTS_LANGUAGE_CODE = "en-US"  # Language code
TTS_SAMPLE_RATE_HERTZ = 24000  # Sample rate for audio output
TTS_NUM_CHANNELS = 1  # Number of audio channels (mono)
TTS_SAMPLE_WIDTH_BYTES = 2  # Sample width in bytes (16-bit)

# Output directory for logs and results
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
AUDIO_OUTPUT_FILE = os.path.join(OUTPUT_DIR, 'tts_output.wav')
LOG_FILE = os.path.join(OUTPUT_DIR, 'logs', 'test_tts.log')

# ============================================================================
# SETUP
# ============================================================================

# Load environment variables
load_dotenv(ENV_FILE_PATH)

# Get Google Cloud credentials from environment
GOOGLE_TYPE = os.getenv("GOOGLE_TYPE")
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
GOOGLE_PRIVATE_KEY_ID = os.getenv("GOOGLE_PRIVATE_KEY_ID")
GOOGLE_PRIVATE_KEY = os.getenv("GOOGLE_PRIVATE_KEY")
GOOGLE_CLIENT_EMAIL = os.getenv("GOOGLE_CLIENT_EMAIL")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_AUTH_URI = os.getenv("GOOGLE_AUTH_URI")
GOOGLE_TOKEN_URI = os.getenv("GOOGLE_TOKEN_URI")
GOOGLE_AUTH_PROVIDER_CERT_URL = os.getenv("GOOGLE_AUTH_PROVIDER_CERT_URL")
GOOGLE_CLIENT_CERT_URL = os.getenv("GOOGLE_CLIENT_CERT_URL")
GOOGLE_UNIVERSE_DOMAIN = os.getenv("GOOGLE_UNIVERSE_DOMAIN")

# Create output directories
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, 'logs'), exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Add backend directory to path for imports (needed for relative imports in components)
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

# ============================================================================
# GOOGLE CLOUD CREDENTIALS SETUP
# ============================================================================

def create_google_credentials_file():
    """Create a temporary Google Cloud credentials JSON file from environment variables."""
    credentials = {
        "type": GOOGLE_TYPE,
        "project_id": GOOGLE_PROJECT_ID,
        "private_key_id": GOOGLE_PRIVATE_KEY_ID,
        "private_key": GOOGLE_PRIVATE_KEY,
        "client_email": GOOGLE_CLIENT_EMAIL,
        "client_id": GOOGLE_CLIENT_ID,
        "auth_uri": GOOGLE_AUTH_URI,
        "token_uri": GOOGLE_TOKEN_URI,
        "auth_provider_x509_cert_url": GOOGLE_AUTH_PROVIDER_CERT_URL,
        "client_x509_cert_url": GOOGLE_CLIENT_CERT_URL,
        "universe_domain": GOOGLE_UNIVERSE_DOMAIN
    }
    
    # Validate all required fields
    missing_fields = [key for key, value in credentials.items() if not value]
    if missing_fields:
        raise ValueError(f"Missing required Google Cloud credential fields: {missing_fields}")
    
    # Create a temporary file for Google Cloud credentials
    temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(credentials, temp_file, indent=2)
    temp_file.close()
    
    logger.info(f"Created temporary Google Cloud credentials file: {temp_file.name}")
    return temp_file.name

# ============================================================================
# MAIN TEST FUNCTION
# ============================================================================

def play_audio(audio_bytes: bytes, sample_rate: int, num_channels: int):
    """Play audio using PyAudio."""
    pa = None
    stream = None
    
    try:
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=num_channels,
            rate=sample_rate,
            output=True
        )
        
        logger.info("Playing audio...")
        stream.write(audio_bytes)
        stream.stop_stream()
        logger.info("Audio playback completed")
        
    except Exception as e:
        logger.error(f"Error playing audio: {e}", exc_info=True)
    finally:
        if stream:
            try:
                stream.close()
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")
        if pa:
            try:
                pa.terminate()
            except Exception as e:
                logger.error(f"Error terminating PyAudio: {e}")

def save_audio_to_wav(audio_bytes: bytes, output_path: str):
    """Save audio bytes to WAV file."""
    import wave
    
    try:
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(TTS_NUM_CHANNELS)
            wf.setsampwidth(TTS_SAMPLE_WIDTH_BYTES)
            wf.setframerate(TTS_SAMPLE_RATE_HERTZ)
            wf.writeframes(audio_bytes)
        
        logger.info(f"Audio saved to: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving audio to WAV: {e}", exc_info=True)
        return False

def test_tts_synthesis(tts_client, text: str):
    """Test TTS synthesis with given text."""
    logger.info("=" * 60)
    logger.info(f"Synthesizing text: '{text}'")
    logger.info("=" * 60)
    
    try:
        # Synthesize speech
        logger.info("Calling TTS synthesize...")
        audio_bytes = tts_client.synthesize(text)
        
        if not audio_bytes:
            logger.error("No audio bytes returned from TTS")
            return False
        
        logger.info(f"Received {len(audio_bytes)} bytes of audio data")
        
        # Play audio
        logger.info("Playing audio...")
        play_audio(audio_bytes, TTS_SAMPLE_RATE_HERTZ, TTS_NUM_CHANNELS)
        
        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = AUDIO_OUTPUT_FILE.replace('.wav', f'_{timestamp}.wav')
        save_audio_to_wav(audio_bytes, output_path)
        
        logger.info("=" * 60)
        logger.info("TTS synthesis completed successfully")
        logger.info("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"Error during TTS synthesis: {e}", exc_info=True)
        return False

def main():
    """Main test function."""
    logger.info("=" * 60)
    logger.info("Text-to-Speech Test Script")
    logger.info("=" * 60)
    
    # Validate Google Cloud credentials
    required_vars = [
        "GOOGLE_TYPE", "GOOGLE_PROJECT_ID", "GOOGLE_PRIVATE_KEY_ID",
        "GOOGLE_PRIVATE_KEY", "GOOGLE_CLIENT_EMAIL", "GOOGLE_CLIENT_ID",
        "GOOGLE_AUTH_URI", "GOOGLE_TOKEN_URI", "GOOGLE_AUTH_PROVIDER_CERT_URL",
        "GOOGLE_CLIENT_CERT_URL", "GOOGLE_UNIVERSE_DOMAIN"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        logger.error(f"Missing required Google Cloud credential environment variables: {missing_vars}")
        logger.error("Please set all GOOGLE_* variables in your .env file")
        return False
    
    logger.info(f"TTS Voice: {TTS_VOICE_NAME}")
    logger.info(f"TTS Language: {TTS_LANGUAGE_CODE}")
    logger.info(f"Sample Rate: {TTS_SAMPLE_RATE_HERTZ} Hz")
    logger.info(f"Channels: {TTS_NUM_CHANNELS}")
    logger.info(f"Output Directory: {OUTPUT_DIR}")
    logger.info(f"Audio Output: {AUDIO_OUTPUT_FILE}")
    logger.info(f"Debug Log: {LOG_FILE}")
    
    credentials_file = None
    tts_client = None
    
    try:
        # Create Google Cloud credentials file
        logger.info("Creating Google Cloud credentials file...")
        credentials_file = create_google_credentials_file()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_file
        
        # Import TTS client
        from src.components.tts import GoogleTTSClient
        from google.cloud import texttospeech
        
        # Initialize TTS client
        logger.info("Initializing Google TTS client...")
        tts_client = GoogleTTSClient(
            voice_name=TTS_VOICE_NAME,
            language_code=TTS_LANGUAGE_CODE,
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            sample_rate_hertz=TTS_SAMPLE_RATE_HERTZ,
            num_channels=TTS_NUM_CHANNELS,
            sample_width_bytes=TTS_SAMPLE_WIDTH_BYTES
        )
        logger.info("TTS client initialized successfully")
        
        # Test loop
        logger.info("=" * 60)
        logger.info("Ready for TTS testing")
        logger.info("Type text to synthesize, or type 'quit' to exit")
        logger.info("=" * 60)
        
        while True:
            try:
                text = input("\nEnter text to synthesize (or 'quit' to exit): ").strip()
                
                if text.lower() == 'quit':
                    break
                
                if not text:
                    logger.warning("Empty text, skipping...")
                    continue
                
                # Run TTS test
                test_tts_synthesis(tts_client, text)
                
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Error in test loop: {e}", exc_info=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Error during TTS test: {e}", exc_info=True)
        return False
        
    finally:
        # Cleanup
        if credentials_file and os.path.exists(credentials_file):
            try:
                os.unlink(credentials_file)
                logger.info(f"Removed temporary credentials file: {credentials_file}")
            except Exception as e:
                logger.warning(f"Failed to remove temporary credentials file: {e}")
        
        logger.info("=" * 60)
        logger.info("Test completed")
        logger.info("=" * 60)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

