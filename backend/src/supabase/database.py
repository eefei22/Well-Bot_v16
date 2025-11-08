from typing import Optional, Dict, Any, List
from .client import get_supabase, fetch_user_by_id
import logging
import random
import json
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# If you're running everything locally now, hardcode your dev user_id here:
DEV_USER_ID = "8517c97f-66ef-4955-86ed-531013d33d3e"

sb = get_supabase(service=True)

def get_user_language(user_id: str) -> Optional[str]:
    """
    Fetch user's language preference from database.
    Returns language code ('en', 'cn', 'bm') or None if not found.
    """
    user = fetch_user_by_id(user_id)
    if user and 'language' in user:
        logger.info(f"Found language '{user['language']}' for user {user_id}")
        return user['language']
    logger.warning(f"No language found for user {user_id}")
    return None

def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """Get full user record by ID."""
    return fetch_user_by_id(user_id)

def start_conversation(user_id: str = DEV_USER_ID, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    data = {
        "user_id": user_id
    }
    res = sb.table("wb_conversation").insert(data).execute()
    return res.data[0]["id"]

def end_conversation(conversation_id: str):
    sb.table("wb_conversation").update({"ended_at": "now()"}).eq("id", conversation_id).execute()

def add_message(conversation_id: str, role: str, content: str, *, tokens: Optional[int] = None,
                intent: Optional[str] = None, lang: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> int:
    rec = {
        "conversation_id": conversation_id,
        "role": role,
        "text": content,  # Schema uses 'text' field, not 'content'
        "tokens": tokens,
        "metadata": metadata or {}
    }
    res = sb.table("wb_message").insert(rec).execute()
    return res.data[0]["id"]

def list_conversations(limit: int = 20, user_id: str = DEV_USER_ID) -> List[Dict[str, Any]]:
    res = sb.table("wb_conversation").select("*").eq("user_id", user_id).order("started_at", desc=True).limit(limit).execute()
    return res.data

def list_messages(conversation_id: str, limit: int = 100) -> List[Dict[str, Any]]:
    res = sb.table("wb_message").select("*").eq("conversation_id", conversation_id).order("id", desc=False).limit(limit).execute()
    return res.data

def upsert_journal(user_id: str, title: str, body: str, mood: int,
                   topics: List[str], is_draft: bool) -> Dict[str, Any]:
    """
    Create a new journal entry.
    
    Args:
        user_id: User ID
        title: Journal entry title
        body: Journal entry body text
        mood: Mood score (1-5)
        topics: List of topic strings
        is_draft: Whether the entry is a draft
    
    Returns:
        Dictionary with inserted journal data
    """
    payload = {
        "user_id": user_id,
        "title": title,
        "body": body,
        "mood": mood,
        "topics": topics,
        "is_draft": is_draft,
    }
    res = sb.table("wb_journal").insert(payload).execute()
    return res.data[0]


# ---------- Gratitude helpers ----------

def save_gratitude_item(user_id: str, text: str) -> Dict[str, Any]:
    """
    Save a gratitude item to the database.
    
    Args:
        user_id: User ID
        text: Gratitude note text
    
    Returns:
        Dictionary with inserted gratitude item data
    """
    payload = {
        "user_id": user_id,
        "text": text,
    }
    res = sb.table("wb_gratitude_item").insert(payload).execute()
    return res.data[0]


# ---------- Spiritual Quote helpers ----------

def _normalize_religion(value: Optional[str]) -> str:
    """Map free-form beliefs to wb_quote categories."""
    if not value:
        return "general"
    v = value.strip().lower()
    if "budd" in v:
        return "buddhist"
    if "christ" in v:
        return "christian"
    if "islam" in v or "muslim" in v:
        return "islamic"
    if "hind" in v:
        return "hindu"
    return "general"


def get_user_religion(user_id: str) -> Optional[str]:
    """
    Resolve the user's religion for quote filtering.
    Priority: wb_preferences.religion → users.spiritual_beliefs → "general".
    Returns a normalized category used by wb_quote.category.
    """
    try:
        pref = sb.table("wb_preferences").select("religion").eq("user_id", user_id).limit(1).execute()
        if pref.data and pref.data[0].get("religion"):
            return _normalize_religion(pref.data[0]["religion"])
    except Exception as e:
        logger.warning(f"Failed to fetch wb_preferences for {user_id}: {e}")

    try:
        user_resp = sb.table("users").select("spiritual_beliefs").eq("id", user_id).limit(1).execute()
        if user_resp.data and user_resp.data[0].get("spiritual_beliefs"):
            return _normalize_religion(user_resp.data[0]["spiritual_beliefs"])
    except Exception as e:
        logger.warning(f"Failed to fetch users.spiritual_beliefs for {user_id}: {e}")

    return "general"


def fetch_next_quote(user_id: str, religion: Optional[str] = None, language: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Fetch a single unseen quote for the user.
    - Filters by category in (religion, 'general').
    - Excludes quotes already seen by the user.
    - Randomizes client-side among a small candidate set.
    Returns {id, category, text} or None.
    """
    try:
        # Gather seen ids
        seen_resp = sb.table("wb_quote_seen").select("quote_id").eq("user_id", user_id).execute()
        seen_ids = {row["quote_id"] for row in (seen_resp.data or [])}

        category = religion or get_user_religion(user_id) or "general"
        lang = language or get_user_language(user_id) or "en"
        categories = [category, "general"] if category != "general" else ["general"]

        # Pull a reasonable pool from DB and then filter locally
        q = (
            sb.table("wb_quote")
            .select("id, category, language, text")
            .in_("category", categories)
            .eq("language", lang)
            .limit(50)
        )
        pool_resp = q.execute()
        pool = [row for row in (pool_resp.data or []) if row["id"] not in seen_ids]

        if not pool:
            logger.info("No unseen quotes available; resetting seen list fallback")
            # Fallback: allow repeats if absolutely necessary
            pool = pool_resp.data or []
            if not pool:
                return None

        return random.choice(pool)
    except Exception as e:
        logger.error(f"Failed to fetch next quote: {e}")
        return None


def mark_quote_seen(user_id: str, quote_id: str) -> bool:
    """Record that the user has been served this quote."""
    try:
        sb.table("wb_quote_seen").insert({"user_id": user_id, "quote_id": quote_id}).execute()
        return True
    except Exception as e:
        logger.warning(f"Failed to mark quote {quote_id} seen for {user_id}: {e}")
        return False


# ---------- User Context Bundle helpers ----------

def get_user_persona_summary(user_id: str) -> Optional[str]:
    """
    Fetch user's persona summary from user_context_bundle table.
    
    Args:
        user_id: User UUID
        
    Returns:
        Persona summary text or None if not found
    """
    try:
        response = sb.table("user_context_bundle")\
            .select("persona_summary")\
            .eq("user_id", user_id)\
            .limit(1)\
            .execute()
        
        if response.data and len(response.data) > 0:
            persona_summary = response.data[0].get("persona_summary")
            if persona_summary:
                logger.info(f"Found persona summary for user {user_id}")
                return persona_summary
            else:
                logger.info(f"No persona summary found for user {user_id} (field is null/empty)")
                return None
        else:
            logger.info(f"No context bundle found for user {user_id}")
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch persona summary for user {user_id}: {e}")
        return None


# ---------- Activity Logging helpers ----------

def log_activity_start(
    user_id: str,
    activity_type: str,
    trigger_type: str,
    context_time_of_day: Optional[str] = None
) -> Optional[str]:
    """
    Log the start of an activity.
    
    Args:
        user_id: User ID
        activity_type: Type of activity ('journal', 'gratitude', 'todo', 'meditation', 'quote')
        trigger_type: How activity was triggered ('direct_command', 'suggestion_flow')
        context_time_of_day: Time of day context. If None, will be auto-derived from current time.
    
    Returns:
        Log ID (UUID string) if successful, None if failed.
        Non-blocking: errors are logged but don't raise exceptions.
    """
    try:
        # Import activity_logger for time-of-day derivation
        from src.components.activity_logger import get_context_time_of_day
        
        # Auto-derive time of day if not provided
        if context_time_of_day is None:
            context_time_of_day = get_context_time_of_day()
        
        # Validate enum values match schema constraints
        valid_activity_types = ['journal', 'gratitude', 'todo', 'meditation', 'quote']
        valid_trigger_types = ['direct_command', 'suggestion_flow']
        valid_time_of_day = ['morning', 'afternoon', 'evening', 'night']
        
        if activity_type not in valid_activity_types:
            logger.error(f"Invalid activity_type: {activity_type}. Must be one of {valid_activity_types}")
            return None
        
        if trigger_type not in valid_trigger_types:
            logger.error(f"Invalid trigger_type: {trigger_type}. Must be one of {valid_trigger_types}")
            return None
        
        if context_time_of_day not in valid_time_of_day:
            logger.error(f"Invalid context_time_of_day: {context_time_of_day}. Must be one of {valid_time_of_day}")
            return None
        
        payload = {
            "user_id": user_id,
            "type": activity_type,
            "trigger_type": trigger_type,
            "context_time_of_day": context_time_of_day,
            "completed": False  # Default to False, will be updated on completion
        }
        
        res = sb.table("wb_activity_logs").insert(payload).execute()
        log_id = res.data[0]["id"]
        logger.info(f"Activity log started: {log_id} for user {user_id}, activity={activity_type}, trigger={trigger_type}")
        return log_id
        
    except Exception as e:
        logger.error(f"Failed to log activity start: {e}", exc_info=True)
        return None


def log_activity_completion(log_id: str, completed: bool) -> bool:
    """
    Update activity log with completion status.
    
    Args:
        log_id: Log ID (UUID string) from log_activity_start()
        completed: True if activity completed successfully, False if skipped/terminated
    
    Returns:
        True if successful, False if failed.
        Non-blocking: errors are logged but don't raise exceptions.
    """
    try:
        if not log_id:
            logger.warning("log_activity_completion called with empty log_id")
            return False
        
        update_data = {
            "completed": completed
        }
        
        res = sb.table("wb_activity_logs").update(update_data).eq("id", log_id).execute()
        
        if res.data:
            logger.info(f"Activity log updated: {log_id}, completed={completed}")
            return True
        else:
            logger.warning(f"No log record found to update: {log_id}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to log activity completion: {e}", exc_info=True)
        return False


def query_recent_activity_logs(
    user_id: str,
    activity_type: Optional[str] = None,
    trigger_type: Optional[str] = None,
    completed: Optional[bool] = None,
    limit: int = 100,
    days_back: int = 30
) -> List[Dict[str, Any]]:
    """
    Query recent activity logs with filtering options.
    
    Args:
        user_id: User ID to filter logs
        activity_type: Optional filter by activity type ('journal', 'gratitude', 'todo', 'meditation', 'quote')
        trigger_type: Optional filter by trigger type ('direct_command', 'suggestion_flow')
        completed: Optional filter by completion status (True/False)
        limit: Maximum number of records to return
        days_back: Number of days to look back from current time
    
    Returns:
        List of log record dictionaries, ordered by created_at descending.
        Returns empty list if query fails.
    """
    try:
        # Calculate cutoff timestamp
        cutoff_time = datetime.now() - timedelta(days=days_back)
        
        # Build query
        query = (
            sb.table("wb_activity_logs")
            .select("*")
            .eq("user_id", user_id)
            .gte("created_at", cutoff_time.isoformat())
        )
        
        # Apply optional filters
        if activity_type:
            query = query.eq("type", activity_type)
        
        if trigger_type:
            query = query.eq("trigger_type", trigger_type)
        
        if completed is not None:
            query = query.eq("completed", completed)
        
        # Order by created_at descending and limit
        query = query.order("created_at", desc=True).limit(limit)
        
        res = query.execute()
        
        logger.debug(f"Query returned {len(res.data) if res.data else 0} activity logs for user {user_id}")
        return res.data if res.data else []
        
    except Exception as e:
        logger.error(f"Failed to query activity logs: {e}", exc_info=True)
        return []