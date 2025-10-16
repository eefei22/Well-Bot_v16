"""
Voice Pipeline Orchestrator

This module orchestrates the complete voice pipeline flow:
Wake Word Detection → Microphone Stream → Speech-to-Text → Transcript Processing
"""

import os
import sys
import threading
import time
import logging
from typing import Optional, Callable

# Add the backend directory to the path to import modules
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

# Handle imports for both module and direct execution
try:
    from .wakeword import WakeWordDetector, create_wake_word_detector
    from .mic_stream import MicStream
    from .stt import GoogleSTTService
    from .intent import IntentInference
except ImportError:
    # Fallback for direct execution
    from wakeword import WakeWordDetector, create_wake_word_detector
    from mic_stream import MicStream
    from stt import GoogleSTTService
    from intent import IntentInference

logger = logging.getLogger(__name__)


class VoicePipeline:
    """
    Orchestrator that ties together wakeword detection, microphone streaming, and STT.
    Manages the complete voice pipeline flow and state transitions.
    """
    
    def __init__(
        self,
        wakeword_detector: WakeWordDetector,
        stt_service: GoogleSTTService,
        lang: str = "en-US",
        on_wake_callback: Optional[Callable[[], None]] = None,
        on_final_transcript: Optional[Callable[[str], None]] = None,
        intent_model_path: Optional[str] = None
    ):
        """
        Initialize the voice pipeline.
        
        Args:
            wakeword_detector: Configured wake word detector
            stt_service: Configured STT service
            lang: Language code for processing
            on_wake_callback: Optional callback for wake word detection
            on_final_transcript: Optional callback for final transcripts
            intent_model_path: Optional path to intent classification model
        """
        self.wakeword = wakeword_detector
        self.stt = stt_service
        self.lang = lang
        self.on_wake_callback = on_wake_callback
        self.on_final_transcript = on_final_transcript
        
        # Initialize intent inference if model path provided
        self.intent_inference = None
        if intent_model_path:
            try:
                self.intent_inference = IntentInference(intent_model_path)
                logger.info(f"Intent inference initialized with spaCy intent classifier")
            except Exception as e:
                logger.warning(f"Failed to initialize intent inference: {e}")
                self.intent_inference = None
        
        self.active = False
        self.stt_active = False
        self._lock = threading.Lock()
        
        logger.info(f"Pipeline initialized | Language: {lang} | Intent: {'Enabled' if self.intent_inference else 'Disabled'}")
    
    def _on_wake(self):
        """
        Callback function triggered when wake word is detected.
        Starts the STT pipeline.
        """
        import threading
        logger.info("Wake word detected - starting STT")
        
        with self._lock:
            if self.stt_active:
                logger.warning("STT already active, ignoring wake")
                return
            self.stt_active = True

        # Call the callback (which should schedule the emit)
        if self.on_wake_callback:
            try:
                self.on_wake_callback()
            except Exception as e:
                logger.error(f"Error in wake callback: {e}")

        # Launch STT thread
        t = threading.Thread(target=self._run_stt, daemon=True)
        t.start()
    
    def _run_stt(self):
        """Runs the STT session in a background thread after wakeword."""
        import threading
        logger.info("STT session started")
        
        mic = MicStream(
            rate=self.stt.get_sample_rate(), 
            chunk_size=int(self.stt.get_sample_rate() / 10)  # 100ms chunks
        )
        
        try:
            mic.start()
            logger.info("Microphone active - processing speech")
            
            def on_transcript(text: str, is_final: bool):
                """Handle transcript results from STT."""
                if not is_final:
                    # Emit interim result to frontend, etc.
                    logger.debug(f"[Pipeline] Interim transcript: {text}")
                    return
                
                # Final transcript arrived
                logger.info(f"Transcript: '{text}'")
                
                # Process with intent inference if available
                intent_result = None
                if self.intent_inference:
                    try:
                        intent_result = self.intent_inference.predict_intent(text)
                        logger.info(f"Intent: {intent_result['intent']} (confidence: {intent_result['confidence']:.3f})")
                    except Exception as e:
                        logger.error(f"Error in intent inference: {e}")
                        intent_result = {
                            "intent": "unknown",
                            "confidence": 0.0,
                            "all_scores": {},
                            "error": str(e)
                        }
                
                # Call user-provided callback if available
                if self.on_final_transcript:
                    try:
                        # Pass both transcript and intent result to callback
                        self.on_final_transcript(text, intent_result)
                    except Exception as e:
                        logger.error(f"Error in final transcript callback: {e}")
                
                # Stop microphone stream
                mic.stop()
                logger.info("STT session completed")
            
            # Start STT streaming
            logger.info("Starting speech recognition")
            self.stt.stream_recognize(
                audio_generator=mic.generator(),
                on_transcript=on_transcript,
                interim_results=True,
                single_utterance=True  # Auto-stop on pause
            )
            
        except Exception as e:
            logger.error(f"Error in STT streaming: {e}")
        finally:
            # Ensure microphone is stopped
            try:
                mic.stop()
            except Exception as e:
                logger.error(f"Error stopping microphone: {e}")
            
            with self._lock:
                self.stt_active = False
            
            logger.info("Returning to wake word listening")
    
    def start(self):
        """Start listening for wake word, and then run STT after detection."""
        if self.active:
            logger.warning("Pipeline is already active")
            return
            
        try:
            # Initialize wake word detector if not already done
            if not self.wakeword.is_initialized:
                logger.info("Initializing wake word detector...")
                if not self.wakeword.initialize():
                    raise RuntimeError("Failed to initialize wake word detector")
            
            # Start wake word detection
            self.wakeword.start(self._on_wake)
            self.active = True
            
            logger.info("Pipeline active - listening for wake word")
            
        except Exception as e:
            logger.error(f"Failed to start pipeline: {e}")
            self.active = False
            raise
    
    def stop(self):
        """Stop the voice pipeline."""
        if not self.active:
            logger.warning("Pipeline is not active")
            return
            
        logger.info("[Pipeline] Stopping voice pipeline...")
        
        try:
            # Stop wake word detection
            self.wakeword.stop()
            
            # Wait for any active STT to complete
            with self._lock:
                if self.stt_active:
                    logger.info("[Pipeline] Waiting for active STT session to complete...")
                    # Note: We don't force stop STT as it should complete naturally
            
            self.active = False
            logger.info("[Pipeline] Voice pipeline stopped")
            
        except Exception as e:
            logger.error(f"Error stopping pipeline: {e}")
    
    def cleanup(self):
        """Clean up all resources."""
        logger.info("[Pipeline] Cleaning up pipeline resources...")
        
        try:
            self.stop()
            self.wakeword.cleanup()
            logger.info("[Pipeline] Pipeline cleanup completed")
        except Exception as e:
            logger.error(f"Error during pipeline cleanup: {e}")
    
    def is_active(self) -> bool:
        """Check if the pipeline is currently active."""
        return self.active
    
    def is_stt_active(self) -> bool:
        """Check if STT is currently processing."""
        with self._lock:
            return self.stt_active
    
    def get_status(self) -> dict:
        """Get current pipeline status."""
        return {
            "active": self.active,
            "stt_active": self.stt_active,
            "language": self.lang,
            "wakeword_initialized": self.wakeword.is_initialized,
            "wakeword_running": self.wakeword.running if hasattr(self.wakeword, 'running') else False
        }


