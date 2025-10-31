#!/usr/bin/env python3
"""
STT Latency Debugging Script

Investigates latency between speech capture and processing in SmallTalk activity.
Tracks timing, resource usage, and audio processing states to identify bottlenecks.
"""

import sys
import os
import time
import threading
import logging
import traceback
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from collections import deque

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.components.stt import GoogleSTTService
from src.components.mic_stream import MicStream
from src.components.conversation_audio_manager import ConversationAudioManager
from src.components.termination_phrase import TerminationPhraseDetector
from src.utils.config_resolver import get_global_config_for_user, get_language_config, resolve_language
from src.supabase.auth import get_current_user_id

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class LatencyTracker:
    """Tracks timing and latency metrics for debugging"""
    
    def __init__(self):
        self.events: List[Dict] = []
        self.lock = threading.Lock()
        self.audio_chunks_received = 0
        self.interim_transcripts = 0
        self.final_transcripts = 0
        
    def log_event(self, event_type: str, details: str = "", timestamp: Optional[float] = None):
        """Log an event with timestamp"""
        if timestamp is None:
            timestamp = time.time()
        
        with self.lock:
            event = {
                "timestamp": timestamp,
                "time_ms": timestamp * 1000,
                "type": event_type,
                "details": details,
                "thread": threading.current_thread().name
            }
            self.events.append(event)
            logger.info(f"[TRACKER] {event_type}: {details}")
    
    def get_events_since(self, start_time: float) -> List[Dict]:
        """Get all events since a start time"""
        with self.lock:
            return [e for e in self.events if e["timestamp"] >= start_time]
    
    def get_summary(self) -> Dict:
        """Get summary statistics"""
        with self.lock:
            if len(self.events) < 2:
                return {}
            
            first_event = self.events[0]
            last_event = self.events[-1]
            total_duration = (last_event["timestamp"] - first_event["timestamp"]) * 1000
            
            event_types = {}
            for event in self.events:
                event_type = event["type"]
                if event_type not in event_types:
                    event_types[event_type] = 0
                event_types[event_type] += 1
            
            return {
                "total_events": len(self.events),
                "total_duration_ms": total_duration,
                "event_types": event_types,
                "audio_chunks": self.audio_chunks_received,
                "interim_transcripts": self.interim_transcripts,
                "final_transcripts": self.final_transcripts,
                "first_event": first_event["timestamp"],
                "last_event": last_event["timestamp"]
            }


