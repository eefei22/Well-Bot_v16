# backend/src/components/_pipeline_smalltalk.py

import json
import os
import sys
import threading
import time
import logging
from typing import Optional, Callable, List, Dict, Iterator

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from .mic_stream import MicStream
    from .stt import GoogleSTTService
    from .llm import DeepSeekClient
    from .tts import GoogleTTSClient
    from ..supabase.database import start_conversation, add_message, end_conversation
except ImportError:
    from mic_stream import MicStream
    from stt import GoogleSTTService
    from llm import DeepSeekClient
    from tts import GoogleTTSClient
    from src.supabase.database import start_conversation, add_message, end_conversation


logger = logging.getLogger(__name__)


class SmallTalkSession:
    """
    Conversation loop:
    - capture user speech → STT → LLM → TTS → play audio → loop
    """
    def __init__(
        self,
        stt: GoogleSTTService,
        mic_factory: Callable[[], MicStream],
        deepseek_config_path: str,
        tts_voice_name: str,
        tts_language_code: str = "en-US",
        system_prompt: Optional[str] = "You are a friendly, concise assistant. Keep responses short unless asked.",
        language_code: str = "en-US",
        min_confidence: float = 0.0,
    ):
        self.stt = stt
        self.mic_factory = mic_factory
        self.language_code = language_code
        self.min_confidence = min_confidence

        # Load DeepSeek config
        with open(deepseek_config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.llm = DeepSeekClient(
            api_key=cfg["api_key"],
            base_url=cfg.get("base_url", "https://api.deepseek.com"),
            model=cfg.get("model", "deepseek-chat"),
        )

        # Initialize TTS client
        self.tts = GoogleTTSClient(
            voice_name=tts_voice_name,
            language_code=tts_language_code,
            # you can set sample_rate, encoding etc as needed in your TTS config
        )

        # Chat memory
        self.messages: List[Dict[str, str]] = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

        self.conversation_id: Optional[str] = None
        self._active = False

    # ---- utterance capture ----
    def _capture_single_transcript(self) -> Optional[str]:
        mic = self.mic_factory()
        mic.start()

        final_text: Optional[str] = None

        def on_transcript(text: str, is_final: bool):
            nonlocal final_text
            if is_final:
                final_text = text
                mic.stop()

        try:
            self.stt.stream_recognize(mic.generator(), on_transcript)
        except Exception as e:
            logger.error(f"[SmallTalk] STT error: {e}")
        finally:
            mic.stop()

        return final_text

    # ---- LLM streaming + TTS streaming ----
    def _stream_llm_and_tts(self) -> Iterator[bytes]:
        """
        Streams LLM response text, then passes chunks into TTS streaming, yielding audio bytes.
        Returns an iterator over PCM audio chunks.
        """
        # Buffer the LLM text streaming, but also emit chunks to TTS
        # This is simplistic: we gather all text first, then feed to TTS streaming
   
        # Option A: stream LLM chunks, buffer them, then feed to TTS
        text_chunks: List[str] = []
        for text_chunk in self.llm.stream_chat(self.messages, temperature=0.6):
            # Print to console
            print(text_chunk, end="", flush=True)
            text_chunks.append(text_chunk)

        print()  # newline after full stream
        full_text = "".join(text_chunks)
        self.messages.append({"role": "assistant", "content": full_text})

        # Then stream TTS audio
        def text_gen():
            # simple chunking: you could split by sentences, but here we yield the entire text as one chunk
            yield full_text

        for audio_chunk in self.tts.synthesize_safe(text_gen()):
            yield audio_chunk

    # ---- public loop start ----
    def start(self):
        self._active = True

        try:
            self.conversation_id = start_conversation(title="Small Talk")
            print("🎤 Small-Talk session started. Speak after wakeword.")
        except Exception as e:
            logger.warning(f"Could not start conversation: {e}")

        try:
            while self._active:
                user_text = self._capture_single_transcript()
                if not user_text:
                    continue

                print(f"\n[You] {user_text}")
                self.messages.append({"role": "user", "content": user_text})

                if self.conversation_id:
                    try:
                        add_message(
                            conversation_id=self.conversation_id,
                            role="user",
                            content=user_text,
                            intent="small_talk",
                            lang=self.language_code
                        )
                    except Exception as e:
                        logger.warning(f"Could not save user message: {e}")

                # Stream LLM → TTS and play audio
                print("[Assistant speaking audio] ", end="", flush=True)
                for pcm_chunk in self._stream_llm_and_tts():
                    # Here, you need a playback mechanism: e.g. feed to audio playback
                    # For now we can write raw PCM chunk to stdout or buffer, placeholder:
                    # (In manager you will connect to actual audio output)
                    # e.g., audio_playback.play(pcm_chunk)
                    # For demo, we just note size:
                    # print(f"<audio chunk size {len(pcm_chunk)}> ", end="", flush=True)
                    pass

                # After streaming audio, store assistant text in DB
                if self.conversation_id:
                    try:
                        add_message(
                            conversation_id=self.conversation_id,
                            role="assistant",
                            content=self.messages[-1]["content"],
                            lang=self.language_code
                        )
                    except Exception as e:
                        logger.warning(f"Could not save assistant message: {e}")

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self._active = False
            if self.conversation_id:
                try:
                    end_conversation(self.conversation_id)
                except Exception as e:
                    logger.warning(f"Could not end conversation: {e}")
            print("\nSession ended.")
