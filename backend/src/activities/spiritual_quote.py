#!/usr/bin/env python3
"""
Spiritual Quote Activity

Fetches a religion-aware quote from Supabase, speaks it via TTS, then
seamlessly hands off to SmallTalk with the quote injected into the
LLM system context and a tailored opening prompt.
"""

import logging
import sys
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
    GoogleTTSClient
)
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id
from src.supabase.database import (
    fetch_next_quote,
    mark_quote_seen,
    get_user_religion,
)
from src.activities.smalltalk import SmallTalkActivity

logger = logging.getLogger(__name__)


class SpiritualQuoteActivity:
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()

        # Components
        self.stt_service: Optional[GoogleSTTService] = None
        self.audio_manager: Optional[ConversationAudioManager] = None
        self.tts: Optional[GoogleTTSClient] = None

        # Configs
        self.global_config = None
        self.language_config = None
        self.audio_paths = None
        self._initialized = False
        self._active = False

    def initialize(self) -> bool:
        try:
            logger.info("Initializing SpiritualQuote activity…")
            self.global_config = get_global_config_for_user(self.user_id)
            self.language_config = get_language_config(self.user_id)
            self.audio_paths = self.language_config.get("audio_paths", {})

            # STT is not used directly here, but ConversationAudioManager expects it
            stt_lang = self.global_config["language_codes"]["stt_language_code"]
            audio_settings = self.global_config.get("audio_settings", {})
            stt_sample_rate = audio_settings.get("stt_sample_rate", 16000)
            self.stt_service = GoogleSTTService(language=stt_lang, sample_rate=stt_sample_rate)

            def mic_factory():
                return MicStream()

            # Audio config - minimal config since we only use this for TTS playback, not recording or silence monitoring
            audio_config = {
                "backend_dir": str(self.backend_dir),
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

            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SpiritualQuote activity: {e}", exc_info=True)
            return False

    def _speak(self, text: str):
        if not self.tts or not self.audio_manager:
            return
        def gen():
            yield text
        pcm = self.tts.stream_synthesize(gen())
        self.audio_manager.play_tts_stream(pcm)

    def run(self) -> bool:
        if not self._initialized:
            logger.error("SpiritualQuote activity not initialized")
            return False

        try:
            self._active = True
            # 1) Fetch religion and quote
            religion = get_user_religion(self.user_id)
            quote = fetch_next_quote(self.user_id, religion)
            if not quote:
                logger.info("No quote available; informing user")
                self._speak("I'm sorry, I don't have a quote for you right now.")
                return True

            # 2) Speak intro and quote (localized)
            quote_cfg = self.language_config.get("quote", {})
            preamble = quote_cfg.get("preamble", "Here is a quote for you.")
            self._speak(preamble)
            self._speak(quote["text"])

            # 3) Mark seen
            mark_quote_seen(self.user_id, quote["id"])

            # 4) Handoff to SmallTalk with seeded context (localized, from config)
            seed_tmpl = quote_cfg.get(
                "seed_system_prompt",
                "You just shared this quote with the user. Transition into a warm, brief small talk. Quote: '{quote}'. Ask one inviting, open question related to the theme.",
            )
            seed = seed_tmpl.replace("{quote}", quote["text"])
            custom_start = quote_cfg.get("opener", "What are your thoughts on that quote?")

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
            logger.error(f"SpiritualQuote activity error: {e}", exc_info=True)
            return False
        finally:
            self._active = False

    def cleanup(self):
        """Complete cleanup of all resources including native libraries, cached resources, and dependencies"""
        logger.info("🧹 Cleaning up SpiritualQuote activity resources...")
        
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
        
        logger.info("✅ SpiritualQuote activity cleanup completed")

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
        """Test the SpiritualQuote activity"""
        try:
            # Get backend directory
            backend_dir = Path(__file__).parent.parent.parent
            
            # Create and initialize activity
            activity = SpiritualQuoteActivity(backend_dir)
            
            if not activity.initialize():
                logger.error("Failed to initialize activity")
                return 1
            
            logger.info("=== Spiritual Quote Activity Test ===")
            logger.info("The activity will:")
            logger.info("- Fetch a religion-aware quote from the database")
            logger.info("- Speak the quote via TTS")
            logger.info("- Transition to SmallTalk with the quote in context")
            logger.info("- Press Ctrl+C to stop")
            
            # Run the activity
            success = activity.run()
            
            # Cleanup
            activity.cleanup()
            
            if success:
                logger.info("=== Spiritual Quote Activity Test Completed Successfully! ===")
            else:
                logger.error("=== Spiritual Quote Activity Test Failed! ===")
                return 1
            
            return 0
            
        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            return 0
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            return 1
    
    exit(main())


