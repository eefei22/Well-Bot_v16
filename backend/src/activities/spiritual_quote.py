#!/usr/bin/env python3
"""
Spiritual Quote Activity

Fetches a religion-aware quote from Supabase, speaks it via TTS, then
seamlessly hands off to SmallTalk with the quote injected into the
LLM system context and a tailored opening prompt.
"""

import logging
from pathlib import Path
from typing import Optional

from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.components.conversation_audio_manager import ConversationAudioManager
from src.components.tts import GoogleTTSClient
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
            self.stt_service = GoogleSTTService(language=stt_lang, sample_rate=16000)

            def mic_factory():
                return MicStream()

            audio_config = {
                "backend_dir": str(self.backend_dir),
                "silence_timeout_seconds": 30,
                "nudge_timeout_seconds": 15,
                "nudge_pre_delay_ms": 200,
                "nudge_post_delay_ms": 300,
                "nudge_audio_path": self.audio_paths.get("nudge_audio_path"),
                "termination_audio_path": self.audio_paths.get("termination_audio_path"),
                "end_audio_path": self.audio_paths.get("end_audio_path"),
                "start_audio_path": self.audio_paths.get("start_smalltalk_audio_path"),
            }
            self.audio_manager = ConversationAudioManager(self.stt_service, mic_factory, audio_config)

            # TTS client
            from google.cloud import texttospeech
            self.tts = GoogleTTSClient(
                voice_name=self.global_config["language_codes"]["tts_voice_name"],
                language_code=self.global_config["language_codes"]["tts_language_code"],
                audio_encoding=texttospeech.AudioEncoding.PCM,
                sample_rate_hertz=24000,
                num_channels=1,
                sample_width_bytes=2,
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
        try:
            if self.audio_manager:
                self.audio_manager.cleanup()
        except Exception:
            pass

    def is_active(self) -> bool:
        return bool(self._active)


