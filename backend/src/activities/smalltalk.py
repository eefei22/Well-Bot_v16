#!/usr/bin/env python3
"""
SmallTalk Activity Class
A direct orchestrator that composes conversation components for SmallTalk functionality.
"""

import os
import sys
import logging
import threading
import time
import json
from pathlib import Path
from typing import Optional
import gc
import os
import tempfile
import requests

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

# Use lazy imports from __init__.py to prevent cascade import issues
from src.components import (
    GoogleSTTService,
    MicStream,
    ConversationAudioManager,
    ConversationSession,
    SmallTalkSession,
    TerminationPhraseDetected,
    normalize_text
)
from src.utils.config_loader import get_deepseek_config
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id
from src.supabase.database import get_user_language
from src.components import UserContextInjector

logger = logging.getLogger(__name__)

# Language name mapping for system prompt
LANGUAGE_NAMES = {
    'en': 'English',
    'cn': 'Chinese',
    'bm': 'Bahasa Malay'
}


class SmallTalkActivity:
    """
    SmallTalk Activity Class
    
    Direct orchestrator that composes conversation components to provide
    SmallTalk functionality without the intermediate manager layer.
    """
    
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None, ui_interface = None):
        """Initialize the SmallTalk activity"""
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()
        self.ui_interface = ui_interface
        
        # Components (initialized in initialize())
        self.audio_manager: Optional[ConversationAudioManager] = None
        self.session_manager: Optional[ConversationSession] = None
        self.llm_pipeline: Optional[SmallTalkSession] = None
        self.stt_service: Optional[GoogleSTTService] = None
        self.audio_config: Optional[dict] = None
        
        # Activity state
        self._active = False
        self._initialized = False
        
        logger.info(f"SmallTalkActivity initialized for user {self.user_id}")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            logger.info(f"Initializing SmallTalk activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            
            # Load user-specific configurations
            logger.info(f"Loading configs for user {self.user_id}")
            self.global_config = get_global_config_for_user(self.user_id)
            self.language_config = get_language_config(self.user_id)
            
            # Extract configs
            self.smalltalk_config = self.language_config.get("smalltalk", {})
            self.audio_paths = self.language_config.get("audio_paths", {})
            self.global_smalltalk_config = self.global_config.get("smalltalk", {})
            
            logger.info(f"Configs loaded - Global section keys: {list(self.global_config.keys())}")
            logger.info(f"Language config section keys: {list(self.language_config.keys())}")
            
            # Initialize STT service
            logger.info("Initializing STT service...")
            stt_lang = self.global_config["language_codes"]["stt_language_code"]
            audio_settings = self.global_config.get("audio_settings", {})
            stt_sample_rate = audio_settings.get("stt_sample_rate", 16000)
            self.stt_service = GoogleSTTService(language=stt_lang, sample_rate=stt_sample_rate)
            logger.info("✓ STT service initialized")
            
            # Create mic factory
            def mic_factory():
                return MicStream()
            
            # Prepare audio configuration for ConversationAudioManager
            audio_config = {
                "backend_dir": str(self.backend_dir),
                "silence_timeout_seconds": self.global_smalltalk_config.get("silence_timeout_seconds", 30),
                "nudge_timeout_seconds": self.global_smalltalk_config.get("nudge_timeout_seconds", 15),
                "nudge_pre_delay_ms": self.global_smalltalk_config.get("nudge_pre_delay_ms", 200),
                "nudge_post_delay_ms": self.global_smalltalk_config.get("nudge_post_delay_ms", 300),
                "nudge_audio_path": self.audio_paths.get("nudge_audio_path"),
                "termination_audio_path": self.audio_paths.get("termination_audio_path"),
                "end_audio_path": self.audio_paths.get("end_audio_path"),
                "start_audio_path": self.audio_paths.get("start_smalltalk_audio_path")
            }
            
            # Initialize ConversationAudioManager
            logger.info("Initializing ConversationAudioManager...")
            self.audio_manager = ConversationAudioManager(
                stt_service=self.stt_service,
                mic_factory=mic_factory,
                audio_config=audio_config,
                ui_interface=self.ui_interface
            )
            logger.info("✓ ConversationAudioManager initialized")
            
            # Store audio config for callback methods
            self.audio_config = audio_config
            
            # Get user language for system prompt
            user_lang = get_user_language(self.user_id) or 'en'
            language_name = LANGUAGE_NAMES.get(user_lang, 'English')
            
            # Build system prompt with language instruction
            base_system_prompt = self.smalltalk_config.get("system_prompt", "You are a friendly assistant. Do not use emojis and always always ask follow up questions.")
            system_prompt_with_language = f"{base_system_prompt}\n\nImportant: Always respond in {language_name}. This is the user's preferred language."
            
            # Initialize ConversationSession
            logger.info("Initializing ConversationSession...")
            self.session_manager = ConversationSession(
                max_turns=self.global_smalltalk_config.get("max_turns", 20),
                system_prompt=system_prompt_with_language,
                language_code=stt_lang
            )
            logger.info("✓ ConversationSession initialized")
            
            # Initialize LLM pipeline
            logger.info("Initializing SmallTalkSession...")
            deepseek_config = get_deepseek_config()
            self.llm_pipeline = SmallTalkSession(
                stt=self.stt_service,
                mic_factory=mic_factory,
                deepseek_config=deepseek_config,
                llm_config_path=None,  # No longer needed
                llm_config_dict=self.smalltalk_config,  # Pass config dict directly
                tts_voice_name=self.global_config["language_codes"]["tts_voice_name"],
                tts_language_code=self.global_config["language_codes"]["tts_language_code"],
                system_prompt=system_prompt_with_language,
                language_code=stt_lang
            )
            logger.info("✓ SmallTalkSession initialized")
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize SmallTalk activity: {e}", exc_info=True)
            return False
    
    def add_system_message(self, content: str):
        """Inject a system message into the LLM pipeline before starting."""
        if self.llm_pipeline:
            self.llm_pipeline.messages.append({"role": "system", "content": content})
    
    def _should_notify_context_processor(self) -> bool:
        """
        Check if context processor should be notified based on turn count.
        
        Returns:
            True if turn count >= 4, False otherwise
        """
        if not self.session_manager:
            logger.warning("Session manager not available, cannot check turn count")
            return False
        
        turn_count = self.session_manager.get_turn_count()
        should_notify = turn_count >= 4
        
        if should_notify:
            logger.info(f"Turn count ({turn_count}) >= 4, context processor will be notified")
        else:
            logger.info(f"Turn count ({turn_count}) < 4, skipping context processor notification")
        
        return should_notify
    
    def notify_context_processor(self, user_id: str, conversation_id: Optional[str] = None) -> bool:
        """
        Notify the context processor service to reprocess context after a conversation completes.
        
        Args:
            user_id: UUID of the user whose context needs updating
            conversation_id: Optional conversation ID (for logging)
            
        Returns:
            True if successful, False otherwise
        """
        # Add log at the very start to confirm function is being called
        logger.info(f"=== notify_context_processor CALLED for user {user_id} ===")
        
        # Get context service URL from config or use default
        context_service_url = self.global_config.get("context_service_url", "http://localhost:8000")
        enable_context_processing = self.global_config.get("enable_context_processing", True)
        
        logger.info(f"Context processing config - URL: {context_service_url}, Enabled: {enable_context_processing}")
        
        if not enable_context_processing:
            logger.warning("Context processing is disabled in config - skipping notification")
            return False
        
        endpoint = f"{context_service_url}/api/context/process"
        
        # Add detailed logging
        logger.info(f"Attempting to notify context processor:")
        logger.info(f"  Endpoint: {endpoint}")
        logger.info(f"  User ID: {user_id}")
        logger.info(f"  Conversation ID: {conversation_id}")
        
        try:
            # First, verify service is reachable (optional health check)
            try:
                health_url = f"{context_service_url}/health"
                logger.debug(f"Checking context service health at: {health_url}")
                health_response = requests.get(health_url, timeout=5)
                if health_response.status_code == 200:
                    logger.info(f"Context service is running: {health_response.json()}")
                else:
                    logger.warning(f"Context service health check returned status {health_response.status_code}")
            except requests.exceptions.RequestException as health_e:
                logger.warning(f"Context service health check failed (continuing anyway): {health_e}")
            except Exception as health_e:
                logger.warning(f"Unexpected error during health check (continuing anyway): {health_e}")
            
            # Make the processing request
            logger.info(f"Making POST request to context processor...")
            response = requests.post(
                endpoint,
                json={"user_id": user_id},
                headers={"Content-Type": "application/json"},
                timeout=300  # 5 minutes - processing can take 1-3 minutes
            )
            
            # Log response status and details
            logger.info(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {dict(response.headers)}")
            
            # Check for HTTP errors before raising
            if response.status_code >= 400:
                error_text = response.text[:500] if response.text else "No error message"
                logger.error(f"Context processor returned error {response.status_code}: {error_text}")
                try:
                    error_json = response.json()
                    logger.error(f"Error details: {error_json}")
                except:
                    pass
                return False
            
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"Context processing completed for user {user_id}")
            logger.info(f"  Status: {result.get('status')}")
            logger.info(f"  Facts extracted: {result.get('facts') is not None}")
            logger.info(f"  Persona summary extracted: {result.get('persona_summary') is not None}")
            
            return True
            
        except requests.exceptions.Timeout:
            logger.error(f"Context processor request timed out for user {user_id} (after 300s)")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to context processor at {endpoint}: {e}")
            logger.error(f"  Please verify the service is running at {context_service_url}")
            return False
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error from context processor: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    logger.error(f"Error details: {error_detail}")
                except:
                    error_text = e.response.text[:500] if e.response.text else "No error message"
                    logger.error(f"Error response text: {error_text}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Request exception during context processing notification: {e}")
            logger.error(f"  Error type: {type(e).__name__}")
            logger.exception(e)
            return False
        except Exception as e:
            logger.error(f"Unexpected error during context processing notification: {e}")
            logger.exception(e)  # This will log the full traceback
            return False

    def start(self, *, seed_system_prompt: Optional[str] = None, custom_start_prompt: Optional[str] = None) -> bool:
        """Start the SmallTalk activity"""
        if not self._initialized:
            logger.error("Activity not initialized")
            return False
        
        if self._active:
            logger.warning("Activity already active")
            return False
        
        # Safety checks
        if not all([self.audio_manager, self.session_manager, self.llm_pipeline]):
            logger.error("❌ Components not properly initialized - cannot start activity")
            return False
        
        try:
            logger.info("🚀 Starting SmallTalk activity...")
            self._active = True
            
            # Start session
            conv_id = self.session_manager.start_session("Small Talk")
            self.llm_pipeline.conversation_id = conv_id
            
            # Inject user context using component
            injector = UserContextInjector()
            context_result = injector.inject_context(
                user_id=self.user_id,
                llm_pipeline=self.llm_pipeline,
                backend_dir=self.backend_dir,
                logger_instance=logger
            )
            
            # Log results but continue regardless of success/failure
            if context_result['success']:
                logger.info(f"Context injection completed: persona={context_result['persona_injected']}, facts={context_result['facts_injected']}, fallback={context_result['used_fallback']}")
            else:
                logger.warning(f"Context injection failed: {context_result.get('error')} - continuing without context")
            
            # Check if audio files should be used
            use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
            
            # Play startup audio if enabled
            if use_audio_files:
                startup_audio_path = self.backend_dir / self.audio_config["start_audio_path"]
                self.audio_manager.play_audio_file(str(startup_audio_path))
            
            # Optionally inject a system message for context seeding
            if seed_system_prompt:
                self.add_system_message(seed_system_prompt)

            # TTS prompt from config or custom override
            try:
                prompts = self.smalltalk_config.get("prompts", {})
                default_start = prompts.get("start", "Hello! I'm here to chat with you. What's on your mind?")
                start_prompt = custom_start_prompt or default_start
            except Exception as e:
                logger.warning(f"Failed to load start prompt from config: {e}")
                start_prompt = custom_start_prompt or "Hello! I'm here to chat with you. What's on your mind?"
            
            self._speak(start_prompt)
            
            # Start silence monitoring
            self.audio_manager.start_silence_monitoring(
                on_nudge=self._handle_nudge,
                on_timeout=self._handle_timeout
            )
            
            logger.info("✅ SmallTalk activity started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start SmallTalk activity: {e}", exc_info=True)
            self._active = False
            return False
    
    def stop(self):
        """Stop the SmallTalk activity"""
        if not self._active:
            logger.warning("Activity not active")
            return
        
        logger.info("🛑 Stopping SmallTalk activity...")
        self._active = False
        
        # Stop silence monitoring
        if self.audio_manager:
            self.audio_manager.stop_silence_monitoring()
        
        # Stop session
        if self.session_manager:
            self.session_manager.stop_session()
        
        logger.info("✅ SmallTalk activity stopped")
    
    def cleanup(self):
        """Complete cleanup of all resources including native libraries, cached resources, and dependencies"""
        logger.info("🧹 Cleaning up SmallTalk activity resources...")
        
        # Stop if still active
        if self._active:
            self.stop()
        
        # Cleanup LLM pipeline first (may have active connections/streams)
        if self.llm_pipeline:
            try:
                logger.info("🧹 Cleaning up LLM pipeline...")
                # Close TTS client if it exists
                if hasattr(self.llm_pipeline, 'tts') and self.llm_pipeline.tts:
                    if hasattr(self.llm_pipeline.tts, 'client'):
                        try:
                            # Google Cloud TTS client cleanup
                            self.llm_pipeline.tts.client = None
                            logger.debug("TTS client closed")
                        except Exception as e:
                            logger.warning(f"Error closing TTS client: {e}")
                
                # Close LLM client if it exists
                if hasattr(self.llm_pipeline, 'llm') and self.llm_pipeline.llm:
                    if hasattr(self.llm_pipeline.llm, 'client'):
                        try:
                            # Close HTTP client connections if applicable
                            if hasattr(self.llm_pipeline.llm.client, 'close'):
                                self.llm_pipeline.llm.client.close()
                            logger.debug("LLM client closed")
                        except Exception as e:
                            logger.warning(f"Error closing LLM client: {e}")
                
                # Cleanup termination detector
                if hasattr(self.llm_pipeline, 'termination_detector'):
                    self.llm_pipeline.termination_detector = None
                
                # Clear messages
                if hasattr(self.llm_pipeline, 'messages'):
                    self.llm_pipeline.messages.clear()
                
                self.llm_pipeline = None
                logger.info("✓ LLM pipeline cleaned up")
            except Exception as e:
                logger.warning(f"Error during LLM pipeline cleanup: {e}")
        
        # Cleanup audio manager (handles PyAudio streams)
        if self.audio_manager:
            try:
                logger.info("🧹 Cleaning up audio manager...")
                self.audio_manager.cleanup()
                self.audio_manager = None
                logger.info("✓ Audio manager cleaned up")
            except Exception as e:
                logger.warning(f"Error during audio manager cleanup: {e}")
        
        # Cleanup STT service (Google Cloud Speech client)
        if self.stt_service:
            try:
                logger.info("🧹 Cleaning up STT service...")
                # Close Google Cloud Speech client
                if hasattr(self.stt_service, 'client') and self.stt_service.client:
                    try:
                        # Google Cloud clients don't have explicit close, but we can clear the reference
                        self.stt_service.client = None
                        logger.debug("STT client closed")
                    except Exception as e:
                        logger.warning(f"Error closing STT client: {e}")
                self.stt_service = None
                logger.info("✓ STT service cleaned up")
            except Exception as e:
                logger.warning(f"Error during STT cleanup: {e}")
        
        # End conversation in database
        conversation_id = None
        if self.session_manager:
            try:
                conversation_id = self.session_manager.get_conversation_id()
                logger.info("🧹 Ending conversation in database...")
                self.session_manager.end_conversation()
                self.session_manager = None
                logger.info("✓ Session manager cleaned up")
            except Exception as e:
                logger.warning(f"Error during session cleanup: {e}")
        
        # Notify context processor service (non-blocking) - only if >= 4 turns
        # Use non-daemon thread for cleanup to ensure it completes
        if self.user_id and self._should_notify_context_processor():
            try:
                # Run in a separate thread to avoid blocking cleanup
                def notify_async():
                    try:
                        logger.info(f"Async thread started for context processor notification (cleanup)")
                        result = self.notify_context_processor(self.user_id, conversation_id)
                        logger.info(f"Async context processor notification completed: {result}")
                    except Exception as e:
                        logger.error(f"Error in async context processor notification: {e}")
                        logger.exception(e)
                
                # Use non-daemon thread for cleanup so it can complete even if main thread exits
                thread = threading.Thread(target=notify_async, daemon=False)
                thread.start()
                logger.info(f"✓ Context processor notification thread started (non-daemon, thread_id={thread.ident})")
                # Give the thread a moment to start the request
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Failed to start context processor notification thread: {e}")
                logger.exception(e)
        elif self.user_id:
            logger.info("Skipping context processor notification - turn count < 4")
        
        # Clear config caches (optional - only if you want to clear on each cleanup)
        try:
            from src.utils.config_resolver import _resolver
            if hasattr(_resolver, 'clear_cache'):
                logger.info("🧹 Clearing config caches...")
                _resolver.clear_cache()
                logger.debug("Config caches cleared")
        except Exception as e:
            logger.debug(f"Could not clear config cache: {e}")
        
        # Cleanup temporary files (if any were created)
        try:
            logger.info("🧹 Checking for temporary files...")
            # Check for temporary Google Cloud credentials file
            # Note: This is a best-effort cleanup - the file may have been cleaned up already
            temp_dir = tempfile.gettempdir()
            # We can't easily track which temp files we created, so this is optional
            # If you track temp file paths, clean them up here
            logger.debug("Temporary file check completed")
        except Exception as e:
            logger.debug(f"Could not check temporary files: {e}")
        
        # Force garbage collection to help release native library resources
        try:
            logger.info("🧹 Running garbage collection...")
            collected = gc.collect()
            logger.debug(f"Garbage collection collected {collected} objects")
        except Exception as e:
            logger.warning(f"Error during garbage collection: {e}")
        
        # Reset initialization state
        self._initialized = False
        
        logger.info("✅ SmallTalk activity cleanup completed")
    
    def _speak(self, text: str, is_nudge: bool = False):
        """Speak text using TTS
        
        Args:
            text: Text to speak
            is_nudge: If True, apply delays to prevent STT from picking up the audio
        """
        if not text:
            logger.warning("_speak called with empty text")
            return
            
        if not self.llm_pipeline:
            logger.error("Cannot speak: llm_pipeline is None")
            return
            
        if not self.llm_pipeline.tts:
            logger.error("Cannot speak: llm_pipeline.tts is None")
            return
        
        try:
            logger.debug(f"TTS: Synthesizing '{text[:50]}...' (is_nudge={is_nudge})")
            def text_gen():
                yield text
            
            # Generate PCM chunks
            pcm_chunks = self.llm_pipeline.tts.stream_synthesize(text_gen())
            
            # Play chunks (with delays if nudge)
            self.audio_manager.play_tts_stream(pcm_chunks, use_nudge_delays=is_nudge)
            logger.debug("TTS: Audio playback completed")
        except Exception as e:
            logger.error(f"TTS error: {e}", exc_info=True)
    
    def reinitialize(self) -> bool:
        """Re-initialize the activity for subsequent runs"""
        logger.info("🔄 Re-initializing SmallTalk activity...")
        
        # Reset state
        self._active = False
        self._initialized = False
        
        # Re-initialize components
        return self.initialize()
    
    def is_active(self) -> bool:
        """Check if the activity is currently active"""
        return self._active and self.session_manager and self.session_manager.is_active()
    
    def run(self) -> bool:
        """
        Run the complete activity: start, conversation loop, and stop
        
        Returns:
            True if activity completed successfully, False otherwise
        """
        logger.info("🎬 SmallTalkActivity.run() - Starting activity execution")
        try:
            # Start the activity
            if not self.start():
                logger.error("❌ SmallTalkActivity.run() - Failed to start activity")
                return False
            
            # Run conversation loop
            success = self._conversation_loop()
            
            # Stop the activity
            self.stop()
            
            return success
            
        except Exception as e:
            logger.error(f"Error running SmallTalk activity: {e}", exc_info=True)
            self.stop()
            self.cleanup()  # Ensure cleanup is called to trigger context processor
            return False
    
    def _conversation_loop(self) -> bool:
        """Main conversation loop"""
        logger.info("💬 Starting conversation loop...")
        
        try:
            while self.session_manager.is_active() and self._active:
                # Capture user speech with timeout
                user_text = self.audio_manager.capture_user_speech()
                if not user_text:
                    logger.debug("No user text captured, continuing...")
                    continue
                
                # Check if activity was stopped during speech capture
                if not self._active:
                    logger.info("Activity stopped during speech capture, exiting conversation loop")
                    break
                
                # Log user input
                logger.info(f"[User] raw_text = '{user_text}'")
                normalized = normalize_text(user_text)
                logger.info(f"[User] normalized_text = '{normalized}'")
                
                # Add user message to LLM pipeline memory
                self.llm_pipeline.messages.append({"role": "user", "content": user_text})
                
                # Save user message to database
                self.session_manager.add_message("user", user_text, intent="small_talk")
                
                # Check for termination phrases
                logger.info("Checking for termination BEFORE LLM processing...")
                try:
                    self.llm_pipeline.check_termination(user_text)
                    logger.info("No termination detected, proceeding with conversation...")
                except TerminationPhraseDetected as e:
                    logger.info(f"TERMINATION TRIGGERED! {e}")
                    
                    use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
                    
                    # Play end audio if enabled
                    if use_audio_files:
                        end_audio_path = self.backend_dir / self.audio_config["end_audio_path"]
                        self.audio_manager.play_audio_file(str(end_audio_path))
                    
                    # TTS prompt from config
                    try:
                        prompts = self.smalltalk_config.get("prompts", {})
                        end_prompt = prompts.get("end", "Goodbye! Take care and talk to you soon.")
                    except Exception as e:
                        logger.warning(f"Failed to load end prompt from config: {e}")
                        end_prompt = "Goodbye! Take care and talk to you soon."
                    
                    self._speak(end_prompt)
                    
                    # Stop both the activity and session manager
                    conversation_id = None
                    if self.session_manager:
                        conversation_id = self.session_manager.get_conversation_id()
                        self.session_manager.stop_session()
                    self.stop()
                    
                    # Also stop the audio manager to prevent further speech capture
                    if self.audio_manager:
                        self.audio_manager.stop()
                    
                    # Notify context processor service (non-blocking) - only if >= 4 turns
                    if self.user_id and self._should_notify_context_processor():
                        try:
                            def notify_async():
                                try:
                                    logger.info(f"Async thread started for context processor notification (termination)")
                                    result = self.notify_context_processor(self.user_id, conversation_id)
                                    logger.info(f"Async context processor notification completed: {result}")
                                except Exception as e:
                                    logger.error(f"Error in async context processor notification: {e}")
                                    logger.exception(e)
                            
                            thread = threading.Thread(target=notify_async, daemon=True)
                            thread.start()
                            logger.info(f"✓ Context processor notification thread started (async, thread_id={thread.ident})")
                        except Exception as e:
                            logger.error(f"Failed to start context processor notification thread: {e}")
                            logger.exception(e)
                    elif self.user_id:
                        logger.info("Skipping context processor notification - turn count < 4")
                    
                    break
                
                # Generate and play response
                logger.info("[Assistant speaking]")
                # Mute microphone BEFORE LLM streaming starts (LLM streaming happens immediately in _stream_llm_and_tts)
                with self.audio_manager._mic_lock:
                    if self.audio_manager._current_mic and self.audio_manager._current_mic.is_running():
                        self.audio_manager._current_mic.mute()
                        logger.debug("Microphone muted before LLM/TTS processing")
                
                try:
                    response_chunks = self.llm_pipeline._stream_llm_and_tts()
                    self.audio_manager.play_tts_stream(response_chunks)
                except Exception as e:
                    logger.error(f"Error during LLM/TTS processing: {e}")
                    # Ensure mic is unmuted even if there's an error
                    with self.audio_manager._mic_lock:
                        if self.audio_manager._current_mic and self.audio_manager._current_mic.is_running():
                            self.audio_manager._current_mic.unmute()
                            logger.debug("Microphone unmuted after error")
                    continue
                
                # Get assistant text and save to database
                assistant_text = self.llm_pipeline.messages[-1]["content"]
                self.session_manager.add_message("assistant", assistant_text)
                
                # Complete turn and reset silence timer
                if not self.session_manager.complete_turn(user_text, assistant_text):
                    logger.info("Max turns reached, ending session")
                    # Notify context processor service (non-blocking) - only if >= 4 turns
                    conversation_id = self.session_manager.get_conversation_id() if self.session_manager else None
                    if self.user_id and self._should_notify_context_processor():
                        try:
                            def notify_async():
                                try:
                                    logger.info(f"Async thread started for context processor notification (max_turns)")
                                    result = self.notify_context_processor(self.user_id, conversation_id)
                                    logger.info(f"Async context processor notification completed: {result}")
                                except Exception as e:
                                    logger.error(f"Error in async context processor notification: {e}")
                                    logger.exception(e)
                            
                            thread = threading.Thread(target=notify_async, daemon=True)
                            thread.start()
                            logger.info(f"✓ Context processor notification thread started (async, thread_id={thread.ident})")
                        except Exception as e:
                            logger.error(f"Failed to start context processor notification thread: {e}")
                            logger.exception(e)
                    elif self.user_id:
                        logger.info("Skipping context processor notification - turn count < 4")
                    break
                
                self.audio_manager.reset_silence_timer()
                
                # Check if activity was stopped after turn completion
                if not self._active:
                    logger.info("Activity stopped after turn completion, exiting conversation loop")
                    # Notify context processor service (non-blocking) - only if >= 4 turns
                    conversation_id = self.session_manager.get_conversation_id() if self.session_manager else None
                    if self.user_id and self._should_notify_context_processor():
                        try:
                            def notify_async():
                                try:
                                    logger.info(f"Async thread started for context processor notification (stopped)")
                                    result = self.notify_context_processor(self.user_id, conversation_id)
                                    logger.info(f"Async context processor notification completed: {result}")
                                except Exception as e:
                                    logger.error(f"Error in async context processor notification: {e}")
                                    logger.exception(e)
                            
                            thread = threading.Thread(target=notify_async, daemon=True)
                            thread.start()
                            logger.info(f"✓ Context processor notification thread started (async, thread_id={thread.ident})")
                        except Exception as e:
                            logger.error(f"Failed to start context processor notification thread: {e}")
                            logger.exception(e)
                    elif self.user_id:
                        logger.info("Skipping context processor notification - turn count < 4")
                    break
            
            logger.info("✅ Conversation loop completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in conversation loop: {e}", exc_info=True)
            return False
    
    def _handle_nudge(self):
        """Handle silence nudge callback"""
        logger.info("🔔 Handling silence nudge...")
        
        try:
            use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
            
            # Play nudge audio if enabled (with delays to prevent STT pickup)
            if use_audio_files:
                nudge_audio_path = self.backend_dir / self.audio_config["nudge_audio_path"]
                if nudge_audio_path.exists():
                    logger.info(f"Playing nudge audio with delays: {nudge_audio_path}")
                    self.audio_manager.play_nudge_audio_with_delays(str(nudge_audio_path))
                else:
                    logger.warning(f"Nudge audio file not found: {nudge_audio_path}")
            
            # TTS prompt from config
            try:
                prompts = self.smalltalk_config.get("prompts", {})
                nudge_prompt = prompts.get("nudge", "Are you still there? Feel free to continue our conversation.")
                logger.info(f"Nudge prompt from config: '{nudge_prompt}'")
            except Exception as e:
                logger.warning(f"Failed to load nudge prompt from config: {e}", exc_info=True)
                nudge_prompt = "Are you still there? Feel free to continue our conversation."
            
            # Speak the nudge prompt (with delays to prevent STT pickup)
            logger.info(f"Speaking nudge prompt...")
            self._speak(nudge_prompt, is_nudge=True)
            logger.info("✅ Nudge prompt spoken successfully")
            
        except Exception as e:
            logger.error(f"❌ Error in _handle_nudge: {e}", exc_info=True)
    
    def _handle_timeout(self):
        """Handle silence timeout callback"""
        logger.info("⏰ Handling silence timeout...")
        
        try:
            use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
            
            # Play termination audio if enabled
            if use_audio_files:
                termination_audio_path = self.backend_dir / self.audio_config["termination_audio_path"]
                if termination_audio_path.exists():
                    logger.info(f"Playing termination audio: {termination_audio_path}")
                    self.audio_manager.play_audio_file(str(termination_audio_path))
                else:
                    logger.warning(f"Termination audio file not found: {termination_audio_path}")
            
            # TTS prompt from config
            try:
                prompts = self.smalltalk_config.get("prompts", {})
                timeout_prompt = prompts.get("timeout", "It seems you've stepped away. I'll be here when you're ready to talk again.")
                logger.info(f"Timeout prompt from config: '{timeout_prompt}'")
            except Exception as e:
                logger.warning(f"Failed to load timeout prompt from config: {e}", exc_info=True)
                timeout_prompt = "It seems you've stepped away. I'll be here when you're ready to talk again."
            
            # Speak the timeout prompt
            logger.info(f"Speaking timeout prompt...")
            self._speak(timeout_prompt)
            logger.info("✅ Timeout prompt spoken successfully")
            
        except Exception as e:
            logger.error(f"❌ Error in _handle_timeout: {e}", exc_info=True)
        finally:
            # Always stop the activity, even if TTS fails
            logger.info("Stopping activity due to timeout...")
            
            # Stop both the activity and session manager
            conversation_id = None
            if self.session_manager:
                conversation_id = self.session_manager.get_conversation_id()
                self.session_manager.stop_session()
            self.stop()
            
            # Also stop the audio manager to prevent further speech capture
            if self.audio_manager:
                self.audio_manager.stop()
            
            # Notify context processor service (non-blocking) - only if >= 4 turns
            if self.user_id and self._should_notify_context_processor():
                try:
                    def notify_async():
                        try:
                            logger.info(f"Async thread started for context processor notification (timeout)")
                            result = self.notify_context_processor(self.user_id, conversation_id)
                            logger.info(f"Async context processor notification completed: {result}")
                        except Exception as e:
                            logger.error(f"Error in async context processor notification: {e}")
                            logger.exception(e)
                    
                    thread = threading.Thread(target=notify_async, daemon=True)
                    thread.start()
                    logger.info(f"✓ Context processor notification thread started (async, thread_id={thread.ident})")
                except Exception as e:
                    logger.error(f"Failed to start context processor notification thread: {e}")
                    logger.exception(e)
            elif self.user_id:
                logger.info("Skipping context processor notification - turn count < 4")
    
    def get_status(self) -> dict:
        """Get current activity status"""
        return {
            "initialized": self._initialized,
            "active": self._active,
            "audio_manager_active": self.audio_manager.is_active() if self.audio_manager else False,
            "session_active": self.session_manager.is_active() if self.session_manager else False,
            "activity_type": "smalltalk"
        }


# For testing when run directly
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def main():
        """Test the SmallTalk activity"""
        try:
            # Get backend directory
            backend_dir = Path(__file__).parent.parent.parent
            
            # Create and initialize activity
            activity = SmallTalkActivity(backend_dir)
            
            if not activity.initialize():
                logger.error("Failed to initialize activity")
                return 1
            
            logger.info("=== SmallTalk Activity Test ===")
            logger.info("The activity will:")
            logger.info("- Start SmallTalk session with component orchestration")
            logger.info("- Handle conversation with user using direct components")
            logger.info("- Play TTS responses with audio coordination")
            logger.info("- Monitor for termination phrases")
            logger.info("- End when user says goodbye or timeout occurs")
            logger.info("- Press Ctrl+C to stop")
            
            # Run the activity
            success = activity.run()
            
            if success:
                logger.info("=== SmallTalk Activity Test Completed Successfully! ===")
            else:
                logger.error("=== SmallTalk Activity Test Failed! ===")
                return 1
            
            return 0
            
        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            return 0
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            return 1
    
    exit(main())
