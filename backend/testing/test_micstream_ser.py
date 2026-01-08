#!/usr/bin/env python3
"""
Standalone Test Script for Microphone Stream to Speech Emotion Recognition Service

This script tests the Well-Bot_SER service with microphone input.
It captures audio from the microphone, saves it to a WAV file, and sends it to the SER service.

Usage:
    python test_micstream_ser.py

Speak when prompted, or press Ctrl+C to stop.
"""

import os
import sys
import logging
import tempfile
import wave
import requests
import json
from datetime import datetime
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION - Tweak these variables as needed
# ============================================================================

# Path to .env file (relative to this script)
ENV_FILE_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')

# SER Service settings
SER_SERVICE_URL = os.getenv("SER_SERVICE_URL", "http://localhost:8008")  # Default to local
SER_ENDPOINT = "/analyze-speech"
SER_TIMEOUT = 30  # Request timeout in seconds
TEST_USER_ID = os.getenv("TEST_USER_ID", "96975f52-5b05-4eb1-bfa5-530485112518")  # Default test user ID

# Audio capture settings
AUDIO_SAMPLE_RATE = 16000  # Audio sample rate in Hz
AUDIO_CHUNK_SIZE = 1600  # Frames per chunk
CAPTURE_DURATION_SECONDS = 5.0  # How long to record (adjust as needed)
SILENCE_THRESHOLD = 500  # Minimum audio level to consider as speech (adjust as needed)

# Output directory for logs and results
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), 'output')
RESULTS_FILE = os.path.join(OUTPUT_DIR, 'ser_results.json')
LOG_FILE = os.path.join(OUTPUT_DIR, 'logs', 'test_micstream_ser.log')

# ============================================================================
# SETUP
# ============================================================================

# Load environment variables
load_dotenv(ENV_FILE_PATH)

# Create output directories
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(os.path.join(OUTPUT_DIR, 'logs'), exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Add backend directory to path for imports
backend_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, backend_dir)

# ============================================================================
# AUDIO CAPTURE FUNCTIONS
# ============================================================================

def save_audio_to_wav(audio_chunks, sample_rate, output_path):
    """
    Save audio chunks to a WAV file.
    
    Args:
        audio_chunks: List of audio data bytes
        sample_rate: Sample rate in Hz
        output_path: Path to save WAV file
    """
    try:
        with wave.open(output_path, 'wb') as wf:
            wf.setnchannels(1)  # Mono
            wf.setsampwidth(2)  # 16-bit (2 bytes)
            wf.setframerate(sample_rate)
            for chunk in audio_chunks:
                wf.writeframes(chunk)
        logger.info(f"Saved audio to: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save audio: {e}")
        return False

