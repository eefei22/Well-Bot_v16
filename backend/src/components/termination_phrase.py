#!/usr/bin/env python3
"""
Termination Phrase Detection Component

Shared component for detecting termination phrases in user input.
Provides text normalization and phrase matching functionality.
"""

import logging
import string
from typing import List, Optional

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """
    Normalize text for robust matching:
    - Convert to lowercase
    - Remove punctuation
    - Collapse whitespace
    """
    if not text:
        return ""
    
    # Convert to lowercase and strip
    normalized = text.strip().lower()
    
    # Remove punctuation
    normalized = normalized.translate(str.maketrans("", "", string.punctuation))
    
    # Collapse multiple spaces into single space
    normalized = " ".join(normalized.split())
    
    return normalized


class TerminationPhraseDetected(Exception):
    """Raised when user utterance matches a termination phrase"""
    pass


class TerminationPhraseDetector:
    """
    Detector for termination phrases in user input.
    
    Uses robust text normalization and multiple matching strategies
    to detect when a user wants to terminate an activity.
    """
    
    def __init__(self, phrases: List[str], require_active: bool = False):
        """
        Initialize termination phrase detector.
        
        Args:
            phrases: List of termination phrases to match against
            require_active: If True, only matches when active flag is set (for JournalActivity compatibility)
        """
        self.phrases = phrases
        self.require_active = require_active
        logger.debug(f"TerminationPhraseDetector initialized with {len(phrases)} phrases")
    
    def is_termination_phrase(self, user_text: str, active: bool = True) -> bool:
        """
        Check if user text contains termination phrases with robust matching.
        
        Args:
            user_text: The user's input text to check
            active: Whether the activity is currently active (required if require_active=True)
            
        Returns:
            True if a termination phrase is detected, False otherwise
        """
        if not user_text:
            return False
        
        # Check active requirement (for JournalActivity compatibility)
        if self.require_active and not active:
            return False
        
        normalized_user = normalize_text(user_text)
        logger.debug(f"Checking termination - user_text='{user_text}' -> normalized='{normalized_user}'")
        
        for phrase in self.phrases:
            normalized_phrase = normalize_text(phrase)
            logger.debug(f"Comparing against phrase='{phrase}' -> normalized='{normalized_phrase}'")
            
            # Multiple matching strategies for robustness
            if (normalized_user == normalized_phrase or 
                normalized_user.startswith(normalized_phrase + " ") or
                normalized_phrase in normalized_user):
                logger.info(f"Termination phrase matched! '{phrase}' in '{user_text}'")
                return True
        
        logger.debug(f"No termination phrase matched for '{user_text}'")
        return False
    
    def check_termination(self, user_text: str, active: bool = True) -> None:
        """
        Check and raise exception if termination phrase detected.
        
        Args:
            user_text: The user's input text to check
            active: Whether the activity is currently active (required if require_active=True)
            
        Raises:
            TerminationPhraseDetected: If a termination phrase is detected
        """
        logger.debug(f"Checking termination for user_text='{user_text}'")
        logger.debug(f"Configured termination phrases: {self.phrases}")
        
        if self.is_termination_phrase(user_text, active=active):
            logger.info(f"TERMINATION DETECTED! User said: '{user_text}'")
            raise TerminationPhraseDetected(f"User requested termination: {user_text}")
        
        logger.debug(f"No termination detected for '{user_text}'")

