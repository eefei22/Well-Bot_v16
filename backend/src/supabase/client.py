from pathlib import Path
import json
from supabase import create_client, Client

def get_supabase(service: bool = True) -> Client:
    # Resolve backend root regardless of where script is run
    THIS_FILE = Path(__file__).resolve()
    BACKEND_ROOT = THIS_FILE.parents[2]               # Well-Bot_v16/backend
    CONFIG_PATH = BACKEND_ROOT / "config" / "Supabase" / "supabase.json"

    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Supabase config not found: {CONFIG_PATH}")

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    url = cfg["url"]
    key = cfg["service_role_key"] if service else cfg["anon_key"]
    return create_client(url, key)
