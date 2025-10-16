from typing import Optional, Dict, Any, List
from .client import get_supabase

# If you’re running everything locally now, hardcode your dev user_id here:
DEV_USER_ID = "8517c97f-66ef-4955-86ed-531013d33d3e"

sb = get_supabase(service=True)

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
