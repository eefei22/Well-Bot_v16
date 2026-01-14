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

# Language name to code mappings (case-insensitive)
# Maps full language names from database to language codes
LANGUAGE_NAME_TO_CODE = {
    'english': 'en',
    'chinese': 'cn',
    'malay': 'bm',
    'bahasa malay': 'bm',
    'bahasa': 'bm'
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
        cached_lang = None
        with self._lock:
            if user_id in self._language_cache:
                lang, timestamp = self._language_cache[user_id]
                cache_age = time.time() - timestamp
                if cache_age < self._cache_ttl:
                    logger.debug(f"Using cached language '{lang}' for user {user_id}")
                    return lang
                cached_lang = lang
        
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
        """
        Normalize and validate language code.
        Handles both language codes ('en', 'cn', 'bm') and full language names
        ('English', 'Chinese', 'Malay', 'Bahasa Malay') from the database.
        """
        if not lang:
            return 'en'
        
        # Normalize input: lowercase and strip whitespace
        lang_normalized = lang.lower().strip()
        
        # First check if it's already a valid language code
        if lang_normalized in ('en', 'cn', 'bm'):
            return lang_normalized
        
        # Check against language name mappings
        if lang_normalized in LANGUAGE_NAME_TO_CODE:
            mapped_code = LANGUAGE_NAME_TO_CODE[lang_normalized]
            logger.debug(f"Mapped language name '{lang}' to code '{mapped_code}'")
            return mapped_code
        
        # No match found - log warning and fall back to 'en'
        logger.warning(
            f"Unmapped language value '{lang}' (normalized: '{lang_normalized}'). "
            f"Falling back to 'en'. Valid values: language codes ('en', 'cn', 'bm') or "
            f"language names ({', '.join(LANGUAGE_NAME_TO_CODE.keys())})"
        )
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
    
    def _check_language_changed(self, user_id: str) -> bool:
        """
        Check if language preference has changed.
        
        Args:
            user_id: User UUID to check
            
        Returns:
            True if language changed, False if unchanged or error
        """
        try:
            # Get cached language
            cached_lang = None
            with self._lock:
                if user_id in self._language_cache:
                    cached_lang, timestamp = self._language_cache[user_id]
            
            # Fetch from database
            from ..supabase.database import get_user_language
            db_lang = get_user_language(user_id)
            db_lang_normalized = self._normalize_language(db_lang)
            
            # Compare
            if cached_lang is None:
                # No cache, can't determine change
                return False
            
            changed = cached_lang != db_lang_normalized
            if changed:
                logger.info(f"Language changed for user {user_id}: {cached_lang} -> {db_lang_normalized}")
            
            return changed
        except Exception as e:
            logger.warning(f"Error checking language change for user {user_id}: {e}")
            return False
    
    def _check_prefer_name_changed(self, user_id: str) -> bool:
        """
        Check if prefer_name has changed.
        
        Args:
            user_id: User UUID to check
            
        Returns:
            True if prefer_name changed, False if unchanged or error
        """
        try:
            # Get from user_persona.json
            from ..supabase.auth import _load_user_persona
            try:
                persona_data = _load_user_persona()
                cached_prefer_name = persona_data.get('prefer_name')
            except (FileNotFoundError, ValueError):
                cached_prefer_name = None
            
            # Fetch from database
            from ..supabase.client import fetch_user_by_id
            user = fetch_user_by_id(user_id)
            if not user:
                return False
            
            db_prefer_name = user.get('prefer_name')
            
            # Compare (handle None cases)
            cached_prefer_name = cached_prefer_name or None
            db_prefer_name = db_prefer_name or None
            
            changed = cached_prefer_name != db_prefer_name
            if changed:
                logger.info(f"prefer_name changed for user {user_id}: {cached_prefer_name} -> {db_prefer_name}")
            
            return changed
        except Exception as e:
            logger.warning(f"Error checking prefer_name change for user {user_id}: {e}")
            return False
    
    def _check_spiritual_beliefs_changed(self, user_id: str) -> bool:
        """
        Check if spiritual_beliefs has changed.
        
        Note: spiritual_beliefs is not currently cached in user_persona.json,
        so we compare against the last known value from database.
        For now, we'll fetch and compare directly.
        
        Args:
            user_id: User UUID to check
            
        Returns:
            True if spiritual_beliefs changed, False if unchanged or error
        """
        try:
            # Get from user_persona.json (if stored)
            from ..supabase.auth import _load_user_persona
            cached_spiritual_beliefs = None
            try:
                persona_data = _load_user_persona()
                cached_spiritual_beliefs = persona_data.get('spiritual_beliefs')
            except (FileNotFoundError, ValueError):
                pass
            
            # Fetch from database
            from ..supabase.client import fetch_user_by_id
            user = fetch_user_by_id(user_id)
            if not user:
                return False
            
            db_spiritual_beliefs = user.get('spiritual_beliefs')
            
            # Compare (handle None cases)
            cached_spiritual_beliefs = cached_spiritual_beliefs or None
            db_spiritual_beliefs = db_spiritual_beliefs or None
            
            changed = cached_spiritual_beliefs != db_spiritual_beliefs
            if changed:
                logger.info(f"spiritual_beliefs changed for user {user_id}: {cached_spiritual_beliefs} -> {db_spiritual_beliefs}")
            
            return changed
        except Exception as e:
            logger.warning(f"Error checking spiritual_beliefs change for user {user_id}: {e}")
            return False

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

def check_user_preferences_changed(user_id: str) -> Dict[str, bool]:
    """
    Check if any user preferences have changed.
    
    Checks:
    - language: Compares cached language with database
    - prefer_name: Compares user_persona.json with database
    - spiritual_beliefs: Compares user_persona.json with database
    
    Args:
        user_id: User UUID to check
        
    Returns:
        Dictionary with keys 'language', 'prefer_name', 'spiritual_beliefs'
        Values are True if changed, False if unchanged or error
    """
    changes = {
        'language': False,
        'prefer_name': False,
        'spiritual_beliefs': False
    }
    
    try:
        # Check language
        changes['language'] = _resolver._check_language_changed(user_id)
        
        # Check prefer_name
        changes['prefer_name'] = _resolver._check_prefer_name_changed(user_id)
        
        # Check spiritual_beliefs
        changes['spiritual_beliefs'] = _resolver._check_spiritual_beliefs_changed(user_id)
        
    except Exception as e:
        logger.warning(f"Error checking user preferences for {user_id}: {e}")
    
    return changes

def force_refresh_user_configs(user_id: str) -> None:
    """
    Force refresh both language and config caches for user.
    Invalidates cache so next access will fetch fresh from database.
    
    Args:
        user_id: User UUID to refresh
    """
    _resolver.invalidate_user(user_id)
    logger.info(f"Force refreshed configs for user {user_id}")