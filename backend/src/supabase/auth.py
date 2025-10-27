"""
Authentication and user identity placeholder.
Currently returns DEV_USER_ID from environment.
Future: Will resolve from JWT/session token.
"""
import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Default dev user ID (fallback)
DEFAULT_DEV_USER_ID = "8517c97f-66ef-4955-86ed-531013d33d3e"

def get_current_user_id() -> str:
    """
    Get the current user ID for this session.
    
    Current behavior: Returns DEV_USER_ID from environment or default.
    Future behavior: Will extract from JWT token or session context.
    """
    user_id = os.getenv("DEV_USER_ID", DEFAULT_DEV_USER_ID)
    logger.info(f"Current user ID: {user_id}")
    return user_id

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
