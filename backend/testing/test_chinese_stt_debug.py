#!/usr/bin/env python3
"""
Debug script for investigating Chinese STT issues in journal activity.

This script tests:
1. STT service initialization with Chinese language
2. Chinese text handling and encoding
3. Termination phrase detection with Chinese characters
4. Full exception capture and logging
5. Journal activity with Chinese configuration
"""

import os
import sys
import logging
import traceback
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_stt_initialization():
    """Test 1: STT service initialization with Chinese"""
    logger.info("=" * 70)
    logger.info("TEST 1: STT Service Initialization with Chinese")
    logger.info("=" * 70)
    
    try:
        # Get config
        user_id = get_current_user_id()
        global_config = get_global_config_for_user(user_id)
        
        stt_language = global_config.get("language_codes", {}).get("stt_language_code", "en-US")
        logger.info(f"STT Language from config: {stt_language}")
        
        # Initialize STT service
        stt_service = GoogleSTTService(language=stt_language, sample_rate=16000)
        logger.info(f"✓ STT service initialized successfully")
        logger.info(f"  - Language: {stt_service.get_language()}")
        logger.info(f"  - Sample rate: {stt_service.get_sample_rate()}")
        
        return True, stt_service
        
    except Exception as e:
        logger.error(f"✗ Failed to initialize STT service: {e}")
        logger.error(traceback.format_exc())
        return False, None


def test_chinese_text_encoding():
    """Test 2: Chinese text encoding and normalization"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 2: Chinese Text Encoding & Normalization")
    logger.info("=" * 70)
    
    # Test Chinese termination phrases
    chinese_phrases = [
        "停止写日记",
        "保存日记",
        "结束记录",
        "就这样",
        "完成写日记",
    ]
    
    # Test Chinese user input (similar to what we see in logs)
    test_inputs = [
        "停止写日记。",
        " 停止写日记。",
        "我说的是我有没有准备到礼物给他，所以我就有点不好意思哦。",
        "亲子写日记。",
    ]
    
    from src.activities.journal import normalize_text
    
    logger.info("Testing normalization of termination phrases:")
    for phrase in chinese_phrases:
        normalized = normalize_text(phrase)
        logger.info(f"  '{phrase}' -> '{normalized}'")
    
    logger.info("")
    logger.info("Testing normalization of user inputs:")
    for text in test_inputs:
        normalized = normalize_text(text)
        logger.info(f"  '{text}' -> '{normalized}'")
        
        # Test matching
        for phrase in chinese_phrases:
            norm_phrase = normalize_text(phrase)
            if norm_phrase in normalized or normalized.startswith(norm_phrase + " "):
                logger.info(f"    → MATCHES: '{phrase}'")
    
    return True


def test_termination_phrase_detection():
    """Test 3: Termination phrase detection with Chinese"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 3: Termination Phrase Detection")
    logger.info("=" * 70)
    
    try:
        # Load Chinese config
        user_id = get_current_user_id()
        language_config = get_language_config(user_id)
        journal_config = language_config.get("journal", {})
        termination_phrases = journal_config.get("termination_phrases", [])
        
        logger.info(f"Loaded {len(termination_phrases)} termination phrases:")
        for phrase in termination_phrases:
            logger.info(f"  - '{phrase}'")
        
        # Import the termination check function
        from src.activities.journal import normalize_text
        
        # Test cases from actual logs
        test_cases = [
            ("停止写日记。", True),
            (" 停止写日记。", True),
            ("亲子写日记。", False),  # Should NOT match
            ("我说停止写日记了", True),
            ("停止写日记 好了", True),
        ]
        
        logger.info("")
        logger.info("Testing phrase matching:")
        for user_text, expected_match in test_cases:
            normalized_user = normalize_text(user_text)
            matched = False
            
            for phrase in termination_phrases:
                normalized_phrase = normalize_text(phrase)
                
                if (normalized_user == normalized_phrase or 
                    normalized_user.startswith(normalized_phrase + " ") or
                    normalized_phrase in normalized_user):
                    matched = True
                    logger.info(f"  '{user_text}' -> MATCHES '{phrase}' ✓")
                    break
            
            if not matched:
                logger.info(f"  '{user_text}' -> NO MATCH {'(expected match!)' if expected_match else ''}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Termination phrase test failed: {e}")
        logger.error(traceback.format_exc())
        return False


