"""
Emotion Service Clients

This module provides HTTP clients for communicating with SER and FER services.
"""

import os
import requests
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


class SERServiceClient:
    """
    Client for communicating with the Speech Emotion Recognition (SER) service.
    """
    
    def __init__(self, service_url: Optional[str] = None):
        """
        Initialize the SER service client.
        
        Args:
            service_url: Optional service URL. If not provided, uses SER_SERVICE_URL from .env
        """
        self.service_url = service_url or os.getenv("SER_SERVICE_URL", "https://well-bot-emotionrecognition-520080168829.asia-south1.run.app")
        self.analyze_endpoint = f"{self.service_url}/ser/analyze-speech"
        self.timeout = 30  # 30 second timeout for requests
        
        logger.info(f"SERServiceClient initialized with URL: {self.service_url}")
    
    def send_audio(self, audio_file_path: Path, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Send audio file to SER service for analysis.
        
        Args:
            audio_file_path: Path to WAV audio file
            user_id: UUID of the user
        
        Returns:
            Dictionary with analysis results if successful, None if failed
        """
        try:
            if not audio_file_path.exists():
                logger.error(f"Audio file not found: {audio_file_path}")
                return None
            
            logger.info(f"Sending audio to SER service: {self.analyze_endpoint}")
            logger.debug(f"User ID: {user_id}, File: {audio_file_path}")
            
            with open(audio_file_path, 'rb') as audio_file:
                files = {'file': (audio_file_path.name, audio_file, 'audio/wav')}
                data = {'user_id': user_id}
                response = requests.post(
                    self.analyze_endpoint,
                    files=files,
                    data=data,
                    timeout=self.timeout
                )
            
            response.raise_for_status()
            result = response.json()
            
            logger.info("Successfully sent audio to SER service")
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"Request to {self.analyze_endpoint} timed out after {self.timeout}s")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to {self.analyze_endpoint}: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} from {self.analyze_endpoint}: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Error sending audio to SER service: {e}", exc_info=True)
            return None


class FERServiceClient:
    """
    Client for communicating with the Face Emotion Recognition (FER) service.
    
    Note: This is a placeholder implementation. The actual FER service exists remotely
    and will be integrated when service details are available.
    """
    
    def __init__(self, service_url: Optional[str] = None):
        """
        Initialize the FER service client.
        
        Args:
            service_url: Optional service URL. If not provided, uses FER_SERVICE_URL from .env or placeholder
        """
        self.service_url = service_url or os.getenv("FER_SERVICE_URL", "https://wellbot-fer-backend-520080168829.asia-southeast1.run.app")
        self.analyze_endpoint = f"{self.service_url}/emotion" if self.service_url else None
        self.timeout = 30  # 30 second timeout for requests
        
        if self.service_url and self.service_url != "https://wellbot-fer-backend-520080168829.asia-southeast1.run.app":
            logger.info(f"FERServiceClient initialized with URL: {self.service_url}")
        else:
            logger.info("FERServiceClient initialized in placeholder mode (no service URL configured)")
    
    def send_image(self, image_file_path: Path, user_id: str) -> bool:
        """
        Send image file to FER service for analysis.
        
        This is a placeholder implementation. When FER service URL is configured,
        it will send actual requests. For now, it logs and returns success to not block the flow.
        
        Args:
            image_file_path: Path to image file
            user_id: UUID of the user
        
        Returns:
            True if successful (or placeholder), False if failed
        """
        if not self.service_url or self.service_url == "https://wellbot-fer-backend-520080168829.asia-southeast1.run.app" or not self.analyze_endpoint:
            logger.debug("FER service URL not configured - placeholder mode (returning success)")
            return True
        
        try:
            if not image_file_path.exists():
                logger.error(f"Image file not found: {image_file_path}")
                return False
            
            logger.info(f"Sending image to FER service: {self.analyze_endpoint}")
            logger.debug(f"User ID: {user_id}, File: {image_file_path}")
            
            with open(image_file_path, 'rb') as image_file:
                files = {'file': (image_file_path.name, image_file, 'image/jpeg')}
                data = {'user_id': user_id}
                response = requests.post(
                    self.analyze_endpoint,
                    files=files,
                    data=data,
                    timeout=self.timeout
                )
            
            response.raise_for_status()
            logger.info("Successfully sent image to FER service")
            return True
            
        except requests.exceptions.Timeout:
            logger.warning(f"Request to {self.analyze_endpoint} timed out after {self.timeout}s")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error to {self.analyze_endpoint}: {e}")
            return False
        except requests.exceptions.HTTPError as e:
            logger.warning(f"HTTP error {e.response.status_code} from {self.analyze_endpoint}: {e.response.text}")
            return False
        except Exception as e:
            logger.warning(f"Error sending image to FER service: {e}", exc_info=True)
            return False
