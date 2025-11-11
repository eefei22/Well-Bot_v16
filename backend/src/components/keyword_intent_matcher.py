#!/usr/bin/env python3
"""
Keyword Intent Matcher Component

Matches user transcripts against intent keywords using text normalization.
Similar to TerminationPhraseDetector but for intent classification.
"""

import json
import logging
import string
from pathlib import Path
from typing import Optional, Dict, Any

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


class KeywordIntentMatcher:
    """
    Matches user transcripts against intent keywords.
    
    Uses robust text normalization and keyword matching to classify
    user intent from transcribed speech.
    """
    
    def __init__(self, intents_path: Optional[Path] = None, backend_dir: Optional[Path] = None, user_id: Optional[str] = None):
        """
        Initialize keyword intent matcher.
        
        Args:
            intents_path: Path to intents.json file (deprecated, use backend_dir + user_id instead)
            backend_dir: Path to backend directory (used to resolve config directory)
            user_id: User ID to determine language preference (if None, defaults to 'en')
        """
        self.intents: Dict[str, list] = {}
        
        # Determine which intents file to load based on user language
        if backend_dir and user_id:
            # Resolve user language and load appropriate intents file
            from ..utils.config_resolver import resolve_language
            
            language = resolve_language(user_id)
            
            # Map language to intents file
            intents_filename = f"intents_{language}.json"
            self.intents_path = Path(backend_dir) / "config" / intents_filename
            
            logger.info(f"Loading intents for user {user_id} with language '{language}' from {self.intents_path}")
        elif intents_path:
            # Legacy: use provided path directly
            self.intents_path = Path(intents_path)
            logger.info(f"Loading intents from provided path: {self.intents_path}")
        else:
            raise ValueError("Either (backend_dir + user_id) or intents_path must be provided")
        
        if not self.intents_path.exists():
            raise FileNotFoundError(f"Intents file not found: {self.intents_path}")
        
        self._load_intents()
        logger.info(f"KeywordIntentMatcher initialized with {len(self.intents)} intent categories")
    
    def _load_intents(self):
        """Load intents from JSON file."""
        try:
            with open(self.intents_path, 'r', encoding='utf-8') as f:
                self.intents = json.load(f)
            logger.debug(f"Loaded {len(self.intents)} intent categories from {self.intents_path}")
        except Exception as e:
            logger.error(f"Failed to load intents from {self.intents_path}: {e}")
            raise
    
    def match_intent(self, transcript: str) -> Optional[Dict[str, Any]]:
        """
        Match transcript against intent keywords.
        
        Args:
            transcript: User's transcribed speech text
            
        Returns:
            Dict with "intent" and "confidence" keys if matched, None otherwise.
            Format: {"intent": str, "confidence": float}
        """
        if not transcript:
            logger.debug("Empty transcript provided")
            return None
        
        normalized_transcript = normalize_text(transcript)
        logger.debug(f"Matching transcript: '{transcript}' -> normalized: '{normalized_transcript}'")
        
        # Check each intent category
        for intent_name, keywords in self.intents.items():
            for keyword in keywords:
                normalized_keyword = normalize_text(keyword)
                
                # Multiple matching strategies for robustness
                if (normalized_transcript == normalized_keyword or
                    normalized_transcript.startswith(normalized_keyword + " ") or
                    normalized_keyword in normalized_transcript):
                    logger.info(f"Intent matched! '{intent_name}' from keyword '{keyword}' in transcript '{transcript}'")
                    return {
                        "intent": intent_name,
                        "confidence": 1.0
                    }
        
        logger.debug(f"No intent matched for transcript: '{transcript}'")
        return None
    
    def get_intent(self, transcript: str) -> Optional[str]:
        """
        Get intent name from transcript (convenience method).
        
        Args:
            transcript: User's transcribed speech text
            
        Returns:
            Intent name if matched, None otherwise
        """
        result = self.match_intent(transcript)
        return result.get("intent") if result else None

