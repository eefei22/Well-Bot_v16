"""
Journal Title Service Client

This module provides a client for communicating with the Well-Bot cloud journal title generation service.
"""

import os
import requests
import logging
from typing import Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Get cloud service URL from environment variable
CLOUD_SERVICE_URL = os.getenv("CLOUD_SERVICE_URL", "https://user-context-well-bot-520080168829.asia-south1.run.app")


class JournalTitleClient:
    """
    Client for communicating with the Well-Bot cloud journal title generation service.
    """
    
    def __init__(self, service_url: Optional[str] = None):
        """
        Initialize the journal title service client.
        
        Args:
            service_url: Optional service URL. If not provided, uses CLOUD_SERVICE_URL from .env
        """
        self.service_url = service_url or CLOUD_SERVICE_URL
        self.generate_title_endpoint = f"{self.service_url}/api/journal/generate-title"
        self.timeout = 30  # 30 second timeout for requests
        
        logger.info(f"JournalTitleClient initialized with URL: {self.service_url}")
    
    def generate_title(self, body: str, retry: bool = True) -> Optional[str]:
        """
        Request title generation from cloud service.
        
        Args:
            body: Journal entry body text
            retry: Whether to retry once on failure (default: True)
        
        Returns:
            Generated title string if successful, None if failed.
        """
        # First attempt
        result = self._make_request(body)
        if result is not None:
            return result
        
        # Retry once if enabled and first attempt failed
        if retry:
            logger.info("Retrying title generation request...")
            result = self._make_request(body)
            if result is not None:
                return result
        
        logger.warning("Title generation failed after retry, returning None for fallback")
        return None
    
    def _make_request(self, body: str) -> Optional[str]:
        """
        Make a single request to the title generation endpoint.
        
        Args:
            body: Journal entry body text
        
        Returns:
            Generated title string if successful, None if failed
        """
        try:
            # Prepare request payload
            payload = {
                "body": body
            }
            
            logger.info(f"Requesting title generation from {self.generate_title_endpoint}")
            logger.debug(f"Body length: {len(body)} chars")
            
            # Make HTTP request
            response = requests.post(
                self.generate_title_endpoint,
                json=payload,
                timeout=self.timeout
            )
            
            # Check response status
            response.raise_for_status()
            
            # Parse JSON response
            result = response.json()
            title = result.get("title")
            
            if not title:
                logger.error("Response missing 'title' field")
                return None
            
            logger.info(f"Successfully received title: '{title}'")
            return title
            
        except requests.exceptions.Timeout:
            logger.error(f"Request to {self.generate_title_endpoint} timed out after {self.timeout}s")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to {self.generate_title_endpoint}: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} from {self.generate_title_endpoint}: {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error to {self.generate_title_endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error requesting title generation: {e}", exc_info=True)
            return None

