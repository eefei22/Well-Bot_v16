# backend/src/components/_pipeline_smalltalk.py

import json
import os
import sys
import threading
import time
import logging
import string
from typing import Optional, Callable, List, Dict, Iterator, Tuple

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    from .mic_stream import MicStream
    from .stt import GoogleSTTService
    from .llm import DeepSeekClient
    from .tts import GoogleTTSClient
    from .termination_phrase import TerminationPhraseDetector, TerminationPhraseDetected, normalize_text
    from .conversation_session import ConversationSession
    from ..utils.config_loader import get_deepseek_config
except ImportError:
    from mic_stream import MicStream
    from stt import GoogleSTTService
    from llm import DeepSeekClient
    from tts import GoogleTTSClient
    from termination_phrase import TerminationPhraseDetector, TerminationPhraseDetected, normalize_text
    from conversation_session import ConversationSession
    from utils.config_loader import get_deepseek_config


logger = logging.getLogger(__name__)


def _detect_language_simple(text: str) -> Optional[str]:
    """
    Simple language detection using heuristics.
    Returns 'en', 'cn', 'bm', or None if uncertain.
    """
    if not text or not text.strip():
        return None
    
    # Count Chinese characters (CJK Unified Ideographs)
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    total_chars = len([c for c in text if c.isalnum() or '\u4e00' <= c <= '\u9fff'])
    
    if total_chars == 0:
        return None
    
    chinese_ratio = chinese_chars / total_chars if total_chars > 0 else 0
    
    # If more than 30% Chinese characters, likely Chinese
    if chinese_ratio > 0.3:
        return 'cn'
    
    # Check for common Malay words/patterns
    malay_indicators = ['saya', 'anda', 'tidak', 'adalah', 'dengan', 'untuk', 'yang', 'ini', 'itu', 'dan', 'atau']
    text_lower = text.lower()
    malay_count = sum(1 for word in malay_indicators if word in text_lower)
    
    # If contains multiple Malay words, likely Malay
    if malay_count >= 2:
        return 'bm'
    
    # Default to English if no strong indicators
    return 'en'


def _validate_response_language(response: str, expected_lang: str, language_code: str) -> Tuple[str, bool]:
    """
    Validate that LLM response is in the expected language.
    
    Args:
        response: LLM response text
        expected_lang: Expected language code ('en', 'cn', 'bm')
        language_code: Language code from config (e.g., 'cmn-CN', 'en-US')
    
    Returns:
        Tuple of (corrected_response, was_corrected)
    """
    detected = _detect_language_simple(response)
    
    # Map language_code to expected_lang for comparison
    lang_map = {
        'en': 'en',
        'cn': 'cn', 
        'cmn-CN': 'cn',
        'bm': 'bm',
        'id-ID': 'bm',
        'ms': 'bm'
    }
    
    expected_from_code = lang_map.get(language_code, expected_lang)
    
    # If detected language matches expected, return as-is
    if detected == expected_from_code:
        return response, False
    
    # Language mismatch detected - log warning
    logger.warning(
        f"Language mismatch detected! Expected: {expected_from_code}, Detected: {detected}. "
        f"Response preview: {response[:100]}"
    )
    
    # For now, return the response as-is but log the issue
    # In the future, we could add translation or retry logic here
    return response, False


