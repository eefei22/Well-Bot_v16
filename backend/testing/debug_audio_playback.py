#!/usr/bin/env python3
"""
Debug script for audio playback issues in SmallTalkManager.

This script tests various audio playback methods and path resolution
to identify the root cause of the playsound errors.
"""

import os
import sys
import logging
from pathlib import Path
import time

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

def test_path_resolution():
    """Test path resolution logic from SmallTalkManager."""
    logger.info("=== Testing Path Resolution ===")
    
    # Simulate the path resolution logic from SmallTalkManager
    llm_config_path = backend_dir / "config" / "LLM" / "smalltalk_instructions.json"
    backend_dir_calculated = os.path.dirname(os.path.dirname(os.path.dirname(str(llm_config_path))))
    
    logger.info(f"Backend dir (calculated): {backend_dir_calculated}")
    logger.info(f"Backend dir (actual): {backend_dir}")
    logger.info(f"Match: {backend_dir_calculated == str(backend_dir)}")
    
    # Test nudge audio path
    nudge_audio_relative = "assets/ENGLISH/inactivity_nudge_EN_male.wav"
    nudge_audio_path = os.path.join(backend_dir_calculated, nudge_audio_relative)
    
    logger.info(f"Nudge audio relative: {nudge_audio_relative}")
    logger.info(f"Nudge audio absolute: {nudge_audio_path}")
    logger.info(f"Nudge audio exists: {os.path.exists(nudge_audio_path)}")
    
    # Test with pathlib
    nudge_audio_pathlib = backend_dir / "assets" / "ENGLISH" / "inactivity_nudge_EN_male.wav"
    logger.info(f"Nudge audio (pathlib): {nudge_audio_pathlib}")
    logger.info(f"Nudge audio (pathlib) exists: {nudge_audio_pathlib.exists()}")
    
    return nudge_audio_path, str(nudge_audio_pathlib)

def test_playsound_import():
    """Test playsound import and basic functionality."""
    logger.info("=== Testing Playsound Import ===")
    
    try:
        from playsound import playsound
        logger.info("✓ playsound imported successfully")
        return playsound
    except ImportError as e:
        logger.error(f"✗ playsound import failed: {e}")
        return None

def test_playsound_basic(playsound_func, audio_path):
    """Test basic playsound functionality."""
    logger.info("=== Testing Playsound Basic Functionality ===")
    
    if not playsound_func:
        logger.error("Playsound not available")
        return False
    
    if not os.path.exists(audio_path):
        logger.error(f"Audio file does not exist: {audio_path}")
        return False
    
    logger.info(f"Testing playsound with: {audio_path}")
    
    try:
        # Test with raw path
        logger.info("Testing with raw path...")
        playsound_func(audio_path)
        logger.info("✓ Raw path works")
        return True
    except Exception as e:
        logger.error(f"✗ Raw path failed: {e}")
        
        # Test with normalized path
        try:
            normalized_path = os.path.normpath(audio_path)
            logger.info(f"Testing with normalized path: {normalized_path}")
            playsound_func(normalized_path)
            logger.info("✓ Normalized path works")
            return True
        except Exception as e2:
            logger.error(f"✗ Normalized path failed: {e2}")
            
            # Test with forward slashes
            try:
                forward_slash_path = audio_path.replace('\\', '/')
                logger.info(f"Testing with forward slashes: {forward_slash_path}")
                playsound_func(forward_slash_path)
                logger.info("✓ Forward slash path works")
                return True
            except Exception as e3:
                logger.error(f"✗ Forward slash path failed: {e3}")
                return False

