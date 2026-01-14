#!/usr/bin/env python3
"""
Mood Rating Component

Scripted, single-shot mood rating prompt and capture.
Uses shared STT/TTS/audio manager from the Assistant.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any

from .mic_stream import MicStream
from src.utils.mood_rating import parse_mood_rating_from_speech

logger = logging.getLogger(__name__)


class MoodRatingComponent:
    """
    Prompt for a mood rating (1-10) and capture a single response.
    """

    def __init__(self, stt_service, tts_service, audio_manager, language_config: dict, global_config: dict, ui_interface=None):
        self.stt_service = stt_service
        self.tts_service = tts_service
        self.audio_manager = audio_manager
        self.language_config = language_config
        self.global_config = global_config
        self.ui_interface = ui_interface

    def prompt(self, phase: str = "pre") -> Dict[str, Any]:
        """
        Prompt for mood rating.

        Returns:
            dict with keys: rating, silence, invalid, transcript
        """
        prompt_text = self._get_prompt_text(phase)
        timeout_seconds = self.global_config.get("assistant", {}).get("response_timeout_seconds", 10.0)
        skip_phrases = self.language_config.get("mood_rating", {}).get(
            "skip_phrases", ["skip", "no", "not now", "later", "pass"]
        )

        self._speak(prompt_text)
        logger.info(f"Prompting for mood rating (phase={phase}, timeout={timeout_seconds}s)")
        transcript = self._capture_single_transcript(timeout_seconds=timeout_seconds)
        logger.info(f"Mood rating transcript captured: '{transcript}'")

        if not transcript:
            return {"rating": None, "silence": True, "invalid": False, "transcript": None}

        rating = parse_mood_rating_from_speech(transcript, skip_phrases)
        if rating is None:
            return {"rating": None, "silence": False, "invalid": True, "transcript": transcript}

        return {"rating": rating, "silence": False, "invalid": False, "transcript": transcript}

    def _get_prompt_text(self, phase: str) -> str:
        assistant_cfg = self.language_config.get("assistant", {})
        assistant_prompts = assistant_cfg.get("prompts", {})
        mood_cfg = self.language_config.get("mood_rating", {})

        if phase == "post":
            return assistant_prompts.get("post_mood", mood_cfg.get("prompt_after", "How are you feeling right now?"))
        return assistant_prompts.get("pre_mood", mood_cfg.get("prompt_before", "How are you feeling right now?"))

    def _speak(self, text: str):
        if not text:
            return

        def text_gen():
            yield text

        # Notify UI (if available) that we're speaking. The audio manager
        # will also set speaker status while playing, but we set it here
        # for extra safety / immediate feedback.
        try:
            if self.ui_interface:
                self.ui_interface.update_speaker_status("speaking")
        except Exception:
            pass

        pcm_chunks = self.tts_service.stream_synthesize(text_gen())
        try:
            self.audio_manager.play_tts_stream(pcm_chunks, use_nudge_delays=False)
        finally:
            try:
                if self.ui_interface:
                    self.ui_interface.update_speaker_status("idle")
            except Exception:
                pass

    def _capture_single_transcript(self, timeout_seconds: float = 10.0) -> Optional[str]:
        mic: MicStream = self.audio_manager.mic_factory()
        mic.start()
        logger.info(f"Mood rating mic started (muted={mic.is_muted()})")

        with self.audio_manager._mic_lock:
            self.audio_manager._current_mic = mic

        # Notify UI that mic is listening for mood rating
        try:
            if self.ui_interface:
                self.ui_interface.update_mic_status("listening")
        except Exception:
            pass

        final_text: Optional[str] = None
        interim_text: Optional[str] = None
        stt_completed = threading.Event()
        stt_error = None

        def on_transcript(text: str, is_final: bool):
            nonlocal final_text
            nonlocal interim_text
            if text:
                logger.info(f"Mood rating STT transcript (final={is_final}): '{text}'")
            if is_final and text:
                final_text = text
                mic.stop()
            elif text:
                interim_text = text

        def run_stt():
            nonlocal stt_error
            try:
                self.stt_service.stream_recognize(
                    mic.generator(),
                    on_transcript,
                    single_utterance=True,
                    interim_results=True,
                )
            except Exception as e:
                stt_error = e
            finally:
                stt_completed.set()

        stt_thread = threading.Thread(target=run_stt, daemon=True)
        stt_thread.start()

        start_time = time.time()
        check_interval = 0.1
        while not stt_completed.wait(check_interval):
            if time.time() - start_time >= timeout_seconds:
                logger.warning("Mood rating STT timeout reached")
                mic.stop()
                break

        stt_thread.join(timeout=1.0)

        if stt_error:
            logger.error(f"STT error during mood rating capture: {stt_error}")

        mic.stop()
        with self.audio_manager._mic_lock:
            self.audio_manager._current_mic = None

        # Notify UI that mic is now idle
        try:
            if self.ui_interface:
                self.ui_interface.update_mic_status("idle")
        except Exception:
            pass

        if final_text:
            return final_text
        if interim_text:
            logger.info("Using interim transcript for mood rating")
            return interim_text
        return None
