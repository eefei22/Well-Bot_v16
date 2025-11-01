from typing import Optional, Dict, Any, List
from .client import get_supabase, fetch_user_by_id
import logging
import random

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