import os
import threading
import time
import re
import json
import logging
from typing import Optional, Callable

from ..components._pipeline_smalltalk import SmallTalkSession
from ..components.intent import IntentInference
from ..components.mic_stream import MicStream
from ..components.stt import GoogleSTTService

# For playing audio file
try:
    from playsound import playsound
except ImportError:
    playsound = None
    logging.warning("playsound not available - nudge audio will not work")

logger = logging.getLogger(__name__)

class SmallTalkManager:
    def __init__(
        self,
        stt: GoogleSTTService,
        mic_factory: Callable[[], MicStream],
        deepseek_config_path: str,
        llm_config_path: str,
        nudge_audio_path: str,
        intent_model_path: Optional[str] = None,
        language_code: str = "en-US"
    ):
        self.stt = stt
        self.mic_factory = mic_factory
        self.language_code = language_code
        
        # Load LLM / manager config
        with open(llm_config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.system_prompt = cfg.get("system_prompt", "You are a friendly assistant. Do not use emojis.")
        self.termination_phrases = [p.lower() for p in cfg.get("termination_phrases", [])]
        self.silence_timeout = cfg.get("silence_timeout_seconds", 30)
        self.nudge_timeout = cfg.get("nudge_timeout_seconds", 15)
        self.max_turns = cfg.get("max_turns", 20)

        self.nudge_audio_path = nudge_audio_path

        # Create pipeline with system prompt
        self.pipeline = SmallTalkSession(
            stt=stt,
            mic_factory=mic_factory,
            deepseek_config_path=deepseek_config_path,
            system_prompt=self.system_prompt,
            language_code=language_code
        )

        self._active = False
        self._turn_count = 0
        self._last_user_time = None
        self._nudged = False
        self._silence_watcher_thread = None

        # Optional IntentRecognizer to detect "termination intent"
        self.intent_inf = None
        if intent_model_path and os.path.exists(intent_model_path):
            try:
                self.intent_inf = IntentInference(intent_model_path)
                logger.info("Intent inference model loaded successfully")
            except Exception as e:
                logger.warning(f"Could not load intent model: {e}")

    def _strip_emojis(self, text: str) -> str:
        """Remove emojis via regex (basic)"""
        return re.sub(r"[^\w\s.,!?'-]", "", text)

    def _is_termination_phrase(self, user_text: str) -> bool:
        """Check if user text contains termination phrases"""
        low = user_text.lower().strip()
        for phrase in self.termination_phrases:
            if low == phrase or low.startswith(phrase + " "):
                return True
        
        # Optionally use intent classifier:
        if self.intent_inf:
            try:
                res = self.intent_inf.predict_intent(user_text)
                if res["intent"] == "terminate_intent" and res["confidence"] > 0.8:
                    return True
            except Exception as e:
                logger.warning(f"Intent classification error: {e}")
        
        return False

    def _play_nudge(self):
        """Play the nudge audio file"""
        if not playsound:
            logger.warning("playsound not available - cannot play nudge audio")
            return
            
        try:
            playsound(self.nudge_audio_path)
            logger.info("Nudge audio played successfully")
        except Exception as e:
            logger.error(f"Error playing nudge audio: {e}")

    def _silence_watcher(self):
        """
        Runs in a background thread to monitor silence.
        If no user input beyond silence_timeout, triggers nudge or termination.
        """
        while self._active:
            if self._last_user_time is None:
                time.sleep(1)
                continue
            
            elapsed = time.time() - self._last_user_time
            
            if elapsed >= self.silence_timeout and not self._nudged:
                # time to nudge
                logger.info("Nudging user (silence detected)")
                self._play_nudge()
                self._nudged = True
                # after nudging, wait for nudge_timeout more
            elif elapsed >= self.silence_timeout + self.nudge_timeout:
                logger.info("No response after nudge, ending session")
                self.stop()
                break
            
            time.sleep(1)

    def _on_turn_complete(self, user_text: str, assistant_reply: str):
        """
        Called after each turn (user → assistant).
        This is a custom callback that we'll integrate with the pipeline.
        """
        self._turn_count += 1
        self._last_user_time = time.time()
        self._nudged = False  # reset nudge status after user speaks

        logger.info(f"Turn {self._turn_count} completed")

        # 1. Strip emojis from assistant text
        clean_reply = self._strip_emojis(assistant_reply)
        if clean_reply != assistant_reply:
            logger.info("Emojis stripped from assistant reply")
            # Update the last message in pipeline's messages
            if self.pipeline.messages and self.pipeline.messages[-1]["role"] == "assistant":
                self.pipeline.messages[-1]["content"] = clean_reply

        # 2. Check for termination phrases
        if self._is_termination_phrase(user_text):
            logger.info("Termination phrase detected, ending session")
            self.stop()
            return

        # 3. Check turn limit
        if self._turn_count >= self.max_turns:
            logger.info("Reached max turns, ending session")
            self.stop()

    def start(self):
        """Start the smalltalk session with manager controls"""
        if self._active:
            logger.warning("Manager is already active")
            return
            
        self._active = True
        self._turn_count = 0
        self._nudged = False
        self._last_user_time = None

        # Start silence watcher
        self._silence_watcher_thread = threading.Thread(target=self._silence_watcher, daemon=True)
        self._silence_watcher_thread.start()

        logger.info("SmallTalkManager session started")
        
        # We need to modify the pipeline to support our callback
        # For now, we'll run the pipeline in a separate thread and monitor it
        def run_pipeline():
            try:
                # Start conversation in database
                try:
                    from ..supabase.database import start_conversation
                    self.pipeline.conversation_id = start_conversation(title="Small Talk")
                    logger.info("Database conversation started")
                except Exception as e:
                    logger.warning(f"Could not start database conversation: {e}")

                logger.info("🎤 Small-Talk session started. Speak after the wakeword.")
                logger.info("Press Ctrl+C to end.\n")

                while self._active:
                    # 1) capture one user utterance
                    user_text = self.pipeline._capture_single_transcript()
                    if not user_text:
                        # Could be silence or error — loop back
                        continue

                    logger.info(f"[You] {user_text}")
                    self.pipeline.messages.append({"role": "user", "content": user_text})
                    
                    # Add user message to database
                    if self.pipeline.conversation_id:
                        try:
                            from ..supabase.database import add_message
                            add_message(
                                conversation_id=self.pipeline.conversation_id,
                                role="user",
                                content=user_text,
                                intent="small_talk",
                                lang="en"
                            )
                        except Exception as e:
                            logger.warning(f"Could not save user message to database: {e}")

                    # Check for termination before processing
                    if self._is_termination_phrase(user_text):
                        logger.info("Termination phrase detected, ending session")
                        self.stop()
                        break

                    # 2) stream LLM reply
                    logger.info("[Assistant] ", end="", flush=True)
                    reply = self.pipeline._stream_llm_reply()
                    
                    # Strip emojis from reply
                    clean_reply = self._strip_emojis(reply)
                    self.pipeline.messages.append({"role": "assistant", "content": clean_reply})
                    
                    # Add assistant message to database
                    if self.pipeline.conversation_id:
                        try:
                            from ..supabase.database import add_message
                            add_message(
                                conversation_id=self.pipeline.conversation_id,
                                role="assistant",
                                content=clean_reply,
                                lang="en"
                            )
                        except Exception as e:
                            logger.warning(f"Could not save assistant message to database: {e}")

                    # Call our turn completion callback
                    self._on_turn_complete(user_text, clean_reply)
                    
                    # Check if we should stop after callback
                    if not self._active:
                        break

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
            except Exception as e:
                logger.error(f"Pipeline error: {e}")
            finally:
                self._active = False
                
                # End conversation in database
                if self.pipeline.conversation_id:
                    try:
                        from ..supabase.database import end_conversation
                        end_conversation(self.pipeline.conversation_id)
                        logger.info("Small-Talk session ended (conversation saved to database)")
                    except Exception as e:
                        logger.warning(f"Could not end database conversation: {e}")
                else:
                    logger.info("Small-Talk session ended")

        # Run pipeline in separate thread
        pipeline_thread = threading.Thread(target=run_pipeline, daemon=True)
        pipeline_thread.start()

    def stop(self):
        """Stop the smalltalk session"""
        if not self._active:
            return
            
        self._active = False
        logger.info("SmallTalkManager stopping session")
        
        # Wait for silence watcher to finish
        if self._silence_watcher_thread and self._silence_watcher_thread.is_alive():
            self._silence_watcher_thread.join(timeout=1)

    def is_active(self) -> bool:
        """Check if the manager is currently active"""
        return self._active
