import json, os
from supabase import create_client, Client

def get_supabase(service: bool = True) -> Client:
    cfg_path = os.path.join("backend", "Config", "Supabase", "supabase.json")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    url = cfg["url"]
    key = cfg["service_role_key"] if service else cfg["anon_key"]
    return create_client(url, key)
