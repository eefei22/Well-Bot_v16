#!/usr/bin/env python3
"""
Activity Suggestion Activity Class
Presents ranked activity suggestions to users and routes them to activities based on keyword matching.
"""

import os
import sys
import logging
import threading
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
import gc

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
    KeywordIntentMatcher
)
from src.utils.config_loader import get_deepseek_config
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id
from src.supabase.database import get_user_language
from src.utils.intervention_record import InterventionRecordManager

logger = logging.getLogger(__name__)

# Language name mapping for system prompt
LANGUAGE_NAMES = {
    'en': 'English',
    'cn': 'Chinese',
    'bm': 'Bahasa Malay'
}


class ActivitySuggestionActivity:
    """
    Activity Suggestion Activity Class
    
    Presents ranked activity suggestions to users and routes them to the appropriate
    activity based on keyword matching.
    """
    
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        """Initialize the Activity Suggestion activity"""
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()
        
        # Components (initialized in initialize())
        self.audio_manager: Optional[ConversationAudioManager] = None
        self.session_manager: Optional[ConversationSession] = None
        self.llm_pipeline: Optional[SmallTalkSession] = None
        self.stt_service: Optional[GoogleSTTService] = None
        self.intent_matcher: Optional[KeywordIntentMatcher] = None
        self.audio_config: Optional[dict] = None
        
        # Activity state
        self._active = False
        self._initialized = False
        self._selected_activity: Optional[str] = None  # Store selected activity for routing
        self._conversation_context: List[Dict[str, str]] = []  # Store conversation for smalltalk seeding
        self._timeout_detected = False  # Flag to track if timeout occurred
        
        logger.info(f"ActivitySuggestionActivity initialized for user {self.user_id}")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            logger.info(f"Initializing Activity Suggestion activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            
            # Load user-specific configurations
            logger.info(f"Loading configs for user {self.user_id}")
            self.global_config = get_global_config_for_user(self.user_id)
            self.language_config = get_language_config(self.user_id)
            
            # Extract configs
            self.smalltalk_config = self.language_config.get("smalltalk", {})
            self.activity_suggestion_config = self.language_config.get("activity_suggestion", {})
            self.audio_paths = self.language_config.get("audio_paths", {})
            self.global_smalltalk_config = self.global_config.get("smalltalk", {})
            
            logger.info(f"Configs loaded - Global section keys: {list(self.global_config.keys())}")
            logger.info(f"Language config section keys: {list(self.language_config.keys())}")
            
            # Initialize STT service (needed for ConversationAudioManager and keyword matching)
            logger.info("Initializing STT service...")
            stt_lang = self.global_config["language_codes"]["stt_language_code"]
            audio_settings = self.global_config.get("audio_settings", {})
            stt_sample_rate = audio_settings.get("stt_sample_rate", 16000)
            self.stt_service = GoogleSTTService(language=stt_lang, sample_rate=stt_sample_rate)
            logger.info("✓ STT service initialized")
            
            # Initialize keyword intent matcher (uses user language preference)
            logger.info("Initializing keyword intent matcher...")
            try:
                self.intent_matcher = KeywordIntentMatcher(backend_dir=self.backend_dir, user_id=self.user_id)
                logger.info("✓ Keyword intent matcher initialized")
            except Exception as e:
                logger.error(f"Failed to initialize keyword intent matcher: {e}", exc_info=True)
                self.intent_matcher = None
            
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
                llm_config_path=None,
                llm_config_dict=self.smalltalk_config,
                tts_voice_name=self.global_config["language_codes"]["tts_voice_name"],
                tts_language_code=self.global_config["language_codes"]["tts_language_code"],
                system_prompt=system_prompt_with_language,
                language_code=stt_lang
            )
            logger.info("✓ SmallTalkSession initialized")
            
            self._initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Activity Suggestion activity: {e}", exc_info=True)
            return False
    
    
    def _load_ranked_activities(self) -> List[Dict[str, Any]]:
        """Load ranked activities from intervention_record.json (always fetches fresh data)"""
        try:
            record_path = self.backend_dir / "config" / "intervention_record.json"
            logger.info(f"Loading fresh ranked activities from {record_path}")
            
            # Always create a new manager to ensure fresh read
            record_manager = InterventionRecordManager(record_path)
            record = record_manager.load_record()
            
            # Handle case where record is None or empty
            if not record:
                logger.warning("intervention_record.json is empty or invalid - no ranked activities available")
                return []
            
            suggestion = record.get("latest_suggestion")
            if not suggestion:
                logger.warning("No latest_suggestion found in intervention_record.json")
                return []
            
            ranked_activities = suggestion.get("ranked_activities", [])
            
            # Log the activities for debugging
            if ranked_activities:
                logger.info(f"Loaded {len(ranked_activities)} ranked activities from intervention_record.json:")
                for activity in ranked_activities:
                    logger.info(f"  - Rank {activity.get('rank')}: {activity.get('activity_type')} (score: {activity.get('score', 0.0):.3f})")
            else:
                logger.warning("No ranked activities found in intervention_record.json")
            
            return ranked_activities
            
        except Exception as e:
            logger.error(f"Failed to load ranked activities: {e}", exc_info=True)
            return []
    
    def _format_activities_for_tts(self, ranked_activities: List[Dict[str, Any]]) -> str:
        """Format ranked activities into a readable string for TTS (explicitly from highest to lowest)"""
        if not ranked_activities:
            return "No activities available"
        
        # Get localized activity names and descriptions from language config
        activity_names = self.activity_suggestion_config.get("activity_names", {})
        activity_descriptions = self.activity_suggestion_config.get("activity_descriptions", {})
        
        # Sort by rank to ensure correct order (rank 1 = highest, rank 2 = second, etc.)
        sorted_activities = sorted(ranked_activities[:5], key=lambda x: x.get("rank", 999))
        
        formatted = []
        for activity in sorted_activities:
            activity_type = activity.get("activity_type", "")
            rank = activity.get("rank", 0)
            
            # Get localized name (handle both "journal" and "journaling")
            display_name = activity_names.get(activity_type, activity_type.title())
            if not display_name and activity_type == "journal":
                display_name = activity_names.get("journaling", "Journaling")
            
            # Get localized description
            description = activity_descriptions.get(activity_type, "")
            if not description and activity_type == "journal":
                description = activity_descriptions.get("journaling", "")
            
            # Format: "Rank {rank}: {activity_name} – {description}"
            if description:
                formatted.append(f"Rank {rank}: {display_name} – {description}")
            else:
                formatted.append(f"Rank {rank}: {display_name}")
        
        logger.debug(f"Formatted activities in rank order: {[a.get('rank') for a in sorted_activities]}")
        return "\n\n".join(formatted)
    
    def _format_all_activities_without_rankings(self) -> str:
        """Format all available activities without rankings (for cold starts)"""
        # Get localized activity names and descriptions from language config
        activity_names = self.activity_suggestion_config.get("activity_names", {})
        activity_descriptions = self.activity_suggestion_config.get("activity_descriptions", {})
        
        # Define all available activities in a default order
        all_activities = [
            {"type": "meditation", "key": "meditation"},
            {"type": "journaling", "key": "journaling"},
            {"type": "quote", "key": "quote"},
            {"type": "gratitude", "key": "gratitude"}
        ]
        
        formatted = []
        for activity_info in all_activities:
            activity_key = activity_info["key"]
            
            # Get localized name
            display_name = activity_names.get(activity_key, activity_key.title())
            
            # Get localized description
            description = activity_descriptions.get(activity_key, "")
            
            # Format: "{activity_name} – {description}"
            if description:
                formatted.append(f"{display_name} – {description}")
            else:
                formatted.append(display_name)
        
        logger.debug("Formatted all activities without rankings for cold start")
        return "\n\n".join(formatted)
    
    def _greet_with_suggestions(self) -> bool:
        """Format and speak greeting with ranked activities (always loads fresh data)"""
        try:
            # Load ranked activities (always fetches fresh from file)
            ranked_activities = self._load_ranked_activities()
            
            if not ranked_activities:
                # Cold start: no ranked activities available (new account or missing data)
                logger.info("No ranked activities available - using cold start suggestions without rankings")
                
                # Get cold start intro message (or use default)
                # Note: cold_start_intro should contain the full message with all activities and proper punctuation
                cold_start_intro = self.activity_suggestion_config.get(
                    "cold_start_intro",
                    "Here are some wellness activities you can try:"
                )
                
                # Speak the complete cold start intro message via TTS
                self._speak(cold_start_intro)
                logger.info(f"Spoke cold start activity suggestions: '{cold_start_intro[:50]}...'")
                
                # Store conversation context (full message for smalltalk seeding)
                self._conversation_context = [{"role": "assistant", "content": cold_start_intro}]
                
                return True
            
            # Normal flow: ranked activities available
            # Get introductory message from language config
            intro_message = self.activity_suggestion_config.get(
                "system_prompt",
                "Here are some suggested activities for you, they are ranked from highest to lowest based on our past interactions."
            )
            
            # Format activities for TTS (explicitly from highest to lowest ranking)
            activities_text = self._format_activities_for_tts(ranked_activities)
            logger.debug(f"Formatted activities for TTS:\n{activities_text}")
            
            # Combine intro message and activities
            full_message = f"{intro_message}\n\n{activities_text}"
            
            # Speak full message via TTS
            self._speak(full_message)
            logger.info(f"Spoke activity suggestions with intro: '{full_message[:50]}...'")
            
            # Store conversation context (full message for smalltalk seeding)
            self._conversation_context = [{"role": "assistant", "content": full_message}]
            
            return True
            
        except Exception as e:
            logger.error(f"Error in _greet_with_suggestions: {e}", exc_info=True)
            # Fallback greeting
            fallback = "I'm here to help you with wellness activities. What would you like to do today?"
            self._speak(fallback)
            self._conversation_context = [{"role": "assistant", "content": fallback}]
            return False
    
    def _listen_for_activity_choice(self) -> Optional[str]:
        """Listen for user's activity selection using STT and keyword matching"""
        if not self.stt_service or not self.intent_matcher:
            logger.error("STT service or keyword matcher not initialized, cannot listen for activity choice")
            return None
        
        try:
            logger.info("Listening for activity choice with keyword matching...")
            
            # Use standard STT parameters (16kHz)
            mic = MicStream(rate=16000, chunk_size=1600)  # 100ms chunks at 16kHz
            
            intent_result: Optional[dict] = None
            transcript: Optional[str] = None
            start_time = time.time()
            
            # Get timeout from global config (same as wakeword pipeline)
            timeout_s = self.global_config.get("wakeword", {}).get("stt_timeout_s", 8.0)
            
            try:
                mic.start()
                logger.info("Microphone active, awaiting speech for keyword matching")
                
                # Capture transcript using STT
                def on_transcript(text: str, is_final: bool):
                    nonlocal transcript
                    if is_final and text:
                        transcript = text
                        mic.stop()
                
                # Run STT with timeout
                try:
                    self.stt_service.stream_recognize(
                        mic.generator(),
                        on_transcript,
                        interim_results=True,
                        single_utterance=True  # Stop after first final result
                    )
                except Exception as e:
                    logger.error(f"STT error during keyword matching: {e}")
                
                # Check if activity was stopped (e.g., due to timeout)
                if not self._active:
                    logger.info("Activity was stopped during listening - returning None")
                    return None
                
                # Check timeout
                if time.time() - start_time > timeout_s:
                    logger.warning(f"No speech detected within {timeout_s:.1f}s → timing out")
                
                # Match transcript against keywords
                if transcript:
                    logger.info(f"Transcript received: '{transcript}'")
                    intent_result = self.intent_matcher.match_intent(transcript)
                    if intent_result:
                        logger.info(f"Intent detected: {intent_result.get('intent')}")
                
                # Map intent to activity type
                if intent_result:
                    intent_name = intent_result.get("intent")
                    # Map recognized intents to activity types
                    intent_to_activity = {
                        "journaling": "journaling",
                        "gratitude": "gratitude",
                        "meditation": "meditation",
                        "quote": "quote",
                        "smalltalk": "smalltalk"
                    }
                    matched_activity = intent_to_activity.get(intent_name)
                    if matched_activity:
                        logger.info(f"Mapped intent '{intent_name}' to activity '{matched_activity}'")
                        return matched_activity
                    else:
                        logger.info(f"Intent '{intent_name}' does not map to a known activity")
                        return None
                else:
                    logger.info("No intent matched from transcript")
                    return None
                    
            except Exception as e:
                logger.error(f"Error during keyword matching: {e}", exc_info=True)
                return None
            finally:
                mic.stop()
            
        except Exception as e:
            logger.error(f"Error listening for activity choice: {e}", exc_info=True)
            return None
    
    def _speak_starting_activity(self, activity_type: str):
        """Speak feedback message when starting an activity"""
        try:
            # Get localized activity name from language config
            activity_names = self.activity_suggestion_config.get("activity_names", {})
            activity_name = activity_names.get(activity_type, activity_type.title())
            
            # Get feedback template
            feedback_template = self.activity_suggestion_config.get(
                "starting_activity_feedback",
                "Starting {activity} now"
            )
            
            # Format message
            feedback_message = feedback_template.format(activity=activity_name)
            
            # Speak it
            self._speak(feedback_message)
            logger.info(f"Spoke starting activity feedback: '{feedback_message}'")
            
        except Exception as e:
            logger.error(f"Error speaking starting activity feedback: {e}", exc_info=True)
    
    def _speak_no_match(self):
        """Speak feedback message when no intent matched"""
        try:
            # Get feedback message from language config
            no_match_msg = self.activity_suggestion_config.get(
                "no_match_feedback",
                "I didn't quite catch that"
            )
            
            # Speak it
            self._speak(no_match_msg)
            logger.info(f"Spoke no match feedback: '{no_match_msg}'")
            
        except Exception as e:
            logger.error(f"Error speaking no match feedback: {e}", exc_info=True)
    
    def _route_to_selected_activity(self, activity_type: str):
        """Store selected activity for orchestrator to route"""
        # Map activity types to orchestrator intent names
        activity_to_intent = {
            "journaling": "journaling",
            "gratitude": "gratitude",
            "meditation": "meditation",
            "quote": "quote"
        }
        
        intent = activity_to_intent.get(activity_type, activity_type)
        self._selected_activity = intent
        logger.info(f"Selected activity: {intent} (from type: {activity_type})")
    
    def get_selected_activity(self) -> Optional[str]:
        """Get the selected activity for routing"""
        return self._selected_activity
    
    def get_conversation_context(self) -> List[Dict[str, str]]:
        """Get conversation context for seeding smalltalk"""
        return self._conversation_context.copy()
    
    def add_system_message(self, content: str):
        """Inject a system message into the LLM pipeline before starting."""
        if self.llm_pipeline:
            self.llm_pipeline.messages.append({"role": "system", "content": content})
    
    def _handle_nudge(self):
        """Handle silence nudge"""
        logger.info("Silence nudge triggered in activity suggestion")
        # Get nudge text from config and speak it using TTS
        try:
            prompts = self.activity_suggestion_config.get("prompts", {})
            nudge_text = prompts.get("nudge", "Are you still there? Which activity would you like to try?")
        except Exception as e:
            logger.warning(f"Failed to load nudge prompt from config: {e}")
            nudge_text = "Are you still there? Which activity would you like to try?"
        
        # Speak nudge with delays to prevent STT pickup
        self._speak(nudge_text, is_nudge=True)
    
    def _handle_timeout(self):
        """Handle silence timeout"""
        logger.info("Silence timeout triggered in activity suggestion - ending activity gracefully")
        
        # Set timeout flag so run() knows not to route to smalltalk
        self._timeout_detected = True
        
        # Get timeout message from config and speak it
        try:
            prompts = self.activity_suggestion_config.get("prompts", {})
            timeout_text = prompts.get("timeout", "I'll be here when you're ready. Just call my name when you want to try an activity.")
        except Exception as e:
            logger.warning(f"Failed to load timeout prompt from config: {e}")
            timeout_text = "I'll be here when you're ready. Just call my name when you want to try an activity."
        
        # Speak timeout message
        self._speak(timeout_text)
        
        # Stop the activity (this will trigger cleanup and return to wakeword)
        self.stop()
    
    def start(self) -> bool:
        """Start the Activity Suggestion activity"""
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
        
        # Check if keyword matcher is initialized (required for activity suggestion)
        if not self.intent_matcher:
            logger.error("❌ Keyword intent matcher not initialized - cannot start activity")
            # Speak error message and return False
            unavailable_msg = self.activity_suggestion_config.get(
                "suggestions_unavailable",
                "Suggestions not available now"
            )
            self._speak(unavailable_msg)
            return False
        
        try:
            logger.info("🚀 Starting Activity Suggestion activity...")
            self._active = True
            self._selected_activity = None
            self._conversation_context = []
            
            
            # Start session
            conv_id = self.session_manager.start_session("Activity Suggestion")
            self.llm_pipeline.conversation_id = conv_id
            
            # Check if audio files should be used
            use_audio_files = self.global_smalltalk_config.get("use_audio_files", False)
            
            # Play startup audio if enabled
            if use_audio_files and self.audio_config.get("start_audio_path"):
                startup_audio_path = self.backend_dir / self.audio_config["start_audio_path"]
                if startup_audio_path.exists():
                    self.audio_manager.play_audio_file(str(startup_audio_path))
            
            # Generate and speak greeting with suggestions
            self._greet_with_suggestions()
            
            # Start silence monitoring
            self.audio_manager.start_silence_monitoring(
                on_nudge=self._handle_nudge,
                on_timeout=self._handle_timeout
            )
            
            logger.info("✅ Activity Suggestion activity started successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start Activity Suggestion activity: {e}", exc_info=True)
            self._active = False
            return False
    
    def stop(self):
        """Stop the Activity Suggestion activity"""
        if not self._active:
            logger.warning("Activity not active")
            return
        
        logger.info("🛑 Stopping Activity Suggestion activity...")
        self._active = False
        
        # Stop silence monitoring
        if self.audio_manager:
            self.audio_manager.stop_silence_monitoring()
        
        # Stop session
        if self.session_manager:
            self.session_manager.stop_session()
        
        logger.info("✅ Activity Suggestion activity stopped")
    
    def cleanup(self):
        """Complete cleanup of all resources"""
        logger.info("🧹 Cleaning up Activity Suggestion activity resources...")
        
        # Stop if still active
        if self._active:
            self.stop()
        
        # Cleanup LLM pipeline
        if self.llm_pipeline:
            try:
                logger.info("🧹 Cleaning up LLM pipeline...")
                if hasattr(self.llm_pipeline, 'tts') and self.llm_pipeline.tts:
                    if hasattr(self.llm_pipeline.tts, 'client'):
                        try:
                            self.llm_pipeline.tts.client = None
                            logger.debug("TTS client closed")
                        except Exception as e:
                            logger.warning(f"Error closing TTS client: {e}")
                
                if hasattr(self.llm_pipeline, 'llm') and self.llm_pipeline.llm:
                    if hasattr(self.llm_pipeline.llm, 'client'):
                        try:
                            if hasattr(self.llm_pipeline.llm.client, 'close'):
                                self.llm_pipeline.llm.client.close()
                            logger.debug("LLM client closed")
                        except Exception as e:
                            logger.warning(f"Error closing LLM client: {e}")
                
                if hasattr(self.llm_pipeline, 'termination_detector'):
                    self.llm_pipeline.termination_detector = None
                
                if hasattr(self.llm_pipeline, 'messages'):
                    self.llm_pipeline.messages.clear()
                
                self.llm_pipeline = None
                logger.info("✓ LLM pipeline cleaned up")
            except Exception as e:
                logger.warning(f"Error during LLM pipeline cleanup: {e}")
        
        # Cleanup audio manager
        if self.audio_manager:
            try:
                logger.info("🧹 Cleaning up audio manager...")
                self.audio_manager.cleanup()
                self.audio_manager = None
                logger.info("✓ Audio manager cleaned up")
            except Exception as e:
                logger.warning(f"Error during audio manager cleanup: {e}")
        
        # Cleanup STT service
        if self.stt_service:
            try:
                logger.info("🧹 Cleaning up STT service...")
                self.stt_service = None
                logger.info("✓ STT service cleaned up")
            except Exception as e:
                logger.warning(f"Error during STT cleanup: {e}")
        
        # Keyword matcher doesn't need explicit cleanup
        
        # Force garbage collection
        try:
            logger.info("🧹 Running garbage collection...")
            collected = gc.collect()
            logger.debug(f"Garbage collection collected {collected} objects")
        except Exception as e:
            logger.warning(f"Error during garbage collection: {e}")
        
        # Reset initialization state
        self._initialized = False
        
        logger.info("✅ Activity Suggestion activity cleanup completed")
    
    def _speak(self, text: str, is_nudge: bool = False):
        """Speak text using TTS"""
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
        logger.info("🔄 Re-initializing Activity Suggestion activity...")
        
        # Reset state
        self._active = False
        self._initialized = False
        self._selected_activity = None
        self._conversation_context = []
        self._timeout_detected = False
        
        # Re-initialize components
        return self.initialize()
    
    def is_active(self) -> bool:
        """Check if the activity is currently active"""
        return self._active and self.session_manager and self.session_manager.is_active()
    
    def run(self) -> bool:
        """
        Run the complete activity: start, listen for choice, route
        
        Returns:
            True if activity completed successfully, False otherwise
        """
        logger.info("🎬 ActivitySuggestionActivity.run() - Starting activity execution")
        try:
            # Start the activity
            if not self.start():
                logger.error("❌ ActivitySuggestionActivity.run() - Failed to start activity")
                return False
            
            # Listen for user's activity choice
            matched_activity = self._listen_for_activity_choice()
            
            # Check if timeout occurred - if so, don't route to smalltalk, just return
            if self._timeout_detected:
                logger.info("Timeout detected - returning to wakeword without routing")
                self._selected_activity = "__timeout__"  # Special sentinel value to indicate timeout
                return True
            
            if matched_activity:
                if matched_activity == "smalltalk":
                    # Smalltalk doesn't need starting feedback
                    self._route_to_selected_activity(matched_activity)
                    logger.info(f"✅ User selected activity: {matched_activity}")
                else:
                    # Speak feedback and route to selected activity
                    self._speak_starting_activity(matched_activity)
                    self._route_to_selected_activity(matched_activity)
                    logger.info(f"✅ User selected activity: {matched_activity}")
            else:
                # No match - speak feedback and route to smalltalk
                self._speak_no_match()
                # Store conversation context for smalltalk seeding
                # (conversation_context already contains greeting from _greet_with_suggestions)
                self._selected_activity = None  # Will route to smalltalk
                logger.info("No activity match found - will route to smalltalk")
            
            # Stop the activity
            self.stop()
            
            return True
            
        except TerminationPhraseDetected:
            logger.info("Termination phrase detected in activity suggestion")
            self.stop()
            return True
        except Exception as e:
            logger.error(f"Error running Activity Suggestion activity: {e}", exc_info=True)
            self.stop()
            return False


