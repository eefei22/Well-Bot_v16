"""
GUI Package

Provides GUI components for displaying system status.
"""

from .face_animation_window import FaceAnimationWindow, start_gui

__all__ = ['FaceAnimationWindow', 'start_gui']

# Note: Don't bind to self.root at module import time — the instance (self) is not defined here.
# If you want an Escape key to close the window, add the binding inside FaceAnimationWindow, e.g.:
#     self.root.bind("<Escape>", lambda e: self.root.destroy())
# or perform the binding in start_gui after creating the window instance.


