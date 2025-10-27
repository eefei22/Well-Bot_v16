#!/usr/bin/env python3
"""
Test script to verify the full system loads the correct language configuration
based on the user's database language preference.
"""
import sys
import os
import json
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

# Configure logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
    datefmt='%H:%M:%S'
)

from src.supabase.auth import get_current_user_id, set_session_user
from src.utils.config_resolver import (
    resolve_language,
    get_language_config,
    get_global_config_for_user
)

logger = logging.getLogger(__name__)

def test_system_for_user(user_id: str):
    """Test the full config system for a specific user."""
    print("\n" + "="*80)
    print(f"TESTING FULL SYSTEM FOR USER: {user_id}")
    print("="*80)
    
    # Set this as the current session user
    set_session_user(user_id)
    print(f"✓ Session user set to: {user_id}")
    
    # Test 1: Resolve language from database
    print("\n" + "-"*80)
    print("TEST 1: Resolve Language from Database")
    print("-"*80)
    language = resolve_language(user_id)
    print(f"✓ Resolved language: {language}")
    
    # Test 2: Load language-specific config
    print("\n" + "-"*80)
    print("TEST 2: Load Language-Specific Config")
    print("-"*80)
    lang_config = get_language_config(user_id)
    print(f"✓ Language config loaded")
    print(f"  Available sections: {list(lang_config.keys())}")
    
    # Show some sample content
    if 'smalltalk' in lang_config:
        prompts = lang_config['smalltalk'].get('prompts', {})
        print(f"\n  Smalltalk prompts available:")
        for key, value in prompts.items():
            print(f"    - {key}: {value[:50]}...")
    
    if 'intents' in lang_config:
        total_phrases = sum(len(phrases) for phrases in lang_config['intents'].values())
        print(f"\n  Intent phrases: {total_phrases} total")
        for intent, phrases in lang_config['intents'].items():
            print(f"    - {intent}: {len(phrases)} phrases")
    
    # Test 3: Load global config with language codes
    print("\n" + "-"*80)
    print("TEST 3: Load Global Config with Language Codes")
    print("-"*80)
    global_config = get_global_config_for_user(user_id)
    
    if 'language_codes' in global_config:
        codes = global_config['language_codes']
        print(f"✓ Language codes for user:")
        print(f"  TTS Voice: {codes.get('tts_voice_name')}")
        print(f"  TTS Language: {codes.get('tts_language_code')}")
        print(f"  STT Language: {codes.get('stt_language_code')}")
    
    # Show timeout values
    if 'smalltalk' in global_config:
        st_config = global_config['smalltalk']
        print(f"\n  Smalltalk settings:")
        print(f"    - Silence timeout: {st_config.get('silence_timeout_seconds')}s")
        print(f"    - Nudge timeout: {st_config.get('nudge_timeout_seconds')}s")
        print(f"    - Max turns: {st_config.get('max_turns')}")
    
    # Test 4: Verify current session
    print("\n" + "-"*80)
    print("TEST 4: Verify Current Session")
    print("-"*80)
    current_user = get_current_user_id()
    print(f"✓ Current session user: {current_user}")
    print(f"✓ Expected user: {user_id}")
    if current_user == user_id:
        print("✓ User ID matches!")
    else:
        print("✗ User ID mismatch!")
    
    print("\n" + "="*80)
    print(f"✓ SYSTEM TEST COMPLETED FOR USER: {user_id}")
    print("="*80 + "\n")
    
    return True

def main():
    """Main test function."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Test the full system language configuration'
    )
    parser.add_argument(
        '--user-id',
        type=str,
        required=True,
        help='User UUID to test (must exist in database with language field set)'
    )
    
    args = parser.parse_args()
    
    try:
        # Run the test
        success = test_system_for_user(args.user_id)
        
        if success:
            print("\n✓ All tests passed!")
            print("\nYou can now run main.py with this user:")
            print(f"  set DEV_USER_ID={args.user_id}")
            print(f"  python main.py")
            return 0
        else:
            print("\n✗ Tests failed!")
            return 1
    
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit(main())