def capture_audio_from_mic(duration_seconds, sample_rate, chunk_size):
    """
    Capture audio from microphone for specified duration.
    
    Args:
        duration_seconds: How long to record
        sample_rate: Sample rate in Hz
        chunk_size: Frames per chunk
    
    Returns:
        List of audio chunks (bytes)
    """
    try:
        import pyaudio
    except ImportError:
        logger.error("=" * 60)
        logger.error("ERROR: pyaudio is not installed!")
        logger.error("=" * 60)
        logger.error("To install pyaudio:")
        logger.error("  Windows: pip install pyaudio")
        logger.error("  Linux:   sudo apt-get install portaudio19-dev && pip install pyaudio")
        logger.error("  Mac:     brew install portaudio && pip install pyaudio")
        logger.error("")
        logger.error("Alternatively, use the file-based test option:")
        logger.error("  python test_micstream_ser.py --file path/to/audio.wav")
        logger.error("=" * 60)
        raise ImportError("pyaudio is required for microphone capture. Install it or use --file option.")
    
    import importlib.util
    import types
    
    # Set up package structure for relative imports
    if 'src' not in sys.modules:
        sys.modules['src'] = types.ModuleType('src')
    if 'src.components' not in sys.modules:
        sys.modules['src.components'] = types.ModuleType('src.components')
    
    # Import MicStream
    mic_file_path = os.path.join(backend_dir, 'src', 'components', 'mic_stream.py')
    spec = importlib.util.spec_from_file_location("src.components.mic_stream", mic_file_path)
    mic_module = importlib.util.module_from_spec(spec)
    mic_module.__package__ = 'src.components'
    mic_module.__name__ = 'src.components.mic_stream'
    sys.modules['src.components.mic_stream'] = mic_module
    spec.loader.exec_module(mic_module)
    MicStream = mic_module.MicStream
    
    mic = None
    audio_chunks = []
    
    try:
        logger.info(f"Initializing microphone (rate: {sample_rate}Hz)...")
        mic = MicStream(rate=sample_rate, chunk_size=chunk_size)
        mic.start()
        logger.info("Microphone active - speak now!")
        
        # Calculate number of chunks needed
        chunks_per_second = sample_rate // chunk_size
        total_chunks = int(duration_seconds * chunks_per_second)
        
        logger.info(f"Recording for {duration_seconds} seconds...")
        
        # Collect audio chunks
        for i in range(total_chunks):
            try:
                chunk = mic.generator().__next__()
                audio_chunks.append(chunk)
                if (i + 1) % chunks_per_second == 0:
                    logger.info(f"Recording... {i // chunks_per_second + 1}/{int(duration_seconds)} seconds")
            except StopIteration:
                logger.warning("Audio stream ended early")
                break
            except Exception as e:
                logger.error(f"Error capturing audio chunk: {e}")
                break
        
        logger.info(f"Captured {len(audio_chunks)} audio chunks")
        return audio_chunks
        
    except Exception as e:
        logger.error(f"Error during audio capture: {e}", exc_info=True)
        return []
        
    finally:
        if mic:
            try:
                mic.stop()
                logger.debug("Microphone stopped")
            except Exception as e:
                logger.error(f"Error stopping microphone: {e}")

# ============================================================================
# SER SERVICE FUNCTIONS
# ============================================================================

def send_audio_to_ser(audio_file_path, service_url, endpoint, user_id):
    """
    Send audio file to SER service for analysis.
    
    Args:
        audio_file_path: Path to WAV audio file
        service_url: Base URL of SER service
        endpoint: API endpoint path
        user_id: UUID of the user
    
    Returns:
        Dictionary with analysis results or None on error
    """
    try:
        url = f"{service_url}{endpoint}"
        logger.info(f"Sending audio to SER service: {url}")
        logger.info(f"User ID: {user_id}")
        
        with open(audio_file_path, 'rb') as audio_file:
            files = {'file': (os.path.basename(audio_file_path), audio_file, 'audio/wav')}
            data = {'user_id': user_id}
            response = requests.post(url, files=files, data=data, timeout=SER_TIMEOUT)
        
        if response.status_code == 200:
            result = response.json()
            logger.info("SER service responded successfully")
            return result
        else:
            logger.error(f"SER service error: {response.status_code} - {response.text}")
            return None
            
    except requests.exceptions.Timeout:
        logger.error(f"Request timeout after {SER_TIMEOUT} seconds")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error - is the SER service running at {service_url}?")
        return None
    except Exception as e:
        logger.error(f"Error sending audio to SER service: {e}", exc_info=True)
        return None

def save_result(result, audio_file_path):
    """
    Save analysis result to file.
    
    Args:
        result: Analysis result dictionary
        audio_file_path: Path to the audio file that was analyzed
    """
    try:
        result_entry = {
            "timestamp": datetime.now().isoformat(),
            "audio_file": audio_file_path,
            "result": result
        }
        
        # Load existing results
        results = []
        if os.path.exists(RESULTS_FILE):
            try:
                with open(RESULTS_FILE, 'r', encoding='utf-8') as f:
                    results = json.load(f)
            except:
                results = []
        
        # Append new result
        results.append(result_entry)
        
        # Save all results
        with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved result to: {RESULTS_FILE}")
        
    except Exception as e:
        logger.error(f"Failed to save result: {e}")

