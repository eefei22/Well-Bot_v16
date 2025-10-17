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
    from ..supabase.database import start_conversation, add_message, end_conversation
except ImportError:
    from mic_stream import MicStream
    from stt import GoogleSTTService
    from llm import DeepSeekClient
    from src.supabase.database import start_conversation, add_message, end_conversation


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

        # Database conversation tracking
        self.conversation_id: Optional[str] = None
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
        
        # Start conversation in database
        try:
            self.conversation_id = start_conversation(title="Small Talk")
            print("🎤 Small-Talk session started. Speak after the wakeword you already have.")
            print("Press Ctrl+C to end.\n")
        except Exception as e:
            print(f"⚠️  Warning: Could not start database conversation: {e}")
            print("🎤 Small-Talk session started (without database logging). Speak after the wakeword you already have.")
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
                
                # Add user message to database
                if self.conversation_id:
                    try:
                        add_message(
                            conversation_id=self.conversation_id,
                            role="user",
                            content=user_text,
                            intent="small_talk",
                            lang="en"
                        )
                    except Exception as e:
                        print(f"⚠️  Warning: Could not save user message to database: {e}")

                # 2) stream LLM reply
                print("[Assistant] ", end="", flush=True)
                reply = self._stream_llm_reply()
                self.messages.append({"role": "assistant", "content": reply})
                
                # Add assistant message to database
                if self.conversation_id:
                    try:
                        add_message(
                            conversation_id=self.conversation_id,
                            role="assistant",
                            content=reply,
                            lang="en"
                        )
                    except Exception as e:
                        print(f"⚠️  Warning: Could not save assistant message to database: {e}")

                # 3) loop; mic will be reopened for next utterance
        except KeyboardInterrupt:
            pass
        finally:
            self._active = False
            
            # End conversation in database
            if self.conversation_id:
                try:
                    end_conversation(self.conversation_id)
                    print("\nSmall-Talk session ended (conversation saved to database).")
                except Exception as e:
                    print(f"\nSmall-Talk session ended (⚠️  Warning: Could not end database conversation: {e})")
            else:
                print("\nSmall-Talk session ended.")