"""
Authentication and user identity placeholder.
Currently returns DEV_USER_ID from environment.
Future: Will resolve from JWT/session token.
"""
import os
from typing import Optional, Dict
import logging
from pathlib import Path
import json

logger = logging.getLogger(__name__)

# Default dev user ID (fallback)
DEFAULT_DEV_USER_ID = "8517c97f-66ef-4955-86ed-531013d33d3e"

def resolve_user_from_device_id(device_id: str) -> Dict[str, str]:
    """
    Resolve user information from device_id by querying the database.
    
    Args:
        device_id: Device UUID to look up
    
    Returns:
        Dictionary with keys: 'user_id', 'prefer_name', 'full_name'
    
    Raises:
        ValueError: If device_id is not found in database or resolution fails
    """
    from .client import fetch_user_by_device_id
    
    if not device_id:
        raise ValueError("device_id cannot be empty")
    
    logger.info(f"Resolving user from device_id: {device_id}")
    user = fetch_user_by_device_id(device_id)
    
    if not user:
        raise ValueError(f"No user found for device_id: {device_id}. Please ensure the device is registered in the database.")
    
    user_id = user.get('id')
    prefer_name = user.get('prefer_name')
    full_name = user.get('full_name')
    
    if not user_id:
        raise ValueError(f"User record found but missing user_id for device_id: {device_id}")
    
    logger.info(f"Successfully resolved user_id: {user_id} for device_id: {device_id}")
    logger.info(f"  prefer_name: {prefer_name}, full_name: {full_name}")
    
    return {
        'user_id': user_id,
        'prefer_name': prefer_name,
        'full_name': full_name
    }

def _get_user_persona_path() -> Path:
    """
    Get the path to user_persona.json file.
    
    Returns:
        Path object pointing to backend/config/user_persona.json
    """
    # Infer backend directory from current file location
    backend_dir = Path(__file__).parent.parent.parent
    return backend_dir / "config" / "user_persona.json"

def _load_user_persona() -> Dict:
    """
    Load user_persona.json file.
    
    Returns:
        Dictionary with user information
    
    Raises:
        FileNotFoundError: If user_persona.json does not exist
        ValueError: If user_persona.json is invalid or missing required fields
    """
    file_path = _get_user_persona_path()
    
    if not file_path.exists():
        raise FileNotFoundError(
            f"user_persona.json not found at {file_path}. "
            "The system must be started with a valid DEVICE_ID to resolve user information."
        )
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in user_persona.json: {e}")
    
    if not isinstance(data, dict):
        raise ValueError("user_persona.json must contain a JSON object")
    
    if 'user_id' not in data:
        raise ValueError("user_persona.json is missing required field: user_id")
    
    return data

def get_current_user_id() -> str:
    """
    Get the current user ID for this session.
    
    Reads from user_persona.json file (which is populated at startup from DEVICE_ID).
    Falls back to DEV_USER_ID environment variable for backward compatibility.
    
    Returns:
        User UUID string
    
    Raises:
        FileNotFoundError: If user_persona.json does not exist
        ValueError: If user_persona.json is invalid
    """
    try:
        data = _load_user_persona()
        user_id = data.get('user_id')
        if user_id:
            logger.debug(f"Current user ID (from user_persona.json): {user_id}")
            return user_id
    except (FileNotFoundError, ValueError) as e:
        logger.warning(f"Failed to load user_id from user_persona.json: {e}")
        # Fallback to legacy DEV_USER_ID for backward compatibility
        try:
            from ..utils.config_loader import DEV_USER_ID
            if DEV_USER_ID:
                logger.info(f"Using DEV_USER_ID fallback: {DEV_USER_ID}")
                return DEV_USER_ID
        except (ImportError, AttributeError):
            pass
        
        # Final fallback
        user_id = os.getenv("DEV_USER_ID", DEFAULT_DEV_USER_ID)
        logger.warning(f"Using default fallback user ID: {user_id}")
        return user_id
    
    # Should not reach here, but handle edge case
    raise ValueError("user_persona.json exists but user_id field is empty")

def get_user_prefer_name() -> Optional[str]:
    """
    Get the user's preferred name from user_persona.json.
    
    Returns:
        Preferred name string or None if not set/available
    """
    try:
        data = _load_user_persona()
        return data.get('prefer_name')
    except Exception as e:
        logger.warning(f"Failed to load prefer_name from user_persona.json: {e}")
        return None

def get_user_full_name() -> Optional[str]:
    """
    Get the user's full name from user_persona.json.
    
    Returns:
        Full name string or None if not set/available
    """
    try:
        data = _load_user_persona()
        return data.get('full_name')
    except Exception as e:
        logger.warning(f"Failed to load full_name from user_persona.json: {e}")
        return None

def set_session_user(user_id: str) -> None:
    """
    Set the current session user (for testing multi-user scenarios).
    Future: Will be replaced by proper auth context.
    """
    # For now, just set env var
    os.environ["DEV_USER_ID"] = user_id
    logger.info(f"Session user set to: {user_id}")

def get_user_from_token(token: str) -> Optional[str]:
    """
    Placeholder for future JWT token validation.
    Returns user_id from token.
    """
    # TODO: Implement JWT validation with Supabase Auth
    raise NotImplementedError("Auth not yet implemented")
