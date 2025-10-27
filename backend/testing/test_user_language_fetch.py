#!/usr/bin/env python3
"""
Test script to fetch user language from database and display fetched content.
"""
import sys
import json
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent
sys.path.append(str(backend_dir))

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
    datefmt='%H:%M:%S'
)

from src.supabase.database import get_user_by_id, get_user_language
from src.supabase.auth import set_session_user, get_current_user_id
from src.utils.config_resolver import (
    resolve_language, 
    get_language_config, 
    get_global_config,
    get_global_config_for_user,
    update_global_config_for_user
)

logger = logging.getLogger(__name__)

def test_user_fetch(user_id: str):
    """Test fetching user data and language from database."""
    print("\n" + "="*80)
    print(f"Testing user language fetch for user_id: {user_id}")
    print("="*80)
    
    # Fetch full user record
    print("\n1. Fetching full user record from database...")
    user = get_user_by_id(user_id)
    
    if user:
        print(f"✓ User found in database:")
        print(json.dumps(user, indent=2, default=str))
    else:
        print("✗ User not found in database")
        return False
    
    # Fetch language specifically
    print("\n2. Fetching user language...")
    language = get_user_language(user_id)
    
    if language:
        print(f"✓ Language code: {language}")
    else:
        print("✗ Language not found")
        return False
    
    # Test config resolver
    print("\n3. Testing config resolver...")
    resolved_lang = resolve_language(user_id)
    print(f"✓ Resolved language: {resolved_lang}")
    
    # Get language config
    print("\n4. Loading language-specific config...")
    lang_config = get_language_config(user_id)
    print(f"✓ Loaded config for language: {resolved_lang}")
    
    # Display some key configs
    print("\n5. Sample config content:")
    print("-" * 80)
    
    if 'smalltalk' in lang_config:
        if 'prompts' in lang_config['smalltalk']:
            print("Smalltalk start prompt:")
            print(f"  {lang_config['smalltalk']['prompts'].get('start', 'N/A')}")
    
    if 'intents' in lang_config:
        intent_count = sum(len(phrases) for phrases in lang_config['intents'].values())
        print(f"\nTotal intent phrases: {intent_count}")
        for intent, phrases in lang_config['intents'].items():
            print(f"  {intent}: {len(phrases)} phrases")
    
    if 'audio_paths' in lang_config:
        print(f"\nAudio paths configured: {len(lang_config['audio_paths'])} files")
    
    # Test caching
    print("\n6. Testing cache (second call should be instant)...")
    import time
    start = time.time()
    _ = resolve_language(user_id)
    elapsed = time.time() - start
    print(f"✓ Second call completed in {elapsed:.4f}s (cached)")
    
    # Get global config with user's language codes
    print("\n7. Testing dynamic language code update...")
    global_config_dynamic = get_global_config_for_user(user_id)
    print(f"Updated language codes for user {user_id}:")
    if 'language_codes' in global_config_dynamic:
        print(json.dumps(global_config_dynamic['language_codes'], indent=2))
    
    # Show the actual update to file
    print("\n8. Updating global.json file with language codes...")
    updated_config = update_global_config_for_user(user_id)
    print(f"✓ Updated global.json with language codes: {updated_config['language_codes']}")
    
    # Show file contents
    print("\n9. Displaying updated global.json content:")
    print("-" * 80)
    with open('config/global.json', 'r', encoding='utf-8') as f:
        file_contents = json.load(f)
        print(json.dumps(file_contents, indent=2))
    
    print("\n" + "="*80)
    print("✓ All tests completed successfully!")
    print("="*80)
    
    return True

def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Test user language fetch from database'
    )
    parser.add_argument(
        '--user-id',
        type=str,
        default='',
        help='User UUID to test (or leave empty to use current session user)'
    )
    
    args = parser.parse_args()
    
    # Determine which user_id to use
    if args.user_id:
        test_user_id = args.user_id
        print(f"\nTesting with provided user_id: {test_user_id}")
    else:
        test_user_id = get_current_user_id()
        print(f"\nUsing current session user_id: {test_user_id}")
        print("(Hint: use --user-id <uuid> to test a different user)")
    
    # Run the test
    success = test_user_fetch(test_user_id)
    
    if success:
        print("\n✓ Test passed!")
        return 0
    else:
        print("\n✗ Test failed!")
        return 1

if __name__ == "__main__":
    exit(main())