def test_transcript_callback_safety():
    """Test 4: Transcript callback exception handling"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 4: Transcript Callback Exception Handling")
    logger.info("=" * 70)
    
    callback_errors = []
    
    def on_transcript(text: str, is_final: bool):
        """Callback that might raise exceptions"""
        try:
            logger.info(f"  Callback received: '{text}' (final: {is_final})")
            
            # Simulate termination phrase detection
            if "停止" in text:
                logger.info("  → Simulating termination phrase detection")
                raise Exception("TerminationPhraseDetected - simulated")
            
            # Simulate other operations
            if text:
                # This might fail with encoding issues
                text_length = len(text)
                text_bytes = text.encode('utf-8')
                logger.info(f"  → Text processed: {text_length} chars, {len(text_bytes)} bytes")
            
        except Exception as e:
            error_info = {
                'text': text,
                'is_final': is_final,
                'error': str(e),
                'traceback': traceback.format_exc()
            }
            callback_errors.append(error_info)
            logger.error(f"  ✗ Error in callback: {e}")
            logger.error(f"    Full traceback:\n{traceback.format_exc()}")
            # Re-raise to see how STT service handles it
            raise
    
    # Test with Chinese text
    test_texts = [
        ("停止写日记。", True),
        ("我说的是我有没有准备到礼物给他", True),
        ("亲子写日记。", True),
        ("", False),  # Empty text
    ]
    
    logger.info("Testing callback with Chinese text:")
    for text, is_final in test_texts:
        try:
            on_transcript(text, is_final)
        except Exception as e:
            logger.warning(f"  Callback raised exception (expected): {e}")
    
    if callback_errors:
        logger.warning(f"Captured {len(callback_errors)} callback errors")
    
    return True


def test_journal_activity_chinese():
    """Test 5: Full journal activity with Chinese config"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 5: Journal Activity with Chinese Configuration")
    logger.info("=" * 70)
    
    try:
        from src.activities.journal import JournalActivity
        
        # Get user and configs
        user_id = get_current_user_id()
        logger.info(f"Testing with user_id: {user_id}")
        
        global_config = get_global_config_for_user(user_id)
        language_config = get_language_config(user_id)
        
        logger.info(f"Global config language_codes: {global_config.get('language_codes', {})}")
        logger.info(f"Language config language: {language_config.get('_resolved_language', 'unknown')}")
        
        # Create journal activity
        journal = JournalActivity(backend_dir=backend_dir, user_id=user_id)
        
        # Initialize
        logger.info("Initializing journal activity...")
        if not journal.initialize():
            logger.error("✗ Failed to initialize journal activity")
            return False
        
        logger.info("✓ Journal activity initialized")
        
        # Check STT language
        if journal.stt_service:
            logger.info(f"  STT Language: {journal.stt_service.get_language()}")
        
        # Check termination phrases
        logger.info(f"  Termination phrases: {journal.termination_phrases}")
        
        # Check configs
        logger.info(f"  Global journal config keys: {list(journal.global_journal_config.keys())}")
        logger.info(f"  Language journal config keys: {list(journal.config.keys())}")
        
        logger.info("")
        logger.info("Note: To test actual recording, run the activity manually")
        logger.info("  This test only verifies initialization")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Journal activity test failed: {e}")
        logger.error(traceback.format_exc())
        return False


def test_stt_error_logging():
    """Test 6: Improve error logging in STT callback"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 6: STT Error Logging Improvement")
    logger.info("=" * 70)
    
    logger.info("Current STT error handling only logs: 'Error in transcript callback: {e}'")
    logger.info("")
    logger.info("Suggested improvement:")
    logger.info("  - Log full exception type")
    logger.info("  - Log full traceback")
    logger.info("  - Log transcript text that caused error")
    logger.info("  - Log callback state")
    
    # Show what the improved error handling would look like
    example_error = {
        'exception_type': 'TerminationPhraseDetected',
        'message': 'Termination phrase detected',
        'transcript': '停止写日记。',
        'is_final': True,
        'traceback': 'Traceback...'
    }
    
    logger.info("")
    logger.info("Example improved error format:")
    for key, value in example_error.items():
        logger.info(f"  {key}: {value}")
    
    return True


def main():
    """Run all debug tests"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("CHINESE STT DEBUG SUITE")
    logger.info("=" * 70)
    logger.info("")
    
    results = {}
    
    # Run tests
    try:
        results['stt_init'] = test_stt_initialization()
        results['text_encoding'] = test_chinese_text_encoding()
        results['termination'] = test_termination_phrase_detection()
        results['callback'] = test_transcript_callback_safety()
        results['journal'] = test_journal_activity_chinese()
        results['error_logging'] = test_stt_error_logging()
    except Exception as e:
        logger.error(f"Fatal error during testing: {e}")
        logger.error(traceback.format_exc())
        return
    
    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    for test_name, result in results.items():
        # Handle both tuple results (bool, data) and simple bool results
        if isinstance(result, tuple):
            status = "✓ PASS" if result[0] else "✗ FAIL"
        else:
            status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"  {test_name:20s}: {status}")
    
    logger.info("")
    logger.info("RECOMMENDATIONS:")
    logger.info("  1. Improve STT error logging to include full traceback")
    logger.info("  2. Check for race conditions when mic.stop() is called")
    logger.info("  3. Ensure TerminationPhraseDetected exception propagates correctly")
    logger.info("  4. Test with actual Chinese audio input")
    logger.info("")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)

