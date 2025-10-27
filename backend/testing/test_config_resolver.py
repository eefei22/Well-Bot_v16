#!/usr/bin/env python3
"""
Quick test to verify config resolver works with a user UUID.
"""
import sys
import os
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)-8s | %(message)s'
)

from src.utils.config_resolver import resolve_language, get_language_config, get_global_config_for_user
from src.supabase.auth import get_current_user_id

def main():
    # Get current user
    user_id = get_current_user_id()
    print(f"\nCurrent user ID: {user_id}")
    print("-" * 60)
    
    # Test language resolution
    print("\n1. Resolving user language...")
    language = resolve_language(user_id)
    print(f"   ✓ Language: {language}")
    
    # Test config loading
    print("\n2. Loading language config...")
    lang_config = get_language_config(user_id)
    print(f"   ✓ Config sections: {list(lang_config.keys())}")
    
    if 'smalltalk' in lang_config:
        print(f"   - Smalltalk prompts available: {list(lang_config['smalltalk'].get('prompts', {}).keys())}")
    
    if 'intents' in lang_config:
        total = sum(len(phrases) for phrases in lang_config['intents'].values())
        print(f"   - Intent phrases: {total} total")
    
    # Test global config
    print("\n3. Loading global config with language codes...")
    global_config = get_global_config_for_user(user_id)
    
    if 'language_codes' in global_config:
        codes = global_config['language_codes']
        print(f"   ✓ Language codes:")
        print(f"     - TTS Voice: {codes.get('tts_voice_name')}")
        print(f"     - TTS Lang:  {codes.get('tts_language_code')}")
        print(f"     - STT Lang:  {codes.get('stt_language_code')}")
    
    print("\n" + "="*60)
    print("✓ Config resolution test completed!")
    print("="*60)
    print(f"\nYou can now run main.py and it will use user {user_id}")
    print(f"with language preference: {language}")

if __name__ == "__main__":
    main()

