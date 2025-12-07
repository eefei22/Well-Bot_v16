Breakdown of changes by file:

## File-by-file breakdown

### 1. `main.py` — Orchestrator integration

**Changes made:**

**A. Added GUI imports (lines 43-45)**
```python
# GUI imports
from src.components.ui_interface import UIInterface, NoOpUIInterface
from src.gui import start_gui
```
- Purpose: Import UI components for GUI support

**B. Added UI interface attributes (lines 102-104)**
```python
# UI interface (for GUI updates)
self.ui_interface = None
self._gui_window = None
```
- Purpose: Store UI interface and GUI window references

**C. Added `_initialize_ui()` method (lines 191-207)**
```python
def _initialize_ui(self):
    """Initialize UI interface based on configuration."""
    try:
        gui_config = self.global_config.get("gui", {})
        gui_enabled = gui_config.get("enabled", False)
        
        if gui_enabled:
            logger.info("Initializing UI interface for GUI...")
            self.ui_interface = UIInterface()
            logger.info("✓ UI interface initialized")
        else:
            logger.info("GUI disabled - using NoOp UI interface")
            self.ui_interface = NoOpUIInterface()
    except Exception as e:
        logger.warning(f"Failed to initialize UI interface: {e}")
        logger.warning("Falling back to NoOp UI interface")
        self.ui_interface = NoOpUIInterface()
```
- Purpose: Create UI interface based on config; use NoOp when disabled

**D. Added `_start_gui_if_enabled()` method (lines 209-227)**
```python
def _start_gui_if_enabled(self):
    """Start GUI window if enabled in configuration."""
    try:
        gui_config = self.global_config.get("gui", {})
        gui_enabled = gui_config.get("enabled", False)
        update_interval_ms = gui_config.get("update_interval_ms", 100)
        
        if gui_enabled and self.ui_interface and not isinstance(self.ui_interface, NoOpUIInterface):
            logger.info("Starting GUI window...")
            self._gui_window = start_gui(self.ui_interface, update_interval_ms)
            if self._gui_window:
                logger.info("✓ GUI window started")
            else:
                logger.warning("GUI window failed to start, continuing without GUI")
        else:
            logger.debug("GUI not enabled or NoOp interface in use")
    except Exception as e:
        logger.warning(f"Failed to start GUI: {e}")
        logger.warning("Continuing without GUI")
```
- Purpose: Start GUI window if enabled; handle failures gracefully

**E. Call UI initialization (line 181)**
```python
# Initialize UI interface
self._initialize_ui()
```
- Purpose: Initialize UI during component setup

**F. Call GUI startup (line 935)**
```python
# Start GUI if enabled
self._start_gui_if_enabled()
```
- Purpose: Start GUI after system is ready

**G. Pass `ui_interface` to SmallTalk activity (lines 338-342)**
```python
self.smalltalk_activity = SmallTalkActivity(
    backend_dir=self.backend_dir, 
    user_id=self.user_id,
    ui_interface=self.ui_interface  # NEW: Pass UI interface
)
```
- Purpose: Provide UI interface to SmallTalk activity

**H. Added GUI update loop in `main()` (lines 1046-1063)**
```python
# On Windows, update GUI periodically in main thread
import sys
gui_update_interval = 0.05  # 50ms for smooth GUI updates
last_gui_update = time.time()

while orchestrator.is_active():
    # Update GUI if on Windows and GUI exists
    if sys.platform == "win32" and orchestrator._gui_window:
        current_time = time.time()
        if current_time - last_gui_update >= gui_update_interval:
            try:
                orchestrator._gui_window.update_non_blocking()
                last_gui_update = current_time
            except Exception as e:
                # GUI might be closed
                if "application has been destroyed" not in str(e).lower():
                    logger.debug(f"GUI update error: {e}")
                orchestrator._gui_window = None
    
    time.sleep(0.1)  # Smaller sleep for more responsive GUI updates
```
- Purpose: Update GUI on Windows from the main thread (Tkinter requirement)

---

### 2. `smalltalk.py` — Activity integration

**Changes made:**

**A. Added `ui_interface` parameter to `__init__()` (line 58)**
```python
def __init__(self, backend_dir: Path, user_id: Optional[str] = None, ui_interface = None):
    """Initialize the SmallTalk activity"""
    self.backend_dir = backend_dir
    self.user_id = user_id or get_current_user_id()
    self.ui_interface = ui_interface  # NEW: Store UI interface
```
- Purpose: Accept and store UI interface for later use

**B. Pass `ui_interface` to ConversationAudioManager (line 127)**
```python
self.audio_manager = ConversationAudioManager(
    stt_service=self.stt_service,
    mic_factory=mic_factory,
    audio_config=audio_config,
    ui_interface=self.ui_interface  # NEW: Pass UI interface
)
```
- Purpose: Forward UI interface to audio manager so it can report mic/speaker status

---

### 3. `conversation_audio_manager.py` — Audio I/O status reporting

**Changes made:**