class ResourceMonitor:
    """Monitors system resource usage"""
    
    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.monitoring = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.samples: List[Dict] = []
        self.lock = threading.Lock()
    
    def start(self):
        """Start resource monitoring"""
        if self.monitoring:
            return
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Resource monitoring started")
    
    def stop(self):
        """Stop resource monitoring"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
        logger.info("Resource monitoring stopped")
    
    def _monitor_loop(self):
        """Monitor resource usage in background"""
        try:
            import psutil
            has_psutil = True
        except ImportError:
            has_psutil = False
            logger.warning("psutil not available - resource monitoring will be limited")
        
        while self.monitoring:
            try:
                sample = {
                    "timestamp": time.time(),
                    "thread_count": threading.active_count(),
                }
                
                if has_psutil:
                    process = psutil.Process()
                    sample.update({
                        "cpu_percent": process.cpu_percent(interval=None),
                        "memory_mb": process.memory_info().rss / 1024 / 1024,
                        "threads": process.num_threads(),
                    })
                
                with self.lock:
                    self.samples.append(sample)
                    
            except Exception as e:
                logger.error(f"Error in resource monitoring: {e}")
            
            time.sleep(self.interval)
    
    def get_samples_since(self, start_time: float) -> List[Dict]:
        """Get resource samples since a start time"""
        with self.lock:
            return [s for s in self.samples if s["timestamp"] >= start_time]


def test_speech_capture_latency(language: str = "cn", duration: int = 30):
    """Test speech capture and processing latency"""
    
    logger.info("=" * 80)
    logger.info("STT LATENCY DEBUG TEST")
    logger.info("=" * 80)
    logger.info(f"Language: {language}")
    logger.info(f"Test duration: {duration} seconds")
    logger.info("Speak normally, and we'll track when your speech is captured vs processed")
    logger.info("=" * 80)
    
    user_id = get_current_user_id()
    
    # Initialize tracker and monitor
    tracker = LatencyTracker()
    monitor = ResourceMonitor(interval=0.2)
    
    try:
        # Load configs
        tracker.log_event("CONFIG_LOAD_START", f"Loading configs for language: {language}")
        global_config = get_global_config_for_user(user_id)
        language_config = get_language_config(user_id)
        stt_lang = global_config["language_codes"]["stt_language_code"]
        tracker.log_event("CONFIG_LOAD_COMPLETE", f"STT language: {stt_lang}")
        
        # Initialize STT
        tracker.log_event("STT_INIT_START", f"Initializing STT with language: {stt_lang}")
        stt_service = GoogleSTTService(language=stt_lang, sample_rate=16000)
        tracker.log_event("STT_INIT_COMPLETE")
        
        # Initialize microphone
        tracker.log_event("MIC_INIT_START")
        mic = MicStream()
        tracker.log_event("MIC_INIT_COMPLETE")
        
        # Track audio chunk reception
        audio_start_time = [None]  # Use list to avoid nonlocal in nested function
        
        def audio_chunk_handler(chunk):
            if audio_start_time[0] is None:
                audio_start_time[0] = time.time()
                tracker.log_event("AUDIO_CHUNK_FIRST", "First audio chunk received")
            tracker.audio_chunks_received += 1
        
        # Track transcripts
        transcript_times = {}
        last_interim_time = None
        
        def on_transcript(text: str, is_final: bool):
            nonlocal last_interim_time
            transcript_time = time.time()
            
            if is_final:
                tracker.final_transcripts += 1
                tracker.log_event(
                    "TRANSCRIPT_FINAL",
                    f"Text: '{text}'",
                    transcript_time
                )
                
                # Calculate latency if we have audio start time
                if audio_start_time[0] is not None:
                    latency = (transcript_time - audio_start_time[0]) * 1000
                    tracker.log_event(
                        "LATENCY_CALC",
                        f"Audio-to-Final latency: {latency:.2f}ms",
                        transcript_time
                    )
            else:
                tracker.interim_transcripts += 1
                if last_interim_time is not None:
                    interval = (transcript_time - last_interim_time) * 1000
                    tracker.log_event(
                        "TRANSCRIPT_INTERIM",
                        f"Text: '{text[:50]}...' | Interval: {interval:.2f}ms since last",
                        transcript_time
                    )
                else:
                    tracker.log_event(
                        "TRANSCRIPT_INTERIM",
                        f"Text: '{text[:50]}...' (first)",
                        transcript_time
                    )
                last_interim_time = transcript_time
        
        # Start resource monitoring
        monitor.start()
        
        # Start microphone
        tracker.log_event("MIC_START")
        mic.start()
        
        # Create a generator that tracks audio chunks
        def tracked_generator():
            for chunk in mic.generator():
                if chunk:
                    audio_chunk_handler(chunk)
                yield chunk
        
        # Start STT recognition
        tracker.log_event("STT_STREAM_START", "Starting STT stream recognition")
        stt_start_time = time.time()
        
        # Run STT in a separate thread so we can monitor it
        stt_completed = threading.Event()
        stt_error = None
        
        def run_stt():
            nonlocal stt_error
            try:
                stt_service.stream_recognize(tracked_generator(), on_transcript)
            except Exception as e:
                stt_error = e
                tracker.log_event("STT_ERROR", str(e))
            finally:
                stt_completed.set()
        
        stt_thread = threading.Thread(target=run_stt, name="STT-Thread")
        stt_thread.start()
        tracker.log_event("STT_THREAD_STARTED")
        
        # Monitor for specified duration
        logger.info(f"\n🎤 Listening for {duration} seconds... Speak now!")
        logger.info("Tracking: audio capture, STT processing, transcript delivery\n")
        
        test_end_time = time.time() + duration
        check_interval = 0.1
        
        while time.time() < test_end_time:
            if not stt_thread.is_alive():
                tracker.log_event("STT_THREAD_ENDED", "STT thread finished unexpectedly")
                break
            
            # Check for inactivity periods
            current_time = time.time()
            if last_interim_time:
                silence_duration = (current_time - last_interim_time) * 1000
                if silence_duration > 2000:  # 2 seconds
                    tracker.log_event(
                        "SILENCE_DETECTED",
                        f"Silence for {silence_duration:.0f}ms",
                        current_time
                    )
            
            time.sleep(check_interval)
        
        # Stop microphone
        tracker.log_event("MIC_STOP", "Stopping microphone")
        mic.stop()
        
        # Wait for STT to finish
        tracker.log_event("STT_WAIT", "Waiting for STT to complete")
        stt_completed.wait(timeout=5.0)
        stt_end_time = time.time()
        
        if stt_error:
            logger.error(f"STT error occurred: {stt_error}")
        
        tracker.log_event("STT_COMPLETE", f"Total STT duration: {(stt_end_time - stt_start_time)*1000:.2f}ms")
        
        # Stop monitoring
        monitor.stop()
        
        # Print summary
        logger.info("\n" + "=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)
        
        summary = tracker.get_summary()
        for key, value in summary.items():
            logger.info(f"{key}: {value}")
        
        logger.info("\n" + "=" * 80)
        logger.info("EVENT TIMELINE (top 50 events)")
        logger.info("=" * 80)
        
        # Show timeline of events
        first_time = tracker.events[0]["timestamp"] if tracker.events else time.time()
        for i, event in enumerate(tracker.events[:50]):
            elapsed = (event["timestamp"] - first_time) * 1000
            logger.info(f"[{elapsed:8.2f}ms] {event['type']:30s} | {event['details']}")
        
        if len(tracker.events) > 50:
            logger.info(f"... ({len(tracker.events) - 50} more events)")
        
        # Show resource usage if available
        if monitor.samples:
            logger.info("\n" + "=" * 80)
            logger.info("RESOURCE USAGE")
            logger.info("=" * 80)
            monitor_start = monitor.samples[0]["timestamp"]
            for sample in monitor.samples[:20]:
                elapsed = (sample["timestamp"] - monitor_start) * 1000
                if "memory_mb" in sample:
                    logger.info(
                        f"[{elapsed:8.2f}ms] CPU: {sample.get('cpu_percent', 'N/A'):.1f}% | "
                        f"Memory: {sample.get('memory_mb', 'N/A'):.1f}MB | "
                        f"Threads: {sample.get('threads', 'N/A')}"
                    )
                else:
                    logger.info(f"[{elapsed:8.2f}ms] Active threads: {sample.get('thread_count', 'N/A')}")
        
        # Analyze latency patterns
        logger.info("\n" + "=" * 80)
        logger.info("LATENCY ANALYSIS")
        logger.info("=" * 80)
        
        final_transcripts = [e for e in tracker.events if e["type"] == "TRANSCRIPT_FINAL"]
        if len(final_transcripts) > 1:
            latencies = []
            for i in range(1, len(final_transcripts)):
                interval = (final_transcripts[i]["timestamp"] - final_transcripts[i-1]["timestamp"]) * 1000
                latencies.append(interval)
            
            if latencies:
                avg_latency = sum(latencies) / len(latencies)
                max_latency = max(latencies)
                min_latency = min(latencies)
                logger.info(f"Final transcript intervals: avg={avg_latency:.2f}ms, min={min_latency:.2f}ms, max={max_latency:.2f}ms")
        
        return {
            "tracker": tracker,
            "monitor": monitor,
            "summary": summary
        }
        
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
    finally:
        monitor.stop()
        try:
            mic.stop()
        except:
            pass


def test_termination_phrase_latency(language: str = "cn"):
    """Test termination phrase detection latency specifically"""
    
    logger.info("=" * 80)
    logger.info("TERMINATION PHRASE LATENCY TEST")
    logger.info("=" * 80)
    logger.info("This test will monitor latency when you say a termination phrase")
    logger.info("=" * 80)
    
    user_id = get_current_user_id()
    tracker = LatencyTracker()
    
    try:
        global_config = get_global_config_for_user(user_id)
        language_config = get_language_config(user_id)
        stt_lang = global_config["language_codes"]["stt_language_code"]
        
        # Load termination phrases
        meditation_config = language_config.get("meditation", {})
        termination_phrases = meditation_config.get("termination_phrases", [])
        termination_detector = TerminationPhraseDetector(termination_phrases)
        logger.info(f"Loaded termination phrases: {termination_phrases}")
        
        stt_service = GoogleSTTService(language=stt_lang, sample_rate=16000)
        mic = MicStream()
        
        phrase_detected = threading.Event()
        detection_time = None
        
        def on_transcript(text: str, is_final: bool):
            transcript_time = time.time()
            tracker.log_event(
                "TRANSCRIPT",
                f"{'FINAL' if is_final else 'INTERIM'}: '{text}'",
                transcript_time
            )
            
            if is_final:
                tracker.final_transcripts += 1
            else:
                tracker.interim_transcripts += 1
            
            # Check for termination phrase
            try:
                termination_detector.check_termination(text, active=True)
                tracker.log_event("TERMINATION_CHECK", f"No match in: '{text}'")
            except Exception as e:
                nonlocal detection_time
                detection_time = time.time()
                tracker.log_event("TERMINATION_DETECTED", f"Phrase detected in: '{text}'")
                phrase_detected.set()
        
        tracker.log_event("TEST_START")
        mic.start()
        
        def tracked_generator():
            first_chunk_time = None
            for chunk in mic.generator():
                if chunk and first_chunk_time is None:
                    first_chunk_time = time.time()
                    tracker.log_event("FIRST_AUDIO_CHUNK")
                yield chunk
        
        stt_start = time.time()
        tracker.log_event("STT_START")
        
        def run_stt():
            try:
                stt_service.stream_recognize(tracked_generator(), on_transcript)
            except Exception as e:
                tracker.log_event("STT_ERROR", str(e))
        
        stt_thread = threading.Thread(target=run_stt, name="STT-Thread")
        stt_thread.start()
        
        logger.info("\n🎤 Say a termination phrase now (waiting up to 30 seconds)...")
        phrase_detected.wait(timeout=30.0)
        
        if detection_time:
            latency = (detection_time - stt_start) * 1000
            logger.info(f"\n✅ Termination phrase detected! Latency: {latency:.2f}ms")
        else:
            logger.info("\n❌ No termination phrase detected within 30 seconds")
        
        mic.stop()
        stt_thread.join(timeout=2.0)
        
        tracker.log_event("TEST_END")
        
        # Print timeline
        logger.info("\n" + "=" * 80)
        logger.info("EVENT TIMELINE")
        logger.info("=" * 80)
        first_time = tracker.events[0]["timestamp"] if tracker.events else time.time()
        for event in tracker.events:
            elapsed = (event["timestamp"] - first_time) * 1000
            logger.info(f"[{elapsed:8.2f}ms] {event['type']:30s} | {event['details']}")
        
    except Exception as e:
        logger.error(f"Test error: {e}", exc_info=True)
    finally:
        try:
            mic.stop()
        except:
            pass


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Debug STT latency issues")
    parser.add_argument("--language", choices=["en", "cn", "bm"], default="cn", help="Language to test")
    parser.add_argument("--duration", type=int, default=30, help="Test duration in seconds")
    parser.add_argument("--test-type", choices=["general", "termination"], default="general", 
                       help="Type of test to run")
    
    args = parser.parse_args()
    
    if args.test_type == "termination":
        test_termination_phrase_latency(args.language)
    else:
        test_speech_capture_latency(args.language, args.duration)

