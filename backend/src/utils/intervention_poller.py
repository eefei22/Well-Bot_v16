"""
Intervention Polling Service

This module provides a polling service that periodically checks for new emotion log entries
and requests intervention suggestions from the cloud service.
"""

import logging
import threading
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path

from src.supabase.database import query_emotional_logs_since
from src.utils.intervention_client import InterventionServiceClient
from src.utils.intervention_record import InterventionRecordManager

logger = logging.getLogger(__name__)


class InterventionPoller:
    """
    Polling service that checks for new emotion log entries and requests intervention suggestions.
    """
    
    def __init__(
        self,
        user_id: str,
        record_file_path: Path,
        poll_interval_minutes: int = 15,
        service_url: Optional[str] = None
    ):
        """
        Initialize the intervention poller.
        
        Args:
            user_id: User UUID
            record_file_path: Path to intervention_record.json file
            poll_interval_minutes: Interval between polls in minutes (default: 15)
            service_url: Optional cloud service URL (uses CLOUD_SERVICE_URL from .env if not provided)
        """
        self.user_id = user_id
        self.poll_interval_minutes = poll_interval_minutes
        self.poll_interval_seconds = poll_interval_minutes * 60
        
        # Initialize components
        self.record_manager = InterventionRecordManager(record_file_path)
        self.service_client = InterventionServiceClient(service_url=service_url)
        
        # Polling state
        self._running = False
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        
        logger.info(f"InterventionPoller initialized for user {user_id}, poll interval: {poll_interval_minutes} minutes")
    
    def start(self):
        """Start the polling service."""
        with self._lock:
            if self._running:
                logger.warning("Poller is already running")
                return
            
            self._running = True
            logger.info("Starting intervention poller...")
            
            # Run initial check immediately
            self._check_for_new_emotions()
            
            # Schedule periodic checks
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
        
        self._timer = threading.Timer(self.poll_interval_seconds, self._check_for_new_emotions)
        self._timer.daemon = True
        self._timer.start()
        logger.debug(f"Next poll scheduled in {self.poll_interval_minutes} minutes")
    
    def _check_for_new_emotions(self):
        """
        Check for new emotion log entries and process them.
        This method is called periodically and on startup.
        
        Always updates latest_emotion_entry with the latest entry from database.
        Only calls cloud service if there's a new entry (timestamp > last processed).
        """
        if not self._running:
            return
        
        query_time = datetime.now()
        
        try:
            logger.debug("Checking for new emotion log entries...")
            
            # Get current record BEFORE querying to compare timestamps
            record = self.record_manager.load_record()
            last_processed_entry = record.get("latest_emotion_entry")
            last_processed_timestamp = None
            
            if last_processed_entry and last_processed_entry.get("timestamp"):
                try:
                    timestamp_str = last_processed_entry["timestamp"]
                    last_processed_timestamp = datetime.fromisoformat(timestamp_str.replace('Z', ''))
                except Exception as e:
                    logger.warning(f"Failed to parse last processed timestamp: {e}")
            
            # Always query for the latest entry in the last 24 hours to get current latest
            cutoff_time = datetime.now() - timedelta(hours=24)
            all_recent_entries = query_emotional_logs_since(self.user_id, cutoff_time)
            
            # Get the latest entry (last in list since ordered ascending)
            latest_entry = all_recent_entries[-1] if all_recent_entries else None
            
            # Always update latest_emotion_entry and last_database_query_time
            self.record_manager.update_emotion_entry_only(latest_entry, query_time)
            
            if latest_entry:
                logger.info(f"Updated latest_emotion_entry: {latest_entry.get('emotion_label')} "
                           f"(confidence: {latest_entry.get('confidence_score'):.2f})")
            else:
                logger.info("No emotion entries found in last 24 hours")
            
            # Now check if we need to call cloud service (only if there's a NEW entry)
            # Compare latest entry timestamp with what we had before updating
            if latest_entry:
                latest_entry_timestamp_str = latest_entry.get("timestamp")
                if latest_entry_timestamp_str:
                    try:
                        latest_entry_timestamp = datetime.fromisoformat(latest_entry_timestamp_str.replace('Z', ''))
                        
                        # Only process if this is a new entry (timestamp > last processed)
                        # If last_processed_timestamp is None, it means we never processed anything, so process it
                        if last_processed_timestamp is None or latest_entry_timestamp > last_processed_timestamp:
                            logger.info(f"Found new emotion entry, processing...")
                            self._process_new_emotion_entry(latest_entry)
                        else:
                            logger.debug("Latest entry is not new, skipping cloud service call")
                    except Exception as e:
                        logger.warning(f"Failed to parse latest entry timestamp: {e}")
            else:
                logger.debug("No latest entry to process")
            
        except Exception as e:
            logger.error(f"Error checking for new emotions: {e}", exc_info=True)
        finally:
            # Schedule next check
            if self._running:
                self._schedule_next_check()
    
    def _process_new_emotion_entry(self, entry: Dict[str, Any]):
        """
        Process a new emotion log entry by requesting suggestion from cloud service.
        
        Args:
            entry: Dictionary with emotion log entry data
        """
        try:
            emotion_label = entry.get("emotion_label")
            confidence_score = entry.get("confidence_score")
            timestamp_str = entry.get("timestamp")
            
            if not emotion_label or confidence_score is None or not timestamp_str:
                logger.error(f"Invalid emotion entry: missing required fields")
                return
            
            # Parse timestamp
            try:
                # Handle timezone-naive timestamps
                timestamp = datetime.fromisoformat(timestamp_str.replace('Z', ''))
            except Exception as e:
                logger.error(f"Failed to parse timestamp from entry: {e}")
                return
            
            logger.info(f"Processing new emotion entry: {emotion_label} (confidence: {confidence_score:.2f}) at {timestamp}")
            
            # Record request time
            request_time = datetime.now()
            
            # Request suggestion from cloud service
            response = self.service_client.get_suggestion(
                user_id=self.user_id,
                emotion_label=emotion_label,
                confidence_score=confidence_score,
                timestamp=timestamp
            )
            
            # Record response time
            response_time = datetime.now()
            
            if response:
                # Extract decision and suggestion from response
                decision = response.get("decision", {})
                suggestion = response.get("suggestion", {})
                
                # Update record
                self.record_manager.update_record(
                    emotion_entry=entry,
                    decision=decision,
                    suggestion=suggestion,
                    request_time=request_time,
                    response_time=response_time
                )
                
                logger.info(f"Successfully processed emotion entry and updated record")
                logger.debug(f"Decision: trigger={decision.get('trigger_intervention')}, "
                            f"confidence={decision.get('confidence_score')}")
            else:
                logger.error("Failed to get suggestion from cloud service")
                
        except Exception as e:
            logger.error(f"Error processing emotion entry: {e}", exc_info=True)

