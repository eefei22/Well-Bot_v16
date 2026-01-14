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


class GuardrailPhraseDetected(Exception):
    """Raised when user utterance matches a guardrail phrase (e.g., suicide risk)"""
    def __init__(self, message: str, matched_phrase: str, user_text: str):
        super().__init__(message)
        self.matched_phrase = matched_phrase
        self.user_text = user_text


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


class GuardrailPhraseDetector:
    """
    Detector for guardrail phrases in user input (e.g., suicide risk detection).
    
    Uses the same robust text normalization and matching strategies as TerminationPhraseDetector,
    but does NOT terminate the conversation - instead raises an exception that should be handled
    to trigger appropriate responses while continuing the conversation.
    """
    
    def __init__(self, phrases: List[str]):
        """
        Initialize guardrail phrase detector.
        
        Args:
            phrases: List of guardrail phrases to match against
        """
        self.phrases = phrases
        logger.debug(f"GuardrailPhraseDetector initialized with {len(phrases)} phrases")
    
    def is_guardrail_phrase(self, user_text: str) -> tuple[bool, Optional[str]]:
        """
        Check if user text contains guardrail phrases with robust matching.
        
        Args:
            user_text: The user's input text to check
            
        Returns:
            Tuple of (True if guardrail phrase detected, matched phrase or None)
        """
        if not user_text:
            return False, None
        
        normalized_user = normalize_text(user_text)
        logger.debug(f"Checking guardrail - user_text='{user_text}' -> normalized='{normalized_user}'")
        
        for phrase in self.phrases:
            normalized_phrase = normalize_text(phrase)
            logger.debug(f"Comparing against phrase='{phrase}' -> normalized='{normalized_phrase}'")
            
            # Multiple matching strategies for robustness
            if (normalized_user == normalized_phrase or 
                normalized_user.startswith(normalized_phrase + " ") or
                normalized_phrase in normalized_user):
                logger.warning(f"GUARDRAIL phrase matched! '{phrase}' in '{user_text}'")
                return True, phrase
        
        logger.debug(f"No guardrail phrase matched for '{user_text}'")
        return False, None
    
    def check_guardrail(self, user_text: str) -> None:
        """
        Check and raise exception if guardrail phrase detected.
        
        Args:
            user_text: The user's input text to check
            
        Raises:
            GuardrailPhraseDetected: If a guardrail phrase is detected
        """
        logger.debug(f"Checking guardrail for user_text='{user_text}'")
        logger.debug(f"Configured guardrail phrases: {self.phrases}")
        
        is_match, matched_phrase = self.is_guardrail_phrase(user_text)
        if is_match:
            logger.warning(f"GUARDRAIL DETECTED! User said: '{user_text}'")
            raise GuardrailPhraseDetected(
                f"Guardrail phrase detected: {user_text}",
                matched_phrase=matched_phrase or "",
                user_text=user_text
            )
        
        logger.debug(f"No guardrail detected for '{user_text}'")

