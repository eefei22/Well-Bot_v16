# backend/src/components/conversation_audio_manager.py

import os
import sys
import threading
import time
import logging
from typing import Optional, Callable, Iterator
from pathlib import Path

# Audio playback dependencies
try:
    from pydub import AudioSegment
    from pydub.playback import play
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logging.warning("pydub not available - will use PowerShell fallback for audio")


import pyaudio

logger = logging.getLogger(__name__)


class ConversationAudioManager:
    """
    Unified component that coordinates audio playback, speech capture,
    and silence monitoring with proper microphone management.
    
    This component handles the complex interdependencies between:
    - Speech capture (microphone input)
    - Audio playback (TTS, notifications)
    - Silence detection and user engagement
    """
    
    def __init__(
        self,
        stt_service,
        mic_factory: Callable,
        audio_config: dict,
        sample_rate: int = 24000,
        sample_width_bytes: int = 2,
        num_channels: int = 1
    ):
        """
        Initialize the audio manager with services and configuration.
        
        Args:
            stt_service: GoogleSTTService instance
            mic_factory: Factory function that creates MicStream instances
            audio_config: Configuration dict with audio settings
            sample_rate: Audio sample rate for playback
            sample_width_bytes: Sample width for audio playback
            num_channels: Number of audio channels
        """
        self.stt = stt_service
        self.mic_factory = mic_factory
        
        # Load audio configuration
        self.silence_timeout = audio_config.get("silence_timeout_seconds", 30)
        self.nudge_timeout = audio_config.get("nudge_timeout_seconds", 15)
        self.nudge_pre_delay = audio_config.get("nudge_pre_delay_ms", 200) / 1000.0
        self.nudge_post_delay = audio_config.get("nudge_post_delay_ms", 300) / 1000.0
        
        # Audio file paths (resolved relative to backend directory)
        backend_dir = Path(audio_config.get("backend_dir", "."))
        self.nudge_audio_path = backend_dir / audio_config.get("nudge_audio_path", "assets/inactivity_nudge_EN_male.wav")
        self.termination_audio_path = backend_dir / audio_config.get("termination_audio_path", "assets/termination_EN_male.wav")
        self.end_audio_path = backend_dir / audio_config.get("end_audio_path", "assets/end_EN_male.wav")
        self.start_audio_path = backend_dir / audio_config.get("start_audio_path", "assets/start_smalltalk_EN_male.wav")
        
        # Microphone management
        self._current_mic = None
        self._mic_lock = threading.Lock()
        
        # Audio playback state
        self._is_playing_audio = False
        self._playback_lock = threading.Lock()
        
        # Silence monitoring
        self._last_user_time = None
        self._nudged = False
        self._silence_watcher_thread = None
        self._active = False
        
        # PyAudio for playback
        self._pyaudio = pyaudio.PyAudio()
        self._audio_stream = None
        self.sample_rate = sample_rate
        self.sample_width_bytes = sample_width_bytes
        self.num_channels = num_channels
        
        # Callbacks for silence monitoring
        self._on_nudge_callback = None
        self._on_timeout_callback = None
        
        logger.info(f"ConversationAudioManager initialized")
        logger.info(f"Silence timeout: {self.silence_timeout}s")
        logger.info(f"Nudge timeout: {self.nudge_timeout}s")
        logger.info(f"Nudge audio: {self.nudge_audio_path}")
        logger.info(f"Termination audio: {self.termination_audio_path}")
    
    def capture_user_speech(self) -> Optional[str]:
        """
        Capture user speech with microphone tracking.
        
        Returns:
            Final transcript text or None if no speech captured
        """
        # Check if audio manager is still active
        if not self._active:
            logger.debug("Audio manager not active, skipping speech capture")
            return None
            
        mic = self.mic_factory()
        with self._mic_lock:
            self._current_mic = mic
        
        try:
            mic.start()
            final_text: Optional[str] = None
            
            def on_transcript(text: str, is_final: bool):
                nonlocal final_text
                # Reset silence timer when any transcript arrives (interim or final)
                # This indicates actual speech detected by STT (not just background noise)
                if text:
                    self.reset_silence_timer()
                    logger.debug(f"Silence timer reset due to transcript: '{text[:30]}...'")
                
                if is_final:
                    final_text = text
                    mic.stop()
            
            # Pass audio chunks directly without resetting timer on raw audio
            # We only reset on transcripts (actual speech detected by STT)
            # This prevents background noise from constantly resetting the silence timer
            
            # Add timeout and check for activity state during STT
            import threading
            stt_completed = threading.Event()
            stt_error = None
            
            def run_stt():
                nonlocal stt_error
                try:
                    # Pass audio directly - timer resets only on actual transcripts (speech detected)
                    self.stt.stream_recognize(mic.generator(), on_transcript)
                except Exception as e:
                    stt_error = e
                finally:
                    stt_completed.set()
            
            stt_thread = threading.Thread(target=run_stt, daemon=True)
            stt_thread.start()
            
            # Wait for STT completion with timeout and activity checks
            timeout = 30.0  # 30 second timeout
            check_interval = 0.5  # Check every 500ms
            
            while not stt_completed.wait(check_interval):
                # Check if audio manager is still active
                if not self._active:
                    logger.debug("Audio manager stopped during STT, interrupting")
                    mic.stop()
                    break
                
                timeout -= check_interval
                if timeout <= 0:
                    logger.debug("STT timeout reached, stopping")
                    mic.stop()
                    break
            
            # Wait briefly for thread to finish
            stt_thread.join(timeout=1.0)
            
            if stt_error:
                logger.error(f"STT error: {stt_error}")
                return None
                
            return final_text
            
        except Exception as e:
            logger.error(f"STT error: {e}")
            return None
        finally:
            mic.stop()
            with self._mic_lock:
                self._current_mic = None
    
    def play_nudge_audio_with_delays(self, audio_path: str) -> bool:
        """
        Play nudge audio file with pre/post delays to prevent STT from picking it up.
        
        Args:
            audio_path: Path to audio file
            
        Returns:
            True if successful, False otherwise
        """
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return False
        
        # Pre-delay: Wait before muting to let current audio settle
        if self.nudge_pre_delay > 0:
            logger.debug(f"Nudge pre-delay: {self.nudge_pre_delay*1000:.0f}ms")
            time.sleep(self.nudge_pre_delay)
        
        # Mute microphone before playback
        with self._mic_lock:
            if self._current_mic and self._current_mic.is_running():
                self._current_mic.mute()
                logger.debug("Microphone muted for nudge playback")
        
        try:
            logger.info(f"Playing nudge audio: {audio_path}")
            self._set_playback_state(True)
            
            success = False
            
            # Method 1: Try pydub (most reliable)
            if PYDUB_AVAILABLE:
                try:
                    audio = AudioSegment.from_wav(audio_path)
                    play(audio)
                    logger.debug("Nudge audio played successfully with pydub")
                    success = True
                except Exception as e:
                    logger.warning(f"pydub playback failed: {e}, trying fallback")
            
            # Method 2: Try PowerShell (Windows-specific fallback)
            if not success and sys.platform == "win32":
                try:
                    import subprocess
                    ps_cmd = f'powershell -c "(New-Object Media.SoundPlayer \'{audio_path}\').PlaySync()"'
                    result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0:
                        logger.debug("Nudge audio played successfully with PowerShell")
                        success = True
                    else:
                        logger.warning(f"PowerShell playback failed: {result.stderr}")
                except Exception as e:
                    logger.warning(f"PowerShell playback error: {e}")
            
            if not success:
                logger.error(f"All audio playback methods failed for nudge: {audio_path}")
                return False
            
            # Post-delay: Wait after playback before unmuting
            if self.nudge_post_delay > 0:
                logger.debug(f"Nudge post-delay: {self.nudge_post_delay*1000:.0f}ms")
                time.sleep(self.nudge_post_delay)
            
            return True
            
        except Exception as e:
            logger.error(f"Error playing nudge audio: {e}")
            return False
        finally:
            self._set_playback_state(False)
            
            # Unmute microphone after delays
            with self._mic_lock:
                if self._current_mic and self._current_mic.is_running():
                    self._current_mic.unmute()
                    logger.debug("Microphone unmuted after nudge playback")
    
    def play_audio_file(self, audio_path: str, mute_mic: bool = True) -> bool:
        """
        Play an audio file with optional microphone muting.
        
        Args:
            audio_path: Path to audio file
            mute_mic: Whether to mute microphone during playback
            
        Returns:
            True if successful, False otherwise
        """
        if not os.path.exists(audio_path):
            logger.error(f"Audio file not found: {audio_path}")
            return False
        
        # Mute microphone if requested
        if mute_mic:
            with self._mic_lock:
                if self._current_mic and self._current_mic.is_running():
                    self._current_mic.mute()
        
        try:
            logger.info(f"Playing audio: {audio_path}")
            self._set_playback_state(True)
            
            # Method 1: Try pydub (most reliable)
            if PYDUB_AVAILABLE:
                try:
                    audio = AudioSegment.from_wav(audio_path)
                    play(audio)
                    logger.debug("Audio played successfully with pydub")
                    return True
                except Exception as e:
                    logger.warning(f"pydub playback failed: {e}, trying fallback")
            
            # Method 2: Try PowerShell (Windows-specific fallback)
            if sys.platform == "win32":
                try:
                    import subprocess
                    ps_cmd = f'powershell -c "(New-Object Media.SoundPlayer \'{audio_path}\').PlaySync()"'
                    result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=10)
                    
                    if result.returncode == 0:
                        logger.debug("Audio played successfully with PowerShell")
                        return True
                    else:
                        logger.warning(f"PowerShell playback failed: {result.stderr}")
                except Exception as e:
                    logger.warning(f"PowerShell playback error: {e}")
            
            logger.error(f"All audio playback methods failed for: {audio_path}")
            return False
            
        except Exception as e:
            logger.error(f"Error playing audio: {e}")
            return False
        finally:
            self._set_playback_state(False)
            
            # Unmute microphone if it was muted
            if mute_mic:
                with self._mic_lock:
                    if self._current_mic and self._current_mic.is_running():
                        self._current_mic.unmute()
    
    def play_tts_stream(self, pcm_chunks: Iterator[bytes], use_nudge_delays: bool = False):
        """
        Play streaming TTS audio with microphone coordination.
        
        Args:
            pcm_chunks: Iterator of PCM audio chunks
            use_nudge_delays: If True, apply pre/post delays (for nudge prompts to prevent STT pickup)
        """
        # Pre-delay for nudge prompts
        if use_nudge_delays and self.nudge_pre_delay > 0:
            logger.debug(f"TTS nudge pre-delay: {self.nudge_pre_delay*1000:.0f}ms")
            time.sleep(self.nudge_pre_delay)
        
        # Initialize audio stream if needed
        if not self._audio_stream:
            self._init_audio_stream()
        
        # Mute microphone during TTS playback
        with self._mic_lock:
            if self._current_mic and self._current_mic.is_running():
                self._current_mic.mute()
        
        try:
            self._set_playback_state(True)
            
            for pcm_chunk in pcm_chunks:
                try:
                    self._audio_stream.write(pcm_chunk)
                except Exception as e:
                    logger.error(f"Audio playback error: {e}")
                    break
                    
        finally:
            self._set_playback_state(False)
            
            # Post-delay for nudge prompts (before unmuting)
            if use_nudge_delays and self.nudge_post_delay > 0:
                logger.debug(f"TTS nudge post-delay: {self.nudge_post_delay*1000:.0f}ms")
                time.sleep(self.nudge_post_delay)
            
            # Unmute microphone after TTS playback and delays
            with self._mic_lock:
                if self._current_mic and self._current_mic.is_running():
                    self._current_mic.unmute()
    
    def start_silence_monitoring(self, on_nudge: Callable, on_timeout: Callable):
        """
        Start background silence monitoring.
        
        Args:
            on_nudge: Callback function called when nudge should be played
            on_timeout: Callback function called when timeout occurs
        """
        if self._silence_watcher_thread and self._silence_watcher_thread.is_alive():
            logger.warning("Silence monitoring already active")
            return
        
        self._on_nudge_callback = on_nudge
        self._on_timeout_callback = on_timeout
        self._active = True
        
        # Initialize silence timer when monitoring starts
        # This ensures the timer begins counting immediately
        self._last_user_time = time.time()
        self._nudged = False
        
        self._silence_watcher_thread = threading.Thread(target=self._silence_watcher, daemon=True)
        self._silence_watcher_thread.start()
        
        logger.info(f"Silence monitoring started - will nudge after {self.silence_timeout}s, timeout after {self.silence_timeout + self.nudge_timeout}s")
    
    def stop_silence_monitoring(self):
        """Stop silence monitoring thread."""
        if not self._active:
            return
        
        self._active = False
        logger.info("Stopping silence monitoring")
        
        if self._silence_watcher_thread and self._silence_watcher_thread.is_alive():
            # Don't join if we're in the same thread (avoid RuntimeError)
            if threading.current_thread() != self._silence_watcher_thread:
                self._silence_watcher_thread.join(timeout=1)
    
    def stop(self):
        """Stop the audio manager completely."""
        self._active = False
        self.stop_silence_monitoring()
        logger.info("Audio manager stopped")
    
    def reset_silence_timer(self):
        """Reset silence timer after user interaction."""
        self._last_user_time = time.time()
        self._nudged = False
        logger.debug("Silence timer reset")
    
    def _silence_watcher(self):
        """Background thread for silence monitoring."""
        logger.info("Silence watcher thread started")
        iteration_count = 0
        
        while self._active:
            iteration_count += 1
            
            if self._last_user_time is None:
                if iteration_count % 10 == 0:  # Log every 10 iterations
                    logger.debug("Silence watcher: waiting for timer initialization")
                time.sleep(1)
                continue
            
            # Skip silence counting if audio is playing (TTS/audio files)
            if self._is_audio_playing():
                if iteration_count % 10 == 0:
                    logger.debug("Silence watcher: audio playing, paused")
                time.sleep(1)
                continue
            
            # Check microphone state
            with self._mic_lock:
                mic_exists = self._current_mic is not None
                if mic_exists:
                    mic_running = self._current_mic.is_running()
                    mic_muted = self._current_mic.is_muted()
                    mic_active = mic_running and not mic_muted
                else:
                    mic_active = False
            
            # If mic exists but is muted (e.g., during playback), pause counting
            # If mic doesn't exist yet (e.g., before first user interaction), continue counting
            if mic_exists and not mic_active:
                if iteration_count % 10 == 0:
                    logger.debug(f"Silence watcher paused - mic exists but not active (running={mic_running if mic_exists else 'N/A'}, muted={mic_muted if mic_exists else 'N/A'})")
                time.sleep(1)
                continue
            
            elapsed = time.time() - self._last_user_time
            
            # Log status every 5 seconds
            if iteration_count % 5 == 0:
                logger.debug(f"Silence watcher: {elapsed:.1f}s elapsed, nudged={self._nudged}, mic_exists={mic_exists}, mic_active={mic_active}")
            
            if elapsed >= self.silence_timeout and not self._nudged:
                logger.info(f"Silence detected ({elapsed:.1f}s), triggering nudge")
                if self._on_nudge_callback:
                    try:
                        self._on_nudge_callback()
                        logger.info("Nudge callback executed successfully")
                    except Exception as e:
                        logger.error(f"Error in nudge callback: {e}", exc_info=True)
                else:
                    logger.warning("No nudge callback registered!")
                self._nudged = True
            elif elapsed >= self.silence_timeout + self.nudge_timeout:
                logger.info(f"No reply after nudge ({elapsed:.1f}s), triggering timeout")
                if self._on_timeout_callback:
                    try:
                        self._on_timeout_callback()
                        logger.info("Timeout callback executed successfully")
                    except Exception as e:
                        logger.error(f"Error in timeout callback: {e}", exc_info=True)
                else:
                    logger.warning("No timeout callback registered!")
                break
            else:
                logger.debug(f"Silence watcher: {elapsed:.1f}s elapsed, nudged={self._nudged}")
            
            time.sleep(1)
    
    def _init_audio_stream(self):
        """Initialize PyAudio output stream."""
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
    
    def cleanup(self):
        """Clean up all resources."""
        logger.info("Cleaning up ConversationAudioManager resources...")
        
        # Stop silence monitoring
        self.stop_silence_monitoring()
        
        # Cleanup audio stream
        if self._audio_stream:
            try:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
            except:
                pass
            self._audio_stream = None
        
        # Cleanup PyAudio
        if self._pyaudio:
            try:
                self._pyaudio.terminate()
            except:
                pass
        
        logger.info("ConversationAudioManager cleanup completed")
    
    def is_active(self) -> bool:
        """Check if the audio manager is active."""
        return self._active
    
    def get_status(self) -> dict:
        """Get current audio manager status."""
        return {
            "active": self._active,
            "audio_playing": self._is_audio_playing(),
            "mic_active": bool(self._current_mic and self._current_mic.is_running()),
            "silence_monitoring": bool(self._silence_watcher_thread and self._silence_watcher_thread.is_alive()),
            "last_user_time": self._last_user_time,
            "nudged": self._nudged
        }
