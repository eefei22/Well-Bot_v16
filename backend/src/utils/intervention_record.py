"""
Intervention Record Manager

This module manages the intervention_record.json file that stores the latest
emotion entry, decision, and suggestion from the cloud service.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class InterventionRecordManager:
    """
    Manages the intervention_record.json file.
    """
    
    def __init__(self, record_file_path: Path):
        """
        Initialize the record manager.
        
        Args:
            record_file_path: Path to the intervention_record.json file
        """
        self.record_file_path = Path(record_file_path)
        self._ensure_record_file_exists()
        logger.info(f"InterventionRecordManager initialized with file: {self.record_file_path}")
    
    def _ensure_record_file_exists(self):
        """Ensure the record file exists with initial structure."""
        if not self.record_file_path.exists():
            initial_record = {
                "latest_emotion_entry": None,
                "latest_decision": None,
                "latest_suggestion": None,
                "last_request_time": None,
                "last_response_time": None,
                "last_database_query_time": None
            }
            self._write_record(initial_record)
            logger.info(f"Created initial intervention_record.json at {self.record_file_path}")
    
    def _read_record(self) -> Dict[str, Any]:
        """Read the record from JSON file."""
        try:
            with open(self.record_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to read record file: {e}")
            return {
                "latest_emotion_entry": None,
                "latest_decision": None,
                "latest_suggestion": None,
                "last_request_time": None,
                "last_response_time": None,
                "last_database_query_time": None
            }
    
    def _write_record(self, record: Dict[str, Any]) -> bool:
        """Write the record to JSON file."""
        try:
            # Ensure parent directory exists
            self.record_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.record_file_path, 'w', encoding='utf-8') as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            logger.error(f"Failed to write record file: {e}")
            return False
    
    def load_record(self) -> Dict[str, Any]:
        """
        Load the current record from JSON file.
        
        Returns:
            Dictionary with current record data
        """
        return self._read_record()
    
    def save_record(self, record: Dict[str, Any]) -> bool:
        """
        Save record to JSON file (overwrites existing).
        
        Args:
            record: Dictionary with record data
        
        Returns:
            True if successful, False otherwise
        """
        return self._write_record(record)
    
    def get_latest_emotion_timestamp(self) -> Optional[datetime]:
        """
        Get the timestamp of the last processed emotion entry.
        
        Returns:
            Datetime object if found, None otherwise
        """
        record = self._read_record()
        emotion_entry = record.get("latest_emotion_entry")
        
        if emotion_entry and emotion_entry.get("timestamp"):
            try:
                # Parse ISO format timestamp
                timestamp_str = emotion_entry["timestamp"]
                # Handle both timezone-aware and naive timestamps
                if 'T' in timestamp_str:
                    if timestamp_str.endswith('Z'):
                        timestamp_str = timestamp_str[:-1] + '+00:00'
                    return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                else:
                    return datetime.fromisoformat(timestamp_str)
            except Exception as e:
                logger.warning(f"Failed to parse timestamp from record: {e}")
                return None
        
        return None
    
    def update_record(
        self,
        emotion_entry: Dict[str, Any],
        decision: Dict[str, Any],
        suggestion: Dict[str, Any],
        request_time: datetime,
        response_time: datetime
    ) -> bool:
        """
        Update the record with new data.
        
        Args:
            emotion_entry: Dictionary with emotion log entry data
            decision: Dictionary with decision result from cloud service
            suggestion: Dictionary with suggestion result from cloud service
            request_time: Timestamp when request was made
            response_time: Timestamp when response was received
        
        Returns:
            True if successful, False otherwise
        """
        # Load existing record to preserve last_database_query_time
        record = self._read_record()
        
        # Update all fields
        record["latest_emotion_entry"] = emotion_entry
        record["latest_decision"] = decision
        record["latest_suggestion"] = suggestion
        record["last_request_time"] = request_time.isoformat()
        record["last_response_time"] = response_time.isoformat()
        # Note: last_database_query_time is preserved from previous update
        
        success = self.save_record(record)
        if success:
            logger.info("Updated intervention_record.json with new data")
        else:
            logger.error("Failed to update intervention_record.json")
        
        return success
    
    def update_emotion_entry_only(
        self,
        emotion_entry: Optional[Dict[str, Any]],
        query_time: datetime
    ) -> bool:
        """
        Update only the latest_emotion_entry and last_database_query_time.
        Preserves existing decision and suggestion data.
        
        Args:
            emotion_entry: Dictionary with emotion log entry data, or None if no entries found
            query_time: Timestamp when database query was performed
        
        Returns:
            True if successful, False otherwise
        """
        # Load existing record to preserve decision and suggestion
        record = self._read_record()
        
        # Update only emotion entry and query time
        record["latest_emotion_entry"] = emotion_entry
        record["last_database_query_time"] = query_time.isoformat()
        
        success = self.save_record(record)
        if success:
            logger.debug("Updated latest_emotion_entry and last_database_query_time in intervention_record.json")
        else:
            logger.error("Failed to update intervention_record.json")
        
        return success

