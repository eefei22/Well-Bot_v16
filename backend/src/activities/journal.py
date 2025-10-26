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
from src.supabase.database import upsert_journal, DEV_USER_ID
from google.cloud import texttospeech

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """
    Normalize text for robust matching:
    - Convert to lowercase
    - Remove punctuation
    - Collapse whitespace
    """
    if not text:
        return ""
    
    # Convert to lowercase and strip
    normalized = text.strip().lower()
    
    # Remove punctuation
    normalized = normalized.translate(str.maketrans("", "", string.punctuation))
    
    # Collapse multiple spaces into single space
    normalized = " ".join(normalized.split())
    
    return normalized


class TerminationPhraseDetected(Exception):
    """Raised when user utterance matches a termination phrase"""
    pass


class JournalActivity:
    """
    Journal Activity Class
    
    Captures user speech, detects pauses and termination phrases,
    and automatically saves journal entries to the database.
    """
    
    def __init__(self, backend_dir: Path, user_id: str = DEV_USER_ID):
        """Initialize the Journal activity"""
        self.backend_dir = backend_dir
        self.user_id = user_id
        
        # Components (initialized in initialize())
        self.audio_manager: Optional[ConversationAudioManager] = None
        self.stt_service: Optional[GoogleSTTService] = None
        self.tts_service: Optional[GoogleTTSClient] = None
        self.config: Optional[dict] = None
        self.preferences: Optional[dict] = None
        
        # Activity state
        self.state = "INIT"
        self._active = False
        self._initialized = False
        
        # Paragraph buffering
        self.buffers: List[str] = []
        self.current_buffer = ""
        self.last_final_time = None
        
        # Termination detection
        self.termination_phrases: List[str] = []
        self._termination_detected = False
        self._saved = False  # Track if journal has already been saved
        
        logger.info("JournalActivity initialized")
    
    def initialize(self) -> bool:
        """Initialize the activity components"""
        try:
            # Configuration paths
            journal_config_path = self.backend_dir / "config" / "journal_behavior.json"
            preferences_path = self.backend_dir / "config" / "preference.json"
            
            logger.info(f"Initializing Journal activity...")
            logger.info(f"Backend directory: {self.backend_dir}")
            logger.info(f"Journal config: {journal_config_path}")
            
            # Check if required files exist
            if not journal_config_path.exists():
                logger.error(f"Required file not found: {journal_config_path}")
                return False
            
            if not preferences_path.exists():
                logger.error(f"Required file not found: {preferences_path}")
                return False
            
            # Load journal configuration
            with open(journal_config_path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
                logger.info("✓ Loaded journal configuration")
            
            # Load user preferences for audio paths
            with open(preferences_path, "r", encoding="utf-8") as f:
                self.preferences = json.load(f)
                logger.info("✓ Loaded preferences")
            
            # Initialize STT service
            logger.info("Initializing STT service...")
            self.stt_service = GoogleSTTService(language="en-US", sample_rate=16000)
            logger.info("✓ STT service initialized")
            
            # Create mic factory
            def mic_factory():
                return MicStream()
            
            # Initialize TTS service
            logger.info("Initializing TTS service...")
            self.tts_service = GoogleTTSClient(
                voice_name=self.preferences.get("tts_voice_name", "en-US-Chirp3-HD-Charon"),
                language_code=self.preferences.get("tts_language_code", "en-US"),
                audio_encoding=texttospeech.AudioEncoding.PCM,
                sample_rate_hertz=24000,
                num_channels=1,
                sample_width_bytes=2
            )
            logger.info("✓ TTS service initialized")
            
            # Prepare audio configuration for ConversationAudioManager
            audio_config = {
                "backend_dir": str(self.backend_dir),
                "silence_timeout_seconds": self.config.get("silence_timeout_seconds", 90),
                "nudge_timeout_seconds": self.config.get("nudge_timeout_seconds", 20),
                "nudge_pre_delay_ms": self.config.get("nudge_pre_delay_ms", 200),
                "nudge_post_delay_ms": self.config.get("nudge_post_delay_ms", 300),
                "nudge_audio_path": self.preferences.get("nudge_audio_path", "assets/ENGLISH/inactivity_nudge_EN_male.wav"),
                "termination_audio_path": self.preferences.get("termination_audio_path", "assets/ENGLISH/termination_EN_male.wav"),
                "end_audio_path": "",
                "start_audio_path": self.preferences.get("start_journal_audio_path", "assets/ENGLISH/start_journal_EN_male.wav")
            }
            
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
            
            # Load termination phrases
            self.termination_phrases = self.config.get("termination_phrases", [])
            logger.info(f"✓ Loaded {len(self.termination_phrases)} termination phrases")
            
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
            if self._has_content():
                self.state = "SAVING"
                self._save()
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
        
        use_audio_files = self.config.get("use_audio_files", False)
        
        # Play start audio if enabled
        if use_audio_files:
            start_audio_path = self.preferences.get("start_journal_audio_path", "assets/ENGLISH/start_journal_EN_male.wav")
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
            
            # Reset silence timer on any transcript
            if self.audio_manager:
                self.audio_manager.reset_silence_timer()
            
            if is_final:
                logger.info(f"Final transcript: {text}")
                
                # Check for termination phrase
                if self._is_termination_phrase(text):
                    logger.info(f"Termination phrase detected in: {text}")
                    self._termination_detected = True
                    mic.stop()
                    raise TerminationPhraseDetected()
                
                # Finalize paragraph if long pause detected
                current_time = time.time()
                if self.last_final_time:
                    elapsed = current_time - self.last_final_time
                    pause_threshold = self.config.get("pause_finalization_seconds", 2.5)
                    
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
                    if self._is_termination_phrase(text):
                        logger.info(f"Termination phrase detected in interim: {text}")
                        self._termination_detected = True
                        mic.stop()
                        raise TerminationPhraseDetected()
        
        try:
            # Start STT streaming
            self.stt_service.stream_recognize(
                mic.generator(),
                on_transcript,
                interim_results=True,
                single_utterance=False
            )
        finally:
            mic.stop()
            
            # Unregister mic from ConversationAudioManager
            with self.audio_manager._mic_lock:
                self.audio_manager._current_mic = None
            
            self._stop_silence_monitoring()
            
            # Finalize any remaining buffer
            if self.current_buffer:
                self._finalize_paragraph()
    
    def _is_termination_phrase(self, user_text: str) -> bool:
        """Check if user text contains termination phrases with robust matching"""
        if not user_text or not self._active:
            return False
        
        normalized_user = normalize_text(user_text)
        logger.debug(f"Checking termination - user_text='{user_text}' -> normalized='{normalized_user}'")
        
        for phrase in self.termination_phrases:
            normalized_phrase = normalize_text(phrase)
            
            # Multiple matching strategies for robustness
            if (normalized_user == normalized_phrase or 
                normalized_user.startswith(normalized_phrase + " ") or
                normalized_phrase in normalized_user):
                logger.info(f"Termination phrase matched! '{phrase}' in '{user_text}'")
                return True
        
        return False
    
    def _finalize_paragraph(self):
        """Add current buffer to accumulated paragraphs"""
        if self.current_buffer.strip():
            self.buffers.append(self.current_buffer.strip())
            logger.info(f"Paragraph finalized: {self.current_buffer[:50]}...")
            self.current_buffer = ""
    
    def _has_content(self) -> bool:
        """Check if there's any content to save"""
        all_content = " ".join(self.buffers) + " " + self.current_buffer
        words = all_content.split()
        return len(words) >= self.config.get("min_words_threshold", 5)
    
    def _save(self):
        """Save journal entry to database"""
        # Prevent duplicate saves
        if self._saved:
            logger.info("Journal already saved, skipping duplicate save")
            return
        
        logger.info("Saving journal entry to database...")
        
        # Build entry content
        self._finalize_paragraph()  # Finalize any remaining buffer
        
        if not self.buffers:
            logger.warning("No content to save")
            return
        
        body = "\n\n".join(self.buffers).strip()
        word_count = len(body.split())
        
        # Generate title
        title = self._generate_title()
        
        # Get mood
        mood = self.config.get("default_mood", 3)
        
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
            
            use_audio_files = self.config.get("use_audio_files", False)
            
            # Play nudge audio if enabled
            if use_audio_files:
                nudge_audio_path = self.preferences.get("nudge_audio_path", "assets/ENGLISH/inactivity_nudge_EN_male.wav")
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
        """Cleanup resources"""
        self.state = "DONE"
        self._active = False
        
        logger.info("Cleaning up journal activity...")
        
        if self.audio_manager:
            self.audio_manager.stop()
        
        logger.info("Journal activity cleanup completed")
    
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
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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

