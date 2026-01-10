# """
# Status Window - Simple GUI for displaying mic/speaker status 

# Uses Tkinter to show real-time status of microphone and speaker.
# """

# import os
# import tkinter as tk
# from PIL import Image, ImageTk, ImageSequence
# import threading
# import time
# import logging
# from typing import Optional

# logger = logging.getLogger(__name__)

# # Paths to GIF animations (relative to backend/src)
# ASSET_DIR = os.path.join(os.path.dirname(__file__), "../../assets/GUI")
# IDLE_GIF = os.path.join(ASSET_DIR, "gui_idle.gif")
# LISTEN_GIF = os.path.join(ASSET_DIR, "gui_listen.gif")
# SPEAK_GIF = os.path.join(ASSET_DIR, "gui_speak.gif")


# class FaceDisplayWindow:
#     """
#     Fullscreen Tkinter window that displays animated robot face GIFs.

#     States:
#         - idle      → gui_idle.gif
#         - listening → gui_listen.gif
#         - speaking  → gui_speak.gif
#     """

#     def __init__(self, ui_interface, update_interval_ms: int = 100):
#         self.ui_interface = ui_interface
#         self.update_interval_ms = update_interval_ms

#         # Tk window
#         self.root = tk.Tk()
#         self.root.title("Well-Bot Face Display")
#         self.root.attributes("-fullscreen", True)
#         self.root.configure(bg="black")

#         # Screen size
#         self.screen_w = self.root.winfo_screenwidth()
#         self.screen_h = self.root.winfo_screenheight()

#         # Label to show animation frames
#         self.label = tk.Label(self.root, bg="black")
#         self.label.pack(expand=True, fill="both")

#         # Load animation frames
#         self.animations = {
#             "idle": self._load_gif(IDLE_GIF),
#             "listening": self._load_gif(LISTEN_GIF),
#             "speaking": self._load_gif(SPEAK_GIF),
#         }

#         # Set initial state
#         self.current_state = "idle"
#         self.current_frames = self.animations["idle"]

#         # Animation control
#         self._running = True
#         self._frame_index = 0

#         # Start animation thread
#         threading.Thread(target=self._animation_loop, daemon=True).start()

#         # Poll UIInterface
#         self._poll_updates()

#         logger.info("FaceDisplayWindow initialized")

#     ###########################################################################
#     # GIF LOADING
#     ###########################################################################
#     def _load_gif(self, path):
#         """Load a GIF into a list of Tkinter-compatible frames."""
#         frames = []
#         img = Image.open(path)

#         for frame in ImageSequence.Iterator(img):
#             frame = frame.convert("RGBA")
#             frame = frame.resize((self.screen_w, self.screen_h), Image.ANTIALIAS)
#             frames.append(ImageTk.PhotoImage(frame))

#         return frames

#     ###########################################################################
#     # STATE UPDATE FROM BACKEND (MIC/SPEAKER)
#     ###########################################################################
#     def _poll_updates(self):
#         """Poll UIInterface for mic/speaker state and update animation state."""
#         try:
#             snapshot = self.ui_interface.get_snapshot()
#             mic = snapshot.get("mic_status", "idle")
#             speaker = snapshot.get("speaker_status", "idle")

#             new_state = "idle"

#             if speaker == "speaking":
#                 new_state = "speaking"
#             elif mic == "listening":
#                 new_state = "listening"

#             if new_state != self.current_state:
#                 logger.info(f"FaceDisplay switching to state: {new_state}")
#                 self.current_state = new_state
#                 self.current_frames = self.animations[new_state]
#                 self._frame_index = 0  # restart animation

#         except Exception as e:
#             logger.error(f"Error polling UIInterface: {e}", exc_info=True)

#         # Poll every update interval
#         self.root.after(self.update_interval_ms, self._poll_updates)

#     ###########################################################################
#     # ANIMATION LOOP
#     ###########################################################################
#     def _animation_loop(self):
#         """Continuously display GIF frames."""
#         while self._running:
#             try:
#                 frame = self.current_frames[self._frame_index]
#                 self.root.after(0, self._update_frame, frame)

#                 self._frame_index = (self._frame_index + 1) % len(self.current_frames)
#                 time.sleep(0.07)  # ~14 FPS (adjust based on GIF speed)
#             except Exception as e:
#                 logger.error(f"Animation loop error: {e}", exc_info=True)
#                 time.sleep(0.1)

#     def _update_frame(self, frame):
#         self.label.config(image=frame)
#         self.label.image = frame

#     ###########################################################################
#     # WINDOW CONTROL
#     ###########################################################################
#     def run(self):
#         """Run Tkinter main loop."""
#         self.root.mainloop()

#     def stop(self):
#         self._running = False
#         self.root.quit()
#         self.root.destroy()


# ###############################################################################
# # ENTRY POINT FOR APP
# ###############################################################################
# def start_gui(ui_interface, update_interval_ms: int = 100) -> FaceDisplayWindow:
#     """
#     Create and launch the robot face GUI window (for Raspberry Pi display).
#     """
#     try:
#         window = FaceDisplayWindow(ui_interface, update_interval_ms)
#         threading.Thread(target=window.run, daemon=True).start()
#         logger.info("FaceDisplayWindow started")
#         return window
#     except Exception as e:
#         logger.error(f"Failed to start face GUI: {e}", exc_info=True)
#         return None
