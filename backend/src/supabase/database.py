from typing import Optional, Dict, Any, List
from .client import get_supabase, fetch_user_by_id
from .auth import get_current_user_id
import logging
import random
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Malaysian timezone (UTC+8) - for consistent timestamp handling
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


def get_current_time_utc8_naive() -> datetime:
    """
    Get current time in UTC+8 (Malaysia timezone) as timezone-naive.
    This is used for database timestamps which are stored as timezone-naive in UTC+8.
    
    Returns:
        Datetime object without timezone info (but represents UTC+8 time)
    """
    malaysia_tz = get_malaysia_timezone()
    now_utc8 = datetime.now(malaysia_tz)
    # Convert to naive datetime (removes timezone but keeps the UTC+8 time)
    return now_utc8.replace(tzinfo=None)

# If you're running everything locally now, hardcode your dev user_id here:
# NOTE: This constant is deprecated. Use get_current_user_id() instead.
# DEV_USER_ID = "8517c97f-66ef-4955-86ed-531013d33d3e"

sb = get_supabase(service=True)

# ---------- User helper functions ----------

def normalize_gender(gender: str) -> str:
    """
    Normalize gender value to match new schema constraints.
    
    Args:
        gender: Gender string (case-insensitive, can be 'male', 'female', 'other')
    
    Returns:
        Normalized gender: 'Male' or 'Female'
        Defaults to 'Male' for 'other' or invalid values (with warning)
    """
    if not gender:
        logger.warning("Empty gender value provided, defaulting to 'Male'")
        return 'Male'
    
    gender_lower = gender.strip().lower()
    
    if gender_lower == 'male':
        return 'Male'
    elif gender_lower == 'female':
        return 'Female'
    elif gender_lower == 'other':
        logger.warning(f"Gender 'other' mapped to 'Male' (schema constraint)")
        return 'Male'
    else:
        logger.warning(f"Invalid gender value '{gender}', defaulting to 'Male'")
        return 'Male'


def get_user_display_name(user_id: str) -> Optional[str]:
    """
    Get user's display name: prefer_name if set, otherwise full_name.
    
    Args:
        user_id: User UUID
    
    Returns:
        Display name string or None if user not found
    """
    try:
        user = fetch_user_by_id(user_id)
        if not user:
            return None
        
        # Prefer prefer_name, fallback to full_name
        display_name = user.get('prefer_name') or user.get('full_name')
        return display_name
    except Exception as e:
        logger.error(f"Failed to get display name for user {user_id}: {e}")
        return None


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

