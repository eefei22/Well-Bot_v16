# Journaling Feature — Conceptual Implementation Plan (Well-Bot v16)

Below is a pragmatic, code-ready plan that plugs into your existing pipeline and keeps components reusable.

---

## 1) High-Level Flow (end-to-end)

Wake Word → Intent → **JournalActivity** → Prompt user (TTS) → Record speech (MicStream) → STT transcript stream → Finalize entry → Save to DB (Supabase) → Audio confirmation.

---

## 2) Activity Lifecycle (finite state machine)

**States**

* `INIT` → construct activity, load configs, pick language assets.
* `PROMPT_START` → short TTS prompt: “Ready to journal. Start speaking after the tone. Say ‘stop journal’ to finish.”
* `RECORDING` → Mic on, STT streaming; aggregate partials; auto-split on long pauses; end conditions: wake phrase (“stop journal”), silence timeout, or max duration.
* `CONFIRMATION` → TTS: “Shall I save this? Say ‘save’ or ‘discard’. You can also say ‘as draft’.”
* `SAVING` → write to `wb_journal`; on success: TTS “Saved.”; on fail: TTS “Couldn’t save; I kept it as draft locally.”
* `DONE` → cleanup; return to orchestrator.

**Transitions**

* `INIT → PROMPT_START` (on activity start)
* `PROMPT_START → RECORDING` (after tone)
* `RECORDING → CONFIRMATION` (on stop phrase / timeout / max duration)
* `CONFIRMATION → SAVING` (on save intent)
* `CONFIRMATION → DONE` (on discard)
* `SAVING → DONE` (on success/fail)

**Termination phrases**

* Stop: `["stop journal", "save journal", "end entry", "that’s all"]`
* Save: `["save", "save now", "save entry", "as draft"]`
* Discard: `["discard", "don’t save"]`

(Keep these in `config/preference.json` by language.)

---

## 3) Module & File Additions

### 3.1 `backend/src/activities/journal.py`

A self-contained activity class with a clean interface.

```python
# journal.py (outline)
from ..components.mic_stream import MicStream
from ..components.stt import GoogleSTTService
from ..components.tts import TTSService
from ..supabase.database import upsert_journal
from ..components.conversation_audio_manager import ConversationAudioManager
from ..components.conversation_session import ConversationSession
from ..config_loader import load_prefs
import datetime as dt

class JournalActivity:
    def __init__(self, session: ConversationSession, audio: ConversationAudioManager,
                 stt: GoogleSTTService, tts: TTSService, user_id: str, lang: str = "ENGLISH"):
        self.session = session
        self.audio = audio
        self.stt = stt
        self.tts = tts
        self.user_id = user_id
        self.lang = lang
        self.state = "INIT"
        self.buffers = []   # list[str] accumulated paragraphs
        self.config = load_prefs()  # timeouts, phrases

    def start(self):
        self._prompt_start()
        self._record_loop()
        confirmed, draft = self._confirm()
        if confirmed is None:  # user abandoned
            return
        if confirmed:
            self._save(draft)
        self._cleanup()

    def _prompt_start(self):
        self.state = "PROMPT_START"
        self.audio.play_asset(self.lang, "start_journal_tone.wav")
        self.tts.say("Ready to journal. Start speaking after the tone. Say 'stop journal' to finish.")
    
    def _record_loop(self):
        self.state = "RECORDING"
        # stream STT, collect partials -> finalize paragraphs on long pauses
        # break on stop phrase, silence timeout, or max duration

    def _confirm(self):
        self.state = "CONFIRMATION"
        # summarize length, ask save/discard/draft, listen briefly for response
        # return (True/False, draft_bool)

    def _save(self, draft: bool):
        self.state = "SAVING"
        title = self._default_title()
        body = "\n\n".join(self.buffers).strip()
        mood = self._derive_mood_or_default()
        topics = self._extract_topics(body)  # optional simple heuristic/empty list
        upsert_journal(
            user_id=self.user_id,
            title=title,
            body=body,
            mood=mood,
            topics=topics,
            is_draft=draft
        )
        self.tts.say("Journal saved." if not draft else "Draft saved.")

    def _cleanup(self):
        self.state = "DONE"

    def _default_title(self):
        return f"Journal {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}"

    def _derive_mood_or_default(self) -> int:
        # v1: default neutral (3). v2: plug your SER pipeline here.
        return 3

    def _extract_topics(self, text: str) -> list[str]:
        # v1: empty list; v2: simple keyword bag; v3: LLM-based tags.
        return []
```

### 3.2 `backend/src/supabase/database.py` (add a thin journal DAL)

```python
# database.py (additions)
from .client import supabase

def upsert_journal(user_id: str, title: str, body: str, mood: int,
                   topics: list[str], is_draft: bool):
    payload = {
        "user_id": user_id,
        "title": title,
        "body": body,
        "mood": mood,
        "topics": topics,
        "is_draft": is_draft,
    }
    return supabase.table("wb_journal").insert(payload).execute()
```

*(If you want idempotency on retries, you can pre-create a UUID in the activity and call `upsert` with `on_conflict="id"`.)*

### 3.3 `backend/src/components/stt.py` (ensure stream hooks)

* Expose callbacks for partial and final transcripts.
* Provide `on_phrase_detected` hook to end on termination phrases.
* Emit “finalized paragraph” signals on long pause (>1.5–2.0s) or VAD signal.

### 3.4 `backend/src/components/conversation_audio_manager.py`

* Provide `play_asset(lang, filename)` and `say(tts_text)` wrappers so all activities share the same audio surface.

### 3.5 `backend/src/components/intent_detection.py`

* Map `journal_write` → `JournalActivity`.

