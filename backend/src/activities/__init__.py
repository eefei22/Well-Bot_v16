"""
Activities Module

This module contains standalone activity components that can be called from main.py.
Each activity is a self-contained component with its own configuration and lifecycle.
"""

from .smalltalk import SmallTalkActivity
from .journal import JournalActivity
from .idle_mode import IdleModeActivity

__all__ = ['SmallTalkActivity', 'JournalActivity', 'IdleModeActivity']


