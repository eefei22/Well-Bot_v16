"""
Intervention Service Client

This module provides a client for communicating with the Well-Bot cloud intervention service.
"""

import os
import requests
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Get cloud service URL from environment variable
CLOUD_SERVICE_URL = os.getenv("CLOUD_SERVICE_URL", "https://user-context-well-bot-520080168829.asia-south1.run.app")


class InterventionServiceClient:
    """
    Client for communicating with the Well-Bot cloud intervention service.
    """
    
    def __init__(self, service_url: Optional[str] = None):
        """
        Initialize the intervention service client.
        
        Args:
            service_url: Optional service URL. If not provided, uses CLOUD_SERVICE_URL from .env
        """
        self.service_url = service_url or CLOUD_SERVICE_URL
        self.suggest_endpoint = f"{self.service_url}/api/intervention/suggest"
        self.health_endpoint = f"{self.service_url}/api/intervention/health"
        self.timeout = 30  # 30 second timeout for requests
        
        logger.info(f"InterventionServiceClient initialized with URL: {self.service_url}")
    
    def get_suggestion(
        self,
        user_id: str,
        context_time_of_day: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Request intervention suggestion from cloud service.
        
        Args:
            user_id: User UUID
            context_time_of_day: Optional time of day context ('morning', 'afternoon', 'evening', 'night')
        
        Returns:
            Dictionary with response data if successful, None if failed.
            Response structure:
            {
                "user_id": str,
                "decision": {
                    "trigger_intervention": bool,
                    "confidence_score": float,
                    "reasoning": str or None
                },
                "suggestion": {
                    "ranked_activities": [
                        {
                            "activity_type": str,
                            "rank": int,
                            "score": float
                        },
                        ...
                    ],
                    "reasoning": str or None
                }
            }
        """
        try:
            # Prepare request payload
            payload = {
                "user_id": user_id
            }
            
            if context_time_of_day:
                payload["context_time_of_day"] = context_time_of_day
            
            logger.info(f"Requesting suggestion from {self.suggest_endpoint}")
            logger.debug(f"Payload: user_id={user_id}")
            
            # Make HTTP request
            response = requests.post(
                self.suggest_endpoint,
                json=payload,
                timeout=self.timeout
            )
            
            # Check response status
            response.raise_for_status()
            
            # Parse JSON response
            result = response.json()
            
            logger.info(f"Successfully received suggestion response")
            logger.debug(f"Decision: trigger={result.get('decision', {}).get('trigger_intervention')}, "
                        f"confidence={result.get('decision', {}).get('confidence_score')}")
            
            return result
            
        except requests.exceptions.Timeout:
            logger.error(f"Request to {self.suggest_endpoint} timed out after {self.timeout}s")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection error to {self.suggest_endpoint}: {e}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error {e.response.status_code} from {self.suggest_endpoint}: {e.response.text}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error to {self.suggest_endpoint}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error requesting suggestion: {e}", exc_info=True)
            return None
    
    def check_health(self) -> bool:
        """
        Check if the intervention service is healthy.
        
        Returns:
            True if service is healthy, False otherwise
        """
        try:
            response = requests.get(self.health_endpoint, timeout=10)
            response.raise_for_status()
            result = response.json()
            is_healthy = result.get("status") == "healthy"
            logger.debug(f"Health check: {result.get('status')}")
            return is_healthy
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

