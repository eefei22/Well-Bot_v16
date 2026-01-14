"""
Face Animation Window - Optimized with Preloading & Latency Buffering
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageSequence
import threading
import logging
from pathlib import Path
from typing import Optional, Dict, List, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 1. NEW HELPER: Preload raw PIL images
# ---------------------------------------------------------
def preload_gif_data(gif_paths: Dict[str, str]) -> Dict[str, List[Image.Image]]:
    """
    Reads GIF files and decompresses them into PIL Image objects.
    """
    preloaded_cache = {}
    
    backend_dir = Path(__file__).parent.parent.parent
    default_asset_dir = backend_dir / "assets" / "GUI"

    for name, path_str in gif_paths.items():
        try:
            p = Path(path_str)
            if not p.is_absolute():
                p = (default_asset_dir / p).resolve()
            
            gif = Image.open(str(p))
            frames = []
            for frame in ImageSequence.Iterator(gif):
                frames.append(frame.copy())
            
            preloaded_cache[name] = frames
            logger.info(f"Preloaded {len(frames)} frames for '{name}' into memory.")
            
        except Exception as e:
            logger.error(f"Failed to preload GIF {path_str}: {e}")
            preloaded_cache[name] = []
            
    return preloaded_cache


class FaceAnimationWindow:
    """
    Tkinter fullscreen animation window.
    """

    def __init__(self, ui_interface, gif_source: Union[Dict[str, str], Dict[str, List]], update_interval_ms=83):
        self.ui_interface = ui_interface
        self.update_interval_ms = update_interval_ms

        # Keep a reference to the original gif source and whether it's preloaded.
        # This allows on-demand synchronous loading of a state (e.g. speaking)
        # if the background loader hasn't finished yet.
        self._gif_source = gif_source
        self._is_preloaded = False

        # Tkinter setup
        self.root = tk.Tk()
        self.root.title("Well-Bot Face Display")
        
        # --- FEATURE: Toggle Fullscreen ---
        self.is_fullscreen = True
        self.root.attributes("-fullscreen", self.is_fullscreen)
        self.root.configure(bg="black")
        
        # Bind Escape to TOGGLE size instead of closing
        self.root.bind("<Escape>", lambda e: self.toggle_fullscreen())
        # Bind Control-Q to actually close
        self.root.bind("<Control-q>", lambda e: self._on_close())

        # Display label
        self.label = tk.Label(self.root, bg="black")
        self.label.pack(expand=True, fill="both")

        # Animation state
        self.current_state = "idle"
        self.requested_state = "idle"
        self.frame_index = 0
        self.gif_frames: Dict[str, list] = {}

        self._ready_event = threading.Event()

        # Start prioritized loading (idle first, others in background)
        self.root.after(10, lambda: self._load_assets_and_start(self._gif_source))

        logger.info("FaceAnimationWindow initialized")

    def toggle_fullscreen(self):
        """Switches between Fullscreen and a small window."""
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)
        if not self.is_fullscreen:
            # Set a small size when not fullscreen so you can see the terminal
            self.root.geometry("800x480")

    def _load_assets_and_start(self, gif_source):
        """
        Optimized Loader: 
        1. Loads 'idle' state immediately to unblock window.
        2. Loads other states in background.
        """
        if not gif_source:
            backend_dir = Path(__file__).parent.parent.parent
            default_asset_dir = backend_dir / "assets" / "GUI"
            gif_source = {
                "idle": str(default_asset_dir / "gui_idleing.gif"),
                "listening": str(default_asset_dir / "gui_listening.gif"),
                "speaking": str(default_asset_dir / "gui_speaking.gif"),
                "loading": str(default_asset_dir / "gui_loading.gif"),
                "gratitude": str(default_asset_dir / "gui_gratitude.gif"),
            }

        # Keep a reference for on-demand loading
        self._gif_source = gif_source

        first_value = next(iter(gif_source.values())) if gif_source else None
        is_preloaded = isinstance(first_value, list)
        # record preloaded flag for later on-demand conversions
        self._is_preloaded = is_preloaded

        # 1. IMMEDIATE LOAD: idle
        if "idle" in gif_source:
            if is_preloaded:
                self.gif_frames["idle"] = [ImageTk.PhotoImage(image=img, master=self.root) for img in gif_source["idle"]]
            else:
                self.gif_frames["idle"] = self._load_frames_from_disk(gif_source["idle"])
        else:
            empty_img = ImageTk.PhotoImage(Image.new('RGB', (100, 100), 'black'), master=self.root)
            self.gif_frames["idle"] = [empty_img]

        # Start Animation Loop immediately with idle
        self.current_frame_list = self.gif_frames.get("idle", [])
        self._poll_state()
        self._play_frame()

        # 2. BACKGROUND LOAD: remaining states
        remaining_keys = [k for k in gif_source.keys() if k != "idle"]
        self.root.after(100, lambda: self._background_loader(remaining_keys, gif_source, is_preloaded))



    def _background_loader(self, keys, source, is_preloaded):
        if not keys:
            return

        key = keys.pop(0)
        try:
            if is_preloaded:
                # FIX 3: Add master=self.root
                self.gif_frames[key] = [
                    ImageTk.PhotoImage(image=img, master=self.root) 
                    for img in source[key]
                ]
            else:
                self.gif_frames[key] = self._load_frames_from_disk(source[key])
        except Exception as e:
            logger.error(f"Background load failed for {key}: {e}")

        self.root.after(50, lambda: self._background_loader(keys, source, is_preloaded))

    def _ensure_state_loaded(self, state: str):
        """Synchronously load frames for a specific state if not already loaded."""
        if state in self.gif_frames:
            return

        source = self._gif_source
        if not source or state not in source:
            return

        try:
            if self._is_preloaded:
                # FIX 4: Add master=self.root
                self.gif_frames[state] = [
                    ImageTk.PhotoImage(image=img, master=self.root) 
                    for img in source[state]
                ]
            else:
                self.gif_frames[state] = self._load_frames_from_disk(source[state])
            logger.info(f"Synchronously loaded frames for state '{state}'")
        except Exception as e:
            logger.error(f"Failed to synchronously load state '{state}': {e}")

    def _load_frames_from_disk(self, path):
        try:
            gif = Image.open(path)
            frames = []
            for frame in ImageSequence.Iterator(gif):
                # FIX 5: Add master=self.root
                frames.append(ImageTk.PhotoImage(image=frame.copy(), master=self.root))
            return frames
        except Exception:
            return []

    def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        return self._ready_event.wait(timeout)

    def _poll_state(self):
        try:
            snapshot = self.ui_interface.get_snapshot()
            new_state = snapshot.get("face_state")
            if not new_state:
                loading = snapshot.get("loading_status", "idle")
                speaker = snapshot.get("speaker_status", "idle")
                mic = snapshot.get("mic_status", "idle")
                
                if loading == "loading": new_state = "loading"
                elif speaker == "speaking": new_state = "speaking"
                elif mic == "listening": new_state = "listening"
                else: new_state = "idle"

            # If the desired state isn't loaded yet, attempt an on-demand load
            if new_state not in self.gif_frames:
                try:
                    self._ensure_state_loaded(new_state)
                except Exception:
                    pass

            if new_state in self.gif_frames:
                if new_state != self.requested_state:
                    self.requested_state = new_state
        except Exception:
            pass
        self.root.after(100, self._poll_state)

    def _play_frame(self):
        """
        Play next frame. 
        CRITICAL FIX: Logic priority changed to prevent 'idle' glitch.
        """
        try:
            if not self.current_frame_list:
                return

            frame = self.current_frame_list[self.frame_index]
            self.label.config(image=frame)
            self.label.image = frame
            self.frame_index += 1

            if not self._ready_event.is_set():
                self._ready_event.set()

            # Loop Finished
            if self.frame_index >= len(self.current_frame_list):
                self.frame_index = 0
                
                # -------------------------------------------------------------
                # LOGIC FIX: Determine Next State
                # -------------------------------------------------------------
                next_state = self.requested_state

                # [INTERCEPT]
                # If we are currently active (speaking/listening) and the backend 
                # momentarily reports "idle", DO NOT go to idle. Go to "loading".
                # This buffers the gap.
                if (self.current_state in ("speaking", "listening") 
                    and next_state == "idle" 
                    and "loading" in self.gif_frames):
                    
                    next_state = "loading" 
                    # Note: We do NOT update self.requested_state. We just override
                    # the local decision. This ensures that if the backend stays 
                    # idle for long enough, the NEXT loop (of the loading gif) 
                    # will eventually fall through to idle.

                # Apply the transition
                if next_state != self.current_state and next_state in self.gif_frames:
                    self.current_state = next_state
                    self.current_frame_list = self.gif_frames[self.current_state]

        except Exception as e:
            logger.error(f"Animation error: {e}")

        self.root.after(self.update_interval_ms, self._play_frame)

    def _on_close(self):
        self.root.destroy()
    
    def run(self):
        self.root.mainloop()
    
    def update_non_blocking(self):
        """
        Process pending GUI events without blocking (for Windows main thread).
        This allows the GUI to remain responsive when not running in mainloop().
        """
        try:
            if self.root:
                self.root.update()
        except Exception as e:
            logger.error(f"Error updating GUI: {e}")
            raise  # Re-raise so main.py can handle cleanup


def start_gui(ui_interface, gif_source_or_interval=None, update_interval_ms=83, wait_for_ready_seconds: float = 1.0):
    import sys
    gif_source = None
    if isinstance(gif_source_or_interval, dict):
        gif_source = gif_source_or_interval
    elif isinstance(gif_source_or_interval, int):
        update_interval_ms = gif_source_or_interval

    if sys.platform == "win32":
        return FaceAnimationWindow(ui_interface, gif_source, update_interval_ms)

    created_event = threading.Event()
    container = {"window": None}

    def run_gui():
        try:
            win = FaceAnimationWindow(ui_interface, gif_source, update_interval_ms)
            container["window"] = win
            created_event.set()
            win.run()
        except Exception as e:
            logger.error(f"GUI Thread failed: {e}")

    t = threading.Thread(target=run_gui, daemon=True, name="Face-GUI-Thread")
    t.start()

    if created_event.wait(timeout=wait_for_ready_seconds):
        return container.get("window")
    return None