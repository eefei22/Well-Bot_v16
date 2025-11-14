#!/usr/bin/env python3
"""
Gratitude Activity

Prompts the user to speak their gratitude note, records it via STT,
saves it to the database, and seamlessly hands off to SmallTalk with
the gratitude note injected into the LLM system context.
"""

import logging
import sys
import time
import gc
import os
import tempfile
from pathlib import Path
from typing import Optional

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

# Use lazy imports from __init__.py to prevent cascade import issues
from src.components import (
    GoogleSTTService,
    MicStream,
    ConversationAudioManager,
    GoogleTTSClient,
    TerminationPhraseDetector,
    TerminationPhraseDetected
)
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id
from src.supabase.database import save_gratitude_item
from src.activities.smalltalk import SmallTalkActivity

logger = logging.getLogger(__name__)


class GratitudeActivity:
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()

        # Components
        self.stt_service: Optional[GoogleSTTService] = None
        self.audio_manager: Optional[ConversationAudioManager] = None
        self.tts: Optional[GoogleTTSClient] = None
        self.termination_detector: Optional[TerminationPhraseDetector] = None

        # Configs
        self.global_config = None
        self.language_config = None
        self.audio_paths = None
        self.gratitude_config = None
        self._initialized = False
        self._active = False
        self._activity_public_id: Optional[str] = None  # Track public_id for duration tracking (optional)
        
        # Recording state
        self.gratitude_text = ""
        self._termination_detected = False
        self._accumulated_text = []

    def initialize(self) -> bool:
        try:
            logger.info("Initializing Gratitude activity…")
            self.global_config = get_global_config_for_user(self.user_id)
            self.language_config = get_language_config(self.user_id)
            self.audio_paths = self.language_config.get("audio_paths", {})
            self.gratitude_config = self.language_config.get("gratitude", {})

            # STT service for recording
            stt_lang = self.global_config["language_codes"]["stt_language_code"]
            audio_settings = self.global_config.get("audio_settings", {})
            stt_sample_rate = audio_settings.get("stt_sample_rate", 16000)
            self.stt_service = GoogleSTTService(language=stt_lang, sample_rate=stt_sample_rate)

            def mic_factory():
                return MicStream()

            # Get timeout configs from global config
            gratitude_global_config = self.global_config.get("gratitude", {})
            audio_config = {
                "backend_dir": str(self.backend_dir),
                "silence_timeout_seconds": gratitude_global_config.get("silence_timeout_seconds", 30),
                "nudge_timeout_seconds": gratitude_global_config.get("nudge_timeout_seconds", 15),
                "nudge_pre_delay_ms": gratitude_global_config.get("nudge_pre_delay_ms", 200),
                "nudge_post_delay_ms": gratitude_global_config.get("nudge_post_delay_ms", 300),
                "nudge_audio_path": self.audio_paths.get("nudge_audio_path"),
                "termination_audio_path": self.audio_paths.get("termination_audio_path"),
                "end_audio_path": self.audio_paths.get("end_audio_path"),
                "start_audio_path": self.audio_paths.get("start_gratitude_audio_path"),
            }
            self.audio_manager = ConversationAudioManager(self.stt_service, mic_factory, audio_config)

            # TTS client
            # Import texttospeech locally for AudioEncoding enum
            from google.cloud import texttospeech
            self.tts = GoogleTTSClient(
                voice_name=self.global_config["language_codes"]["tts_voice_name"],
                language_code=self.global_config["language_codes"]["tts_language_code"],
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=audio_settings.get("tts_sample_rate_hertz", 24000),
                num_channels=audio_settings.get("tts_num_channels", 1),
                sample_width_bytes=audio_settings.get("tts_sample_width_bytes", 2),
            )

            # Termination phrase detector (optional, can be empty list)
            termination_phrases = self.gratitude_config.get("termination_phrases", [])
            self.termination_detector = TerminationPhraseDetector(termination_phrases, require_active=True)

            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Gratitude activity: {e}", exc_info=True)
            return False

    def _speak(self, text: str):
        if not self.tts or not self.audio_manager:
            return
        def gen():
            yield text
        pcm = self.tts.stream_synthesize(gen())
        self.audio_manager.play_tts_stream(pcm)

    def _record_gratitude(self) -> str:
        """Record user's gratitude note via STT streaming."""
        logger.info("Starting gratitude recording...")
        
        # Play start audio if enabled
        use_audio_files = self.global_config.get("gratitude", {}).get("use_audio_files", False)
        if use_audio_files:
            start_audio_path = self.audio_paths.get("start_gratitude_audio_path")
            if start_audio_path:
                full_audio_path = self.backend_dir / start_audio_path
                if full_audio_path.exists():
                    logger.info(f"Playing start audio: {start_audio_path}")
                    self.audio_manager.play_audio_file(str(full_audio_path), mute_mic=False)

        # Get and speak start prompt
        prompts = self.gratitude_config.get("prompts", {})
        start_prompt = prompts.get("start", "What are you grateful for today? Speak after the tone.")
        self._speak(start_prompt)

        # Create mic stream
        mic = self.audio_manager.mic_factory()
        mic.start()

        # Register mic with ConversationAudioManager for silence monitoring
        with self.audio_manager._mic_lock:
            self.audio_manager._current_mic = mic

        # Start silence monitoring
        self._start_silence_monitoring()

        # Buffer for accumulated text (store on self so it's accessible)
        self._accumulated_text = []

        def on_transcript(text: str, is_final: bool):
            if not self._active:
                mic.stop()
                return

            # Skip if termination already detected
            if self._termination_detected:
                logger.debug(f"Skipping transcript after termination: '{text}'")
                return

            # Reset silence timer on any transcript
            if self.audio_manager:
                self.audio_manager.reset_silence_timer()

            if is_final:
                logger.info(f"Final transcript: {text}")
                
                # Check for termination phrase first - if found, stop and exclude it
                if self.termination_detector.is_termination_phrase(text, active=self._active):
                    logger.info(f"✅ Termination phrase detected in final: '{text}' - stopping recording")
                    self._termination_detected = True
                    mic.stop()
                    return  # Stop recording, use whatever content we already have
                else:
                    logger.debug(f"No termination phrase in: '{text}'")
                
                # Add to accumulated text (not a termination phrase)
                if text.strip():
                    self._accumulated_text.append(text.strip())
                    logger.info(f"Content received: {len(self._accumulated_text)} final transcripts")
                    # Continue recording - wait for termination phrase

            else:
                # Interim result - check for termination phrase
                logger.debug(f"Interim transcript: {text}")
                if text and self.termination_detector.is_termination_phrase(text, active=self._active):
                    logger.info(f"Termination phrase detected in interim: {text}")
                    self._termination_detected = True
                    mic.stop()
                    # Stop recording - we already have content from previous final transcripts if any
                    return

        try:
            # Start STT streaming
            logger.debug("Starting STT streaming recognition...")
            self.stt_service.stream_recognize(
                mic.generator(),
                on_transcript,
                interim_results=True,
                single_utterance=False
            )
            logger.debug("STT streaming completed normally")
        except Exception as e:
            logger.error(f"Unexpected error in _record_gratitude during STT streaming: {e}")
            raise
        finally:
            mic.stop()
            # Unregister mic
            with self.audio_manager._mic_lock:
                self.audio_manager._current_mic = None
            self._stop_silence_monitoring()

        # Combine accumulated text
        gratitude_text = " ".join(self._accumulated_text).strip()
        logger.info(f"Recorded gratitude note: {gratitude_text[:100]}...")
        return gratitude_text

    def _start_silence_monitoring(self):
        """Start silence monitoring for inactivity detection."""
        if not self.audio_manager:
            return

        def on_nudge():
            """Called when silence timeout reached"""
            # Nudge user - remind them to say termination phrase or continue
            logger.info("Silence nudge triggered")
            
            use_audio_files = self.global_config.get("gratitude", {}).get("use_audio_files", False)
            
            # Play nudge audio if enabled
            if use_audio_files:
                nudge_audio_path = self.audio_paths.get("nudge_audio_path")
                if nudge_audio_path:
                    full_audio_path = self.backend_dir / nudge_audio_path
                    if full_audio_path.exists():
                        self.audio_manager.play_nudge_audio_with_delays(str(full_audio_path))

            # TTS nudge from config
            prompts = self.gratitude_config.get("prompts", {})
            nudge_text = prompts.get("nudge", "Are you still there? Continue speaking or say 'done' when finished.")
            self._speak(nudge_text)

        def on_timeout():
            """Called when timeout reached after nudge"""
            # If we have content, save it as a fallback (user didn't say termination phrase)
            if self._accumulated_text:
                logger.info("Timeout reached after nudge with content - saving as fallback")
                self._termination_detected = True
                with self.audio_manager._mic_lock:
                    if self.audio_manager._current_mic:
                        self.audio_manager._current_mic.stop()
            else:
                # No content and timeout - just stop
                logger.info("Timeout reached with no content - ending")
                self._termination_detected = True
                with self.audio_manager._mic_lock:
                    if self.audio_manager._current_mic:
                        self.audio_manager._current_mic.stop()

        self.audio_manager.start_silence_monitoring(on_nudge, on_timeout)

    def _stop_silence_monitoring(self):
        """Stop silence monitoring"""
        if self.audio_manager:
            self.audio_manager.stop_silence_monitoring()

    def set_activity_log_id(self, public_id: Optional[str]):
        """Set the activity public_id for duration tracking (optional)."""
        self._activity_public_id = public_id

    def run(self) -> bool:
        if not self._initialized:
            logger.error("Gratitude activity not initialized")
            return False

        completed = False
        try:
            self._active = True
            self._termination_detected = False
            self.gratitude_text = ""
            self._accumulated_text = []

            # 1) Record user's gratitude note
            prompts = self.gratitude_config.get("prompts", {})
            try:
                self.gratitude_text = self._record_gratitude()
            except Exception as e:
                logger.error(f"Error during gratitude recording: {e}", exc_info=True)
                recording_error = prompts.get("recording_error", "I'm sorry, I had trouble recording your gratitude note.")
                self._speak(recording_error)
                completed = False
                return False

            # Validate we have content
            if not self.gratitude_text or not self.gratitude_text.strip():
                logger.warning("No gratitude text recorded")
                no_content = prompts.get("no_content", "I didn't catch that. Let's try again another time.")
                self._speak(no_content)
                completed = False
                return True

            # 2) Save to database
            try:
                result = save_gratitude_item(self.user_id, self.gratitude_text)
                logger.info(f"Gratitude item saved successfully: {result.get('id')}")
                completed = True
            except Exception as e:
                logger.error(f"Failed to save gratitude item: {e}", exc_info=True)
                save_error = prompts.get("save_error", "I had trouble saving your gratitude note, but I heard what you said.")
                self._speak(save_error)
                completed = False
                # Continue to smalltalk anyway

            # 3) Confirm save with TTS
            saved_template = prompts.get("saved", "Thank you for sharing. I've saved your gratitude note.")
            self._speak(saved_template)

            # 4) Handoff to SmallTalk with seeded context (localized, from config)
            seed_tmpl = self.gratitude_config.get(
                "seed_system_prompt",
                "The user just shared a gratitude note. Transition into a warm, brief small talk. Gratitude note: '{gratitude_note}'. Ask one inviting, open question related to gratitude or positivity.",
            )
            seed = seed_tmpl.replace("{gratitude_note}", self.gratitude_text)
            custom_start = self.gratitude_config.get("opener", "That's beautiful. What else is on your mind?")

            smalltalk = SmallTalkActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not smalltalk.initialize():
                logger.error("Failed to initialize SmallTalk for handoff")
                return False
            smalltalk.start(seed_system_prompt=seed, custom_start_prompt=custom_start)
            # Continue the normal conversation loop
            ok = smalltalk._conversation_loop()
            smalltalk.stop()
            smalltalk.cleanup()
            smalltalk.reinitialize()
            return ok
        except Exception as e:
            logger.error(f"Gratitude activity error: {e}", exc_info=True)
            completed = False
            return False
        finally:
            # Note: Completion tracking removed in new schema
            # Duration can be tracked via log_intervention_duration() if needed
            
            self._active = False

    def cleanup(self):
        """Complete cleanup of all resources including native libraries, cached resources, and dependencies"""
        logger.info("🧹 Cleaning up Gratitude activity resources...")
        
        # Stop if still active
        if self._active:
            self._active = False
        
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
        
        # Cleanup TTS service (Google Cloud TTS client)
        if self.tts:
            try:
                logger.info("🧹 Cleaning up TTS service...")
                # Close Google Cloud TTS client
                if hasattr(self.tts, 'client') and self.tts.client:
                    try:
                        self.tts.client = None
                        logger.debug("TTS client closed")
                    except Exception as e:
                        logger.warning(f"Error closing TTS client: {e}")
                self.tts = None
                logger.info("✓ TTS service cleaned up")
            except Exception as e:
                logger.warning(f"Error during TTS cleanup: {e}")
        
        # Cleanup termination detector
        if self.termination_detector:
            try:
                logger.info("🧹 Cleaning up termination detector...")
                self.termination_detector = None
                logger.debug("Termination detector cleaned up")
            except Exception as e:
                logger.warning(f"Error during termination detector cleanup: {e}")
        
        # Clear config caches
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
        
        logger.info("✅ Gratitude activity cleanup completed")

    def is_active(self) -> bool:
        return bool(self._active)


# For testing when run directly
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def main():
        """Test the Gratitude activity"""
        try:
            # Get backend directory
            backend_dir = Path(__file__).parent.parent.parent
            
            # Create and initialize activity
            activity = GratitudeActivity(backend_dir)
            
            if not activity.initialize():
                logger.error("Failed to initialize activity")
                return 1
            
            logger.info("=== Gratitude Activity Test ===")
            logger.info("The activity will:")
            logger.info("- Prompt you to speak your gratitude note")
            logger.info("- Record your speech via STT")
            logger.info("- Save the gratitude note to the database")
            logger.info("- Transition to SmallTalk with the gratitude note in context")
            logger.info("- Press Ctrl+C to stop")
            
            # Run the activity
            success = activity.run()
            
            # Cleanup
            activity.cleanup()
            
            if success:
                logger.info("=== Gratitude Activity Test Completed Successfully! ===")
            else:
                logger.error("=== Gratitude Activity Test Failed! ===")
                return 1
            
            return 0
            
        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            return 0
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            return 1
    
    exit(main())