def display_result(result):
    """
    Display analysis result in a readable format.
    
    Args:
        result: Analysis result dictionary
    """
    if not result:
        logger.warning("No result to display")
        return
    
    logger.info("=" * 60)
    logger.info("SER ANALYSIS RESULTS")
    logger.info("=" * 60)
    
    if "analysis_result" in result:
        analysis = result["analysis_result"]
        
        logger.info(f"Emotion: {analysis.get('emotion', 'N/A')}")
        logger.info(f"Emotion Confidence: {analysis.get('emotion_confidence', 0.0):.2%}")
        logger.info(f"Transcript: {analysis.get('transcript', 'N/A')}")
        logger.info(f"Language: {analysis.get('language', 'N/A')}")
        logger.info(f"Sentiment: {analysis.get('sentiment', 'N/A')}")
        logger.info(f"Sentiment Confidence: {analysis.get('sentiment_confidence', 0.0):.2%}")
    else:
        logger.info(f"Raw result: {json.dumps(result, indent=2)}")
    
    logger.info("=" * 60)

# ============================================================================
# MAIN TEST FUNCTION
# ============================================================================

def test_ser_with_file(audio_file_path, service_url=None):
    """
    Test SER service with an existing audio file.
    
    Args:
        audio_file_path: Path to existing WAV audio file
        service_url: SER service URL (defaults to SER_SERVICE_URL)
    
    Returns:
        Analysis result dictionary or None
    """
    if service_url is None:
        service_url = SER_SERVICE_URL
        
    if not os.path.exists(audio_file_path):
        logger.error(f"Audio file not found: {audio_file_path}")
        return None
    
    logger.info("=" * 60)
    logger.info(f"Testing SER service with audio file: {audio_file_path}")
    logger.info("=" * 60)
    
    try:
        # Send audio to SER service
        result = send_audio_to_ser(audio_file_path, service_url, SER_ENDPOINT, TEST_USER_ID)
        
        if result:
            # Display and save result
            display_result(result)
            save_result(result, audio_file_path)
            return result
        else:
            logger.warning("No result received from SER service")
            return None
            
    except Exception as e:
        logger.error(f"Error testing with file: {e}", exc_info=True)
        return None

def test_ser_capture(service_url=None):
    """
    Test SER service with a single audio capture.
    
    Args:
        service_url: SER service URL (defaults to SER_SERVICE_URL)
    """
    if service_url is None:
        service_url = SER_SERVICE_URL
        
    logger.info("=" * 60)
    logger.info("Starting audio capture for SER analysis...")
    logger.info(f"Recording duration: {CAPTURE_DURATION_SECONDS} seconds")
    logger.info("=" * 60)
    
    # Step 1: Capture audio from microphone
    audio_chunks = capture_audio_from_mic(
        CAPTURE_DURATION_SECONDS,
        AUDIO_SAMPLE_RATE,
        AUDIO_CHUNK_SIZE
    )
    
    if not audio_chunks:
        logger.error("No audio captured")
        return None
    
    # Step 2: Save audio to temporary WAV file
    temp_audio_file = tempfile.mktemp(suffix='.wav', prefix='ser_test_')
    if not save_audio_to_wav(audio_chunks, AUDIO_SAMPLE_RATE, temp_audio_file):
        logger.error("Failed to save audio file")
        return None
    
    try:
        # Step 3: Send audio to SER service
        result = send_audio_to_ser(temp_audio_file, service_url, SER_ENDPOINT, TEST_USER_ID)
        
        if result:
            # Step 4: Display and save result
            display_result(result)
            save_result(result, temp_audio_file)
            return result
        else:
            logger.warning("No result received from SER service")
            return None
            
    finally:
        # Clean up temp audio file
        if os.path.exists(temp_audio_file):
            try:
                os.remove(temp_audio_file)
                logger.debug(f"Cleaned up temp file: {temp_audio_file}")
            except Exception as e:
                logger.warning(f"Failed to clean up temp file: {e}")

