#!/usr/bin/env python3
"""
Standalone Test Script for Microphone Stream to Speech-to-Text

This script tests Google Cloud Speech-to-Text with microphone input.
It captures audio from the microphone and streams it to STT for transcription.

Usage:
    python test_micstream_stt.py

Speak when prompted, or press Ctrl+C to stop.
"""

import os
import sys
import json
import tempfile
import logging
from datetime import datetime
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION - Tweak these variables as needed
# ============================================================================

# Path to .env file (relative to this script)
ENV_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')

# STT settings
STT_LANGUAGE = "en-US"  # Language code for recognition
STT_SAMPLE_RATE = 16000  # Audio sample rate in Hz
STT_INTERIM_RESULTS = True  # Show interim results
STT_SINGLE_UTTERANCE = False  # Continue listening after first result

# Audio capture settings
CAPTURE_TIMEOUT_SECONDS = 30.0  # Maximum time to wait for transcription

# Output directory for logs and results
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
TRANSCRIPTS_FILE = os.path.join(OUTPUT_DIR, 'stt_transcripts.txt')
LOG_FILE = os.path.join(OUTPUT_DIR, 'logs', 'test_micstream_stt.log')

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

# Add backend/src to path for imports
backend_src_path = os.path.join(os.path.dirname(__file__), '..', 'src')
sys.path.insert(0, backend_src_path)

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

def save_transcript(transcript: str, is_final: bool, timestamp: str):
    """Save transcript to file."""
    try:
        with open(TRANSCRIPTS_FILE, 'a', encoding='utf-8') as f:
            status = "FINAL" if is_final else "INTERIM"
            f.write(f"[{timestamp}] [{status}] {transcript}\n")
    except Exception as e:
        logger.error(f"Failed to save transcript: {e}")

def test_stt_capture(stt_service):
    """Test STT with a single audio capture."""
    logger.info("=" * 60)
    logger.info("Starting audio capture for speech-to-text...")
    logger.info(f"Speak now. Timeout: {CAPTURE_TIMEOUT_SECONDS}s")
    logger.info("=" * 60)
    
    from components.mic_stream import MicStream
    
    mic = None
    final_transcript = None
    
    try:
        # Create and start microphone stream
        logger.info(f"Initializing microphone (rate: {STT_SAMPLE_RATE}Hz)...")
        mic = MicStream(rate=STT_SAMPLE_RATE, chunk_size=1600)
        mic.start()
        logger.info("Microphone active")
        
        # Transcript callback
        def on_transcript(text: str, is_final: bool):
            nonlocal final_transcript
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            
            if is_final:
                final_transcript = text
                logger.info("=" * 60)
                logger.info(f"🎯 FINAL TRANSCRIPT: {text}")
                logger.info("=" * 60)
                save_transcript(text, True, timestamp)
            else:
                logger.info(f"⏳ Interim: {text}")
                save_transcript(text, False, timestamp)
        
        # Start STT streaming
        logger.info("Starting STT streaming recognition...")
        import threading
        import time
        
        stt_completed = threading.Event()
        stt_error = None
        
        def run_stt():
            nonlocal stt_error
            try:
                stt_service.stream_recognize(
                    mic.generator(),
                    on_transcript,
                    interim_results=STT_INTERIM_RESULTS,
                    single_utterance=STT_SINGLE_UTTERANCE
                )
            except Exception as e:
                stt_error = e
                logger.error(f"STT error: {e}", exc_info=True)
            finally:
                stt_completed.set()
        
        stt_thread = threading.Thread(target=run_stt, daemon=True)
        stt_thread.start()
        
        # Wait for STT completion with timeout
        check_interval = 0.5
        timeout = CAPTURE_TIMEOUT_SECONDS
        
        while not stt_completed.wait(check_interval):
            timeout -= check_interval
            if timeout <= 0:
                logger.warning("STT timeout reached, stopping...")
                mic.stop()
                break
        
        # Wait for thread to finish
        stt_thread.join(timeout=1.0)
        
        if stt_error:
            logger.error(f"STT error occurred: {stt_error}")
            return None
        
        return final_transcript
        
    except Exception as e:
        logger.error(f"Error during STT capture: {e}", exc_info=True)
        return None
        
    finally:
        if mic:
            try:
                mic.stop()
                logger.debug("Microphone stopped")
            except Exception as e:
                logger.error(f"Error stopping microphone: {e}")

def main():
    """Main test function."""
    logger.info("=" * 60)
    logger.info("Microphone Stream to Speech-to-Text Test Script")
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
    
    logger.info(f"STT Language: {STT_LANGUAGE}")
    logger.info(f"STT Sample Rate: {STT_SAMPLE_RATE} Hz")
    logger.info(f"Interim Results: {STT_INTERIM_RESULTS}")
    logger.info(f"Single Utterance: {STT_SINGLE_UTTERANCE}")
    logger.info(f"Output Directory: {OUTPUT_DIR}")
    logger.info(f"Transcripts File: {TRANSCRIPTS_FILE}")
    logger.info(f"Debug Log: {LOG_FILE}")
    
    credentials_file = None
    stt_service = None
    
    try:
        # Create Google Cloud credentials file
        logger.info("Creating Google Cloud credentials file...")
        credentials_file = create_google_credentials_file()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_file
        
        # Import STT service
        from components.stt import GoogleSTTService
        
        # Initialize STT service
        logger.info("Initializing Google STT service...")
        stt_service = GoogleSTTService(
            language=STT_LANGUAGE,
            sample_rate=STT_SAMPLE_RATE
        )
        logger.info("STT service initialized successfully")
        
        # Test loop
        logger.info("=" * 60)
        logger.info("Ready for STT testing")
        logger.info("Press Enter to start a test, or type 'quit' to exit")
        logger.info("=" * 60)
        
        while True:
            try:
                user_input = input("\nPress Enter to test (or 'quit' to exit): ").strip().lower()
                if user_input == 'quit':
                    break
                
                # Run STT test
                transcript = test_stt_capture(stt_service)
                
                if transcript:
                    logger.info(f"\n✅ Final transcript received: '{transcript}'")
                else:
                    logger.warning("\n⚠️  No final transcript received")
                
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Error in test loop: {e}", exc_info=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Error during STT test: {e}", exc_info=True)
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

