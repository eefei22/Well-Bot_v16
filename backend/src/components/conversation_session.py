# backend/src/components/conversation_session.py

import logging
import re
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class ConversationSession:
    """
    Manages conversation session state, turn counting, and database integration.
    
    Handles:
    - Session lifecycle (start/stop)
    - Turn counting and limits
    - Database conversation management
    - Message storage
    """
    
    def __init__(
        self,
        max_turns: int = 20,
        system_prompt: str = "You are a friendly assistant. Do not use emojis.",
        language_code: str = "en-US"
    ):
        """
        Initialize conversation session.
        
        Args:
            max_turns: Maximum number of conversation turns
            system_prompt: System prompt for the conversation
            language_code: Language code for messages
        """
        self.max_turns = max_turns
        self.system_prompt = system_prompt
        self.language_code = language_code
        
        # Session state
        self._active = False
        self._turn_count = 0
        self.conversation_id: Optional[str] = None
        
        logger.info(f"ConversationSession initialized")
        logger.info(f"Max turns: {max_turns}")
        logger.info(f"Language: {language_code}")
    
    def start_session(self, title: str = "Conversation") -> str:
        """
        Start a new conversation session.
        
        Args:
            title: Title for the conversation
            
        Returns:
            Conversation ID from database
        """
        if self._active:
            logger.warning("Session already active")
            return self.conversation_id
        
        try:
            # Import here to avoid circular imports
            from ..supabase.database import start_conversation
            
            self.conversation_id = start_conversation(title=title)
            self._active = True
            self._turn_count = 0
            
            logger.info(f"Conversation session started: {self.conversation_id}")
            return self.conversation_id
            
        except Exception as e:
            logger.error(f"Failed to start conversation: {e}")
            self._active = False
            self.conversation_id = None
            raise
    
    def stop_session(self):
        """Stop the conversation session."""
        if not self._active:
            logger.warning("Session not active")
            return
        
        logger.info("Stopping conversation session")
        self._active = False
        
        # Note: We don't call end_conversation here as it might be called
        # by the activity orchestrator after cleanup
    
    def complete_turn(self, user_text: str, assistant_text: str) -> bool:
        """
        Complete a conversation turn and update counters.
        
        Args:
            user_text: User's input text
            assistant_text: Assistant's response text
            
        Returns:
            True if session should continue, False if max turns reached
        """
        self._turn_count += 1
        
        # Clean emojis from assistant response
        clean_assistant_text = self._strip_emojis(assistant_text)
        
        logger.info(f"Turn {self._turn_count} completed")
        logger.debug(f"User: {user_text}")
        logger.debug(f"Assistant: {clean_assistant_text}")
        
        # Check if max turns reached
        if self._turn_count >= self.max_turns:
            logger.info(f"Max turns ({self.max_turns}) reached, ending session")
            self.stop_session()
            return False
        
        return True
    
    def add_message(self, role: str, content: str, intent: Optional[str] = None) -> bool:
        """
        Add a message to the database.
        
        Args:
            role: Message role ('user' or 'assistant')
            content: Message content
            intent: Intent classification (optional)
            
        Returns:
            True if successful, False otherwise
        """
        if not self.conversation_id:
            logger.warning("No active conversation to add message to")
            return False
        
        try:
            # Import here to avoid circular imports
            from ..supabase.database import add_message
            
            add_message(
                conversation_id=self.conversation_id,
                role=role,
                content=content,
                intent=intent,
                lang=self.language_code
            )
            
            logger.debug(f"Message added to database: {role}")
            return True
            
        except Exception as e:
            logger.warning(f"Could not save message: {e}")
            return False
    
    def end_conversation(self):
        """Mark the conversation as ended in the database."""
        if not self.conversation_id:
            logger.warning("No active conversation to end")
            return
        
        try:
            # Import here to avoid circular imports
            from ..supabase.database import end_conversation
            
            end_conversation(self.conversation_id)
            logger.info(f"Conversation ended: {self.conversation_id}")
            
        except Exception as e:
            logger.warning(f"Could not end conversation: {e}")
    
    def _strip_emojis(self, text: str) -> str:
        """
        Strip emojis from text.
        
        Args:
            text: Input text
            
        Returns:
            Text with emojis removed
        """
        return re.sub(r"[^\w\s.,!?'-]", "", text)
    
    def is_active(self) -> bool:
        """Check if the session is currently active."""
        return self._active
    
    def get_turn_count(self) -> int:
        """Get the current turn count."""
        return self._turn_count
    
    def get_conversation_id(self) -> Optional[str]:
        """Get the conversation ID."""
        return self.conversation_id
    
    def get_status(self) -> Dict[str, Any]:
        """Get current session status."""
        return {
            "active": self._active,
            "turn_count": self._turn_count,
            "max_turns": self.max_turns,
            "conversation_id": self.conversation_id,
            "language_code": self.language_code,
            "turns_remaining": max(0, self.max_turns - self._turn_count)
        }