**A. Added `ui_interface` parameter to `__init__()` (line 45)**
```python
def __init__(
    self,
    stt_service,
    mic_factory: Callable,
    audio_config: dict,
    sample_rate: int = 24000,
    sample_width_bytes: int = 2,
    num_channels: int = 1,
    ui_interface = None  # NEW: Optional UI interface parameter
):
```
- Purpose: Accept UI interface for status updates

**B. Store UI interface (line 61)**
```python
self.stt = stt_service
self.mic_factory = mic_factory
self.ui_interface = ui_interface  # NEW: Store for later use
```
- Purpose: Keep reference for status updates

**C. Update mic status when listening starts (lines 126-128)**
```python
mic.start()

# Update UI: mic is now listening
if self.ui_interface:
    self.ui_interface.update_mic_status("listening")
```
- Purpose: Report mic listening state to GUI

**D. Update mic status when listening stops (lines 198-200)**
```python
mic.stop()

# Update UI: mic is now idle
if self.ui_interface:
    self.ui_interface.update_mic_status("idle")
```
- Purpose: Report mic idle state to GUI

**E. Update speaker status when TTS starts (lines 382-384)**
```python
self._set_playback_state(True)

# Update UI: speaker is now speaking
if self.ui_interface:
    self.ui_interface.update_speaker_status("speaking")
```
- Purpose: Report speaker active state during TTS

**F. Update speaker status when TTS ends (lines 396-398)**
```python
self._set_playback_state(False)

# Update UI: speaker is now idle
if self.ui_interface:
    self.ui_interface.update_speaker_status("idle")
```
- Purpose: Report speaker idle state after TTS

**G. Update speaker status for audio file playback (lines 309-311, 347-349)**
```python
# At start of play_audio_file():
# Update UI: speaker is now speaking
if self.ui_interface:
    self.ui_interface.update_speaker_status("speaking")

# At end of play_audio_file():
# Update UI: speaker is now idle
if self.ui_interface:
    self.ui_interface.update_speaker_status("idle")
```
- Purpose: Report speaker status for audio file playback

---

### 4. `ui_interface.py` — New file: UI event bus

**Purpose:** Thread-safe event bus for GUI updates

**Key components:**

**A. UIInterface class (lines 15-108)**
- Thread-safe state storage using locks
- State dictionary with `mic_status` and `speaker_status`
- Update methods: `update_mic_status()`, `update_speaker_status()`
- Snapshot method: `get_snapshot()` for polling
- Listener pattern: `register_listener()`, `unregister_listener()`

**B. NoOpUIInterface class (lines 111-137)**
- Stub implementation when GUI is disabled
- All methods are no-ops
- Allows components to call UI methods without null checks

**Design pattern:**
- Components update state via methods
- GUI polls via `get_snapshot()`
- Thread-safe with locks
- Optional via NoOp implementation

---

### 5. `status_window.py` — New file: Tkinter GUI window

**Purpose:** Visual display of mic/speaker status

**Key components:**

**A. StatusWindow class (lines 16-200)**
- Tkinter window with status indicators
- Two status displays: Microphone and Speaker
- Color-coded indicators: Green (listening), Blue (speaking), Gray (idle)

**B. Widget creation (lines 55-96)**
- Labels for "Microphone:" and "Speaker:"
- Status text labels (Listening/Idle)
- Canvas indicators (colored circles)

**C. Polling mechanism (lines 134-166)**
```python
def _poll_updates(self):
    """Poll UI interface for updates and refresh display."""
    snapshot = self.ui_interface.get_snapshot()
    
    # Update mic status display
    mic_status = snapshot.get("mic_status", "idle")
    # ... update widgets ...
    
    # Schedule next poll
    self.root.after(self.update_interval_ms, self._poll_updates)
```
- Purpose: Poll UI interface and update display

**D. Windows compatibility (lines 183-194, 203-246)**
- `update_non_blocking()` for Windows main-thread updates
- Platform detection for threading strategy
- On Windows: create window in main thread, update via `update_non_blocking()`
- On Linux/Mac: can run in separate thread

---

## Summary: change flow

```
1. main.py initializes UI interface
   ↓
2. main.py starts GUI window (if enabled)
   ↓
3. main.py passes ui_interface to SmallTalk activity
   ↓
4. SmallTalk activity passes ui_interface to ConversationAudioManager
   ↓
5. ConversationAudioManager calls ui_interface.update_*() when mic/speaker state changes
   ↓
6. UIInterface stores state (thread-safe)
   ↓
7. StatusWindow polls UIInterface.get_snapshot() and updates display
   ↓
8. main.py calls window.update_non_blocking() periodically (Windows)
```

## Design principles

1. Separation of concerns: UI logic separate from business logic
2. Optional GUI: NoOp implementation when disabled
3. Thread safety: Locks in UIInterface
4. Platform awareness: Windows main-thread handling
5. Graceful degradation: App continues if GUI fails
6. Extensibility: Easy to add more status fields

This architecture supports adding more activities and GUI features without major refactoring.