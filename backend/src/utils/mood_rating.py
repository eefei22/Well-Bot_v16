"""
Mood rating parsing utilities.
"""

from typing import Optional, List
import logging
import re

logger = logging.getLogger(__name__)


def parse_mood_rating_from_speech(text: str, skip_phrases: Optional[List[str]] = None) -> Optional[int]:
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
                logger.debug("Skip phrase detected: '%s'", phrase)
                return None

    # Word-to-number mapping
    word_to_number = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        # Chinese numbers (simplified)
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
        # Malay numbers
        "satu": 1,
        "dua": 2,
        "tiga": 3,
        "empat": 4,
        "lima": 5,
        "enam": 6,
        "tujuh": 7,
        "lapan": 8,
        "sembilan": 9,
        "sepuluh": 10,
    }

    # Try word-to-number conversion
    for word, num in word_to_number.items():
        if word in text_lower:
            logger.debug("Found word number '%s' -> %s", word, num)
            return num

    # Extract numeric digits
    numbers = re.findall(r"\d+", text)
    if numbers:
        rating = int(numbers[0])
        if 1 <= rating <= 10:
            logger.debug("Found numeric rating: %s", rating)
            return rating
        logger.debug("Number out of range: %s", rating)
        return None

    logger.debug("No valid rating found in text: '%s'", text)
    return None
