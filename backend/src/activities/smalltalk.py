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

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.components.conversation_audio_manager import ConversationAudioManager
from src.components.conversation_session import ConversationSession
from src.components._pipeline_smalltalk import SmallTalkSession, TerminationPhraseDetected, normalize_text
from src.utils.config_loader import get_deepseek_config
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id

logger = logging.getLogger(__name__)


class SmallTalkActivity:
    """
    SmallTalk Activity Class
    
    Direct orchestrator that composes conversation components to provide
    SmallTalk functionality without the intermediate manager layer.
    """
    
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        """Initialize the SmallTalk activity"""
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()
        
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
            self.stt_service = GoogleSTTService(language=stt_lang, sample_rate=16000)
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
                audio_config=audio_config
            )
            logger.info("✓ ConversationAudioManager initialized")
            
            # Store audio config for callback methods
            self.audio_config = audio_config
            
            # Initialize ConversationSession
            logger.info("Initializing ConversationSession...")
            self.session_manager = ConversationSession(
                max_turns=self.global_smalltalk_config.get("max_turns", 20),
                system_prompt=self.smalltalk_config.get("system_prompt", "You are a friendly assistant. Do not use emojis."),
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
                system_prompt=self.smalltalk_config.get("system_prompt", "You are a friendly assistant. Do not use emojis."),
                language_code=stt_lang
            )
            logger.info("✓ SmallTalkSession initialized")
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize SmallTalk activity: {e}", exc_info=True)
            return False
    
    def start(self) -> bool:
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
            
            # Check if audio files should be used
            use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
            
            # Play startup audio if enabled
            if use_audio_files:
                startup_audio_path = self.backend_dir / self.audio_config["start_audio_path"]
                self.audio_manager.play_audio_file(str(startup_audio_path))
            
            # TTS prompt from config
            try:
                prompts = self.smalltalk_config.get("prompts", {})
                start_prompt = prompts.get("start", "Hello! I'm here to chat with you. What's on your mind?")
            except Exception as e:
                logger.warning(f"Failed to load start prompt from config: {e}")
                start_prompt = "Hello! I'm here to chat with you. What's on your mind?"
            
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
        """Complete cleanup of all resources"""
        logger.info("🧹 Cleaning up SmallTalk activity resources...")
        
        # Stop if still active
        if self._active:
            self.stop()
        
        # Cleanup audio manager
        if self.audio_manager:
            try:
                logger.info("🧹 Cleaning up audio manager...")
                self.audio_manager.cleanup()
                self.audio_manager = None
            except Exception as e:
                logger.warning(f"Error during audio manager cleanup: {e}")
        
        # End conversation in database
        if self.session_manager:
            try:
                logger.info("🧹 Ending conversation in database...")
                self.session_manager.end_conversation()
                self.session_manager = None
            except Exception as e:
                logger.warning(f"Error during session cleanup: {e}")
        
        # Cleanup LLM pipeline
        if self.llm_pipeline:
            try:
                logger.info("🧹 Cleaning up LLM pipeline...")
                self.llm_pipeline = None
            except Exception as e:
                logger.warning(f"Error during LLM pipeline cleanup: {e}")
        
        # Cleanup STT service
        if self.stt_service:
            try:
                logger.info("🧹 Cleaning up STT service...")
                self.stt_service = None
            except Exception as e:
                logger.warning(f"Error during STT cleanup: {e}")
        
        # Reset initialization state
        self._initialized = False
        
        logger.info("✅ SmallTalk activity cleanup completed")
    
    def _speak(self, text: str):
        """Speak text using TTS"""
        if not self.llm_pipeline or not self.llm_pipeline.tts:
            return
        
        try:
            def text_gen():
                yield text
            
            # Generate PCM chunks
            pcm_chunks = self.llm_pipeline.tts.stream_synthesize(text_gen())
            
            # Play chunks
            self.audio_manager.play_tts_stream(pcm_chunks)
        except Exception as e:
            logger.error(f"TTS error: {e}")
    
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
                    if self.session_manager:
                        self.session_manager.stop_session()
                    self.stop()
                    
                    # Also stop the audio manager to prevent further speech capture
                    if self.audio_manager:
                        self.audio_manager.stop()
                    break
                
                # Generate and play response
                logger.info("[Assistant speaking]")
                try:
                    response_chunks = self.llm_pipeline._stream_llm_and_tts()
                    self.audio_manager.play_tts_stream(response_chunks)
                except Exception as e:
                    logger.error(f"Error during LLM/TTS processing: {e}")
                    continue
                
                # Get assistant text and save to database
                assistant_text = self.llm_pipeline.messages[-1]["content"]
                self.session_manager.add_message("assistant", assistant_text)
                
                # Complete turn and reset silence timer
                if not self.session_manager.complete_turn(user_text, assistant_text):
                    logger.info("Max turns reached, ending session")
                    break
                
                self.audio_manager.reset_silence_timer()
                
                # Check if activity was stopped after turn completion
                if not self._active:
                    logger.info("Activity stopped after turn completion, exiting conversation loop")
                    break
            
            logger.info("✅ Conversation loop completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error in conversation loop: {e}", exc_info=True)
            return False
    
    def _handle_nudge(self):
        """Handle silence nudge callback"""
        logger.info("🔔 Handling silence nudge...")
        
        use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
        
        # Play nudge audio if enabled
        if use_audio_files:
            nudge_audio_path = self.backend_dir / self.audio_config["nudge_audio_path"]
            self.audio_manager.play_audio_file(str(nudge_audio_path))
        
        # TTS prompt from config
        try:
            prompts = self.smalltalk_config.get("prompts", {})
            nudge_prompt = prompts.get("nudge", "Are you still there? Feel free to continue our conversation.")
        except Exception as e:
            logger.warning(f"Failed to load nudge prompt from config: {e}")
            nudge_prompt = "Are you still there? Feel free to continue our conversation."
        
        self._speak(nudge_prompt)
    
    def _handle_timeout(self):
        """Handle silence timeout callback"""
        logger.info("⏰ Handling silence timeout...")
        
        use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
        
        # Play termination audio if enabled
        if use_audio_files:
            termination_audio_path = self.backend_dir / self.audio_config["termination_audio_path"]
            self.audio_manager.play_audio_file(str(termination_audio_path))
        
        # TTS prompt from config
        try:
            prompts = self.smalltalk_config.get("prompts", {})
            timeout_prompt = prompts.get("timeout", "It seems you've stepped away. I'll be here when you're ready to talk again.")
        except Exception as e:
            logger.warning(f"Failed to load timeout prompt from config: {e}")
            timeout_prompt = "It seems you've stepped away. I'll be here when you're ready to talk again."
        
        self._speak(timeout_prompt)
        
        # Stop both the activity and session manager
        if self.session_manager:
            self.session_manager.stop_session()
        self.stop()
        
        # Also stop the audio manager to prevent further speech capture
        if self.audio_manager:
            self.audio_manager.stop()
    
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
