# Turn-Taking Logic in SmallTalk Activity

## Overview

The system uses **Google Cloud Speech-to-Text's Voice Activity Detection (VAD)** to automatically detect when you've finished speaking. The turn-taking is controlled by Google STT's internal silence/pause detection algorithms.

## Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│  SmallTalk Conversation Loop (smalltalk.py)            │
│                                                          │
│  while active:                                           │
│    1. Call capture_user_speech()  ← BLOCKS HERE         │
│    2. Wait for final transcript                         │
│    3. Process transcript → LLM                          │
│    4. Generate & play response                          │
│    5. Loop back to step 1                               │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│  ConversationAudioManager.capture_user_speech()         │
│                                                          │
│  1. Create MicStream & start audio capture              │
│  2. Start STT streaming in separate thread             │
│  3. Register callback: on_transcript(text, is_final)   │
│  4. WAIT for final transcript (is_final=True)           │
│  5. Return final_text                                   │
└─────────────────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────────────────┐
│  Google STT Service (stt.py)                           │
│                                                          │
│  stream_recognize() with:                                │
│    - interim_results=True                               │
│    - single_utterance=False  ← KEEPS LISTENING          │
│                                                          │
│  Google STT internally:                                  │
│    1. Receives audio chunks continuously                │
│    2. Sends INTERIM results (is_final=False)            │
│    3. Detects silence/pause using VAD                   │
│    4. After silence threshold → sends FINAL (is_final=True)│
└─────────────────────────────────────────────────────────┘
```

## Key Components

### 1. Google STT Voice Activity Detection (VAD)

**Location**: Google Cloud Speech-to-Text API (internal)

**How it works**:
- Continuously analyzes audio for speech patterns
- When it detects silence/pause, it:
  1. Waits for a silence threshold (typically 0.5-1 second)
  2. Sends a **final transcript** with `is_final=True`
  3. Continues listening (since `single_utterance=False`)

**Important**: The VAD threshold is **language-dependent** and controlled by Google's algorithms. Chinese may have different thresholds than English.

### 2. ConversationAudioManager.capture_user_speech()

**File**: `backend/src/components/conversation_audio_manager.py` (line 111-186)

**Logic**:
```python
def on_transcript(text: str, is_final: bool):
    nonlocal final_text
    if is_final:  # ← THIS IS THE KEY
        final_text = text
        mic.stop()  # Stop microphone when final received
```

**Behavior**:
- Blocks until Google STT sends `is_final=True`
- Returns immediately when final transcript arrives
- Has a 30-second timeout as a safety mechanism

### 3. SmallTalk Conversation Loop

**File**: `backend/src/activities/smalltalk.py` (line 335-428)

**Logic**:
```python
while active:
    # BLOCKS HERE - waits for final transcript
    user_text = self.audio_manager.capture_user_speech()
    
    if user_text:
        # Send to LLM immediately
        self.llm_pipeline._stream_llm_and_tts()
```

**Turn Sequence**:
1. **User speaks** → Google STT detects speech
2. **Google STT sends interim results** → Not processed, just logged
3. **User stops speaking** → Google STT VAD detects silence
4. **Google STT sends final result** → `is_final=True` triggers return
5. **System processes** → Sends to LLM, generates response

## The Problem You're Experiencing

Based on your logs, here's what's happening:

1. **User speaks** at 22:15:34
2. **SmallTalk timeout triggers** at 22:15:30 (due to inactivity monitoring)
3. **Activity stops** at 22:15:36
4. **Final transcript arrives** at 22:15:35 - **TOO LATE**

### Root Cause

The **silence monitoring** in `ConversationAudioManager` (lines 343-380) is **independent** of Google STT's VAD:

- **Silence Monitor**: Tracks `_last_user_time` and triggers timeout after 10s of no activity
- **Google STT**: Has its own VAD that detects end-of-speech (may take longer)

When you're speaking in Chinese:
- Google STT may take longer to detect end-of-speech (language-specific VAD)
- The silence monitor doesn't know you're still speaking
- Silence monitor times out → activity stops
- Final transcript arrives after activity already stopped

### The Conflict

```
Timeline:
T+0s:  User starts speaking
T+10s: Silence monitor detects no activity → triggers nudge
T+15s: Silence continues → triggers timeout
T+16s: Activity stops
T+17s: Google STT finally sends final transcript (too late!)
```

The silence monitor is based on **transcript arrival**, not **audio activity**. When STT is slow to process, the monitor thinks you're silent even though you're speaking.

## Solutions

### Option 1: Increase Silence Timeout for Chinese

The silence timeout may be too short for Chinese STT processing.

**Location**: `backend/config/global.json` - `smalltalk.silence_timeout_seconds`

### Option 2: Use Audio Activity Detection

Instead of tracking transcript timing, monitor actual audio input levels to detect when user is speaking vs. silent.

### Option 3: Disable Silence Monitoring During Active STT

When `capture_user_speech()` is blocking (meaning STT is actively listening), pause the silence monitor since STT handles the turn-taking.

## Current Configuration

**Silence Timeouts** (from `global.json`):
- `silence_timeout_seconds`: 10 seconds (before nudge)
- `nudge_timeout_seconds`: 15 seconds (after nudge, before timeout)
- **Total**: 25 seconds before timeout

**Google STT Settings**:
- `interim_results`: True
- `single_utterance`: False (keeps listening)
- **VAD threshold**: Controlled by Google (language-dependent, not configurable)

## Recommendations

1. **Short-term**: Increase silence timeout for better Chinese support
2. **Medium-term**: Add audio-level monitoring to detect actual speech activity
3. **Long-term**: Integrate silence monitoring with STT state (pause when STT is actively processing)

