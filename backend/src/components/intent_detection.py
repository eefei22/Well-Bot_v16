#!/usr/bin/env python3
"""
Intent Detection Component
Phrase-based intent detection using configurable phrase matching.
Replaces traditional intent classification with simple phrase detection.
"""

import json
import logging
import string
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


class IntentDetection:
    """
    Phrase-based intent detection system.
    
    Loads intent phrases from a JSON configuration file and matches
    user input against these phrases using robust text normalization.
    """
    
    def __init__(self, config_path: str):
        """
        Initialize intent detection with configuration file.
        
        Args:
            config_path: Path to the intents.json configuration file
        """
        self.config_path = Path(config_path)
        self.intent_phrases: Dict[str, List[str]] = {}
        self._load_config()
    
    def _load_config(self):
        """Load intent phrases from configuration file"""
        try:
            if not self.config_path.exists():
                logger.warning(f"Intent config file not found: {self.config_path}")
                self.intent_phrases = {}
                return
            
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # Load phrases for each intent category
            self.intent_phrases = {}
            for intent_name, phrases in config.items():
                if isinstance(phrases, list):
                    # Normalize phrases for consistent matching
                    normalized_phrases = [normalize_text(phrase) for phrase in phrases]
                    self.intent_phrases[intent_name] = normalized_phrases
                    logger.debug(f"Loaded {len(phrases)} phrases for intent '{intent_name}'")
                else:
                    logger.warning(f"Invalid phrase list for intent '{intent_name}': {phrases}")
            
            logger.info(f"Loaded intent detection config with {len(self.intent_phrases)} intent categories")
            
        except Exception as e:
            logger.error(f"Failed to load intent config: {e}")
            self.intent_phrases = {}
    
    def detect_intent(self, user_text: str) -> Optional[Tuple[str, str]]:
        """
        Detect intent from user text using phrase matching.
        
        Args:
            user_text: The user's spoken text to analyze
            
        Returns:
            Tuple of (intent_name, matched_phrase) if intent detected, None otherwise
        """
        if not user_text or not self.intent_phrases:
            return None
        
        normalized_user = normalize_text(user_text)
        logger.debug(f"Intent detection: checking '{user_text}' -> normalized='{normalized_user}'")
        
        # Check each intent category
        for intent_name, phrases in self.intent_phrases.items():
            for phrase in phrases:
                if self._phrase_matches(normalized_user, phrase):
                    logger.info(f"Intent detected: '{intent_name}' for phrase '{phrase}' in '{user_text}'")
                    return (intent_name, phrase)
        
        logger.debug(f"No intent detected for '{user_text}'")
        return None
    
    def _phrase_matches(self, normalized_user: str, normalized_phrase: str) -> bool:
        """
        Check if normalized user text matches a normalized phrase.
        
        Uses multiple matching strategies for robustness:
        - Exact match
        - Phrase at start of user text
        - Phrase contained anywhere in user text
        """
        # Multiple matching strategies for robustness
        if (normalized_user == normalized_phrase or 
            normalized_user.startswith(normalized_phrase + " ") or
            normalized_phrase in normalized_user):
            return True
        
        return False
    
    def get_available_intents(self) -> List[str]:
        """Get list of available intent categories"""
        return list(self.intent_phrases.keys())
    
    def get_phrases_for_intent(self, intent_name: str) -> List[str]:
        """Get all phrases for a specific intent"""
        return self.intent_phrases.get(intent_name, [])
    
    def reload_config(self):
        """Reload configuration from file"""
        logger.info("Reloading intent detection configuration...")
        self._load_config()
    
    def get_status(self) -> Dict:
        """Get current status of intent detection"""
        return {
            "config_loaded": bool(self.intent_phrases),
            "config_path": str(self.config_path),
            "available_intents": self.get_available_intents(),
            "total_phrases": sum(len(phrases) for phrases in self.intent_phrases.values())
        }


# For testing when run directly
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def test_intent_detection():
        """Test the intent detection component"""
        try:
            # Get the config path
            current_dir = Path(__file__).parent
            config_path = current_dir.parent.parent / "config" / "WakeWord" / "intents.json"
            
            # Create intent detector
            detector = IntentDetection(str(config_path))
            
            print("=== Intent Detection Test ===")
            print(f"Config path: {config_path}")
            print(f"Status: {detector.get_status()}")
            print()
            
            # Test phrases
            test_phrases = [
                "can we talk?",
                "i'm bored",
                "journal entry",
                "start journaling",
                "meditation session",
                "begin meditation",
                "quote of the day",
                "gratitude practice",
                "hello there",
                "goodbye"
            ]
            
            print("Testing phrase detection:")
            for phrase in test_phrases:
                result = detector.detect_intent(phrase)
                if result:
                    intent_name, matched_phrase = result
                    print(f"✓ '{phrase}' -> Intent: {intent_name}, Matched: '{matched_phrase}'")
                else:
                    print(f"✗ '{phrase}' -> No intent detected")
            
            return True
            
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            return False
    
    success = test_intent_detection()
    if success:
        print("\n=== Intent Detection Test Completed Successfully! ===")
    else:
        print("\n=== Intent Detection Test Failed! ===")
