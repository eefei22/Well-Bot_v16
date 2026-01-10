import tkinter as tk
from PIL import Image, ImageTk, ImageSequence
import time

# --------------------------
# Load GIF frames into memory
# --------------------------
def load_gif_frames(path):
    gif = Image.open(path)
    frames = []

    for frame in ImageSequence.Iterator(gif):
        frames.append(ImageTk.PhotoImage(frame.copy()))
    return frames


# --------------------------
# Tkinter GUI Class
# --------------------------
class GIFPlayer:
    def __init__(self, root, gif_paths):
        self.root = root
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg="black")

        # Press ESC to exit fullscreen
        self.root.bind("<Escape>", lambda e: self.root.destroy())

        self.label = tk.Label(root, bg="black")
        self.label.pack(expand=True)

        self.gif_paths = gif_paths
        self.gif_sets = [load_gif_frames(p) for p in gif_paths]
        self.current_gif = 0
        self.current_frame = 0

        self.play_gif()

    def play_gif(self):
        frames = self.gif_sets[self.current_gif]
        frame = frames[self.current_frame]

        self.label.config(image=frame)
        self.label.image = frame

        self.current_frame = (self.current_frame + 1) % len(frames)

        # If reached first frame again → move to next GIF
        if self.current_frame == 0:
            self.current_gif = (self.current_gif + 1) % len(self.gif_sets)

        # Play at 30ms per frame (~33 FPS)
        self.root.after(83, self.play_gif)


# --------------------------
# MAIN
# --------------------------
if __name__ == "__main__":
    # Put your GIF paths here
    gif_list = [
        "gui_idle.gif",
        "gui_listen.gif",
        "gui_speak.gif"
    ]

    root = tk.Tk()
    player = GIFPlayer(root, gif_list)
    root.mainloop()
