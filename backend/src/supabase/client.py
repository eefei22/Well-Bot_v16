from typing import Optional, Dict
from supabase import create_client, Client
import logging
from ..utils.config_loader import get_supabase_config

logger = logging.getLogger(__name__)

def get_supabase(service: bool = True) -> Client:
    """Get Supabase client using environment variables."""
    config = get_supabase_config()
    
    url = config["url"]
    key = config["service_role_key"] if service else config["anon_key"]
    return create_client(url, key)

def fetch_user_by_id(user_id: str, client: Optional[Client] = None) -> Optional[Dict]:
    """
    Fetch user record by ID.
    Returns user dict or None if not found.
    """
    if client is None:
        client = get_supabase(service=True)
    
    try:
        response = client.table("users")\
            .select("id, email, language, full_name, prefer_name")\
            .eq("id", user_id)\
            .limit(1)\
            .execute()
        
        if response.data and len(response.data) > 0:
            logger.info(f"Successfully fetched user {user_id}")
            return response.data[0]
        logger.warning(f"User {user_id} not found")
        return None
    except Exception as e:
        logger.error(f"Failed to fetch user {user_id}: {e}")
        return None
