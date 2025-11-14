## Guide: Adding GUI Support to Other Activities & Future GUI Features

### Phase 1: Add GUI Support to Existing Activities

To add GUI support to Journal, Gratitude, Meditation, Spiritual Quote, and Activity Suggestion, follow this pattern:

#### Pattern (same as SmallTalk)

**Step 1: Modify Activity `__init__()` Method**

For each activity file (`journal.py`, `gratitude.py`, `meditation.py`, `spiritual_quote.py`, `activity_suggestion.py`):

```python
# BEFORE:
def __init__(self, backend_dir: Path, user_id: Optional[str] = None):
    # ... existing code ...

# AFTER:
def __init__(self, backend_dir: Path, user_id: Optional[str] = None, ui_interface = None):
    # ... existing code ...
    self.ui_interface = ui_interface
```

**Step 2: Pass `ui_interface` to ConversationAudioManager**

In each activity's `initialize()` method, find where `ConversationAudioManager` is created and add the parameter:

```python
# BEFORE:
self.audio_manager = ConversationAudioManager(
    stt_service=self.stt_service,
    mic_factory=mic_factory,
    audio_config=audio_config,
    # ... other params ...
)

# AFTER:
self.audio_manager = ConversationAudioManager(
    stt_service=self.stt_service,
    mic_factory=mic_factory,
    audio_config=audio_config,
    ui_interface=self.ui_interface,  # Add this line
    # ... other params ...
)
```

**Step 3: Update `main.py` Activity Starters**

For each `_start_*_activity()` method in `main.py`, pass `ui_interface` when creating the activity:

```python
# Example for Journal (line ~444):
# BEFORE:
self.journal_activity = JournalActivity(backend_dir=self.backend_dir, user_id=self.user_id)

# AFTER:
self.journal_activity = JournalActivity(
    backend_dir=self.backend_dir, 
    user_id=self.user_id,
    ui_interface=self.ui_interface
)
```

**Files to modify in `main.py`:**
- `_start_journal_activity()` (line ~436)
- `_start_gratitude_activity()` (line ~557)
- `_start_meditation_activity()` (line ~610)
- `_start_spiritual_quote_activity()` (line ~504)
- `_start_activity_suggestion_activity()` (line ~663)

---

### Phase 2: General Guide for Future GUI Features

#### Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    GUI Layer                            │
│  (status_window.py, future GUI components)             │
│  - Displays visual information                         │
│  - Polls UIInterface for updates                       │
└──────────────────────┬──────────────────────────────────┘
                      │ polls
┌──────────────────────▼──────────────────────────────────┐
│              UI Interface Layer                         │
│  (ui_interface.py)                                     │
│  - Thread-safe state storage                           │
│  - update_mic_status(), update_speaker_status()        │
│  - Future: update_activity_state(), add_conversation() │
└──────────────────────┬──────────────────────────────────┘
                      │ updates
┌──────────────────────▼──────────────────────────────────┐
│           Component/Activity Layer                      │
│  (ConversationAudioManager, Activities)                │
│  - Calls ui_interface.update_*() methods                │
│  - Reports state changes                                │
└─────────────────────────────────────────────────────────┘
```

#### Pattern for Adding New GUI Features

**1. Define the UI Data Model**

Add new state fields to `UIInterface`:

```python
# In ui_interface.py
def __init__(self):
    # ... existing state ...
    self._state = {
        "mic_status": "idle",
        "speaker_status": "idle",
        # NEW: Add your new state fields
        "activity_name": "Idle",      # Example
        "conversation_turns": [],      # Example
        "system_status": {}            # Example
    }
```

**2. Add Update Methods to UIInterface**

```python
# In ui_interface.py
def update_activity_state(self, activity_name: str, status: str):
    """Update current activity name and status."""
    with self._lock:
        self._state["activity_name"] = activity_name
        self._state["activity_status"] = status
    self._notify_listeners()

def add_conversation_turn(self, role: str, text: str):
    """Add a conversation turn (user or bot message)."""
    with self._lock:
        turn = {"role": role, "text": text, "timestamp": time.time()}
        self._state["conversation_turns"].append(turn)
        # Keep only last N turns (e.g., 50)
        if len(self._state["conversation_turns"]) > 50:
            self._state["conversation_turns"] = self._state["conversation_turns"][-50:]
    self._notify_listeners()