# For testing when run directly
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def main():
        """Test the Activity Suggestion activity"""
        try:
            # Get backend directory
            backend_dir = Path(__file__).parent.parent.parent
            
            # Create and initialize activity
            activity = ActivitySuggestionActivity(backend_dir)
            
            if not activity.initialize():
                logger.error("Failed to initialize activity")
                return 1
            
            logger.info("=== Activity Suggestion Activity Test ===")
            logger.info("The activity will:")
            logger.info("- Load ranked activities from intervention_record.json")
            logger.info("- Format and speak activity suggestions directly via TTS")
            logger.info("- Listen for your activity choice using keyword matching")
            logger.info("- Speak feedback and route to selected activity (or smalltalk if no match)")
            logger.info("- Press Ctrl+C to stop")
            
            # Run the activity
            success = activity.run()
            
            # Get selected activity before cleanup
            selected = activity.get_selected_activity()
            
            # Cleanup
            activity.cleanup()
            
            if success:
                logger.info("=== Activity Suggestion Activity Test Completed Successfully! ===")
                if selected:
                    logger.info(f"Selected activity: {selected}")
                else:
                    logger.info("No activity selected - would route to smalltalk")
            else:
                logger.error("=== Activity Suggestion Activity Test Failed! ===")
                return 1
            
            return 0
            
        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            return 0
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            return 1
    
    exit(main())