def test_alternative_audio_libraries():
    """Test alternative audio libraries."""
    logger.info("=== Testing Alternative Audio Libraries ===")
    
    # Test pygame
    try:
        import pygame
        pygame.mixer.init()
        logger.info("✓ pygame available")
        
        # Test loading and playing
        audio_path = backend_dir / "assets" / "ENGLISH" / "inactivity_nudge_EN_male.wav"
        if audio_path.exists():
            sound = pygame.mixer.Sound(str(audio_path))
            sound.play()
            time.sleep(2)  # Let it play
            logger.info("✓ pygame playback successful")
            return True
        else:
            logger.error("Audio file not found for pygame test")
    except ImportError:
        logger.warning("pygame not available")
    except Exception as e:
        logger.error(f"pygame test failed: {e}")
    
    # Test pydub + simpleaudio
    try:
        from pydub import AudioSegment
        from pydub.playback import play
        logger.info("✓ pydub available")
        
        audio_path = backend_dir / "assets" / "ENGLISH" / "inactivity_nudge_EN_male.wav"
        if audio_path.exists():
            audio = AudioSegment.from_wav(str(audio_path))
            play(audio)
            logger.info("✓ pydub playback successful")
            return True
        else:
            logger.error("Audio file not found for pydub test")
    except ImportError:
        logger.warning("pydub not available")
    except Exception as e:
        logger.error(f"pydub test failed: {e}")
    
    return False

def test_windows_specific_solutions():
    """Test Windows-specific solutions for audio playback."""
    logger.info("=== Testing Windows-Specific Solutions ===")
    
    audio_path = backend_dir / "assets" / "ENGLISH" / "inactivity_nudge_EN_male.wav"
    
    # Test using subprocess with Windows Media Player
    try:
        import subprocess
        logger.info("Testing with Windows Media Player...")
        
        # Use subprocess to play with Windows Media Player
        cmd = ['wmplayer', str(audio_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            logger.info("✓ Windows Media Player playback successful")
            return True
        else:
            logger.warning(f"Windows Media Player failed: {result.stderr}")
    except Exception as e:
        logger.error(f"Windows Media Player test failed: {e}")
    
    # Test using subprocess with PowerShell
    try:
        import subprocess
        logger.info("Testing with PowerShell...")
        
        # Use PowerShell to play audio
        ps_cmd = f'powershell -c "(New-Object Media.SoundPlayer \'{audio_path}\').PlaySync()"'
        result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            logger.info("✓ PowerShell playback successful")
            return True
        else:
            logger.warning(f"PowerShell failed: {result.stderr}")
    except Exception as e:
        logger.error(f"PowerShell test failed: {e}")
    
    return False

def test_file_properties(audio_path):
    """Test file properties that might affect playback."""
    logger.info("=== Testing File Properties ===")
    
    if not os.path.exists(audio_path):
        logger.error(f"File does not exist: {audio_path}")
        return
    
    # File size
    file_size = os.path.getsize(audio_path)
    logger.info(f"File size: {file_size} bytes")
    
    # File permissions
    import stat
    file_perms = stat.filemode(os.stat(audio_path).st_mode)
    logger.info(f"File permissions: {file_perms}")
    
    # Path length
    path_length = len(audio_path)
    logger.info(f"Path length: {path_length} characters")
    
    # Check for problematic characters
    problematic_chars = [' ', '(', ')', '[', ']', '{', '}', '&', '|', ';', '`', '$']
    found_chars = [char for char in problematic_chars if char in audio_path]
    if found_chars:
        logger.warning(f"Path contains potentially problematic characters: {found_chars}")
    else:
        logger.info("✓ No problematic characters found in path")

def main():
    """Main debug function."""
    logger.info("=== Audio Playback Debug Script ===")
    logger.info(f"Backend directory: {backend_dir}")
    logger.info(f"Platform: {sys.platform}")
    
    # Test path resolution
    os_path, pathlib_path = test_path_resolution()
    
    # Test file properties
    test_file_properties(os_path)
    
    # Test playsound
    playsound_func = test_playsound_import()
    if playsound_func:
        test_playsound_basic(playsound_func, os_path)
    
    # Test alternative libraries
    test_alternative_audio_libraries()
    
    # Test Windows-specific solutions
    if sys.platform == "win32":
        test_windows_specific_solutions()
    
    logger.info("=== Debug Complete ===")
    logger.info("Check the logs above for successful audio playback methods.")
    logger.info("Use the working method to replace playsound in SmallTalkManager.")

if __name__ == "__main__":
    main()