```

**3. Wire Components to Update UI**

In activities or components, call the update methods:

```python
# In activity's run() or conversation loop:
if self.ui_interface:
    self.ui_interface.update_activity_state("SmallTalk", "running")

# When user speaks:
if self.ui_interface:
    self.ui_interface.add_conversation_turn("user", user_text)

# When bot responds:
if self.ui_interface:
    self.ui_interface.add_conversation_turn("bot", bot_response)
```

**4. Update GUI Window to Display New Information**

In `status_window.py`, add new widgets and update the polling:

```python
def _create_widgets(self):
    # ... existing widgets ...
    
    # NEW: Add activity name display
    self.activity_label = ttk.Label(
        main_frame, 
        text="Activity: Idle",
        font=("Arial", 10, "bold")
    )
    self.activity_label.grid(row=2, column=0, pady=5)
    
    # NEW: Add conversation log
    self.conversation_text = tk.Text(main_frame, height=10, width=40)
    self.conversation_text.grid(row=3, column=0, pady=5)

def _poll_updates(self):
    snapshot = self.ui_interface.get_snapshot()
    
    # ... existing updates ...
    
    # NEW: Update activity name
    activity_name = snapshot.get("activity_name", "Idle")
    self.activity_label.config(text=f"Activity: {activity_name}")
    
    # NEW: Update conversation log
    turns = snapshot.get("conversation_turns", [])
    # Display last few turns in conversation_text widget
```

**5. Update NoOpUIInterface**

Add stub methods to `NoOpUIInterface`:

```python
# In ui_interface.py, NoOpUIInterface class
def update_activity_state(self, activity_name: str, status: str):
    """No-op: do nothing."""
    pass

def add_conversation_turn(self, role: str, text: str):
    """No-op: do nothing."""
    pass
```

---

### Quick Reference: Files to Modify

#### For Adding GUI to Other Activities:

| Activity | Files to Modify |
|----------|----------------|
| **Journal** | `src/activities/journal.py` (2 places), `main.py` (1 place) |
| **Gratitude** | `src/activities/gratitude.py` (2 places), `main.py` (1 place) |
| **Meditation** | `src/activities/meditation.py` (2 places), `main.py` (1 place) |
| **Spiritual Quote** | `src/activities/spiritual_quote.py` (2 places), `main.py` (1 place) |
| **Activity Suggestion** | `src/activities/activity_suggestion.py` (2 places), `main.py` (1 place) |

#### For Adding New GUI Features:

| Feature | Files to Modify |
|---------|----------------|
| **Activity Name Display** | `ui_interface.py` (add method), `status_window.py` (add widget), activities (call method) |
| **Conversation Log** | `ui_interface.py` (add method), `status_window.py` (add widget), activities (call method) |
| **System Status** | `ui_interface.py` (add method), `status_window.py` (add widget), components (call method) |
| **Error Messages** | `ui_interface.py` (add method), `status_window.py` (add widget), activities (call method) |

---

### Best Practices

1. Always guard UI calls: `if self.ui_interface:`
2. Keep UI interface thread-safe (use locks)
3. Update NoOpUIInterface with stub methods
4. Test with GUI disabled (headless mode)
5. Keep GUI polling non-blocking
6. Use snapshot pattern for state retrieval

---

### Example: Adding Activity Name Display

Here's a complete example of adding "Activity Name" display:

**1. Update `ui_interface.py`:**
```python
# In UIInterface.__init__():
self._state["activity_name"] = "Idle"

# Add method:
def update_activity_name(self, name: str):
    with self._lock:
        self._state["activity_name"] = name
    self._notify_listeners()
```

**2. Update `status_window.py`:**
```python
# In _create_widgets():
self.activity_label = ttk.Label(main_frame, text="Activity: Idle")
self.activity_label.grid(row=2, column=0)

# In _poll_updates():
activity_name = snapshot.get("activity_name", "Idle")
self.activity_label.config(text=f"Activity: {activity_name}")
```

**3. Update activities:**
```python
# In activity's start() or run():
if self.ui_interface:
    self.ui_interface.update_activity_name("SmallTalk")
```
