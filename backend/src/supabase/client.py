from supabase import create_client, Client
from ..config_loader import get_supabase_config

def get_supabase(service: bool = True) -> Client:
    """Get Supabase client using environment variables."""
    config = get_supabase_config()
    
    url = config["url"]
    key = config["service_role_key"] if service else config["anon_key"]
    return create_client(url, key)