def start_conversation(user_id: Optional[str] = None, title: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Start a new conversation.
    
    Args:
        user_id: User ID. If None, will use get_current_user_id() to read from environment variable.
        title: Optional conversation title
        metadata: Optional metadata dictionary
        
    Returns:
        Conversation ID
    """
    if user_id is None:
        user_id = get_current_user_id()
        logger.info(f"Using user_id from environment: {user_id}")
    
    data = {
        "user_id": user_id
    }
    res = sb.table("wb_conversation").insert(data).execute()
    logger.info(f"Started conversation {res.data[0]['id']} for user {user_id}")
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

def list_conversations(limit: int = 20, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    List conversations for a user.
    
    Args:
        limit: Maximum number of conversations to return
        user_id: User ID. If None, will use get_current_user_id() to read from environment variable.
        
    Returns:
        List of conversation dictionaries
    """
    if user_id is None:
        user_id = get_current_user_id()
        logger.info(f"Using user_id from environment: {user_id}")
    
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

def get_user_context_bundle(user_id: str) -> Optional[Dict[str, str]]:
    """
    Fetch user's context bundle (persona_summary and facts) from users_context_bundle table.
    
    Args:
        user_id: User UUID
        
    Returns:
        Dictionary with 'persona_summary' and 'facts' keys, or None if not found
    """
    try:
        response = sb.table("users_context_bundle")\
            .select("persona_summary, facts")\
            .eq("user_id", user_id)\
            .limit(1)\
            .execute()
        
        if response.data and len(response.data) > 0:
            data = response.data[0]
            persona_summary = data.get("persona_summary")
            facts = data.get("facts")
            
            # Return dict even if fields are None/empty
            result = {
                "persona_summary": persona_summary if persona_summary else None,
                "facts": facts if facts else None
            }
            
            if persona_summary or facts:
                logger.info(f"Found context bundle for user {user_id} (persona_summary: {bool(persona_summary)}, facts: {bool(facts)})")
                return result
            else:
                logger.info(f"Context bundle found for user {user_id} but both fields are null/empty")
                return None
        else:
            logger.info(f"No context bundle found for user {user_id}")
            return None
    except Exception as e:
        logger.warning(f"Failed to fetch context bundle for user {user_id}: {e}")
        return None


def get_user_persona_summary(user_id: str) -> Optional[str]:
    """
    Fetch user's persona summary from users_context_bundle table.
    Legacy function for backward compatibility.
    
    Args:
        user_id: User UUID
        
    Returns:
        Persona summary text or None if not found
    """
    bundle = get_user_context_bundle(user_id)
    if bundle:
        return bundle.get("persona_summary")
    return None


def save_user_context_to_local(user_id: str, persona_summary: Optional[str] = None, facts: Optional[str] = None, backend_dir: Optional[Path] = None) -> bool:
    """
    Save user context (persona_summary and facts) to local JSON file as fallback.
    
    Args:
        user_id: User UUID
        persona_summary: Persona summary text (optional)
        facts: Facts text (optional)
        backend_dir: Backend directory path (optional, will be inferred if not provided)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if backend_dir is None:
            # Infer backend directory from current file location
            backend_dir = Path(__file__).parent.parent.parent
        
        config_dir = backend_dir / "config"
        config_dir.mkdir(exist_ok=True)
        
        file_path = config_dir / "user_persona.json"
        
        data = {
            "user_id": user_id,
            "persona_summary": persona_summary,
            "facts": facts,
            "last_updated": get_current_time_utc8_naive().isoformat()
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved user context to local file: {file_path}")
        return True
        
    except Exception as e:
        logger.warning(f"Failed to save user context to local file for user {user_id}: {e}")
        return False


def load_user_context_from_local(backend_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """
    Load user context (persona_summary and facts) from local JSON file.
    
    Args:
        backend_dir: Backend directory path (optional, will be inferred if not provided)
        
    Returns:
        Dictionary with 'persona_summary', 'facts', 'user_id', 'last_updated' keys, or None if not found
    """
    try:
        if backend_dir is None:
            # Infer backend directory from current file location
            backend_dir = Path(__file__).parent.parent.parent
        
        file_path = backend_dir / "config" / "user_persona.json"
        
        if not file_path.exists():
            logger.debug(f"Local context file not found: {file_path}")
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Validate structure
        if not isinstance(data, dict):
            logger.warning(f"Invalid format in local context file: {file_path}")
            return None
        
        logger.info(f"Loaded user context from local file: {file_path}")
        return data
        
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse local context file: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to load user context from local file: {e}")
        return None


# ---------- Activity Logging helpers ----------

def log_activity_start(
    user_id: str,
    activity_type: str,
    emotional_log_id: Optional[int] = None
) -> Optional[str]:
    """
    Log the start of an intervention/activity.
    
    Args:
        user_id: User ID
        activity_type: Type of intervention ('journal', 'gratitude', 'todo', 'meditation', 'quote', 'activity_suggestion')
        emotional_log_id: Optional emotional_log ID if intervention was triggered by emotion detection.
                         None for command-triggered interventions.
    
    Returns:
        Public ID (UUID string) if successful, None if failed.
        Non-blocking: errors are logged but don't raise exceptions.
    """
    try:
        # Validate enum values match schema constraints
        valid_activity_types = ['journal', 'gratitude', 'todo', 'meditation', 'quote', 'activity_suggestion']
        
        if activity_type not in valid_activity_types:
            logger.error(f"Invalid activity_type: {activity_type}. Must be one of {valid_activity_types}")
            return None
        
        # Get current timestamp in UTC+8 (timezone-naive for intervention_log)
        current_timestamp = get_current_time_utc8_naive()
        
        payload = {
            "user_id": user_id,
            "intervention_type": activity_type,
            "timestamp": current_timestamp.isoformat(),
            "emotional_log_id": emotional_log_id  # None for command-triggered interventions
        }
        
        res = sb.table("intervention_log").insert(payload).execute()
        public_id = res.data[0]["public_id"]
        logger.info(f"Intervention log started: {public_id} for user {user_id}, intervention_type={activity_type}, emotional_log_id={emotional_log_id}")
        return public_id
        
    except Exception as e:
        logger.error(f"Failed to log intervention start: {e}", exc_info=True)
        return None


def log_intervention_duration(public_id: str, duration_seconds: Optional[float] = None) -> bool:
    """
    Update intervention log with duration.
    
    Args:
        public_id: Public ID (UUID string) from log_activity_start()
        duration_seconds: Duration in seconds. If None, duration will be calculated from timestamp.
    
    Returns:
        True if successful, False if failed.
        Non-blocking: errors are logged but don't raise exceptions.
    """
    try:
        if not public_id:
            logger.warning("log_intervention_duration called with empty public_id")
            return False
        
        update_data = {}
        
        if duration_seconds is not None:
            # Convert seconds to interval format (PostgreSQL interval)
            update_data["duration"] = f"{duration_seconds} seconds"
        else:
            # Calculate duration from timestamp to now
            # First fetch the log to get timestamp
            res = sb.table("intervention_log").select("timestamp").eq("public_id", public_id).limit(1).execute()
            if res.data:
                log_timestamp = datetime.fromisoformat(res.data[0]["timestamp"].replace('Z', '+00:00'))
                if log_timestamp.tzinfo:
                    log_timestamp = log_timestamp.replace(tzinfo=None)
                # Use UTC+8 current time for consistent calculation
                now = get_current_time_utc8_naive()
                duration_seconds = (now - log_timestamp).total_seconds()
                update_data["duration"] = f"{duration_seconds} seconds"
            else:
                logger.warning(f"No intervention log found to update: {public_id}")
                return False
        
        res = sb.table("intervention_log").update(update_data).eq("public_id", public_id).execute()
        
        if res.data:
            logger.info(f"Intervention log updated: {public_id}, duration={update_data.get('duration')}")
            return True
        else:
            logger.warning(f"No log record found to update: {public_id}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to log intervention duration: {e}", exc_info=True)
        return False


def query_recent_activity_logs(
    user_id: str,
    activity_type: Optional[str] = None,
    emotional_log_id: Optional[int] = None,
    limit: int = 100,
    days_back: int = 30
) -> List[Dict[str, Any]]:
    """
    Query recent intervention logs with filtering options.
    
    Args:
        user_id: User ID to filter logs
        activity_type: Optional filter by intervention type ('journal', 'gratitude', 'todo', 'meditation', 'quote')
        emotional_log_id: Optional filter by emotional_log_id (None for command-triggered, int for emotion-triggered)
        limit: Maximum number of records to return
        days_back: Number of days to look back from current time
    
    Returns:
        List of log record dictionaries, ordered by timestamp descending.
        Returns empty list if query fails.
    """
    try:
        # Calculate cutoff timestamp in UTC+8 (timezone-naive)
        cutoff_time = get_current_time_utc8_naive() - timedelta(days=days_back)
        
        # Build query
        query = (
            sb.table("intervention_log")
            .select("*")
            .eq("user_id", user_id)
            .gte("timestamp", cutoff_time.isoformat())
        )
        
        # Apply optional filters
        if activity_type:
            query = query.eq("intervention_type", activity_type)
        
        if emotional_log_id is not None:
            if emotional_log_id:
                query = query.eq("emotional_log_id", emotional_log_id)
            else:
                # Filter for command-triggered (emotional_log_id is NULL)
                query = query.is_("emotional_log_id", "null")
        
        # Order by timestamp descending and limit
        query = query.order("timestamp", desc=True).limit(limit)
        
        res = query.execute()
        
        logger.debug(f"Query returned {len(res.data) if res.data else 0} intervention logs for user {user_id}")
        return res.data if res.data else []
        
    except Exception as e:
        logger.error(f"Failed to query intervention logs: {e}", exc_info=True)
        return []


def query_emotional_logs_since(user_id: str, since_timestamp: datetime) -> List[Dict[str, Any]]:
    """
    Query emotional_log table for entries with timestamp greater than since_timestamp.
    
    Args:
        user_id: User ID to filter logs
        since_timestamp: Datetime object (timezone-naive). Only entries with timestamp > since_timestamp will be returned
    
    Returns:
        List of emotion log dictionaries, ordered by timestamp ascending.
        Each entry contains: id, user_id, timestamp, emotion_label, confidence_score, emotional_score
        Returns empty list if query fails.
    """
    try:
        # Ensure timestamp is timezone-naive for database query
        if since_timestamp.tzinfo is not None:
            since_timestamp = since_timestamp.replace(tzinfo=None)
        
        # Build query
        query = (
            sb.table("emotional_log")
            .select("id, user_id, timestamp, emotion_label, confidence_score, emotional_score")
            .eq("user_id", user_id)
            .gt("timestamp", since_timestamp.isoformat())
            .order("timestamp", desc=False)  # Ascending order (oldest first)
        )
        
        res = query.execute()
        
        logger.debug(f"Query returned {len(res.data) if res.data else 0} emotion logs for user {user_id} since {since_timestamp}")
        return res.data if res.data else []
        
    except Exception as e:
        logger.error(f"Failed to query emotion logs: {e}", exc_info=True)
        return []