# Journal Activity - Complete Workflow Documentation

## Overview
This document describes the complete workflow of the Journal Activity from initialization to completion, including all edge cases and event handling.

## Configuration Values (from `global.json`)
- `silence_timeout_seconds`: 10 seconds
- `nudge_timeout_seconds`: 10 seconds
- `pause_finalization_seconds`: 2.5 seconds
- `min_words_threshold`: 5 words
- `max_duration_seconds`: 150 seconds

---

## Phase 1: Initialization

### Step 1: `initialize()` is called
1. Load user-specific configurations:
   - `global_config` (numerical settings)
   - `language_config` (prompts, termination phrases, audio paths)
   - Extract `global_journal_config` and `journal config` sections

2. Initialize services:
   - **STT Service**: GoogleSTTService (en-US, 16kHz)
   - **TTS Service**: GoogleTTSClient with voice config
   - **ConversationAudioManager**: Handles audio playback and silence monitoring
   - **MicFactory**: Creates microphone streams

3. Load termination phrases from config (e.g., "stop journal", "save journal", "end entry")

4. Set internal state:
   - `state = "INIT"`
   - `_initialized = True`
   - Initialize buffers: `buffers = []`, `current_buffer = ""`
   - `_saved = False`

---

## Phase 2: Session Start

### Step 2: `start()` is called
1. Validate initialization
2. Set `_active = True`
3. Call `_prompt_start()`

### Step 3: `_prompt_start()` - PROMPT_START State
1. Set `state = "PROMPT_START"`
2. **Optional**: Play start audio file (if `use_audio_files = true`)
3. **TTS**: Speak start prompt from config:
   - Default: *"Ready to journal. Start speaking after the tone. You can pause anytime to think. Say 'stop journal' when you're finished."*
4. Transition to recording

### Step 4: `_record_loop()` - RECORDING State
1. Set `state = "RECORDING"`
2. **Start silence monitoring** (calls `_start_silence_monitoring()`)
   - This starts a background thread that monitors user silence
   - Initial silence timeout: 10 seconds
   - After nudge, timeout: 10 seconds
3. **Create microphone stream**:
   - Create mic using `audio_manager.mic_factory()`
   - `mic.start()` - begins audio capture
   - Register mic with `ConversationAudioManager`
4. Initialize `last_final_time = time.time()`
5. **Start STT streaming** with callback: `on_transcript(text, is_final)`

---

## Phase 3: Active Recording - Normal Flow

### Step 5: User Speaks - Transcript Handling

#### A. **Interim Transcript** (is_final = False)
1. `on_transcript()` receives interim text
2. **Reset silence timer**: `audio_manager.reset_silence_timer()`
   - Updates `_last_user_time` to current time
   - Resets `_nudged = False`
3. **Check for termination phrase** in interim text:
   - Normalize text (lowercase, remove punctuation)
   - Compare against termination phrases
   - **IF MATCH**:
     - Set `_termination_detected = True`
     - Stop microphone
     - Raise `TerminationPhraseDetected()` exception
     - **Jumps to Termination Handler** (Step 10)

#### B. **Final Transcript** (is_final = True)
1. `on_transcript()` receives final text
2. **Reset silence timer**: `audio_manager.reset_silence_timer()`
3. **Check for termination phrase**:
   - **IF MATCH**: Same as interim (terminate immediately)
4. **Check for long pause**:
   - Calculate elapsed time: `current_time - last_final_time`
   - **IF elapsed > 2.5 seconds** (`pause_finalization_seconds`):
     - Call `_finalize_paragraph()`:
       - If `current_buffer` has content, append to `buffers[]`
       - Clear `current_buffer = ""`
     - Log: "Long pause detected (X.Xs), finalizing paragraph"
5. **Update buffer**:
   - Append final text to `current_buffer`
   - Update `last_final_time = current_time`

### Example Flow:
```
User says: "Today I went to the park"
  → Interim: "Today I", "Today I went", "Today I went to"
  → Final: "Today I went to the park"
  → Added to current_buffer

[User pauses for 3 seconds]
  → Pause detected (3s > 2.5s threshold)
  → Paragraph finalized → moved to buffers[]
  → current_buffer cleared

User continues: "It was really nice"
  → Final: "It was really nice"
  → Added to new current_buffer
```

---

## Phase 4: User Pauses (Short Pause < 2.5s)

### Scenario A: Normal Pause (1-2 seconds)
1. User stops speaking
2. No new transcripts arrive
3. Silence timer continues counting
4. **If user resumes within 2.5 seconds**:
   - New transcript arrives
   - Silence timer resets
   - Content continues in same `current_buffer`
   - **No paragraph finalization**

---

## Phase 5: User Pauses (Long Pause ≥ 2.5s, < 10s)

