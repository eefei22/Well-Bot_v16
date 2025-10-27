"""
Config resolver with caching for user-specific language preferences.
Fetches user language from database and loads appropriate config.
"""
from typing import Literal, Optional, Dict
import time
import threading
import logging
import json
from pathlib import Path
from .config_loader import load_global_config, load_language_config

logger = logging.getLogger(__name__)

LanguageCode = Literal['en', 'cn', 'bm']

# Language code mappings
LANGUAGE_CODES = {
    'en': {
        'tts_voice_name': 'en-US-Chirp3-HD-Charon',
        'tts_language_code': 'en-US',
        'stt_language_code': 'en-US'
    },
    'cn': {
        'tts_voice_name': 'cmn-CN-Chirp3-HD-Charon',
        'tts_language_code': 'cmn-CN',
        'stt_language_code': 'cmn-CN'
    },
    'bm': {
        'tts_voice_name': 'id-ID-Chirp3-HD-Charon',
        'tts_language_code': 'id-ID',
        'stt_language_code': 'id-ID'
    }
}

class ConfigResolver:
    """Resolves and caches user-specific configurations."""
    
    def __init__(self, cache_ttl_seconds: int = 300):
        # In-memory cache: {user_id: (language, timestamp)}
        self._language_cache: Dict[str, tuple[str, float]] = {}
        # Config cache: {language: config_dict}
        self._config_cache: Dict[str, dict] = {}
        self._cache_ttl = cache_ttl_seconds
        self._lock = threading.Lock()
        self._global_config = load_global_config()
    
    def resolve_language(self, user_id: str) -> LanguageCode:
        """
        Get user's language preference from database with caching.
        Falls back to 'en' on any error.
        """
        # Check cache first
        with self._lock:
            if user_id in self._language_cache:
                lang, timestamp = self._language_cache[user_id]
                if time.time() - timestamp < self._cache_ttl:
                    logger.debug(f"Using cached language '{lang}' for user {user_id}")
                    return lang
        
        # Fetch from database
        from ..supabase.database import get_user_language
        try:
            lang = get_user_language(user_id)
            # Normalize and validate
            lang = self._normalize_language(lang)
            
            # Cache the result
            with self._lock:
                self._language_cache[user_id] = (lang, time.time())
            
            logger.info(f"Fetched language '{lang}' for user {user_id}")
            return lang
        except Exception as e:
            logger.warning(f"Failed to fetch language for user {user_id}: {e}")
            return 'en'
    
    def _normalize_language(self, lang: Optional[str]) -> LanguageCode:
        """Normalize and validate language code."""
        if not lang:
            return 'en'
        lang = lang.lower().strip()
        if lang in ('en', 'cn', 'bm'):
            return lang
        return 'en'
    
    def get_language_config(self, user_id: str) -> dict:
        """Get language-specific config for user."""
        lang = self.resolve_language(user_id)
        
        # Check config cache
        with self._lock:
            if lang in self._config_cache:
                logger.debug(f"Using cached config for language '{lang}'")
                return self._config_cache[lang]
        
        # Load config
        config = load_language_config(lang)
        
        # Cache it
        with self._lock:
            self._config_cache[lang] = config
        
        logger.info(f"Loaded language config for '{lang}'")
        return config
    
    def get_global_config(self) -> dict:
        """Get global numerical configuration."""
        return self._global_config
    
    def get_global_config_with_language(self, language: LanguageCode) -> dict:
        """
        Get global config with language codes updated for specified language.
        Returns a copy with updated language_codes section.
        """
        import copy
        config = copy.deepcopy(self._global_config)
        
        # Update language codes based on language
        if language in LANGUAGE_CODES:
            config['language_codes'] = LANGUAGE_CODES[language].copy()
            logger.info(f"Updated language codes for language: {language}")
        else:
            logger.warning(f"Unknown language '{language}', using default 'en'")
            config['language_codes'] = LANGUAGE_CODES['en'].copy()
        
        return config
    
    def invalidate_user(self, user_id: str) -> None:
        """Manually invalidate cache for a user (e.g., after preference change)."""
        with self._lock:
            self._language_cache.pop(user_id, None)
            logger.info(f"Invalidated cache for user {user_id}")
    
    def invalidate_all(self) -> None:
        """Clear all caches (useful for testing)."""
        with self._lock:
            self._language_cache.clear()
            self._config_cache.clear()
            logger.info("Cleared all caches")

# Global resolver instance
_resolver = ConfigResolver(cache_ttl_seconds=300)

# Convenience functions
def resolve_language(user_id: str) -> LanguageCode:
    """Resolve user's language preference."""
    return _resolver.resolve_language(user_id)

def get_language_config(user_id: str) -> dict:
    """Get language-specific config for user."""
    return _resolver.get_language_config(user_id)

def get_global_config() -> dict:
    """Get global numerical configuration."""
    return _resolver.get_global_config()

def get_global_config_for_user(user_id: str) -> dict:
    """Get global config with language codes set for user's language."""
    lang = _resolver.resolve_language(user_id)
    return _resolver.get_global_config_with_language(lang)

def update_global_config_language(language: LanguageCode) -> dict:
    """
    Update global.json with language-specific codes.
    Modifies the file to use language-specific TTS/STT codes.
    Returns the updated config dict.
    """
    if language not in LANGUAGE_CODES:
        logger.warning(f"Invalid language '{language}', using 'en'")
        language = 'en'
    
    # Get config file path
    config_path = Path(__file__).parent.parent.parent / "config" / "global.json"
    
    # Load existing global config
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Update language codes
    config['language_codes'] = LANGUAGE_CODES[language].copy()
    
    # Write back to file
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Updated global.json with language codes for: {language}")
    return config

def update_global_config_for_user(user_id: str) -> dict:
    """
    Update global.json with language codes for specified user.
    Fetches user's language and updates global.json accordingly.
    Returns the updated config dict.
    """
    lang = _resolver.resolve_language(user_id)
    return update_global_config_language(lang)

def invalidate_user_cache(user_id: str) -> None:
    """Manually invalidate cache for a user."""
    _resolver.invalidate_user(user_id)

