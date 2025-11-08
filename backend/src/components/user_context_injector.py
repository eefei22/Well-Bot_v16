#!/usr/bin/env python3
"""
User Context Injector Component

Handles fetching user context (persona_summary and facts) from database or local file,
and injecting it as system messages into LLM pipeline.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class UserContextInjector:
    """
    Component for injecting user context into LLM pipelines.
    
    Handles:
    - Fetching context from database (users_context_bundle table)
    - Fallback to local file (user_persona.json) if database fails
    - Saving context to local file when database fetch succeeds
    - Injecting persona_summary and facts as system messages
    - Comprehensive error handling with graceful degradation
    """
    
    def inject_context(
        self,
        user_id: str,
        llm_pipeline: Any,  # Any object with .messages list
        backend_dir: Path,
        logger_instance: Optional[logging.Logger] = None
    ) -> Dict[str, Any]:
        """
        Fetch and inject user context into LLM pipeline.
        
        Args:
            user_id: User UUID
            llm_pipeline: Object with .messages attribute (list of dicts with 'role' and 'content')
            backend_dir: Backend directory path for local file operations
            logger_instance: Optional logger instance (uses module logger if not provided)
            
        Returns:
            dict with keys:
            - success: bool - Whether injection completed (even if no context was available)
            - persona_injected: bool - Whether persona_summary was injected
            - facts_injected: bool - Whether facts were injected
            - used_fallback: bool - Whether local file fallback was used
            - error: Optional[str] - Error message if injection failed completely
        """
        log = logger_instance or logger
        
        result = {
            'success': False,
            'persona_injected': False,
            'facts_injected': False,
            'used_fallback': False,
            'error': None
        }
        
        try:
            log.info(f"Fetching context bundle for user {user_id}...")
            
            # Import here to avoid circular imports
            from ..supabase.database import (
                get_user_context_bundle,
                save_user_context_to_local,
                load_user_context_from_local
            )
            
            # Try to fetch from database
            context_bundle = None
            try:
                context_bundle = get_user_context_bundle(user_id)
            except Exception as e:
                log.warning(f"Database fetch failed: {e}")
            
            # Fallback to local file if database fetch fails
            if not context_bundle:
                log.info(f"Database fetch failed, trying local fallback...")
                try:
                    local_context = load_user_context_from_local(backend_dir)
                    if local_context and local_context.get("user_id") == user_id:
                        context_bundle = {
                            "persona_summary": local_context.get("persona_summary"),
                            "facts": local_context.get("facts")
                        }
                        result['used_fallback'] = True
                        log.info(f"✓ Loaded context from local fallback file for user {user_id}")
                    elif local_context:
                        log.warning(f"Local context file exists but for different user ({local_context.get('user_id')} vs {user_id})")
                except Exception as e:
                    log.warning(f"Local file fallback failed: {e}")
            
            # Save to local file if database fetch succeeded
            if context_bundle and not result['used_fallback']:
                try:
                    save_user_context_to_local(
                        user_id,
                        persona_summary=context_bundle.get("persona_summary"),
                        facts=context_bundle.get("facts"),
                        backend_dir=backend_dir
                    )
                except Exception as e:
                    log.warning(f"Failed to save context to local file: {e}")
            
            # Inject persona_summary if available
            persona_summary = context_bundle.get("persona_summary") if context_bundle else None
            if persona_summary and persona_summary.strip():
                try:
                    if not hasattr(llm_pipeline, 'messages'):
                        log.error("LLM pipeline does not have 'messages' attribute")
                        result['error'] = "LLM pipeline missing 'messages' attribute"
                        return result
                    
                    persona_message = f"User persona context: {persona_summary.strip()}"
                    llm_pipeline.messages.append({"role": "system", "content": persona_message})
                    result['persona_injected'] = True
                    log.info(f"✓ Persona summary injected for user {user_id}")
                    log.debug(f"  Injected prompt: {persona_message}")
                except Exception as e:
                    log.error(f"Failed to inject persona_summary: {e}")
                    result['error'] = f"Failed to inject persona_summary: {e}"
            
            # Inject facts if available
            facts = context_bundle.get("facts") if context_bundle else None
            if facts and facts.strip():
                try:
                    if not hasattr(llm_pipeline, 'messages'):
                        log.error("LLM pipeline does not have 'messages' attribute")
                        if not result['error']:
                            result['error'] = "LLM pipeline missing 'messages' attribute"
                        return result
                    
                    facts_message = f"User facts: {facts.strip()}"
                    llm_pipeline.messages.append({"role": "system", "content": facts_message})
                    result['facts_injected'] = True
                    log.info(f"✓ Facts injected for user {user_id}")
                    log.debug(f"  Injected prompt: {facts_message}")
                except Exception as e:
                    log.error(f"Failed to inject facts: {e}")
                    if not result['error']:
                        result['error'] = f"Failed to inject facts: {e}"
            
            # Mark as successful if we got here (even if no context was available)
            if not context_bundle or (not persona_summary and not facts):
                log.info(f"No context bundle available for user {user_id}, continuing without it")
            
            result['success'] = True
            return result
            
        except Exception as e:
            log.error(f"Unexpected error during context injection: {e}", exc_info=True)
            result['error'] = str(e)
            return result

