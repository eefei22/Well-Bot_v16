Websocket but failed

## 🎯 Requirements Recap & Design Choices

You want the manager to:

* Wrap around your existing smalltalk pipeline
* Maintain cached memory / context so RAG retrieval isn’t run every utterance
* Use a **pre-recorded audio file** (“Hey, are you there?”) as the nudge prompt (i.e. play audio)
* No emojis from assistant (strip them)
* Load system prompts / instructions from a config JSON in `backend/Config/LLM`
* Provide voice termination detection (by a phrase)
* Monitor silence, nudge, and end session if no response

Thus, the manager will:

1. Load config (LLM instructions, termination phrases, silence timeouts)
2. Own the pipeline object (SmallTalkSession)
3. Intercept transcript results (user utterance) and reply results (assistant)
4. Decide when to nudge (play audio file)
5. Decide when to stop
6. Provide hooks for RAG (e.g. call retrieval once and cache context)

---

## PART 0 - nudge audio file (DONE)

audio files accessible from here
```
Well-Bot_v16/
  backend/
    assets/
        inactivity_nudge_EN.mp3   ← pre-recorded audio file 
        inactivity_nudge_CN.mp3
        inactivity_nudge_MY.mp3       
```

So manager code can reference it via relative path (e.g. `os.path.join(asset_dir, "inactivity_nudge_EN")`).

---

## PART 1 - Config file for LLM instructions and manager settings
Create something like:

`backend/Config/LLM/llm_instructions.json`
```json
{
  "system_prompt": "You are a friendly assistant. Do not use emojis.",
  "termination_phrases": ["stop", "end conversation", "goodbye", "bye", "exit"],
  "silence_timeout_seconds": 30,
  "nudge_timeout_seconds": 15,
  "max_turns": 20
}
```

Then manager loads this file at initialization.

---

## PART 2 - smalltalk_manager.py Sketch

Here’s a skeleton you can adapt (inside `backend/src/managers/smalltalk_manager.py`):

```python
import os
import threading
import time
import re
from typing import Optional

from ._smalltalk_pipeline import SmallTalkSession
from speech_pipeline.intent import IntentInference  # if you want to detect termination via intent or phrase
import spacy

# For playing audio file
from playsound import playsound  # simple option — install via pip

class SmallTalkManager:
    def __init__(
        self,
        pipeline: SmallTalkSession,
        llm_config_path: str,
        nudge_audio_path: str
    ):
        self.pipeline = pipeline

        # Load LLM / manager config
        import json
        with open(llm_config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        self.system_prompt = cfg.get("system_prompt")
        self.termination_phrases = [p.lower() for p in cfg.get("termination_phrases", [])]
        self.silence_timeout = cfg.get("silence_timeout_seconds", 30)
        self.nudge_timeout = cfg.get("nudge_timeout_seconds", 15)
        self.max_turns = cfg.get("max_turns", 20)

        self.nudge_audio_path = nudge_audio_path

        self._active = False
        self._turn_count = 0
        self._last_user_time = None
        self._nudged = False

        # Optionally an IntentRecognizer to detect “termination intent”
        self.intent_inf = IntentInference(...)  # load model (if you want to use it)

    def _strip_emojis(self, text: str) -> str:
        # remove emojis via regex (basic)
        return re.sub(r"[^\w\s.,!?'-]", "", text)

    def _is_termination_phrase(self, user_text: str) -> bool:
        low = user_text.lower().strip()
        for phrase in self.termination_phrases:
            if low == phrase or low.startswith(phrase + " "):
                return True
        # Optionally use intent classifier:
        # res = self.intent_inf.predict_intent(user_text)
        # if res["intent"] == "terminate_intent" and res["confidence"] > 0.8:
        #     return True
        return False

    def _play_nudge(self):
        try:
            playsound(self.nudge_audio_path)
        except Exception as e:
            print("[SmallTalkManager] Error playing nudge audio:", e)

    def _silence_watcher(self):
        """
        Runs in a background thread to monitor silence.
        If no user input beyond silence_timeout, triggers nudge or termination.
        """
        while self._active:
            if self._last_user_time is None:
                time.sleep(1)
                continue
            elapsed = time.time() - self._last_user_time
            if elapsed >= self.silence_timeout and not self._nudged:
                # time to nudge
                print("[SmallTalkManager] Nudging user (silence).")
                self._play_nudge()
                self._nudged = True
                # after nudging, wait for nudge_timeout more
            elif elapsed >= self.silence_timeout + self.nudge_timeout:
                print("[SmallTalkManager] No response after nudge, ending session.")
                self.stop()
                break
            time.sleep(1)

    def start(self):
        self._active = True
        self._turn_count = 0
        self._nudged = False
        self._last_user_time = None

        # Optionally set pipeline’s system prompt
        # pipeline might accept initial prompt or you inject it via message list

        # start silence watcher
        watcher = threading.Thread(target=self._silence_watcher, daemon=True)
        watcher.start()

        print("[SmallTalkManager] Session start")
        self.pipeline.start(loop_callback=self._on_turn_complete)

        # pipeline.start is blocking (in existing code). If not, you need to wait or join.

    def _on_turn_complete(self, user_text: str, assistant_reply: str):
        """
        Called after each turn (user → assistant).
        """
        self._turn_count += 1
        self._last_user_time = time.time()
        self._nudged = False  # reset nudge status after user speaks

        # 1. Strip emojis from assistant text and maybe override
        clean = self._strip_emojis(assistant_reply)
        # You might want to replace text in pipeline’s storage or UI output

        # 2. Check turn limit
        if self._turn_count >= self.max_turns:
            print("[SmallTalkManager] Reached max turns, ending.")
            self.stop()

    def stop(self):
        if not self._active:
            return
        self._active = False
        print("[SmallTalkManager] Stopping session.")
        self.pipeline.stop()

```

**Notes / how it plugs in**:

* I assume `SmallTalkSession.start(...)` can accept a callback when a turn is completed. If your pipeline doesn’t support that yet, you should modify pipeline to allow reporting back (user_text, assistant_reply) each turn.
* Manager’s `start()` triggers the pipeline; manager monitors for silent gaps and termination conditions.
* Manager intervenes (nudge or stop) independently.
* Clean the assistant replies by stripping emojis before passing to user / DB / UI.
* The `IntentInference` is optional — I included stub for termination detection via intent if you later train a “termination_intent.” (INCLUDE THIS IN THE IMPLEMENTATION BUT WRAP AROUND A COMMENT)

---

## ✅ Summary & Next Steps

* Yes, add `smalltalk_manager.py` that owns/wraps `pipeline_smalltalk`.
* Pipeline plugs into manager (manager calls pipeline).
* You’ll place your nudge audio in something like `backend/assets/nudge_audio/are_you_there.wav`.
* You’ll add `backend/Config/LLM/llm_instructions.json` for system prompts, termination phrases, timeouts.
* RAG logic should live in manager (or manager calls retrieval) rather than polluting pipeline.

If you like, I can polish that manager skeleton into a fully working code file based on your existing pipeline signature (so it fits seamlessly). Do you want me to generate that ready-to-use file for you next?
