"""
Intervention Polling Service

This module provides a polling service that periodically requests intervention suggestions
from the cloud service. The cloud service handles all database queries and processing.
"""

import logging
import threading
from typing import Optional, Dict, Any, Callable
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.utils.intervention_client import InterventionServiceClient
from src.utils.intervention_record import InterventionRecordManager

logger = logging.getLogger(__name__)


def get_malaysia_timezone():
    """
    Get Malaysia timezone (UTC+8) object.
    Tries zoneinfo first, falls back to pytz, then manual offset.
    
    Returns:
        Timezone object for Asia/Kuala_Lumpur (UTC+8)
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Kuala_Lumpur")
    except (ImportError, Exception):
        # ZoneInfoNotFoundError, ImportError, or other issues - fall back to pytz
        try:
            import pytz
            return pytz.timezone("Asia/Kuala_Lumpur")
        except ImportError:
            # Final fallback: manual UTC+8 offset
            return timezone(timedelta(hours=8))


def get_current_time_utc8() -> datetime:
    """
    Get current time in UTC+8 (Malaysia timezone).
    
    Returns:
        Datetime object with UTC+8 timezone
    """
    malaysia_tz = get_malaysia_timezone()
    return datetime.now(malaysia_tz)


class InterventionPoller:
    """
    Polling service that periodically queries latest emotion and requests intervention suggestions.
    """
    
    def __init__(
        self,
        user_id: str,
        record_file_path: Path,
        poll_interval_minutes: int = 15,
        service_url: Optional[str] = None,
        on_intervention_triggered: Optional[Callable[[], None]] = None
    ):
        """
        Initialize the intervention poller.
        
        Args:
            user_id: User UUID
            record_file_path: Path to intervention_record.json file
            poll_interval_minutes: Interval between polls in minutes (default: 15)
            service_url: Optional cloud service URL (uses CLOUD_SERVICE_URL from .env if not provided)
            on_intervention_triggered: Optional callback function called when trigger_intervention = true
        """
        self.user_id = user_id
        self.poll_interval_minutes = poll_interval_minutes
        self.poll_interval_seconds = poll_interval_minutes * 60
        
        # Initialize components
        self.record_manager = InterventionRecordManager(record_file_path)
        self.service_client = InterventionServiceClient(service_url=service_url)
        
        # Callback for intervention trigger
        self.on_intervention_triggered = on_intervention_triggered
        
        # Polling state
        self._running = False
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        
        # Latest decision stored in memory
        self._latest_decision: Optional[Dict[str, Any]] = None
        
        logger.info(f"InterventionPoller initialized for user {user_id}, poll interval: {poll_interval_minutes} minutes")
    
    def start(self):
        """Start the polling service."""
        with self._lock:
            if self._running:
                logger.warning("Poller is already running")
                return
            
            self._running = True
            logger.info("Starting intervention poller...")
            
            # Schedule first poll (no immediate poll)
            self._schedule_next_check()
    
    def stop(self):
        """Stop the polling service."""
        with self._lock:
            if not self._running:
                logger.warning("Poller is not running")
                return
            
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
            
            logger.info("Intervention poller stopped")
    
    def _schedule_next_check(self):
        """Schedule the next polling check."""
        if not self._running:
            return
        
        self._timer = threading.Timer(self.poll_interval_seconds, self._poll_cloud_service)
        self._timer.daemon = True
        self._timer.start()
        logger.debug(f"Next poll scheduled in {self.poll_interval_minutes} minutes")
    
    def _poll_cloud_service(self):
        """
        Poll cloud service for intervention suggestion.
        Cloud service will fetch latest emotion from database and process it.
        """
        if not self._running:
            return
        
        try:
            logger.debug("Polling cloud service for intervention suggestion...")
            
            # Record request time (UTC+8)
            request_time = get_current_time_utc8()
            
            # Request suggestion from cloud service (only user_id needed)
            response = self.service_client.get_suggestion(
                user_id=self.user_id
            )
            
            # Record response time (UTC+8)
            response_time = get_current_time_utc8()
            
            if response:
                # Extract decision and suggestion from response
                decision = response.get("decision", {})
                suggestion = response.get("suggestion", {})
                
                # Store latest decision in memory
                self._latest_decision = decision
                
                # Update record (no emotion_entry needed)
                self.record_manager.update_record(
                    decision=decision,
                    suggestion=suggestion,
                    request_time=request_time,
                    response_time=response_time
                )
                
                logger.info(f"Successfully polled cloud service and updated record")
                logger.debug(f"Decision: trigger={decision.get('trigger_intervention')}, "
                            f"confidence={decision.get('confidence_score')}")
                
                # Check if intervention should be triggered
                trigger_intervention = decision.get("trigger_intervention", False)
                if trigger_intervention and self.on_intervention_triggered:
                    logger.info("Intervention trigger detected, calling callback...")
                    try:
                        self.on_intervention_triggered()
                    except Exception as e:
                        logger.error(f"Error in intervention trigger callback: {e}", exc_info=True)
            else:
                logger.error("Failed to get suggestion from cloud service")
                
        except Exception as e:
            logger.error(f"Error polling cloud service: {e}", exc_info=True)
        finally:
            # Schedule next check
            if self._running:
                self._schedule_next_check()
    
    def get_latest_decision(self) -> Optional[Dict[str, Any]]:
        """
        Get the latest intervention decision.
        
        Returns:
            Dictionary with decision data (trigger_intervention, confidence_score, reasoning) or None
        """
        return self._latest_decision