class SmallTalkSession:
    """
    Conversation loop:
    - capture user speech → STT → LLM → TTS → play audio → loop
    """
    def __init__(
        self,
        stt: GoogleSTTService,
        mic_factory: Callable[[], MicStream],
        deepseek_config: dict,
        llm_config_path: Optional[str] = None,
        llm_config_dict: Optional[dict] = None,
        tts_voice_name: str = "",
        tts_language_code: str = "en-US",
        system_prompt: Optional[str] = "You are a friendly, concise wellness assistant. Keep responses short unless asked.",
        language_code: str = "en-US",
        min_confidence: float = 0.0,
        conversation_session: Optional[ConversationSession] = None,
    ):
        self.stt = stt
        self.mic_factory = mic_factory
        self.language_code = language_code
        self.min_confidence = min_confidence
        
        # Extract expected language code from language_code (e.g., 'cmn-CN' -> 'cn', 'en-US' -> 'en')
        lang_map = {
            'en': 'en', 'en-US': 'en', 'en-GB': 'en',
            'cn': 'cn', 'cmn-CN': 'cn', 'zh-CN': 'cn', 'zh': 'cn',
            'bm': 'bm', 'id-ID': 'bm', 'ms': 'bm', 'ms-MY': 'bm'
        }
        self.expected_lang = lang_map.get(language_code, 'en')
        
        # Initialize or use provided ConversationSession
        if conversation_session is None:
            self.conversation_session = ConversationSession(
                max_turns=20,
                system_prompt=system_prompt or "You are a friendly assistant. Do not use emojis.",
                language_code=language_code
            )
        else:
            self.conversation_session = conversation_session

        # Initialize DeepSeek client with config from environment
        self.llm = DeepSeekClient(
            api_key=deepseek_config["api_key"],
            base_url=deepseek_config.get("base_url", "https://api.deepseek.com"),
            model=deepseek_config.get("model", "deepseek-chat"),
        )

        # Load termination phrases from language config
        if llm_config_dict is not None:
            # Use provided dict config (new structure)
            cfg = llm_config_dict
        elif llm_config_path and os.path.exists(llm_config_path):
            # Load from file path (legacy)
            with open(llm_config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        else:
            # No config provided, use empty dict
            cfg = {}
        
        # Initialize termination phrase detector
        phrases = [p.lower() for p in cfg.get("termination_phrases", [])]  # Keep lowercase conversion
        self.termination_detector = TerminationPhraseDetector(phrases)

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

    def check_termination(self, user_text: str):
        """Check and raise exception if termination phrase detected"""
        self.termination_detector.check_termination(user_text)

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
        
        # Validate response language and apply guardrail
        validated_text, was_corrected = _validate_response_language(
            full_text, 
            self.expected_lang, 
            self.language_code
        )
        
        # If language mismatch detected, add a stronger reminder to system prompt for next time
        detected_lang = _detect_language_simple(validated_text)
        if was_corrected or (detected_lang != self.expected_lang):
            logger.warning(
                f"Language guardrail triggered: Expected {self.expected_lang}, "
                f"but response appears to be in {detected_lang or 'unknown'}"
            )
            # Add a reminder message to reinforce language requirement
            # But limit the reminder length to avoid timeout issues
            lang_names = {'en': 'English', 'cn': 'Chinese', 'bm': 'Bahasa Malay'}
            lang_name = lang_names.get(self.expected_lang, 'the user\'s preferred language')
            reminder = f"\n\n[CRITICAL: Respond ONLY in {lang_name}. Previous response was wrong language.]"
            # Update the system message with stronger reminder (but truncate if too long to avoid timeout)
            if self.messages and self.messages[0].get("role") == "system":
                current_content = self.messages[0]["content"]
                # Limit total system prompt length to avoid API timeouts
                max_length = 2000
                if len(current_content) + len(reminder) > max_length:
                    # Truncate old reminders if needed
                    current_content = current_content[:max_length - len(reminder) - 100]
                self.messages[0]["content"] = current_content + reminder
        
        self.messages.append({"role": "assistant", "content": validated_text})

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
            self.conversation_session.start_session(title="Small Talk")
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

                # Save user message to database via ConversationSession
                try:
                    self.conversation_session.add_message(
                        role="user",
                        content=user_text,
                        intent="small_talk"
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
                try:
                    self.conversation_session.add_message(
                        role="assistant",
                        content=self.messages[-1]["content"]
                    )
                except Exception as e:
                    logger.warning(f"Could not save assistant message: {e}")

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self._active = False
            try:
                self.conversation_session.end_conversation()
            except Exception as e:
                logger.warning(f"Could not end conversation: {e}")
            print("\nSession ended.")