### Scenario B: Thinking Pause (2.5-10 seconds)
1. User stops speaking
2. Silence timer counts up
3. **At 2.5 seconds**: Next final transcript (if any) triggers paragraph finalization
4. **If user resumes within 10 seconds**:
   - Silence timer resets on new transcript
   - User continues speaking
   - Content goes to new paragraph segment

**Example:**
```
User: "I'm feeling anxious today"
[Pauses 3 seconds thinking]
  → Paragraph finalized
  → buffers[0] = "I'm feeling anxious today"
  
User: "But I'm working on it"
  → New content goes to current_buffer
```

---

## Phase 6: User Goes Silent (10 seconds)

### Scenario C: First Silence Timeout (10 seconds)
1. User has been silent for **10 seconds** (`silence_timeout_seconds`)
2. **ConversationAudioManager's silence watcher thread** detects:
   - `elapsed >= silence_timeout` AND `_nudged = False`
3. **Triggers `on_nudge()` callback**:
   - Play nudge audio (if enabled)
   - **TTS**: Speak nudge prompt:
     - *"Are you still there? Continue speaking or say 'stop journal' to finish."*
   - Set `_nudged = True` flag
4. **Silence watcher continues monitoring**

### Step 6A: User Responds After Nudge
- **If user speaks within next 10 seconds**:
  1. New transcript arrives
  2. Silence timer resets (`reset_silence_timer()`)
     - Sets `_nudged = False`
  3. User continues journaling
  4. Flow returns to **Step 5** (normal recording)

---

## Phase 7: User Remains Silent (20 seconds total)

### Scenario D: Final Timeout After Nudge (10s + 10s = 20s total)
1. User continues silent after nudge
2. **10 seconds after nudge** (`nudge_timeout_seconds`):
   - Total silence: 20 seconds
3. **Silence watcher detects**:
   - `elapsed >= silence_timeout + nudge_timeout`
4. **Triggers `on_timeout()` callback**:
   - Sets `_termination_detected = True`
   - **Stops microphone immediately**:
     ```python
     with audio_manager._mic_lock:
         if audio_manager._current_mic:
             audio_manager._current_mic.stop()
     ```
   - This causes `stream_recognize()` to exit
   - `_record_loop()` reaches `finally` block
   - Jumps to **Cleanup & Save** (Phase 9)

---

## Phase 8: Termination Phrase Detection

### Step 7: User Says Termination Phrase
1. User speaks a termination phrase:
   - Examples: "stop journal", "save journal", "end entry", "that's all"
2. **STT recognizes phrase** (either interim or final transcript)
3. `_is_termination_phrase()` checks:
   - Normalizes user text
   - Compares against config phrases using multiple strategies:
     - Exact match
     - Starts with phrase
     - Phrase contained in text
4. **IF MATCH FOUND**:
   - Set `_termination_detected = True`
   - Stop microphone
   - Raise `TerminationPhraseDetected()` exception
5. **Exception caught** in `start()` method:
   ```python
   except TerminationPhraseDetected:
       logger.info("Termination phrase detected, saving journal entry...")
       if self._has_content():
           self.state = "SAVING"
           self._save()
   ```

---

## Phase 9: Cleanup & Save

### Step 8: `_record_loop()` Exits (Finally Block)
After termination (any cause):
1. **Stop microphone**: `mic.stop()`
2. **Unregister mic** from ConversationAudioManager
3. **Stop silence monitoring**: `_stop_silence_monitoring()`
4. **Finalize any remaining buffer**:
   - If `current_buffer` has content → `_finalize_paragraph()`
   - Moves to `buffers[]`

### Step 9: Content Validation
Before saving, check if entry is meaningful:
1. Call `_has_content()`:
   - Combine all buffers + current buffer
   - Count words: `len(all_content.split())`
   - **Return**: `word_count >= min_words_threshold (5)`

### Step 10: Save Decision Tree

#### Path A: Termination Phrase Detected
```python
except TerminationPhraseDetected:
    if self._has_content():  # ≥ 5 words
        self.state = "SAVING"
        self._save()
```

#### Path B: Normal Completion (no termination)
```python
if not self._termination_detected and self._has_content():
    self.state = "SAVING"
    self._save()
```

#### Path C: Keyboard Interrupt (Ctrl+C)
```python
except KeyboardInterrupt:
    if self._has_content():
        self.state = "SAVING"
        self._save()
```

#### Path D: Timeout Termination (in finally block)
```python
finally:
    if self._termination_detected and not self._saved and self._has_content():
        logger.info("Saving accumulated content after timeout termination")
        self.state = "SAVING"
        self._save()
    self._cleanup()
```

---

## Phase 10: Saving Process

### Step 11: `_save()` Method
1. **Prevent duplicate saves**:
   - If `_saved = True` → return early

2. **Finalize remaining content**:
   - Call `_finalize_paragraph()` one last time
   - Ensures all content is in `buffers[]`

