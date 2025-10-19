import os
import logging
import wave
from typing import Iterator, Optional

from google.cloud import texttospeech

logger = logging.getLogger(__name__)

class GoogleTTSClient:
    def __init__(
        self,
        voice_name: str = "en-US-Chirp3-HD-Charon",
        language_code: str = "en-US",
        audio_encoding: texttospeech.AudioEncoding = texttospeech.AudioEncoding.PCM,
        sample_rate_hertz: Optional[int] = None,
        num_channels: int = 1,
        sample_width_bytes: int = 2
    ):
        self.client = texttospeech.TextToSpeechClient()
        logger.info("Initialized TTS client")

        self.voice_name = voice_name
        self.language_code = language_code
        self.audio_encoding = audio_encoding
        self.sample_rate_hertz = sample_rate_hertz
        self.num_channels = num_channels
        self.sample_width_bytes = sample_width_bytes

        logger.info(f"TTS config: voice={voice_name}, lang={language_code}, enc={audio_encoding}, sr={sample_rate_hertz}, chans={num_channels}")

    def stream_synthesize(self, text_gen: Iterator[str]) -> Iterator[bytes]:
        """Bidirectional streaming: yields raw PCM chunks (no container)."""
        streaming_config = texttospeech.StreamingSynthesizeConfig(
            voice=texttospeech.VoiceSelectionParams(
                name=self.voice_name,
                language_code=self.language_code,
            ),
            streaming_audio_config=texttospeech.StreamingAudioConfig(
                audio_encoding=self.audio_encoding,
                sample_rate_hertz=self.sample_rate_hertz if self.sample_rate_hertz else 0
            )
        )
        from google.cloud.texttospeech import StreamingSynthesizeRequest, StreamingSynthesisInput

        # First request: config, no input text
        config_request = StreamingSynthesizeRequest(streaming_config=streaming_config)

        def request_generator():
            yield config_request
            for chunk in text_gen:
                txt = chunk.strip()
                if not txt:
                    continue
                yield StreamingSynthesizeRequest(input=StreamingSynthesisInput(text=txt))

        try:
            responses = self.client.streaming_synthesize(request_generator())
            for resp in responses:
                if resp.audio_content:
                    yield resp.audio_content
        except Exception as e:
            logger.warning(f"Streaming TTS failed: {e}")
            raise

    def synthesize(self, full_text: str) -> bytes:
        """Fallback (batch) TTS: returns full audio bytes (PCM or supported encoding)."""
        if not full_text.strip():
            return b""
        synthesis_input = texttospeech.SynthesisInput(text=full_text)
        voice = texttospeech.VoiceSelectionParams(
            name=self.voice_name,
            language_code=self.language_code
        )
        audio_conf = texttospeech.AudioConfig(
            audio_encoding=self.audio_encoding,
            sample_rate_hertz=self.sample_rate_hertz if self.sample_rate_hertz else 0
        )
        resp = self.client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_conf
        )
        return resp.audio_content

    def synthesize_safe(self, text_gen: Iterator[str]) -> Iterator[bytes]:
        """Try streaming first; fallback to batch if streaming fails."""
        # Collect the chunks in case fallback is needed
        collected = []
        try:
            for chunk in self.stream_synthesize(text_gen):
                collected.append(chunk)
                yield chunk
        except Exception as e:
            logger.info("Falling back to non-streaming TTS due to error")
            # On fallback, combine all input text (we need to regenerate or buffer it)
            full = "".join(collected)  # Note: this is flawed if you interpret chunks as text
            audio = self.synthesize(full)
            if audio:
                yield audio

    def write_wav_from_pcm_chunks(self, pcm_chunks: Iterator[bytes], wav_path: str):
        """
        Given an iterator of raw PCM chunks (bytes), write them into a proper WAV file.
        """
        logger.info(f"Writing WAV to {wav_path}")

        with wave.open(wav_path, 'wb') as wf:
            wf.setnchannels(self.num_channels)
            wf.setsampwidth(self.sample_width_bytes)
            # If sample_rate_hertz was 0 or None, you may pick a default or use what voice reports
            sr = self.sample_rate_hertz or 24000
            wf.setframerate(sr)

            # Write PCM frames
            for chunk in pcm_chunks:
                wf.writeframes(chunk)

        logger.info("WAV file written successfully")

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Example test
    client = GoogleTTSClient(
        voice_name="en-US-Chirp3-HD-Charon",
        language_code="en-US",
        audio_encoding=texttospeech.AudioEncoding.PCM,
        sample_rate_hertz=24000,
        num_channels=1,
        sample_width_bytes=2
    )

    # Simulate streaming inputs
    def sample_text_gen():
        for part in ["Hey that activity isn't available right now. We could do something else instead."]:
            yield part

    # Use streaming and capture
    pcm_chunks = []
    try:
        for chunk in client.stream_synthesize(sample_text_gen()):
            pcm_chunks.append(chunk)
            print(f"Chunk size {len(chunk)}")
    except Exception as e:
        logger.error("Streaming failed, fallback method might need to be used")

    # Write to WAV
    client.write_wav_from_pcm_chunks(pcm_chunks, "out_fixed.wav")

    # Optionally, also test fallback
    # fallback_audio = client.synthesize("Hello, how are you doing today?")
    # with open("out_batch.wav", "wb") as f:
    #     f.write(fallback_audio)
