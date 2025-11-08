#!/usr/bin/env python3
"""
Meditation Activity

Plays guided meditation audio files, listens for termination phrases during
playback, and transitions to SmallTalk with contextual prompts.
"""

import logging
import sys
import threading
import time
import gc
import os
import tempfile
import pyaudio
import wave
from pathlib import Path
from typing import Optional

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent.parent
sys.path.append(str(backend_dir))

# Use lazy imports from __init__.py to prevent cascade import issues
from src.components import (
    MicStream,
    ConversationAudioManager,
    GoogleTTSClient,
    IntentRecognition
)
from src.utils.config_loader import RHINO_ACCESS_KEY
from src.utils.config_resolver import get_global_config_for_user, get_language_config, resolve_language
from src.supabase.auth import get_current_user_id
from src.supabase.database import log_activity_completion
from src.activities.smalltalk import SmallTalkActivity

logger = logging.getLogger(__name__)


class MeditationActivity:
    def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
        self.backend_dir = backend_dir
        self.user_id = user_id or get_current_user_id()

        # Components
        self.audio_manager: Optional[ConversationAudioManager] = None
        self.tts: Optional[GoogleTTSClient] = None
        self.intent_recognition: Optional[IntentRecognition] = None

        # Configs
        self.global_config = None
        self.language_config = None
        self.audio_paths = None
        self.meditation_config = None
        
        # State
        self._initialized = False
        self._active = False
        self._activity_log_id: Optional[str] = None  # Track log ID for completion
        
        # Threading for parallel playback and listening
        self._audio_playback_thread: Optional[threading.Thread] = None
        self._listening_thread: Optional[threading.Thread] = None
        self._termination_detected = threading.Event()
        self._audio_stopped = threading.Event()
        self._meditation_completed = False

    def initialize(self) -> bool:
        try:
            logger.info("Initializing Meditation activity...")
            self.global_config = get_global_config_for_user(self.user_id)
            self.language_config = get_language_config(self.user_id)
            self.audio_paths = self.language_config.get("audio_paths", {})
            self.meditation_config = self.language_config.get("meditation", {})

            # Initialize Rhino intent recognition for termination detection
            context_path = self.backend_dir / "config" / "Intent" / "Well-Bot-Commands_en_windows_v3_0_0.rhn"
            try:
                if not RHINO_ACCESS_KEY:
                    logger.error("RHINO_ACCESS_KEY not configured, cannot initialize Rhino")
                    return False
                elif not context_path.exists():
                    logger.error(f"Rhino context file not found: {context_path}")
                    return False
                else:
                    self.intent_recognition = IntentRecognition(
                        access_key=RHINO_ACCESS_KEY,
                        context_path=context_path,
                        sensitivity=0.5,
                        require_endpoint=True
                    )
                    logger.info("Rhino intent recognition initialized for meditation termination detection")
            except FileNotFoundError as e:
                logger.error(f"Rhino context file not found: {e}", exc_info=True)
                return False
            except Exception as e:
                logger.error(f"Failed to initialize Rhino intent recognition: {e}", exc_info=True)
                return False

            def mic_factory():
                return MicStream()

            # Audio manager doesn't need STT for meditation (we use Rhino directly)
            from src.components.stt import GoogleSTTService
            stt_lang = self.global_config["language_codes"]["stt_language_code"]
            audio_settings = self.global_config.get("audio_settings", {})
            stt_sample_rate = audio_settings.get("stt_sample_rate", 16000)
            stt_service = GoogleSTTService(language=stt_lang, sample_rate=stt_sample_rate)
            
            # Audio config - minimal config since we only use this for TTS playback
            # Meditation uses its own Rhino-based termination detection, not silence monitoring
            audio_config = {
                "backend_dir": str(self.backend_dir),
            }
            self.audio_manager = ConversationAudioManager(stt_service, mic_factory, audio_config)

            # TTS client for speaking prompts
            from google.cloud import texttospeech
            self.tts = GoogleTTSClient(
                voice_name=self.global_config["language_codes"]["tts_voice_name"],
                language_code=self.global_config["language_codes"]["tts_language_code"],
                audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                sample_rate_hertz=audio_settings.get("tts_sample_rate_hertz", 24000),
                num_channels=audio_settings.get("tts_num_channels", 1),
                sample_width_bytes=audio_settings.get("tts_sample_width_bytes", 2),
            )

            self._initialized = True
            logger.info("Meditation activity initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Meditation activity: {e}", exc_info=True)
            return False

    def _get_meditation_file_path(self) -> Optional[Path]:
        """
        Get meditation file path based on user's language preference.
        Returns path to meditation file or None if not found.
        """
        # Get user's language directly from resolver
        user_lang = resolve_language(self.user_id)
        logger.info(f"Resolved user language: {user_lang} for user {self.user_id}")
        
        # Map language codes to file prefixes
        lang_map = {
            "en": "EN",
            "cn": "CN",
            "bm": "BM"
        }
        
        file_prefix = lang_map.get(user_lang, "EN")
        meditation_dir = self.backend_dir / "assets" / "Meditation"
        
        logger.info(f"Looking for meditation file with prefix: {file_prefix} in {meditation_dir}")
        
        # Try to find file with matching prefix
        # Files are named like: EN_3.28.wav, CN_3.56.wav
        for file_path in meditation_dir.glob(f"{file_prefix}_*.wav"):
            if file_path.exists():
                logger.info(f"Found meditation file: {file_path}")
                return file_path
        
        # Fallback to English if user's language not found
        if user_lang != "en":
            logger.warning(f"No meditation file found for language '{user_lang}', falling back to English")
            for file_path in meditation_dir.glob("EN_*.wav"):
                if file_path.exists():
                    logger.info(f"Using fallback meditation file: {file_path}")
                    return file_path
        
        logger.error(f"No meditation file found in {meditation_dir}")
        return None

    def _play_meditation_audio(self, audio_path: Path):
        """Play meditation audio file with interrupt capability (runs in separate thread)"""
        try:
            logger.info(f"Starting meditation audio playback: {audio_path}")
            
            # Use pyaudio for interruptible playback
            wf = wave.open(str(audio_path), 'rb')
            pa = pyaudio.PyAudio()
            
            stream = pa.open(
                format=pa.get_format_from_width(wf.getsampwidth()),
                channels=wf.getnchannels(),
                rate=wf.getframerate(),
                output=True
            )
            
            chunk_size = 1024
            data = wf.readframes(chunk_size)
            
            while data and not self._termination_detected.is_set():
                stream.write(data)
                data = wf.readframes(chunk_size)
            
            # Check if we completed or were interrupted
            if not self._termination_detected.is_set():
                logger.info("Meditation audio playback completed")
                self._meditation_completed = True
            else:
                logger.info("Meditation audio playback interrupted by termination phrase")
            
            stream.stop_stream()
            stream.close()
            pa.terminate()
            wf.close()
            
        except Exception as e:
            logger.error(f"Error during meditation audio playback: {e}", exc_info=True)
        finally:
            # Signal that audio has stopped
            self._audio_stopped.set()

    def _listen_for_termination(self):
        """Listen for termination intent using Rhino during meditation (runs in separate thread)"""
        if not self.intent_recognition:
            logger.error("Rhino intent recognition not initialized, cannot listen for termination")
            return
        
        mic = None
        try:
            logger.info("Starting Rhino termination detection...")
            
            # Get Rhino's required audio format
            rhino_sample_rate = self.intent_recognition.get_sample_rate()
            rhino_frame_length = self.intent_recognition.get_frame_length()
            
            mic = MicStream(rate=rhino_sample_rate, chunk_size=rhino_frame_length)
            
            with self.audio_manager._mic_lock:
                self.audio_manager._current_mic = mic
            
            mic.start()
            
            # Reset Rhino for new session
            self.intent_recognition.reset()
            
            logger.info(f"Rhino termination detection active (sample_rate: {rhino_sample_rate}Hz, frame_length: {rhino_frame_length})")
            
            # Continue listening until termination detected or audio stops
            while self._active and not self._termination_detected.is_set() and not self._audio_stopped.is_set():
                try:
                    # Process audio frames with Rhino
                    for audio_chunk in mic.generator():
                        if not self._active or self._termination_detected.is_set() or self._audio_stopped.is_set():
                            break
                        
                        # Process frame with Rhino
                        if self.intent_recognition.process_bytes(audio_chunk):
                            # Inference is ready
                            inference = self.intent_recognition.get_inference()
                            
                            if inference and inference.get('intent') == 'termination':
                                logger.info(f"🎯 TERMINATION INTENT DETECTED during meditation")
                                self._termination_detected.set()
                                break
                            else:
                                # Not termination, reset and continue listening
                                self.intent_recognition.reset()
                    
                    # If we exited the generator loop but should still be listening, continue
                    if self._active and not self._termination_detected.is_set() and not self._audio_stopped.is_set():
                        logger.debug("Audio stream ended, continuing to listen...")
                        time.sleep(0.1)
                    else:
                        break
                        
                except Exception as e:
                    logger.error(f"Rhino error during termination listening: {e}")
                    # Try to continue listening
                    if self._active and not self._termination_detected.is_set() and not self._audio_stopped.is_set():
                        time.sleep(0.5)
                        self.intent_recognition.reset()
                    else:
                        break
                        
        except Exception as e:
            logger.error(f"Error in termination listening thread: {e}", exc_info=True)
        finally:
            if mic:
                try:
                    mic.stop()
                except:
                    pass
            with self.audio_manager._mic_lock:
                if self.audio_manager._current_mic == mic:
                    self.audio_manager._current_mic = None
            
            logger.info("Termination listening thread ended")

    def _speak(self, text: str):
        """Speak text using TTS"""
        if not self.tts or not self.audio_manager:
            return
        def gen():
            yield text
        pcm = self.tts.stream_synthesize(gen())
        self.audio_manager.play_tts_stream(pcm)

    def set_activity_log_id(self, log_id: Optional[str]):
        """Set the activity log ID for completion tracking."""
        self._activity_log_id = log_id

    def run(self) -> bool:
        if not self._initialized:
            logger.error("Meditation activity not initialized")
            return False

        try:
            self._active = True
            
            # Get meditation file
            meditation_file = self._get_meditation_file_path()
            if not meditation_file:
                logger.error("No meditation file found")
                self._speak("I'm sorry, I couldn't find a meditation file for you right now.")
                return False

            # Play start prompt
            start_prompt = self.meditation_config.get("start_prompt", "Starting your meditation session now.")
            logger.info(f"Playing start prompt: {start_prompt}")
            self._speak(start_prompt)
            
            # Wait before starting meditation (configurable)
            meditation_global_config = self.global_config.get("meditation", {})
            delay_seconds = meditation_global_config.get("meditation_start_delay_seconds", 3.0)
            logger.info(f"Waiting {delay_seconds} seconds before starting meditation...")
            time.sleep(delay_seconds)

            # Reset state flags
            self._termination_detected.clear()
            self._audio_stopped.clear()
            self._meditation_completed = False

            # Start audio playback in separate thread
            logger.info("Starting meditation audio playback thread...")
            self._audio_playback_thread = threading.Thread(
                target=self._play_meditation_audio,
                args=(meditation_file,),
                daemon=True
            )
            self._audio_playback_thread.start()

            # Start termination listening in separate thread
            logger.info("Starting termination phrase listening thread...")
            self._listening_thread = threading.Thread(
                target=self._listen_for_termination,
                daemon=True
            )
            self._listening_thread.start()

            # Wait for either termination or audio completion
            logger.info("Waiting for meditation to complete or be terminated...")
            while self._active:
                # Check if termination detected
                if self._termination_detected.is_set():
                    logger.info("Meditation terminated by user")
                    # Stop audio playback if possible
                    # Note: pydub's play() is blocking, so we can't easily interrupt it
                    # But we can set the flag and continue
                    break
                
                # Check if audio completed
                if self._audio_stopped.is_set():
                    logger.info("Meditation audio completed")
                    break
                
                # Check if threads are still alive
                if not self._audio_playback_thread.is_alive() and not self._listening_thread.is_alive():
                    logger.info("Both threads ended")
                    break
                
                time.sleep(0.5)

            # Clean up meditation activity before transitioning
            logger.info("Cleaning up meditation activity resources...")
            self._active = False
            
            # Wait for threads to finish
            if self._audio_playback_thread and self._audio_playback_thread.is_alive():
                logger.info("Waiting for audio playback thread to finish...")
                self._audio_playback_thread.join(timeout=3.0)
            if self._listening_thread and self._listening_thread.is_alive():
                logger.info("Waiting for listening thread to finish...")
                self._listening_thread.join(timeout=3.0)
            
            # Cleanup audio manager resources
            if self.audio_manager:
                try:
                    logger.info("Stopping and cleaning up audio manager...")
                    self.audio_manager.stop()
                    self.audio_manager.cleanup()
                except Exception as e:
                    logger.warning(f"Error cleaning up audio manager: {e}")
            
            # Small delay to ensure audio devices are fully released
            logger.info("Waiting for audio devices to be released...")
            time.sleep(0.5)

            # Determine completion status
            was_completed = self._meditation_completed and not self._termination_detected.is_set()
            completed = was_completed
            
            # Transition to SmallTalk with contextual prompts
            logger.info(f"Meditation cleanup complete. Transitioning to SmallTalk (completed={was_completed})...")
            
            if was_completed:
                seed = self.meditation_config.get(
                    "seed_system_prompt_completed",
                    "You just completed a guided meditation session with the user. Transition into a warm, brief small talk. Ask one inviting, open question about how the meditation felt or what they experienced."
                )
                opener = self.meditation_config.get(
                    "opener_completed",
                    "How did that meditation feel?"
                )
            else:
                seed = self.meditation_config.get(
                    "seed_system_prompt_stopped",
                    "The user stopped a guided meditation session halfway. Transition into a warm, brief small talk. Ask one inviting, open question about how they're feeling or if everything is okay."
                )
                opener = self.meditation_config.get(
                    "opener_stopped",
                    "I noticed you stopped the meditation. How are you feeling?"
                )

            smalltalk = SmallTalkActivity(backend_dir=self.backend_dir, user_id=self.user_id)
            if not smalltalk.initialize():
                logger.error("Failed to initialize SmallTalk for handoff")
                return False
            
            smalltalk.start(seed_system_prompt=seed, custom_start_prompt=opener)
            # Continue the normal conversation loop
            ok = smalltalk._conversation_loop()
            smalltalk.stop()
            smalltalk.cleanup()
            smalltalk.reinitialize()
            return ok
            
        except Exception as e:
            logger.error(f"Meditation activity error: {e}", exc_info=True)
            completed = False
            return False
        finally:
            # Log completion status
            if self._activity_log_id:
                log_activity_completion(self._activity_log_id, completed)
            
            self._active = False

    def cleanup(self):
        """Complete cleanup of all resources including native libraries, cached resources, and dependencies"""
        logger.info("🧹 Cleaning up Meditation activity resources...")
        
        # Stop if still active
        if self._active:
            self._active = False
        
        # Stop threads if still running
        if self._audio_playback_thread and self._audio_playback_thread.is_alive():
            try:
                logger.info("🧹 Stopping audio playback thread...")
                self._audio_playback_thread.join(timeout=1.0)
                logger.debug("Audio playback thread stopped")
            except Exception as e:
                logger.warning(f"Error stopping audio playback thread: {e}")
        
        if self._listening_thread and self._listening_thread.is_alive():
            try:
                logger.info("🧹 Stopping listening thread...")
                self._listening_thread.join(timeout=1.0)
                logger.debug("Listening thread stopped")
            except Exception as e:
                logger.warning(f"Error stopping listening thread: {e}")
        
        # Cleanup audio manager (handles PyAudio streams)
        if self.audio_manager:
            try:
                logger.info("🧹 Cleaning up audio manager...")
                self.audio_manager.stop()
                self.audio_manager.cleanup()
                self.audio_manager = None
                logger.info("✓ Audio manager cleaned up")
            except Exception as e:
                logger.warning(f"Error during audio manager cleanup: {e}")
        
        # Cleanup TTS service (Google Cloud TTS client)
        if self.tts:
            try:
                logger.info("🧹 Cleaning up TTS service...")
                # Close Google Cloud TTS client
                if hasattr(self.tts, 'client') and self.tts.client:
                    try:
                        self.tts.client = None
                        logger.debug("TTS client closed")
                    except Exception as e:
                        logger.warning(f"Error closing TTS client: {e}")
                self.tts = None
                logger.info("✓ TTS service cleaned up")
            except Exception as e:
                logger.warning(f"Error during TTS cleanup: {e}")
        
        # Cleanup intent recognition (Rhino native library)
        if self.intent_recognition:
            try:
                logger.info("🧹 Cleaning up intent recognition (Rhino)...")
                self.intent_recognition.delete()
                self.intent_recognition = None
                logger.info("✓ Intent recognition cleaned up")
            except Exception as e:
                logger.warning(f"Error during intent recognition cleanup: {e}")
        
        # Clear config caches
        try:
            from src.utils.config_resolver import _resolver
            if hasattr(_resolver, 'clear_cache'):
                logger.info("🧹 Clearing config caches...")
                _resolver.clear_cache()
                logger.debug("Config caches cleared")
        except Exception as e:
            logger.debug(f"Could not clear config cache: {e}")
        
        # Cleanup temporary files (if any were created)
        try:
            logger.info("🧹 Checking for temporary files...")
            # Check for temporary Google Cloud credentials file
            # Note: This is a best-effort cleanup - the file may have been cleaned up already
            temp_dir = tempfile.gettempdir()
            # We can't easily track which temp files we created, so this is optional
            # If you track temp file paths, clean them up here
            logger.debug("Temporary file check completed")
        except Exception as e:
            logger.debug(f"Could not check temporary files: {e}")
        
        # Force garbage collection to help release native library resources
        try:
            logger.info("🧹 Running garbage collection...")
            collected = gc.collect()
            logger.debug(f"Garbage collection collected {collected} objects")
        except Exception as e:
            logger.warning(f"Error during garbage collection: {e}")
        
        # Reset initialization state
        self._initialized = False
        
        logger.info("✅ Meditation activity cleanup completed")

    def is_active(self) -> bool:
        return bool(self._active)


# For testing when run directly
if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def main():
        """Test the Meditation activity"""
        try:
            # Get backend directory
            backend_dir = Path(__file__).parent.parent.parent
            
            # Create and initialize activity
            activity = MeditationActivity(backend_dir)
            
            if not activity.initialize():
                logger.error("Failed to initialize activity")
                return 1
            
            logger.info("=== Meditation Activity Test ===")
            logger.info("The activity will:")
            logger.info("- Play a guided meditation audio file")
            logger.info("- Listen for termination phrases during playback")
            logger.info("- Transition to SmallTalk after completion or termination")
            logger.info("- Press Ctrl+C to stop")
            
            # Run the activity
            success = activity.run()
            
            # Cleanup
            activity.cleanup()
            
            if success:
                logger.info("=== Meditation Activity Test Completed Successfully! ===")
            else:
                logger.error("=== Meditation Activity Test Failed! ===")
                return 1
            
            return 0
            
        except KeyboardInterrupt:
            logger.info("Test interrupted by user")
            return 0
        except Exception as e:
            logger.error(f"Test failed: {e}", exc_info=True)
            return 1
    
    exit(main())

