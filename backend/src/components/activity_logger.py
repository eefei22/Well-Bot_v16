#!/usr/bin/env python3
"""
Activity Logger Component

Provides functional/logic for activity logging:
- Time-of-day context derivation
- Query logic for activity logs

Database access is handled by supabase/database.py functions.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Malaysian timezone (UTC+8)
try:
    from zoneinfo import ZoneInfo
    MALAYSIA_TZ = ZoneInfo("Asia/Kuala_Lumpur")
except ImportError:
    # Fallback for Python < 3.9
    try:
        import pytz
        MALAYSIA_TZ = pytz.timezone("Asia/Kuala_Lumpur")
    except ImportError:
        logger.warning("Neither zoneinfo nor pytz available. Using UTC+8 offset manually.")
        from datetime import timezone, timedelta
        MALAYSIA_TZ = timezone(timedelta(hours=8))


def get_context_time_of_day(timestamp: Optional[datetime] = None) -> str:
    """
    Derive time of day context from timestamp using Malaysian timezone (UTC+8).
    
    Time periods:
    - morning: 5:00 - 11:59
    - afternoon: 12:00 - 16:59
    - evening: 17:00 - 20:59
    - night: 21:00 - 4:59
    
    Args:
        timestamp: Datetime object. If None, uses current time in Malaysian timezone.
                   If provided, assumes it's in UTC and converts to Malaysian time.
    
    Returns:
        One of: 'morning', 'afternoon', 'evening', 'night'
    """
    if timestamp is None:
        # Get current time in Malaysian timezone
        timestamp = datetime.now(MALAYSIA_TZ)
    else:
        # Assume timestamp is UTC, convert to Malaysian time
        if timestamp.tzinfo is None:
            # Naive datetime - assume UTC
            from datetime import timezone as tz
            timestamp = timestamp.replace(tzinfo=tz.utc)
        
        # Convert to Malaysian timezone
        timestamp = timestamp.astimezone(MALAYSIA_TZ)
    
    hour = timestamp.hour
    
    if 5 <= hour < 12:
        return 'morning'
    elif 12 <= hour < 17:
        return 'afternoon'
    elif 17 <= hour < 21:
        return 'evening'
    else:  # 21 <= hour < 5
        return 'night'


def query_activity_logs(
    user_id: str,
    activity_type: Optional[str] = None,
    trigger_type: Optional[str] = None,
    completed: Optional[bool] = None,
    limit: int = 100,
    days_back: int = 30
) -> List[Dict[str, Any]]:
    """
    Query activity logs with filtering options.
    
    This function provides the query logic. Actual database access
    should be performed by calling supabase/database.py functions.
    
    Args:
        user_id: User ID to filter logs
        activity_type: Optional filter by activity type ('journal', 'gratitude', 'todo', 'meditation', 'quote')
        trigger_type: Optional filter by trigger type ('direct_command', 'suggestion_flow')
        completed: Optional filter by completion status (True/False)
        limit: Maximum number of records to return
        days_back: Number of days to look back from current time
    
    Returns:
        List of log record dictionaries (empty list if query fails)
    
    Note:
        This function should be called by database.py query functions
        that perform the actual database access.
    """
    # This function provides query logic/parameters
    # The actual database query should be implemented in database.py
    # This is a placeholder that returns empty list
    # The real implementation will be in database.py's query_recent_activity_logs()
    logger.debug(f"Query activity logs called with: user_id={user_id}, activity_type={activity_type}, "
                 f"trigger_type={trigger_type}, completed={completed}, limit={limit}, days_back={days_back}")
    return []

