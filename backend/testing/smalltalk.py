import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src', 'scripts'))

from mic_stream import MicStream
from stt import GoogleSTTService
from _pipeline_smalltalk import SmallTalkSession

# If you use env var for GCP auth:
# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "backend/Config/STT/GoogleCloud.json"

def mic_factory():
    # tune chunk to ~100ms (rate/10)
    return MicStream(rate=16000, chunk_size=1600)

if __name__ == "__main__":
    stt = GoogleSTTService(language="en-US", sample_rate=16000)
    deepseek_cfg = "backend/Config/LLM/deepseek.json"

    session = SmallTalkSession(
        stt=stt,
        mic_factory=mic_factory,
        deepseek_config_path=deepseek_cfg,
        system_prompt="You are Well-Bot. Keep replies friendly and brief.",
        language_code="en-US"
    )
    session.start()
