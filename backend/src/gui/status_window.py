"""
Status Window - Simple GUI for displaying mic/speaker status

Uses Tkinter to show real-time status of microphone and speaker.
"""

import tkinter as tk
from tkinter import ttk
import threading
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class StatusWindow:
    """
    Simple Tkinter window showing microphone and speaker status.
    
    Polls UI interface for updates and displays status with color indicators.
    """
    
    def __init__(self, ui_interface, update_interval_ms: int = 100):
        """
        Initialize the status window.
        
        Args:
            ui_interface: UIInterface instance to poll for updates
            update_interval_ms: How often to poll for updates (milliseconds)
        """
        self.ui_interface = ui_interface
        self.update_interval_ms = update_interval_ms
        
        # Create root window
        self.root = tk.Tk()
        self.root.title("Well-Bot Status")
        self.root.geometry("300x150")
        self.root.resizable(False, False)
        
        # Configure window close behavior
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        
        # Status variables
        self.mic_status = tk.StringVar(value="Idle")
        self.speaker_status = tk.StringVar(value="Idle")
        
        # Create UI elements
        self._create_widgets()
        
        # Start polling for updates
        self._poll_updates()
        
        logger.info("Status window initialized")
    
    def _create_widgets(self):
        """Create and layout GUI widgets."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Microphone status
        mic_frame = ttk.Frame(main_frame)
        mic_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(mic_frame, text="Microphone:", font=("Arial", 10, "bold")).grid(row=0, column=0, padx=5)
        self.mic_label = ttk.Label(
            mic_frame, 
            textvariable=self.mic_status,
            font=("Arial", 10),
            foreground="gray"
        )
        self.mic_label.grid(row=0, column=1, padx=5)
        self.mic_indicator = tk.Canvas(mic_frame, width=20, height=20, highlightthickness=0)
        self.mic_indicator.grid(row=0, column=2, padx=5)
        self._update_mic_indicator("idle")
        
        # Speaker status
        speaker_frame = ttk.Frame(main_frame)
        speaker_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(speaker_frame, text="Speaker:", font=("Arial", 10, "bold")).grid(row=0, column=0, padx=5)
        self.speaker_label = ttk.Label(
            speaker_frame,
            textvariable=self.speaker_status,
            font=("Arial", 10),
            foreground="gray"
        )
        self.speaker_label.grid(row=0, column=1, padx=5)
        self.speaker_indicator = tk.Canvas(speaker_frame, width=20, height=20, highlightthickness=0)
        self.speaker_indicator.grid(row=0, column=2, padx=5)
        self._update_speaker_indicator("idle")
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
    
    def _update_mic_indicator(self, status: str):
        """
        Update microphone indicator color.
        
        Args:
            status: "listening" (green), "idle" (gray), "muted" (orange)
        """
        self.mic_indicator.delete("all")
        
        if status == "listening":
            color = "green"
        elif status == "muted":
            color = "orange"
        else:  # idle
            color = "gray"
        
        # Draw circle indicator
        self.mic_indicator.create_oval(2, 2, 18, 18, fill=color, outline="black", width=1)
    
    def _update_speaker_indicator(self, status: str):
        """
        Update speaker indicator color.
        
        Args:
            status: "speaking" (blue), "idle" (gray)
        """
        self.speaker_indicator.delete("all")
        
        if status == "speaking":
            color = "blue"
        else:  # idle
            color = "gray"
        
        # Draw circle indicator
        self.speaker_indicator.create_oval(2, 2, 18, 18, fill=color, outline="black", width=1)
    
    def _poll_updates(self):
        """Poll UI interface for updates and refresh display."""
        try:
            snapshot = self.ui_interface.get_snapshot()
            
            # Update mic status
            mic_status = snapshot.get("mic_status", "idle")
            if mic_status == "listening":
                self.mic_status.set("Listening")
                self.mic_label.config(foreground="green")
            elif mic_status == "muted":
                self.mic_status.set("Muted")
                self.mic_label.config(foreground="orange")
            else:
                self.mic_status.set("Idle")
                self.mic_label.config(foreground="gray")
            self._update_mic_indicator(mic_status)
            
            # Update speaker status
            speaker_status = snapshot.get("speaker_status", "idle")
            if speaker_status == "speaking":
                self.speaker_status.set("Speaking")
                self.speaker_label.config(foreground="blue")
            else:
                self.speaker_status.set("Idle")
                self.speaker_label.config(foreground="gray")
            self._update_speaker_indicator(speaker_status)
            
        except Exception as e:
            logger.error(f"Error polling UI updates: {e}", exc_info=True)
        
        # Schedule next poll
        self.root.after(self.update_interval_ms, self._poll_updates)
    
    def _on_close(self):
        """Handle window close event."""
        logger.info("Status window closed by user")
        self.root.destroy()
    
    def run(self):
        """Start the GUI main loop (blocks until window is closed)."""
        try:
            # Start polling updates
            self._poll_updates()
            # Run mainloop (must be in main thread on Windows)
            self.root.mainloop()
        except Exception as e:
            logger.error(f"Error in GUI mainloop: {e}", exc_info=True)
    
    def update_non_blocking(self):
        """
        Update GUI without blocking (for use in main thread polling).
        Call this periodically from main thread instead of mainloop().
        """
        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception as e:
            # Window might be closed
            if "application has been destroyed" not in str(e).lower():
                logger.error(f"Error updating GUI: {e}", exc_info=True)
    
    def close(self):
        """Close the window programmatically."""
        if self.root:
            self.root.quit()
            self.root.destroy()


def start_gui(ui_interface, update_interval_ms: int = 100) -> Optional[StatusWindow]:
    """
    Create the GUI window (must be called from main thread on Windows).
    
    Note: Tkinter on Windows requires running in the main thread. This function
    creates the window and sets up polling. The caller must periodically call
    window.update_non_blocking() from the main thread, or start a separate
    thread only if not on Windows.
    
    Args:
        ui_interface: UIInterface instance
        update_interval_ms: Polling interval in milliseconds
        
    Returns:
        StatusWindow instance or None if GUI failed to start
    """
    try:
        import sys
        window = StatusWindow(ui_interface, update_interval_ms)
        
        # On Windows, Tkinter must run in main thread
        # Use a separate thread only on non-Windows systems
        if sys.platform == "win32":
            # On Windows, we'll use update_non_blocking() from main thread
            # Start polling in the window
            window._poll_updates()
            logger.info("GUI window created (Windows - use update_non_blocking() in main thread)")
        else:
            # On Linux/Mac, we can use a separate thread
            def run_gui():
                try:
                    window.run()
                except Exception as e:
                    logger.error(f"GUI thread error: {e}", exc_info=True)
            
            gui_thread = threading.Thread(target=run_gui, daemon=True, name="GUI-Thread")
            gui_thread.start()
            logger.info("GUI started in separate thread (non-Windows)")
        
        return window
        
    except Exception as e:
        logger.error(f"Failed to start GUI: {e}", exc_info=True)
        return None

