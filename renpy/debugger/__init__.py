"""
Ren'Py Debugger Module

This module provides debugging capabilities for Ren'Py games, including:
- Breakpoints in .rpy scripts and Python code
- Step debugging (step in, step over, step out)
- Variable inspection
- Stack traces

The debugger uses the Debug Adapter Protocol (DAP) for IDE integration,
allowing debugging from VSCode and other DAP-compatible editors.

Usage:
    Start Ren'Py with --debug flag:
        ./run.sh mygame --debug

    Or enable in code:
        import renpy.debugger
        renpy.debugger.start()

    Then connect from VSCode using a launch.json like:
        {
            "name": "Ren'Py Debug",
            "type": "python",
            "request": "attach",
            "connect": {"host": "localhost", "port": 5678}
        }
"""

from __future__ import annotations

import atexit
from typing import Optional, TYPE_CHECKING

from .core import DebuggerCore
from .dap_server import DAPServer
from .breakpoints import BreakpointManager, Breakpoint
from .variables import VariableInspector

if TYPE_CHECKING:
    import renpy

__all__ = [
    "DebuggerCore",
    "DAPServer",
    "BreakpointManager",
    "Breakpoint",
    "VariableInspector",
    "get_debugger",
    "start",
    "stop",
    "is_running",
]

# Session keys for storing debugger instances across reloads
_SESSION_KEY_DEBUGGER = "_renpy_debugger"
_SESSION_KEY_DAP_SERVER = "_renpy_dap_server"


def _get_session():
    """Get the renpy.session dict, which persists across reloads."""
    import renpy
    return renpy.session


def get_debugger() -> Optional[DebuggerCore]:
    """
    Get the global debugger instance.

    Returns None if the debugger hasn't been started.
    """
    return _get_session().get(_SESSION_KEY_DEBUGGER)


def start(port: int = 5678, wait_for_client: bool = False) -> bool:
    """
    Start the debugger and DAP server.

    If the debugger already exists (e.g., after a script reload),
    this will re-register hooks and return the existing instance.

    Args:
        port: TCP port for the DAP server (default 5678)
        wait_for_client: If True, block until a client connects

    Returns:
        True if the debugger started successfully
    """
    session = _get_session()
    debugger = session.get(_SESSION_KEY_DEBUGGER)
    dap_server = session.get(_SESSION_KEY_DAP_SERVER)

    # Check if we're recovering from a reload
    if debugger is not None and dap_server is not None:
        # Re-register hooks that were cleared during reload
        debugger._on_reload()
        return True

    # Fresh start - create new instances
    debugger = DebuggerCore()
    dap_server = DAPServer(debugger, port=port)

    if not dap_server.start():
        return False

    # Store in session so they survive reloads
    session[_SESSION_KEY_DEBUGGER] = debugger
    session[_SESSION_KEY_DAP_SERVER] = dap_server

    atexit.register(stop)

    if wait_for_client:
        dap_server.wait_for_client()

    return True


def stop() -> None:
    """
    Stop the debugger and DAP server.

    This is called automatically when the game exits via atexit,
    but can also be called manually to stop debugging early.
    """
    session = _get_session()
    dap_server = session.get(_SESSION_KEY_DAP_SERVER)
    debugger = session.get(_SESSION_KEY_DEBUGGER)

    if dap_server:
        dap_server.stop()
        session.pop(_SESSION_KEY_DAP_SERVER, None)

    if debugger:
        debugger.shutdown()
        session.pop(_SESSION_KEY_DEBUGGER, None)


def is_running() -> bool:
    """Check if the debugger is running."""
    session = _get_session()
    return (
        session.get(_SESSION_KEY_DEBUGGER) is not None
        and session.get(_SESSION_KEY_DAP_SERVER) is not None
    )
