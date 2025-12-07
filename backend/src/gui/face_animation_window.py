"""
Face Animation Window - Tkinter GUI with loop-safe state switching.
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageSequence
import threading
import logging
import os
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def load_gif_frames(path):
    """Load GIF frames into ImageTk format."""
    try:
        gif = Image.open(path)
        frames = []
        for frame in ImageSequence.Iterator(gif):
            try:
                img = frame.copy()
                frames.append(ImageTk.PhotoImage(img))
            except Exception:
                # skip problematic frames but continue loading
                continue
        return frames
    except Exception as e:
        logger.error(f"Failed to load GIF {path}: {e}")
        return []


class FaceAnimationWindow:
    """
    Tkinter fullscreen animation window for idle/listening/speaking faces.

    NEW FEATURE:
    -------------------------------------
    ✔ GIF loops fully in its current state
    ✔ State changes are only applied after completing 1 full GIF loop
    -------------------------------------
    """

    def __init__(self, ui_interface, gif_paths: Optional[Dict[str, str]] = None, update_interval_ms=83):
        self.ui_interface = ui_interface
        self.update_interval_ms = update_interval_ms

        # Tkinter setup
        self.root = tk.Tk()
        self.root.title("Well-Bot Face Display")
        # self.root.attributes("-fullscreen", True)
        self.root.geometry("480x320")
        self.root.configure(bg="black")
        self.root.bind("<Escape>", lambda e: self._on_close())

        # Display label
        self.label = tk.Label(self.root, bg="black")
        self.label.pack(expand=True, fill="both")

        # Resolve backend asset directory and default GIF paths
        backend_dir = Path(__file__).parent.parent.parent
        default_asset_dir = backend_dir / "assets" / "GUI"

        DEFAULT_GIFS = {
            "idle": str(default_asset_dir / "gui_idle.gif"),
            "listening": str(default_asset_dir / "gui_listen.gif"),
            "speaking": str(default_asset_dir / "gui_speak.gif"),
            "loading": str(default_asset_dir / "gui_loading.gif"),
        }

        if not gif_paths:
            gif_paths = DEFAULT_GIFS

        # Load GIFs (resolve relative paths against the default asset dir)
        self.gif_frames: Dict[str, list] = {}
        for name, path in gif_paths.items():
            try:
                p = Path(path)
                if not p.is_absolute():
                    # allow passing just filenames or paths relative to assets/GUI
                    p = (default_asset_dir / p).resolve()
                frames = load_gif_frames(str(p))
                if frames:
                    logger.info(f"Loaded {len(frames)} frames for state '{name}' from {p}")
                else:
                    logger.warning(f"GIF for state '{name}' failed to load from {p}")
                self.gif_frames[name] = frames
            except Exception as e:
                logger.error(f"Error loading GIF '{name}' from '{path}': {e}")
                self.gif_frames[name] = []

        # Diagnostic info: check asset directory and available GIFs
        try:
            logger.debug(f"Default asset dir: {default_asset_dir} (exists={default_asset_dir.exists()})")
            if default_asset_dir.exists():
                available = [p.name for p in default_asset_dir.glob('*.gif')]
                logger.debug(f"GIFs found in asset dir: {available}")
        except Exception:
            pass

        # Safer check for idle frames (avoid KeyError). If idle frames missing, log error and keep running
        if not self.gif_frames.get("idle"):
            logger.error("Idle GIF failed to load — animation cannot start! Ensure GUI GIFs are present under backend/assets/GUI or pass gif_paths to start_gui()")

        # Animation state
        self.current_state = "idle"         # name of current GIF
        self.requested_state = "idle"       # next state requested by UIInterface
        self.frame_index = 0
        self.current_frame_list = self.gif_frames.get("idle", [])

        # Poll UI for updates
        self._poll_state()

        # Start animation loop
        self._play_frame()

        logger.info("FaceAnimationWindow initialized (loop-safe mode)")

    # -----------------------------------------------------
    # POLL UI STATE
    # -----------------------------------------------------
    def _poll_state(self):
        """Poll UIInterface for requested state changes."""
        try:
            snapshot = self.ui_interface.get_snapshot()

            # Backwards-compatible mapping:
            # - Prefer an explicit 'face_state' if provided by UI
            # - Otherwise derive from speaker_status / mic_status / loading_status
            new_state = snapshot.get("face_state")
            if not new_state:
                loading = snapshot.get("loading_status", "idle")
                speaker = snapshot.get("speaker_status", "idle")
                mic = snapshot.get("mic_status", "idle")

                if loading == "loading":
                    new_state = "loading"
                elif speaker == "speaking":
                    new_state = "speaking"
                elif mic == "listening":
                    new_state = "listening"
                else:
                    new_state = "idle"

            if new_state in self.gif_frames:
                if new_state != self.requested_state:
                    logger.info(f"State change requested: {self.requested_state} → {new_state}")
                    self.requested_state = new_state
            else:
                logger.warning(f"Unknown face state requested: {new_state}")

        except Exception as e:
            logger.error(f"Error polling UIInterface: {e}")

        # Poll reliably every 100 ms
        self.root.after(100, self._poll_state)


    # -----------------------------------------------------
    # ANIMATION LOOP (frame-level control)
    # -----------------------------------------------------
    def _play_frame(self):
        """Play next frame with loop-safe switching and idle fallback."""
        try:
            frames = self.current_frame_list
            if not frames:
                return

            frame = frames[self.frame_index]
            self.label.config(image=frame)
            self.label.image = frame

            self.frame_index += 1

            # Loop finished
            if self.frame_index >= len(frames):
                self.frame_index = 0  # restart

                # Decide next state after completing the current GIF loop.
                # If a different requested_state is present, switch to it.
                # Otherwise, loop the current state indefinitely.
                # This ensures:
                # - Speaking stays speaking while activity is speaking
                # - Listening stays listening while activity is listening
                # - Only returns to idle when explicitly requested
                if self.requested_state != self.current_state and self.requested_state in self.gif_frames:
                    # Normal requested-state transition
                    logger.info(f"Switching to requested state: {self.current_state} → {self.requested_state}")
                    self.current_state = self.requested_state
                    self.current_frame_list = self.gif_frames[self.current_state]
                else:
                    # No direct change requested. Handle a common edge case:
                    # when the backend briefly reports 'idle' between speaking/listening
                    # transitions, we prefer to show a 'loading' animation (if available)
                    # so the face doesn't flash back to idle. Only apply this when
                    # we're currently in a temporary active state.
                    if (
                        self.current_state in ("listening", "speaking")
                        and self.requested_state == "idle"
                        and "loading" in self.gif_frames
                    ):
                        logger.info(
                            f"Interpreting transient idle as loading: {self.current_state} → loading"
                        )
                        self.current_state = "loading"
                        self.current_frame_list = self.gif_frames.get("loading", [])
                        # keep requested_state as-is; next poll will update if real idle
                    # else: continue looping current state (speaking/listening continue)

        except Exception as e:
            logger.error(f"GIF frame error: {e}", exc_info=True)

        self.root.after(self.update_interval_ms, self._play_frame)


    # -----------------------------------------------------
    # WINDOW CONTROL
    # -----------------------------------------------------
    def _on_close(self):
        logger.info("Face animation window closed")
        self.root.destroy()

    def run(self):
        self.root.mainloop()

    def close(self):
        self._on_close()


# ---------------------------------------------------------
# Same start_gui() structure as StatusWindow
# ---------------------------------------------------------
def start_gui(ui_interface, gif_paths_or_update_interval=None, update_interval_ms=83) -> Optional[FaceAnimationWindow]:
    try:
        import sys

        # Backwards-compatible parameter handling:
        # - If caller passes a dict as second arg, treat it as gif_paths
        # - If caller passes an int as second arg, treat it as update_interval_ms
        gif_paths = None
        if isinstance(gif_paths_or_update_interval, dict):
            gif_paths = gif_paths_or_update_interval
        elif isinstance(gif_paths_or_update_interval, int):
            update_interval_ms = gif_paths_or_update_interval

        # On Windows we must create and run Tk in the main thread
        if sys.platform == "win32":
            window = FaceAnimationWindow(ui_interface, gif_paths, update_interval_ms)
            return window

        # On non-Windows (e.g., Linux) create the Tk window inside the GUI thread
        created_event = threading.Event()
        container = {"window": None}

        def run_gui():
            try:
                win = FaceAnimationWindow(ui_interface, gif_paths, update_interval_ms)
                container["window"] = win
                # signal that window was created
                created_event.set()
                win.run()
            except Exception as e:
                logger.error(f"Face animation GUI error: {e}")

        t = threading.Thread(target=run_gui, daemon=True, name="Face-GUI-Thread")
        t.start()

        # Wait briefly for window to be created so caller can get a reference if available
        if created_event.wait(timeout=1.0):
            return container.get("window")
        else:
            # Window not ready yet; return None (GUI runs in background)
            return None

    except Exception as e:
        logger.error(f"Failed to start face animation GUI: {e}")
        return None
