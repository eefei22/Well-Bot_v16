"""
UI Interface - Event bus for GUI updates

This module provides a thread-safe interface for components to report state changes
to the GUI without directly coupling to GUI implementation.
"""

import threading
import logging
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)


class UIInterface:
    """
    Thread-safe UI event bus for reporting state changes to GUI.
    
    Components call update methods from any thread, and the GUI polls
    for state changes in the main thread.
    """
    
    def __init__(self):
        """Initialize the UI interface with empty state."""
        self._lock = threading.Lock()
        self._state: Dict[str, Any] = {
            "mic_status": "idle",      # "listening", "idle", "muted"
            "speaker_status": "idle"   # "speaking", "idle"
        }
        self._listeners: list[Callable] = []
        
        logger.info("UIInterface initialized")
    
    def update_mic_status(self, status: str):
        """
        Update microphone status.
        
        Args:
            status: "listening", "idle", or "muted"
        """
        with self._lock:
            old_status = self._state.get("mic_status")
            self._state["mic_status"] = status
            if old_status != status:
                logger.debug(f"Mic status updated: {old_status} -> {status}")
        
        self._notify_listeners()
    
    def update_speaker_status(self, status: str):
        """
        Update speaker status.
        
        Args:
            status: "speaking" or "idle"
        """
        with self._lock:
            old_status = self._state.get("speaker_status")
            self._state["speaker_status"] = status
            if old_status != status:
                logger.debug(f"Speaker status updated: {old_status} -> {status}")
        
        self._notify_listeners()
    
    def get_snapshot(self) -> Dict[str, Any]:
        """
        Get a snapshot of current UI state.
        
        Returns:
            Dictionary with current state (thread-safe copy)
        """
        with self._lock:
            return self._state.copy()
    
    def register_listener(self, callback: Callable):
        """
        Register a callback to be notified of state changes.
        
        Args:
            callback: Function to call when state changes
        """
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
                logger.debug("Listener registered")
    
    def unregister_listener(self, callback: Callable):
        """
        Unregister a callback.
        
        Args:
            callback: Function to remove from listeners
        """
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)
                logger.debug("Listener unregistered")
    
    def _notify_listeners(self):
        """Notify all registered listeners of state changes."""
        # Get snapshot for listeners (outside lock to avoid deadlock)
        snapshot = self.get_snapshot()
        
        # Call listeners (they should handle exceptions)
        for listener in self._listeners[:]:  # Copy list to avoid modification during iteration
            try:
                listener(snapshot)
            except Exception as e:
                logger.error(f"Error in UI listener callback: {e}", exc_info=True)


class NoOpUIInterface:
    """
    No-operation implementation of UIInterface.
    
    Used when GUI is disabled - all methods do nothing.
    This allows components to call UI methods without checking if GUI exists.
    """
    
    def update_mic_status(self, status: str):
        """No-op: do nothing."""
        pass
    
    def update_speaker_status(self, status: str):
        """No-op: do nothing."""
        pass
    
    def get_snapshot(self) -> Dict[str, Any]:
        """No-op: return empty state."""
        return {"mic_status": "idle", "speaker_status": "idle"}
    
    def register_listener(self, callback: Callable):
        """No-op: do nothing."""
        pass
    
    def unregister_listener(self, callback: Callable):
        """No-op: do nothing."""
        pass

