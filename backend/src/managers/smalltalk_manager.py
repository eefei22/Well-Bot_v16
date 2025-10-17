# backend/src/managers/smalltalk_manager.py

import os
import threading
import time
import re
import json
import logging

from typing import Optional, Callable

from ..components._pipeline_smalltalk import SmallTalkSession
from ..components.mic_stream import MicStream
from ..components.stt import GoogleSTTService

import pyaudio

# For playing nudge audio
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
        sample_rate: int = 24000,
        sample_width_bytes: int = 2,
        num_channels: int = 1
    ):
        self.stt = stt
        self.mic_factory = mic_factory

        # Load manager / LLM config
        with open(llm_config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.system_prompt = cfg.get("system_prompt", "You are a friendly assistant. Do not use emojis.")
        self.termination_phrases = [p.lower() for p in cfg.get("termination_phrases", [])]
        self.silence_timeout = cfg.get("silence_timeout_seconds", 30)
        self.nudge_timeout = cfg.get("nudge_timeout_seconds", 15)
        self.nudge_pre_delay = cfg.get("nudge_pre_delay_ms", 200) / 1000.0
        self.nudge_post_delay = cfg.get("nudge_post_delay_ms", 300) / 1000.0
        self.max_turns = cfg.get("max_turns", 20)
        
        # TTS and language settings from config
        self.tts_voice_name = cfg.get("tts_voice_name", "en-US-Chirp3-HD-Charon")
        self.tts_language_code = cfg.get("tts_language_code", "en-US")
        self.language_code = cfg.get("stt_language_code", "en-US")
        
        # Nudge audio path from config (resolve relative to backend directory)
        nudge_audio_relative = cfg.get("nudge_audio_path", "assets/inactivity_nudge_EN_male.wav")
        backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(llm_config_path)))  # Go up from config/LLM/ to backend/
        self.nudge_audio_path = os.path.join(backend_dir, nudge_audio_relative)
        
        # Termination audio path from config (resolve relative to backend directory)
        termination_audio_relative = cfg.get("termination_audio_path", "assets/termination_EN_male.wav")
        self.termination_audio_path = os.path.join(backend_dir, termination_audio_relative)
        
        # Debug logging for path resolution
        logger.info(f"Nudge audio config: {nudge_audio_relative}")
        logger.info(f"Backend directory: {backend_dir}")
        logger.info(f"Resolved nudge path: {self.nudge_audio_path}")
        logger.info(f"Nudge file exists: {os.path.exists(self.nudge_audio_path)}")
        logger.info(f"Termination audio config: {termination_audio_relative}")
        logger.info(f"Resolved termination path: {self.termination_audio_path}")
        logger.info(f"Termination file exists: {os.path.exists(self.termination_audio_path)}")

        # Create the pipeline (which now handles LLM + TTS)
        self.pipeline = SmallTalkSession(
            stt=stt,
            mic_factory=mic_factory,
            deepseek_config_path=deepseek_config_path,
            tts_voice_name=self.tts_voice_name,
            tts_language_code=self.tts_language_code,
            system_prompt=self.system_prompt,
            language_code=self.language_code
        )

        self._active = False
        self._turn_count = 0
        self._last_user_time = None
        self._nudged = False
        self._silence_watcher_thread = None

        # Mic control
        self._current_mic = None
        self._mic_lock = threading.Lock()

        # Audio playback tracking for silence watcher
        self._is_playing_audio = False
        self._playback_lock = threading.Lock()

        # PyAudio for playback
        self._pyaudio = pyaudio.PyAudio()
        self._audio_stream = None
        self.sample_rate = sample_rate
        self.sample_width_bytes = sample_width_bytes
        self.num_channels = num_channels

    def _strip_emojis(self, text: str) -> str:
        return re.sub(r"[^\w\s.,!?'-]", "", text)

    def _is_termination_phrase(self, user_text: str) -> bool:
        low = user_text.lower().strip()
        for phrase in self.termination_phrases:
            if low == phrase or low.startswith(phrase + " "):
                return True
        return False

    def _play_nudge(self):
        if not playsound:
            logger.warning("playsound not available - cannot nudge")
            return

        # Check if nudge file exists
        if not os.path.exists(self.nudge_audio_path):
            logger.error(f"Nudge audio file not found: {self.nudge_audio_path}")
            return

        with self._mic_lock:
            if self._current_mic and self._current_mic.is_running():
                self._current_mic.mute()

        time.sleep(self.nudge_pre_delay)
        try:
            logger.info(f"Playing nudge audio: {self.nudge_audio_path}")
            self._set_playback_state(True)  # Track nudge audio playback
            playsound(self.nudge_audio_path)
            logger.info("Nudge audio played successfully")
            self._set_playback_state(False)  # End nudge audio playback
        except Exception as e:
            logger.error(f"Error playing nudge: {e}")
            self._set_playback_state(False)  # Ensure state is reset on error
        time.sleep(self.nudge_post_delay)

        with self._mic_lock:
            if self._current_mic and self._current_mic.is_running():
                self._current_mic.unmute()

    def _play_termination_audio(self):
        """Play the termination audio file when session ends due to timeout."""
        if not playsound:
            logger.warning("playsound not available - cannot play termination audio")
            return

        # Check if termination file exists
        if not os.path.exists(self.termination_audio_path):
            logger.error(f"Termination audio file not found: {self.termination_audio_path}")
            return

        with self._mic_lock:
            if self._current_mic and self._current_mic.is_running():
                self._current_mic.mute()

        try:
            logger.info(f"Playing termination audio: {self.termination_audio_path}")
            self._set_playback_state(True)  # Track termination audio playback
            playsound(self.termination_audio_path)
            logger.info("Termination audio played successfully")
            self._set_playback_state(False)  # End termination audio playback
        except Exception as e:
            logger.error(f"Error playing termination audio: {e}")
            self._set_playback_state(False)  # Ensure state is reset on error

        with self._mic_lock:
            if self._current_mic and self._current_mic.is_running():
                self._current_mic.unmute()

    def _silence_watcher(self):
        while self._active:
            if self._last_user_time is None:
                time.sleep(1)
                continue
            
            # Skip silence counting if audio is playing (TTS or nudge)
            if self._is_audio_playing():
                time.sleep(1)
                continue
            
            # Skip silence counting if microphone is not active/muted
            with self._mic_lock:
                mic_active = self._current_mic and self._current_mic.is_running() and not self._current_mic.is_muted()
            
            if not mic_active:
                logger.debug("Silence watcher paused - microphone not active or muted")
                time.sleep(1)
                continue
                
            elapsed = time.time() - self._last_user_time
            if elapsed >= self.silence_timeout and not self._nudged:
                logger.info(f"Silence detected ({elapsed:.1f}s), nudging user")
                self._play_nudge()
                self._nudged = True
            elif elapsed >= self.silence_timeout + self.nudge_timeout:
                logger.info(f"No reply after nudge ({elapsed:.1f}s), playing termination audio")
                self._play_termination_audio()
                logger.info("Stopping session after termination audio")
                self.stop()
                break
            else:
                logger.debug(f"Silence watcher: {elapsed:.1f}s elapsed, nudged={self._nudged}")
            time.sleep(1)

    def _on_turn_complete(self, user_text: str, assistant_reply: str):
        self._turn_count += 1
        
        # Reset silence timeout when turn is complete and microphone becomes active
        self._last_user_time = time.time()
        self._nudged = False
        logger.info(f"Turn {self._turn_count} done - silence timeout reset, microphone active")

        clean = self._strip_emojis(assistant_reply)
        if clean != assistant_reply:
            if self.pipeline.messages and self.pipeline.messages[-1]["role"] == "assistant":
                self.pipeline.messages[-1]["content"] = clean

        if self._is_termination_phrase(user_text):
            logger.info("Termination phrase triggered")
            self.stop()
            return

        if self._turn_count >= self.max_turns:
            logger.info("Max turns reached, ending")
            self.stop()

    def _capture_transcript_with_tracking(self) -> Optional[str]:
        mic = self.mic_factory()
        with self._mic_lock:
            self._current_mic = mic

        try:
            mic.start()
            final_text: Optional[str] = None
            def on_transcript(text: str, is_final: bool):
                nonlocal final_text
                if is_final:
                    final_text = text
                    mic.stop()
            self.stt.stream_recognize(mic.generator(), on_transcript)
            return final_text
        except Exception as e:
            logger.error(f"STT error: {e}")
            return None
        finally:
            mic.stop()
            with self._mic_lock:
                self._current_mic = None

    def _init_audio_stream(self):
        if self._audio_stream:
            return
        format_pa = self._pyaudio.get_format_from_width(self.sample_width_bytes)
        self._audio_stream = self._pyaudio.open(
            format=format_pa,
            channels=self.num_channels,
            rate=self.sample_rate,
            output=True,
            frames_per_buffer=1024
        )

    def _play_pcm_chunk(self, pcm_bytes: bytes):
        if not self._audio_stream:
            self._init_audio_stream()
        try:
            self._audio_stream.write(pcm_bytes)
        except Exception as e:
            logger.error(f"Audio playback error: {e}")

    def _set_playback_state(self, is_playing: bool):
        """Set the audio playback state for silence watcher."""
        with self._playback_lock:
            self._is_playing_audio = is_playing
            if is_playing:
                logger.debug("Audio playback started - pausing silence watcher")
            else:
                logger.debug("Audio playback ended - resuming silence watcher")

    def _is_audio_playing(self) -> bool:
        """Check if audio is currently playing."""
        with self._playback_lock:
            return self._is_playing_audio

    def start(self):
        if self._active:
            logger.warning("Already active")
            return
        self._active = True
        self._turn_count = 0
        self._nudged = False
        self._last_user_time = None

        self._silence_watcher_thread = threading.Thread(target=self._silence_watcher, daemon=True)
        self._silence_watcher_thread.start()

        logger.info("Starting SmallTalk session")

        def run():
            from ..supabase.database import start_conversation
            try:
                self.pipeline.conversation_id = start_conversation(title="Small Talk")
            except Exception as e:
                logger.warning(f"Could not start conversation: {e}")

            while self._active:
                user_text = self._capture_transcript_with_tracking()
                if not user_text:
                    continue

                logger.info(f"[User] {user_text}")
                self.pipeline.messages.append({"role": "user", "content": user_text})

                if self.pipeline.conversation_id:
                    try:
                        from ..supabase.database import add_message
                        add_message(
                            conversation_id=self.pipeline.conversation_id,
                            role="user",
                            content=user_text,
                            intent="small_talk",
                            lang=self.language_code
                        )
                    except Exception as e:
                        logger.warning(f"Could not save user message: {e}")

                if self._is_termination_phrase(user_text):
                    logger.info("Termination phrase, ending")
                    self.stop()
                    break

                logger.info("[Assistant speaking]")
                self._set_playback_state(True)  # Start TTS audio playback
                try:
                    for pcm_chunk in self.pipeline._stream_llm_and_tts():
                        # Before playback, mute mic
                        with self._mic_lock:
                            if self._current_mic and self._current_mic.is_running():
                                self._current_mic.mute()

                        self._play_pcm_chunk(pcm_chunk)
                finally:
                    # After playback, unmute mic and stop playback tracking
                    with self._mic_lock:
                        if self._current_mic and self._current_mic.is_running():
                            self._current_mic.unmute()
                    self._set_playback_state(False)  # End TTS audio playback
                    logger.info("TTS playback finished - microphone active, silence watcher resuming")
                    
                    # Reset silence timeout when microphone becomes active after TTS
                    self._last_user_time = time.time()
                    self._nudged = False
                    logger.info("Silence timeout reset - microphone active after TTS")

                # Log assistant text
                assistant_text = self.pipeline.messages[-1]["content"]
                if self.pipeline.conversation_id:
                    try:
                        from ..supabase.database import add_message
                        add_message(
                            conversation_id=self.pipeline.conversation_id,
                            role="assistant",
                            content=assistant_text,
                            lang=self.language_code
                        )
                    except Exception as e:
                        logger.warning(f"Could not save assistant message: {e}")

                self._on_turn_complete(user_text, assistant_text)
                if not self._active:
                    break

            # cleanup audio
            if self._audio_stream:
                try:
                    self._audio_stream.stop_stream()
                    self._audio_stream.close()
                except:
                    pass
                self._audio_stream = None
            if self._pyaudio:
                try:
                    self._pyaudio.terminate()
                except:
                    pass

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def stop(self):
        if not self._active:
            return
        self._active = False
        logger.info("Stopping session")
        if self._silence_watcher_thread and self._silence_watcher_thread.is_alive() and threading.current_thread() != self._silence_watcher_thread:
            self._silence_watcher_thread.join(timeout=1)

    def is_active(self) -> bool:
        return self._active
