#!/usr/bin/env python3
"""
Journal Activity Class
A standalone journaling feature that captures user speech, detects pauses and termination phrases,
and saves entries to the database.
"""

import os
import sys
import logging
import threading
import time
import json
import re
from pathlib import Path
from typing import Optional, List, Callable
from datetime import datetime
import string

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.components.conversation_audio_manager import ConversationAudioManager
from src.components.tts import GoogleTTSClient
from src.components.termination_phrase import TerminationPhraseDetector, TerminationPhraseDetected
from src.supabase.database import upsert_journal, DEV_USER_ID
from src.utils.config_resolver import get_global_config_for_user, get_language_config
from src.supabase.auth import get_current_user_id
from google.cloud import texttospeech

logger = logging.getLogger(__name__)


class JournalActivity:
    """
    Journal Activity Class
    
    Captures user speech, detects pauses and termination phrases,
    and automatically saves journal entries to the database.
    """
    
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        """Initialize the Journal activity"""
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()
        
        # Components (initialized in initialize())
        self.audio_manager: Optional[ConversationAudioManager] = None
        self.stt_service: Optional[GoogleSTTService] = None
        self.tts_service: Optional[GoogleTTSClient] = None
        self.config: Optional[dict] = None  # journal config from language_config
        self.global_config: Optional[dict] = None  # global numerical config
        
        # Activity state
        self.state = "INIT"
        self._active = False
        self._initialized = False
        
        # Paragraph buffering
        self.buffers: List[str] = []
        self.current_buffer = ""
        self.last_final_time = None
        
        # Termination detection
        self.termination_detector: Optional[TerminationPhraseDetector] = None
        self._termination_detected = False
        self._saved = False  # Track if journal has already been saved
        
        logger.info("JournalActivity initialized")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            logger.info(f"Initializing Journal activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            
            # Load user-specific configurations
            logger.info(f"Loading configs for user {self.user_id}")
            self.global_config = get_global_config_for_user(self.user_id)
            language_config = get_language_config(self.user_id)
            
            # Extract journal config and audio paths
            self.config = language_config.get("journal", {})
            audio_paths = language_config.get("audio_paths", {})
            self.global_journal_config = self.global_config.get("journal", {})
            
            logger.info(f"Configs loaded - Language: {language_config.get('_resolved_language', 'unknown')}")
            logger.info(f"Journal config keys: {list(self.config.keys())}")
            
            logger.info("✓ Loaded journal configuration")
            
            # Initialize STT service
            logger.info("Initializing STT service...")
            stt_language = self.global_config.get("language_codes", {}).get("stt_language_code", "en-US")
            self.stt_service = GoogleSTTService(language=stt_language, sample_rate=16000)
            logger.info(f"✓ STT service initialized with language: {stt_language}")
            
            # Create mic factory
            def mic_factory():
                return MicStream()
            
            # Initialize TTS service
            logger.info("Initializing TTS service...")
            self.tts_service = GoogleTTSClient(
                voice_name=self.global_config["language_codes"]["tts_voice_name"],
                language_code=self.global_config["language_codes"]["tts_language_code"],
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=24000,
                num_channels=1,
                sample_width_bytes=2
            )
            logger.info("✓ TTS service initialized")
            
            # Prepare audio configuration for ConversationAudioManager
            audio_config = {
                "backend_dir": str(self.backend_dir),
                "silence_timeout_seconds": self.global_journal_config.get("silence_timeout_seconds", 90),
                "nudge_timeout_seconds": self.global_journal_config.get("nudge_timeout_seconds", 20),
                "nudge_pre_delay_ms": self.global_journal_config.get("nudge_pre_delay_ms", 200),
                "nudge_post_delay_ms": self.global_journal_config.get("nudge_post_delay_ms", 300),
                "nudge_audio_path": audio_paths.get("nudge_audio_path"),
                "termination_audio_path": audio_paths.get("termination_audio_path"),
                "end_audio_path": "",
                "start_audio_path": audio_paths.get("start_journal_audio_path")
            }
            
            # Store audio paths for later use
            self.audio_paths = audio_paths
            
            # Initialize ConversationAudioManager
            logger.info("Initializing audio manager...")
            self.audio_manager = ConversationAudioManager(
                stt_service=self.stt_service,
                mic_factory=mic_factory,
                audio_config=audio_config,
                sample_rate=24000,
                sample_width_bytes=2,
                num_channels=1
            )
            logger.info("✓ Audio manager initialized")
            
            # Initialize termination phrase detector
            phrases = self.config.get("termination_phrases", [])
            self.termination_detector = TerminationPhraseDetector(phrases, require_active=True)
            logger.info(f"✓ Loaded {len(phrases)} termination phrases")
            
            self._initialized = True
            logger.info("✓ Journal activity fully initialized")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Journal activity: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def start(self):
        """Start the journal session"""
        if not self._initialized:
            logger.error("Journal activity not initialized")
            return
        
        self._active = True
        logger.info("Starting journal session...")
        
        try:
            # State: PROMPT_START
            self._prompt_start()
            
            # State: RECORDING
            self._record_loop()
            
            # Auto-save if we have content (normal completion)
            if not self._termination_detected and self._has_content():
                self.state = "SAVING"
                self._save()
            
            self.state = "DONE"
            logger.info("Journal session completed successfully")
            
        except TerminationPhraseDetected:
            logger.info("Termination phrase detected, saving journal entry...")
            logger.info(f"Content check - buffers: {len(self.buffers)}, current_buffer length: {len(self.current_buffer)}")
            has_content = self._has_content()
            logger.info(f"_has_content() returned: {has_content}")
            if has_content:
                logger.info("Content validated, proceeding to save...")
                self.state = "SAVING"
                self._save()
            else:
                logger.warning("No content to save (below word threshold or empty)")
        except KeyboardInterrupt:
            logger.info("Journal session interrupted by user")
            if self._has_content():
                self.state = "SAVING"
                self._save()
        except Exception as e:
            logger.error(f"Error during journal session: {e}")
            import traceback
            traceback.print_exc()
        finally:
            # If terminated by timeout, save before cleanup (only if not already saved)
            if self._termination_detected and not self._saved and self._has_content():
                logger.info("Saving accumulated content after timeout termination")
                self.state = "SAVING"
                self._save()
            self._cleanup()
    
    def _prompt_start(self):
        """Play start audio and TTS prompt"""
        self.state = "PROMPT_START"
        
        use_audio_files = self.global_journal_config.get("use_audio_files", False)
        
        # Play start audio if enabled
        if use_audio_files:
            start_audio_path = self.audio_paths.get("start_journal_audio_path")
            full_audio_path = self.backend_dir / start_audio_path
            
            if full_audio_path.exists():
                logger.info(f"Playing start audio: {start_audio_path}")
                self.audio_manager.play_audio_file(str(full_audio_path), mute_mic=False)
        
        # TTS prompt from config
        try:
            prompts = self.config.get("prompts", {})
            prompt = prompts.get("start", "Ready to journal. Start speaking after the tone. You can pause anytime to think. Say 'stop journal' when you're finished.")
        except Exception as e:
            logger.warning(f"Failed to load start prompt from config: {e}")
            prompt = "Ready to journal. Start speaking after the tone. You can pause anytime to think. Say 'stop journal' when you're finished."
        
        logger.info("Speaking start prompt...")
        self._speak(prompt)
    
    def _record_loop(self):
        """Main recording loop with STT streaming"""
        self.state = "RECORDING"
        
        # Start silence monitoring BEFORE creating mic
        self._start_silence_monitoring()
        
        # Create mic stream using the mic factory from audio_manager
        # This ensures the mic is tracked by ConversationAudioManager
        mic = self.audio_manager.mic_factory()
        mic.start()
        
        # IMPORTANT: Register the mic with ConversationAudioManager
        # This allows the silence watcher to track it
        with self.audio_manager._mic_lock:
            self.audio_manager._current_mic = mic
        
        self.last_final_time = time.time()
        
        def on_transcript(text: str, is_final: bool):
            if not self._active:
                mic.stop()
                return
            
            # Skip processing if termination already detected (avoid race conditions)
            if self._termination_detected:
                logger.debug(f"Skipping transcript after termination: '{text}'")
                return
            
            # Reset silence timer on any transcript
            if self.audio_manager:
                self.audio_manager.reset_silence_timer()
            
            if is_final:
                logger.info(f"Final transcript: {text}")
                
                # Check for termination phrase
                if self.termination_detector.is_termination_phrase(text, active=self._active):
                    logger.info(f"Termination phrase detected in: {text}")
                    self._termination_detected = True
                    mic.stop()
                    raise TerminationPhraseDetected()
                
                # Finalize paragraph if long pause detected
                current_time = time.time()
                if self.last_final_time:
                    elapsed = current_time - self.last_final_time
                    pause_threshold = self.global_journal_config.get("pause_finalization_seconds", 2.5)
                    
                    if elapsed > pause_threshold:
                        logger.info(f"Long pause detected ({elapsed:.1f}s), finalizing paragraph")
                        self._finalize_paragraph()
                
                # Update buffer
                self.current_buffer += " " + text if self.current_buffer else text
                self.last_final_time = current_time
                
            else:
                # Interim result
                logger.debug(f"Interim transcript: {text}")
                if text:
                    # Check interim for termination phrase
                    if self.termination_detector.is_termination_phrase(text, active=self._active):
                        logger.info(f"Termination phrase detected in interim: {text}")
                        self._termination_detected = True
                        mic.stop()
                        raise TerminationPhraseDetected()
        
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
        except TerminationPhraseDetected:
            logger.info("TerminationPhraseDetected caught in _record_loop")
            # Re-raise so it's caught by the outer handler in start()
            raise
        except Exception as e:
            logger.error(f"Unexpected error in _record_loop during STT streaming: {e}")
            import traceback
            traceback.print_exc()
            raise
        finally:
            mic.stop()
            
            # Unregister mic from ConversationAudioManager
            with self.audio_manager._mic_lock:
                self.audio_manager._current_mic = None
            
            self._stop_silence_monitoring()
            
            # Finalize any remaining buffer
            if self.current_buffer:
                self._finalize_paragraph()
    
    def _finalize_paragraph(self):
        """Add current buffer to accumulated paragraphs"""
        if self.current_buffer.strip():
            self.buffers.append(self.current_buffer.strip())
            logger.info(f"Paragraph finalized: {self.current_buffer[:50]}...")
            self.current_buffer = ""
    
    def _has_content(self) -> bool:
        """Check if there's any content to save"""
        all_content = " ".join(self.buffers) + " " + self.current_buffer
        all_content = all_content.strip()
        
        if not all_content:
            logger.debug("_has_content: empty content")
            return False
        
        # For Chinese/Japanese text (no spaces), count characters instead of words
        # Check if text contains Chinese characters (Unicode range)
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in all_content)
        
        if has_chinese:
            # Count characters (excluding punctuation/whitespace) for Chinese
            chinese_chars = re.findall(r'[\u4e00-\u9fff]', all_content)
            char_count = len(chinese_chars)
            threshold = self.global_journal_config.get("min_words_threshold", 5)
            logger.debug(f"_has_content (Chinese): {char_count} characters, threshold: {threshold}")
            return char_count >= threshold
        else:
            # Count words (split by spaces) for languages with spaces
            words = all_content.split()
            word_count = len(words)
            threshold = self.global_journal_config.get("min_words_threshold", 5)
            logger.debug(f"_has_content (non-Chinese): {word_count} words, threshold: {threshold}")
            return word_count >= threshold
    
    def _save(self):
        """Save journal entry to database"""
        # Prevent duplicate saves
        if self._saved:
            logger.info("Journal already saved, skipping duplicate save")
            return
        
        logger.info("Saving journal entry to database...")
        logger.info(f"Current state - buffers count: {len(self.buffers)}, current_buffer: '{self.current_buffer[:50]}...'")
        
        # Build entry content
        self._finalize_paragraph()  # Finalize any remaining buffer
        logger.info(f"After finalize - buffers count: {len(self.buffers)}")
        
        if not self.buffers:
            logger.warning("No content to save - buffers are empty")
            logger.warning(f"current_buffer was: '{self.current_buffer}'")
            return
        
        body = "\n\n".join(self.buffers).strip()
        
        # Count appropriately for Chinese vs other languages
        has_chinese = any('\u4e00' <= char <= '\u9fff' for char in body)
        if has_chinese:
            chinese_chars = re.findall(r'[\u4e00-\u9fff]', body)
            char_count = len(chinese_chars)
            word_count = char_count  # Use char count for Chinese
            logger.info(f"Prepared journal body: {len(body)} chars, {char_count} Chinese characters (first 100 chars: {body[:100]})")
        else:
            word_count = len(body.split())
            logger.info(f"Prepared journal body: {len(body)} chars, {word_count} words (first 100 chars: {body[:100]})")
        
        # Generate title
        title = self._generate_title()
        
        # Get mood
        mood = self.global_journal_config.get("default_mood", 3)
        
        # Extract topics (placeholder for future)
        topics = self._extract_topics(body)
        
        # Save to database
        try:
            result = upsert_journal(
                user_id=self.user_id,
                title=title,
                body=body,
                mood=mood,
                topics=topics,
                is_draft=False
            )
            logger.info(f"Journal entry saved successfully: {result.get('id')}")
            
            # Mark as saved
            self._saved = True
            
            # Confirmation TTS from config
            try:
                prompts = self.config.get("prompts", {})
                confirmation_template = prompts.get("saved", "Journal entry saved with {word_count} words.")
                confirmation = confirmation_template.format(word_count=word_count)
            except Exception as e:
                logger.warning(f"Failed to load saved prompt from config: {e}")
                confirmation = f"Journal entry saved with {word_count} words."
            
            self._speak(confirmation)
            
        except Exception as e:
            logger.error(f"Failed to save journal entry: {e}")
            import traceback
            traceback.print_exc()
    
    def _generate_title(self) -> str:
        """Generate default title from timestamp"""
        now = datetime.now()
        return f"Journal {now.strftime('%Y-%m-%d %H:%M')}"
    
    def _extract_topics(self, text: str) -> List[str]:
        """Extract topics from text (placeholder for future implementation)"""
        # v1: empty list; v2: simple keyword bag; v3: LLM-based tags
        return []
    
    def _speak(self, text: str):
        """Speak text using TTS"""
        if not self.tts_service:
            return
        
        try:
            def text_gen():
                yield text
            
            # Generate PCM chunks
            pcm_chunks = self.tts_service.stream_synthesize(text_gen())
            
            # Play chunks
            self.audio_manager.play_tts_stream(pcm_chunks)
        except Exception as e:
            logger.error(f"TTS error: {e}")
    
    def _start_silence_monitoring(self):
        """Start silence monitoring for inactivity detection"""
        if not self.audio_manager:
            return
        
        def on_nudge():
            """Called when silence timeout reached"""
            logger.info("Silence nudge triggered")
            
            use_audio_files = self.global_journal_config.get("use_audio_files", False)
            
            # Play nudge audio if enabled
            if use_audio_files:
                nudge_audio_path = self.audio_paths.get("nudge_audio_path")
                full_audio_path = self.backend_dir / nudge_audio_path
                
                if full_audio_path.exists():
                    self.audio_manager.play_audio_file(str(full_audio_path), mute_mic=False)
            
            # TTS nudge from config
            try:
                prompts = self.config.get("prompts", {})
                nudge_text = prompts.get("nudge", "Are you still there? Continue speaking or say 'stop journal' to finish.")
            except Exception as e:
                logger.warning(f"Failed to load nudge prompt from config: {e}")
                nudge_text = "Are you still there? Continue speaking or say 'stop journal' to finish."
            
            self._speak(nudge_text)
        
        def on_timeout():
            """Called when timeout reached after nudge"""
            logger.info("Timeout reached after nudge, finalizing entry")
            self._termination_detected = True
            
            # Stop recording immediately
            with self.audio_manager._mic_lock:
                if self.audio_manager._current_mic:
                    self.audio_manager._current_mic.stop()
            
            # TTS confirmation before saving
            #timeout_message = "Saving your journal entry now."
            #self._speak(timeout_message)
        
        self.audio_manager.start_silence_monitoring(on_nudge, on_timeout)
    
    def _stop_silence_monitoring(self):
        """Stop silence monitoring"""
        if self.audio_manager:
            self.audio_manager.stop_silence_monitoring()
    
    def _cleanup(self):
        """Internal cleanup during session end"""
        self.state = "DONE"
        self._active = False
        
        logger.info("Cleaning up journal activity...")
        
        if self.audio_manager:
            self.audio_manager.stop()
        
        logger.info("Journal activity cleanup completed")
    
    def cleanup(self):
        """Complete cleanup of all resources (public method for orchestrator)"""
        logger.info("🧹 Cleaning up Journal activity resources...")
        
        # Stop if still active
        if self._active:
            self._cleanup()
        
        # Cleanup audio manager
        if self.audio_manager:
            try:
                logger.info("🧹 Cleaning up audio manager...")
                self.audio_manager.cleanup()
                self.audio_manager = None
            except Exception as e:
                logger.warning(f"Error during audio manager cleanup: {e}")
        
        # Cleanup STT service
        if self.stt_service:
            try:
                logger.info("🧹 Cleaning up STT service...")
                self.stt_service = None
            except Exception as e:
                logger.warning(f"Error during STT cleanup: {e}")
        
        # Cleanup TTS service
        if self.tts_service:
            try:
                logger.info("🧹 Cleaning up TTS service...")
                self.tts_service = None
            except Exception as e:
                logger.warning(f"Error during TTS cleanup: {e}")
        
        # Reset state
        self.buffers = []
        self.current_buffer = ""
        self.last_final_time = None
        self._termination_detected = False
        self._saved = False
        
        # Reset initialization state
        self._initialized = False
        
        logger.info("✅ Journal activity cleanup completed")
    
    def reinitialize(self) -> bool:
        """Re-initialize the activity for subsequent runs"""
        logger.info("🔄 Re-initializing Journal activity...")
        
        # Reset state
        self._active = False
        self._initialized = False
        self.buffers = []
        self.current_buffer = ""
        self.last_final_time = None
        self._termination_detected = False
        self._saved = False
        
        # Re-initialize components
        return self.initialize()
    
    def run(self) -> bool:
        """
        Run the complete activity: start and execute journal session
        
        Returns:
            True if activity completed successfully, False otherwise
        """
        logger.info("🎬 JournalActivity.run() - Starting activity execution")
        try:
            # Start the activity (runs the full session synchronously)
            self.start()
            
            # start() handles everything including cleanup, so we just return success
            return True
            
        except Exception as e:
            logger.error(f"Error running Journal activity: {e}", exc_info=True)
            return False
    
    def is_active(self) -> bool:
        """Check if journal session is active"""
        return self._active
    
    def get_status(self) -> dict:
        """Get current status"""
        return {
            "active": self._active,
            "state": self.state,
            "paragraph_count": len(self.buffers),
            "current_buffer_length": len(self.current_buffer),
            "initialized": self._initialized
        }


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Get backend directory
    backend_dir = Path(__file__).parent.parent.parent
    
    # Create activity
    journal = JournalActivity(backend_dir=backend_dir)
    
    # Initialize
    if not journal.initialize():
        logger.error("Failed to initialize journal activity")
        sys.exit(1)
    
    # Start session
    logger.info("=" * 60)
    logger.info("Standalone Journal Feature - Ready to Test")
    logger.info("=" * 60)
    logger.info("Say your journal entry. It will:")
    logger.info("  - Finalize paragraphs after 2.5s pauses")
    logger.info("  - Save automatically after termination phrase")
    logger.info("  - Save automatically after 90s + 20s inactivity")
    logger.info("  - Save on Ctrl+C interrupt")
    logger.info("=" * 60)
    
    try:
        journal.start()
    except KeyboardInterrupt:
        logger.info("\nSession interrupted by user")
    except Exception as e:
        logger.error(f"Session error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        logger.info("Test completed")

