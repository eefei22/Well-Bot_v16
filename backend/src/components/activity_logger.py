#!/usr/bin/env python3
"""
Activity Logger Component

Provides functional/logic for intervention logging:
- Time-of-day context derivation (for reference, not stored in new schema)
- Query logic for intervention logs

Database access is handled by supabase/database.py functions.
Note: New schema uses intervention_log table instead of wb_activity_logs.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

# Import timezone function from database module (uses existing pattern)
from src.supabase.database import get_malaysia_timezone


def get_context_time_of_day(timestamp: Optional[datetime] = None) -> str:
    """
    Derive time of day context from timestamp using Malaysian timezone (UTC+8).
    
    Time periods:
    - morning: 5:00 - 11:59
    - afternoon: 12:00 - 16:59
    - evening: 17:00 - 20:59
    - night: 21:00 - 4:59
    
    Args:
        timestamp: Datetime object. If None, uses current time in Malaysian timezone.
                   If provided, assumes it's in UTC and converts to Malaysian time.
    
    Returns:
        One of: 'morning', 'afternoon', 'evening', 'night'
    """
    malaysia_tz = get_malaysia_timezone()
    
    if timestamp is None:
        # Get current time in Malaysian timezone
        timestamp = datetime.now(malaysia_tz)
    else:
        # Assume timestamp is UTC, convert to Malaysian time
        if timestamp.tzinfo is None:
            # Naive datetime - assume UTC
            from datetime import timezone as tz
            timestamp = timestamp.replace(tzinfo=tz.utc)
        
        # Convert to Malaysian timezone
        timestamp = timestamp.astimezone(malaysia_tz)
    
    hour = timestamp.hour
    
    if 5 <= hour < 12:
        return 'morning'
    elif 12 <= hour < 17:
        return 'afternoon'
    elif 17 <= hour < 21:
        return 'evening'
    else:  # 21 <= hour < 5
        return 'night'


def query_activity_logs(
    user_id: str,
    activity_type: Optional[str] = None,
    emotional_log_id: Optional[int] = None,
    limit: int = 100,
    days_back: int = 30
) -> List[Dict[str, Any]]:
    """
    Query intervention logs with filtering options.
    
    This function provides the query logic. Actual database access
    should be performed by calling supabase/database.py functions.
    
    Args:
        user_id: User ID to filter logs
        activity_type: Optional filter by intervention type ('journal', 'gratitude', 'todo', 'meditation', 'quote')
        emotional_log_id: Optional filter by emotional_log_id (None for command-triggered, int for emotion-triggered)
        limit: Maximum number of records to return
        days_back: Number of days to look back from current time
    
    Returns:
        List of log record dictionaries (empty list if query fails)
    
    Note:
        This function should be called by database.py query functions
        that perform the actual database access.
        The actual implementation is in database.py's query_recent_activity_logs()
    """
    # This function provides query logic/parameters
    # The actual database query should be implemented in database.py
    # This is a placeholder that returns empty list
    # The real implementation is in database.py's query_recent_activity_logs()
    logger.debug(f"Query intervention logs called with: user_id={user_id}, activity_type={activity_type}, "
                 f"emotional_log_id={emotional_log_id}, limit={limit}, days_back={days_back}")
    return []


def parse_mood_rating_from_speech(text: str, skip_phrases: List[str] = None) -> Optional[int]:
    """
    Extract mood rating (1-10) from speech transcript.
    
    Handles:
    - Numeric strings: "5", "10"
    - Word numbers: "five", "ten", "one", "two", etc.
    - Skip phrases: returns None if skip phrase detected
    
    Args:
        text: Speech transcript text
        skip_phrases: List of phrases that indicate user wants to skip (case-insensitive)
    
    Returns:
        Integer 1-10 if valid rating found, None if skipped or invalid
    """
    if not text:
        return None
    
    text_lower = text.lower().strip()
    
    # Check for skip phrases first
    if skip_phrases:
        for phrase in skip_phrases:
            if phrase.lower() in text_lower:
                logger.debug(f"Skip phrase detected: '{phrase}'")
                return None
    
    # Word-to-number mapping
    word_to_number = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        # Chinese numbers (simplified)
        '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
        '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
        # Malay numbers
        'satu': 1, 'dua': 2, 'tiga': 3, 'empat': 4, 'lima': 5,
        'enam': 6, 'tujuh': 7, 'lapan': 8, 'sembilan': 9, 'sepuluh': 10
    }
    
    # Try word-to-number conversion
    for word, num in word_to_number.items():
        if word in text_lower:
            logger.debug(f"Found word number '{word}' -> {num}")
            return num
    
    # Extract numeric digits
    numbers = re.findall(r'\d+', text)
    if numbers:
        # Take the first number found
        rating = int(numbers[0])
        if 1 <= rating <= 10:
            logger.debug(f"Found numeric rating: {rating}")
            return rating
        else:
            logger.debug(f"Number out of range: {rating}")
            return None
    
    # No valid rating found
    logger.debug(f"No valid rating found in text: '{text}'")
    return None


def prompt_mood_rating_before_activity(
    tts_service,
    stt_service,
    audio_manager,
    language_config: dict,
    global_config: dict,
    timeout_seconds: float = 10.0
) -> Optional[int]:
    """
    Prompt user for pre-activity mood rating.
    
    Args:
        tts_service: TTS service for speaking prompt
        stt_service: STT service for capturing response
        audio_manager: Audio manager for microphone handling
        language_config: Language-specific config (contains mood_rating prompts)
        global_config: Global config
        timeout_seconds: Timeout for user response
    
    Returns:
        Integer 1-10 if rating provided, None if skipped/timed out/error
    """
    try:
        mood_config = language_config.get("mood_rating", {})
        prompt = mood_config.get("prompt_before", 
            "If you'd like — on a scale from 1 to 10 — how strong are any negative emotions you feel right now (1 = none, 10 = very strong)?")
        skip_phrases = mood_config.get("skip_phrases", ["skip", "no", "not now", "later"])
        
        logger.info("Prompting for pre-activity mood rating...")
        
        # Speak the prompt using TTS
        if tts_service:
            def text_gen():
                yield prompt
            
            pcm_chunks = tts_service.stream_synthesize(text_gen())
            audio_manager.play_tts_stream(pcm_chunks, use_nudge_delays=False)
        
        # Capture user response with timeout
        from src.components.mic_stream import MicStream
        
        mic = audio_manager.mic_factory()
        mic.start()
        
        with audio_manager._mic_lock:
            audio_manager._current_mic = mic
        
        try:
            final_text: Optional[str] = None
            stt_completed = threading.Event()
            stt_error = None
            
            def on_transcript(text: str, is_final: bool):
                nonlocal final_text
                if is_final and text:
                    final_text = text
                    mic.stop()
            
            def run_stt():
                nonlocal stt_error
                try:
                    stt_service.stream_recognize(mic.generator(), on_transcript, single_utterance=True)
                except Exception as e:
                    stt_error = e
                finally:
                    stt_completed.set()
            
            stt_thread = threading.Thread(target=run_stt, daemon=True)
            stt_thread.start()
            
            # Wait for response with timeout
            start_time = time.time()
            check_interval = 0.1
            
            while not stt_completed.wait(check_interval):
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    logger.debug(f"Mood rating prompt timeout after {timeout_seconds}s")
                    mic.stop()
                    break
            
            # Wait briefly for thread to finish
            stt_thread.join(timeout=1.0)
            
            if stt_error:
                logger.error(f"STT error during mood rating capture: {stt_error}")
                return None
            
            if final_text:
                rating = parse_mood_rating_from_speech(final_text, skip_phrases)
                logger.info(f"Pre-activity mood rating: {rating}")
                return rating
            else:
                logger.debug("No response received for mood rating prompt")
                return None
                
        finally:
            mic.stop()
            with audio_manager._mic_lock:
                audio_manager._current_mic = None
        
    except Exception as e:
        logger.error(f"Error prompting for pre-activity mood rating: {e}", exc_info=True)
        return None


def prompt_mood_rating_after_activity(
    tts_service,
    stt_service,
    audio_manager,
    language_config: dict,
    global_config: dict,
    timeout_seconds: float = 10.0
) -> Optional[int]:
    """
    Prompt user for post-activity mood rating.
    
    Args:
        tts_service: TTS service for speaking prompt
        stt_service: STT service for capturing response
        audio_manager: Audio manager for microphone handling
        language_config: Language-specific config (contains mood_rating prompts)
        global_config: Global config
        timeout_seconds: Timeout for user response
    
    Returns:
        Integer 1-10 if rating provided, None if skipped/timed out/error
    """
    try:
        mood_config = language_config.get("mood_rating", {})
        prompt = mood_config.get("prompt_after",
            "If you'd like — on a scale from 1 to 10 — how strong are any negative emotions you feel right now (1 = none, 10 = very strong)?")
        skip_phrases = mood_config.get("skip_phrases", ["skip", "no", "not now", "later"])
        
        logger.info("Prompting for post-activity mood rating...")
        
        # Speak the prompt using TTS
        if tts_service:
            def text_gen():
                yield prompt
            
            pcm_chunks = tts_service.stream_synthesize(text_gen())
            audio_manager.play_tts_stream(pcm_chunks, use_nudge_delays=False)
        
        # Capture user response with timeout
        from src.components.mic_stream import MicStream
        
        mic = audio_manager.mic_factory()
        mic.start()
        
        with audio_manager._mic_lock:
            audio_manager._current_mic = mic
        
        try:
            final_text: Optional[str] = None
            stt_completed = threading.Event()
            stt_error = None
            
            def on_transcript(text: str, is_final: bool):
                nonlocal final_text
                if is_final and text:
                    final_text = text
                    mic.stop()
            
            def run_stt():
                nonlocal stt_error
                try:
                    stt_service.stream_recognize(mic.generator(), on_transcript, single_utterance=True)
                except Exception as e:
                    stt_error = e
                finally:
                    stt_completed.set()
            
            stt_thread = threading.Thread(target=run_stt, daemon=True)
            stt_thread.start()
            
            # Wait for response with timeout
            start_time = time.time()
            check_interval = 0.1
            
            while not stt_completed.wait(check_interval):
                elapsed = time.time() - start_time
                if elapsed >= timeout_seconds:
                    logger.debug(f"Mood rating prompt timeout after {timeout_seconds}s")
                    mic.stop()
                    break
            
            # Wait briefly for thread to finish
            stt_thread.join(timeout=1.0)
            
            if stt_error:
                logger.error(f"STT error during mood rating capture: {stt_error}")
                return None
            
            if final_text:
                rating = parse_mood_rating_from_speech(final_text, skip_phrases)
                logger.info(f"Post-activity mood rating: {rating}")
                return rating
            else:
                logger.debug("No response received for mood rating prompt")
                return None
                
        finally:
            mic.stop()
            with audio_manager._mic_lock:
                audio_manager._current_mic = None
        
    except Exception as e:
        logger.error(f"Error prompting for post-activity mood rating: {e}", exc_info=True)
        return None

