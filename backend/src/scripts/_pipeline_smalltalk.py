import json
import os
import sys
import threading
import time
import logging
from typing import Optional, Callable, List, Dict

# Add the backend directory to the path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Handle relative/direct execution imports for module and CLI use.
try:
    from .mic_stream import MicStream
    from .stt import GoogleSTTService
    from .llm import DeepSeekClient
except ImportError:
    from mic_stream import MicStream
    from stt import GoogleSTTService
    from llm import DeepSeekClient


class SmallTalkSession:
    """
    Console-first small talk loop:
    - Capture one utterance (mic + STT)
    - Append to messages
    - Stream DeepSeek reply
    - Loop until stopped
    """
    def __init__(
        self,
        stt: GoogleSTTService,
        mic_factory: Callable[[], MicStream],
        deepseek_config_path: str,
        system_prompt: Optional[str] = "You are a friendly, concise assistant. Keep responses short unless asked.",
        language_code: str = "en-US",
        min_confidence: float = 0.0,  # you can wire NLU confidence here if needed later
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

        # Multi-round chat memory
        self.messages: List[Dict[str, str]] = []
        if system_prompt:
            self.messages.append({"role": "system", "content": system_prompt})

        self._active = False

    # ---- utterance capture ----
    def _capture_single_transcript(self) -> Optional[str]:
        """
        Opens mic, runs streaming STT until a FINAL transcript is received,
        returns that transcript (or None if aborted).
        """
        mic = self.mic_factory()
        mic.start()

        final_text: Optional[str] = None

        def on_transcript(text: str, is_final: bool):
            nonlocal final_text
            if is_final:
                final_text = text
                # stop mic to end STT stream gracefully
                mic.stop()

        try:
            self.stt.stream_recognize(mic.generator(), on_transcript)
        except Exception as e:
            print(f"[SmallTalk] STT error: {e}")
        finally:
            mic.stop()

        return final_text

    # ---- LLM streaming ----
    def _stream_llm_reply(self) -> str:
        buffer = []
        for chunk in self.llm.stream_chat(self.messages, temperature=0.6):
            print(chunk, end="", flush=True)  # console stream
            buffer.append(chunk)
        print()  # newline after stream
        return "".join(buffer)

    # ---- public control ----
    def start(self):
        """
        Enters a loop: listen → transcribe → LLM reply → repeat.
        Ctrl+C to exit.
        """
        self._active = True
        print("🎤 Small-Talk session started. Speak after the wakeword you already have.")
        print("Press Ctrl+C to end.\n")

        try:
            while self._active:
                # 1) capture one user utterance
                user_text = self._capture_single_transcript()
                if not user_text:
                    # Could be silence or error — loop back
                    continue

                print(f"\n[You] {user_text}")
                self.messages.append({"role": "user", "content": user_text})

                # 2) stream LLM reply
                print("[Assistant] ", end="", flush=True)
                reply = self._stream_llm_reply()
                self.messages.append({"role": "assistant", "content": reply})

                # 3) loop; mic will be reopened for next utterance
        except KeyboardInterrupt:
            pass
        finally:
            self._active = False
            print("\nSmall-Talk session ended.")