# Factory function for easy pipeline creation
def create_voice_pipeline(
    access_key_file: str,
    custom_keyword_file: Optional[str] = None,
    language: str = "en-US",
    on_wake_callback: Optional[Callable[[], None]] = None,
    on_final_transcript: Optional[Callable[[str, Optional[dict]], None]] = None,
    intent_model_path: Optional[str] = None
) -> VoicePipeline:
    """
    Factory function to create a complete voice pipeline.
    
    Args:
        access_key_file: Path to Picovoice access key file
        custom_keyword_file: Path to custom wake word model file
        language: Language code for STT
        on_wake_callback: Optional callback for wake word detection
        on_final_transcript: Optional callback for final transcripts (text, intent_result)
        intent_model_path: Optional path to intent classification model
        
    Returns:
        Configured VoicePipeline instance
    """
    try:
        # Create wake word detector using existing factory function
        wakeword_detector = create_wake_word_detector(
            access_key_file, custom_keyword_file
        )
        
        # Create STT service
        stt_service = GoogleSTTService(language=language)
        
        # Create pipeline
        pipeline = VoicePipeline(
            wakeword_detector=wakeword_detector,
            stt_service=stt_service,
            lang=language,
            on_wake_callback=on_wake_callback,
            on_final_transcript=on_final_transcript,
            intent_model_path=intent_model_path
        )
        
        logger.info("Voice pipeline created successfully")
        return pipeline
        
    except Exception as e:
        logger.error(f"Failed to create voice pipeline: {e}")
        raise


# Example usage and testing
if __name__ == "__main__":
    # Configure clean logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
        datefmt='%H:%M:%S'
    )
    
    def on_final_transcript(text: str, intent_result: Optional[dict]):
        """Handle final transcripts with intent classification."""
        print(f"\nFinal transcript received: '{text}'")
        
        if intent_result:
            print(f"\nIntent detected: {intent_result['intent']} (confidence: {intent_result['confidence']:.3f})")
            print(f"All scores: {intent_result['all_scores']}\n")
            
            # Handle different intents
            if intent_result['intent'] == 'todo_add':
                print("Processing todo add request...\n")
                # Call your todo module here
            elif intent_result['intent'] == 'small_talk':
                print("Processing small talk...\n")
                # Call LLM for conversational response
            elif intent_result['intent'] == 'journal_write':
                print("Processing journal entry...\n")
                # Call your journal module here
            else:
                print(f"Unknown intent: {intent_result['intent']}\n")
        else:
            print("No intent classification available")
        
        # Here you would typically send to NLU/downstream processing
    
    try:
        # Paths relative to this file
        current_dir = os.path.dirname(__file__)
        access_key_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'PorcupineAccessKey.txt')
        custom_keyword_path = os.path.join(current_dir, '..', '..', 'config', 'WakeWord', 'WellBot_WakeWordModel.ppn')
        intent_model_path = os.path.join(current_dir, '..', '..', 'config', 'intent_classifier')
        
        # Create pipeline
        pipeline = create_voice_pipeline(
            access_key_file=access_key_path,
            custom_keyword_file=custom_keyword_path,
            language="en-US",
            on_final_transcript=on_final_transcript,
            intent_model_path=intent_model_path
        )
        
        # Start pipeline
        pipeline.start()
        
        print("Voice pipeline started!")
        print("Say the wake word to activate STT")
        print("Press Ctrl+C to stop")
        
        # Keep running until interrupted
        try:
            while True:
                time.sleep(0.5)
                # Optional: Print status periodically
                # status = pipeline.get_status()
                # print(f"Status: {status}")
                
        except KeyboardInterrupt:
            print("\nStopping pipeline...\n")
            pipeline.stop()
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        try:
            pipeline.cleanup()
            print("Pipeline cleanup completed")
        except:
            pass