3. **Build journal entry**:
   - Combine paragraphs: `body = "\n\n".join(buffers).strip()`
   - Count words
   - Generate title: `"Journal YYYY-MM-DD HH:MM"`
   - Get default mood: `default_mood` (default: 3)
   - Extract topics (placeholder, returns empty list)

4. **Save to database**:
   - Call `upsert_journal()` with:
     - `user_id`
     - `title`
     - `body`
     - `mood`
     - `topics`
     - `is_draft = False`

5. **Mark as saved**: `_saved = True`

6. **Confirmation TTS**:
   - Speak: *"Journal entry saved with {word_count} words."*

### Step 12: If Content Too Short (< 5 words)
- **No save occurs**
- Logs: "No content to save" (if buffers empty)
- Or silently skips if `_has_content()` returns False
- Proceeds directly to cleanup

---

## Phase 11: Cleanup

### Step 13: `_cleanup()`
1. Set `state = "DONE"`
2. Set `_active = False`
3. Stop audio manager: `audio_manager.stop()`
   - Stops silence monitoring
   - Cleans up audio resources
4. Log completion

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ INITIALIZATION                                               │
│ - Load configs, initialize STT/TTS/AudioManager             │
│ - Load termination phrases                                  │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ START SESSION                                                │
│ - _prompt_start() → Play audio + TTS start prompt          │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│ RECORDING LOOP                                               │
│ - Start silence monitoring (background thread)              │
│ - Start mic stream                                           │
│ - Start STT streaming                                        │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌──────────────┐    ┌─────────────────────┐
│ USER SPEAKS  │    │  USER PAUSES        │
│              │    │                     │
│ - Reset      │    │ < 2.5s: Continue   │
│   silence    │    │ ≥ 2.5s: Finalize   │
│   timer      │    │   paragraph         │
│              │    │ ≥ 10s: Nudge       │
│ - Check      │    │ ≥ 20s: Timeout     │
│   termination│    │                     │
│              │    └──────────┬──────────┘
│ - Update     │               │
│   buffer     │               │
└──────┬───────┘               │
       │                       │
       │                       ▼
       │              ┌─────────────────────┐
       │              │ SILENCE NUDGE       │
       │              │ (10s silence)       │
       │              │ → TTS: "Are you...?"│
       │              └──────┬──────────────┘
       │                     │
       │                     │ (No response)
       │                     │
       │                     ▼
       │              ┌─────────────────────┐
       │              │ FINAL TIMEOUT       │
       │              │ (20s total)        │
       │              │ → Stop mic          │
       │              │ → Set termination   │
       │              └──────┬──────────────┘
       │                     │
       └─────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌──────────────────┐  ┌──────────────────────┐
│ TERMINATION      │  │ NORMAL EXIT          │
│ PHRASE           │  │ (mic.stop() called)  │
│ DETECTED         │  │                      │
│                  │  │                      │
│ - Stop mic       │  │ - Exit stream        │
│ - Raise exception│  │ - Finalize buffer    │
└────────┬─────────┘  └──────────┬───────────┘
         │                       │
         └───────────┬───────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ CLEANUP & SAVE        │
         │                       │
         │ 1. Finalize buffer    │
         │ 2. Check word count    │
         │    (≥ 5 words?)       │
         │                       │
         │ IF YES:               │
         │   - Build entry       │
         │   - Save to DB        │
         │   - TTS confirmation  │
         │                       │
         │ IF NO:                │
         │   - Skip save         │
         │                       │
         │ 3. Cleanup resources  │
         └───────────────────────┘
                     │
                     ▼
         ┌───────────────────────┐
         │ SESSION COMPLETE      │
         │ state = "DONE"        │
         └───────────────────────┘
```

---

## Key Timings Summary

| Event | Time Threshold | Action |
|-------|---------------|--------|
| Short pause | < 2.5s | Continue in same buffer |
| Long pause | ≥ 2.5s | Finalize paragraph |
| Silence nudge | 10s silence | Play nudge prompt |
| Final timeout | 10s after nudge (20s total) | Auto-terminate |
| Max duration | 150s | (Future: hard timeout) |

---

## State Transitions

```
INIT → PROMPT_START → RECORDING → SAVING → DONE
                         │
                         ├─→ (on error/exception)
                         └─→ DONE (no save if < 5 words)
```

---

## Important Notes

1. **Silence Timer Reset**: Every transcript (interim or final) resets the silence timer, preventing false timeouts during active speech.

2. **Paragraph Finalization**: Only happens on final transcripts, and only when pause between final transcripts exceeds 2.5 seconds.

3. **Termination Detection**: Works on both interim and final transcripts for immediate response.

4. **Duplicate Save Prevention**: `_saved` flag ensures journal is only saved once per session.

5. **Buffer Management**:
   - `current_buffer`: Active paragraph being built
   - `buffers[]`: Completed paragraphs
   - Final paragraph finalized before save

6. **Word Threshold**: Entries with < 5 words are not saved to prevent noise/clutter.