def main():
    """Main test function."""
    import argparse
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Test SER service with microphone or audio file"
    )
    parser.add_argument(
        '--file',
        type=str,
        help='Path to audio file to test (skips microphone capture)'
    )
    parser.add_argument(
        '--url',
        type=str,
        help='SER service URL (overrides SER_SERVICE_URL env var)'
    )
    args = parser.parse_args()
    
    # Use command-line URL if provided, otherwise use env var or default
    service_url = args.url if args.url else SER_SERVICE_URL
    
    logger.info("=" * 60)
    logger.info("Microphone Stream to SER Service Test Script")
    logger.info("=" * 60)
    
    logger.info(f"SER Service URL: {service_url}")
    logger.info(f"SER Endpoint: {SER_ENDPOINT}")
    logger.info(f"Test User ID: {TEST_USER_ID}")
    logger.info(f"Output Directory: {OUTPUT_DIR}")
    logger.info(f"Results File: {RESULTS_FILE}")
    logger.info(f"Debug Log: {LOG_FILE}")
    
    # If file option is provided, test with file instead of microphone
    if args.file:
        logger.info(f"Audio Sample Rate: N/A (using file: {args.file})")
        logger.info(f"Capture Duration: N/A (using file)")
        
        # Test SER service connectivity
        try:
            test_url = f"{service_url}/docs"
            response = requests.get(test_url, timeout=5)
            if response.status_code == 200:
                logger.info("SER service is reachable")
            else:
                logger.warning(f"  SER service responded with status {response.status_code}")
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to SER service at {service_url}")
            logger.error("   Make sure the SER service is running!")
            return False
        
        # Test with file (update function to use service_url)
        result = test_ser_with_file(args.file, service_url)
        return result is not None
    
    # Otherwise, use microphone (requires pyaudio)
    logger.info(f"Audio Sample Rate: {AUDIO_SAMPLE_RATE} Hz")
    logger.info(f"Capture Duration: {CAPTURE_DURATION_SECONDS} seconds")
    
    # Test SER service connectivity
    try:
        test_url = f"{service_url}/docs"  # Try to access FastAPI docs
        response = requests.get(test_url, timeout=5)
        if response.status_code == 200:
            logger.info("SER service is reachable")
        else:
            logger.warning(f"  SER service responded with status {response.status_code}")
    except requests.exceptions.ConnectionError:
        logger.error(f"Cannot connect to SER service at {service_url}")
        logger.error("   Make sure the SER service is running!")
        logger.error("   For local testing: cd Well-Bot_SER && uvicorn app.main:app --reload --port 8008")
        return False
    except Exception as e:
        logger.warning(f"  Could not verify SER service connectivity: {e}")
    
    # Test loop
    logger.info("=" * 60)
    logger.info("Ready for SER testing")
    logger.info("Press Enter to start a test, or type 'quit' to exit")
    logger.info("=" * 60)
    
    try:
        while True:
            try:
                user_input = input("\nPress Enter to test (or 'quit' to exit): ").strip().lower()
                if user_input == 'quit':
                    break
                
                # Run SER test (update function to use service_url)
                result = test_ser_capture(service_url)
                
                if result:
                    logger.info("\nSER analysis completed successfully")
                else:
                    logger.warning("\n  SER analysis failed or returned no result")
                
            except KeyboardInterrupt:
                logger.info("\nInterrupted by user (Ctrl+C)")
                break
            except Exception as e:
                logger.error(f"Error in test loop: {e}", exc_info=True)
        
        return True
        
    except Exception as e:
        logger.error(f"Error during SER test: {e}", exc_info=True)
        return False
    
    finally:
        logger.info("=" * 60)
        logger.info("Test completed")
        logger.info("=" * 60)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

