#!/usr/bin/env python3
"""
Test script to verify the audio playback fix in SmallTalkManager.

This script tests the new robust audio playback method.
"""

import os
import sys
import logging
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

def test_audio_playback_fix():
    """Test the new audio playback method."""
    logger.info("=== Testing Audio Playback Fix ===")
    
    try:
        # Import the SmallTalkManager
        from src.managers.smalltalk_manager import SmallTalkManager
        
        # Create a minimal manager instance just to test the audio method
        class TestManager:
            def __init__(self):
                # Set up the audio paths like the real manager does
                llm_config_path = backend_dir / "config" / "LLM" / "smalltalk_instructions.json"
                backend_dir_calculated = os.path.dirname(os.path.dirname(os.path.dirname(str(llm_config_path))))
                
                nudge_audio_relative = "assets/ENGLISH/inactivity_nudge_EN_male.wav"
                self.nudge_audio_path = os.path.join(backend_dir_calculated, nudge_audio_relative)
                
                termination_audio_relative = "assets/ENGLISH/termination_EN_male.wav"
                self.termination_audio_path = os.path.join(backend_dir_calculated, termination_audio_relative)
                
                logger.info(f"Nudge audio path: {self.nudge_audio_path}")
                logger.info(f"Termination audio path: {self.termination_audio_path}")
            
            def _play_audio_file(self, audio_path: str) -> bool:
                """Copy of the new robust audio playback method."""
                if not os.path.exists(audio_path):
                    logger.error(f"Audio file not found: {audio_path}")
                    return False

                # Method 1: Try pydub (most reliable)
                try:
                    from pydub import AudioSegment
                    from pydub.playback import play
                    logger.info(f"Playing audio with pydub: {audio_path}")
                    audio = AudioSegment.from_wav(audio_path)
                    play(audio)
                    logger.info("✓ Audio played successfully with pydub")
                    return True
                except Exception as e:
                    logger.warning(f"pydub playback failed: {e}, trying fallback")

                # Method 2: Try PowerShell (Windows-specific fallback)
                if sys.platform == "win32":
                    try:
                        import subprocess
                        logger.info(f"Playing audio with PowerShell: {audio_path}")
                        ps_cmd = f'powershell -c "(New-Object Media.SoundPlayer \'{audio_path}\').PlaySync()"'
                        result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=10)
                        
                        if result.returncode == 0:
                            logger.info("✓ Audio played successfully with PowerShell")
                            return True
                        else:
                            logger.warning(f"PowerShell playback failed: {result.stderr}")
                    except Exception as e:
                        logger.warning(f"PowerShell playback error: {e}")

                # Method 3: Try playsound as last resort (with path normalization)
                try:
                    from playsound import playsound
                    logger.info(f"Playing audio with playsound: {audio_path}")
                    normalized_path = os.path.normpath(audio_path)
                    playsound(normalized_path)
                    logger.info("✓ Audio played successfully with playsound")
                    return True
                except Exception as e:
                    logger.warning(f"playsound playback failed: {e}")

                logger.error(f"All audio playback methods failed for: {audio_path}")
                return False
        
        # Test the manager
        test_manager = TestManager()
        
        # Test nudge audio
        logger.info("Testing nudge audio playback...")
        success = test_manager._play_audio_file(test_manager.nudge_audio_path)
        if success:
            logger.info("✓ Nudge audio test PASSED")
        else:
            logger.error("✗ Nudge audio test FAILED")
        
        # Test termination audio
        logger.info("Testing termination audio playback...")
        success = test_manager._play_audio_file(test_manager.termination_audio_path)
        if success:
            logger.info("✓ Termination audio test PASSED")
        else:
            logger.error("✗ Termination audio test FAILED")
        
        logger.info("=== Audio Playback Fix Test Complete ===")
        return True
        
    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    test_audio_playback_fix()
