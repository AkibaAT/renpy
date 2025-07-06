# Copyright 2004-2024 Tom Rothamel <pytom@bishoujo.us>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
Automated Testing Interface for Ren'Py

This module provides comprehensive programmatic access to Ren'Py's internal
state and controls for automated testing purposes.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy

# Import all testing components
from . import interface
from . import state_inspector
from . import state_manager
from . import game_controller
from . import headless
from . import cli
from . import http_server
from . import debugger

# Main testing interface instance
_testing_interface = None

def get_testing_interface():
    """
    Get the global testing interface instance.
    
    Returns:
        TestingInterface: The global testing interface instance
    """
    global _testing_interface
    if _testing_interface is None:
        _testing_interface = interface.TestingInterface()
    return _testing_interface

# Convenience functions for direct access
def inspect_state():
    """Get current game state information."""
    return get_testing_interface().inspect_state()

def save_state(slot=None):
    """Save current game state."""
    return get_testing_interface().save_state(slot)

def load_state(slot):
    """Load game state from slot."""
    return get_testing_interface().load_state(slot)

def advance_dialogue():
    """Advance to next dialogue/statement."""
    return get_testing_interface().advance_dialogue()

def rollback(steps=1):
    """Roll back the specified number of steps."""
    return get_testing_interface().rollback(steps)

def select_choice(choice):
    """Select a menu choice by index or text."""
    return get_testing_interface().select_choice(choice)

def get_choices():
    """Get available menu choices."""
    return get_testing_interface().get_choices()

def get_current_label():
    """Get the current label/scene."""
    return get_testing_interface().get_current_label()

def get_variables():
    """Get current game variables."""
    return get_testing_interface().get_variables()

def set_variable(name, value):
    """Set a game variable."""
    return get_testing_interface().set_variable(name, value)

def is_headless():
    """Check if running in headless mode."""
    return headless.is_headless()

def enable_headless():
    """Enable headless mode."""
    return headless.enable_headless()

def disable_headless():
    """Disable headless mode."""
    return headless.disable_headless()

def start_http_server(host='localhost', port=8080):
    """Start the HTTP API server."""
    return get_testing_interface().start_http_server(host, port)

def stop_http_server():
    """Stop the HTTP API server."""
    return get_testing_interface().stop_http_server()

def is_http_server_running():
    """Check if HTTP API server is running."""
    return get_testing_interface().is_http_server_running()

def get_http_server_url():
    """Get the HTTP API server URL."""
    return get_testing_interface().get_http_server_url()

# Debugging and Breakpoint Functions
def enable_debug_mode():
    """Enable debug mode for breakpoint functionality."""
    return get_testing_interface().enable_debug_mode()

def disable_debug_mode():
    """Disable debug mode."""
    return get_testing_interface().disable_debug_mode()

def is_debug_mode():
    """Check if debug mode is enabled."""
    return get_testing_interface().is_debug_mode()

def is_paused():
    """Check if execution is paused at a breakpoint."""
    return get_testing_interface().is_paused()

def set_breakpoint(filename, line, condition=None):
    """Set a breakpoint at the specified location."""
    return get_testing_interface().set_breakpoint(filename, line, condition)

def clear_breakpoint(filename, line):
    """Clear a breakpoint at the specified location."""
    return get_testing_interface().clear_breakpoint(filename, line)

def clear_all_breakpoints(filename=None):
    """Clear all breakpoints, optionally for a specific file."""
    return get_testing_interface().clear_all_breakpoints(filename)

def list_breakpoints():
    """Get a list of all current breakpoints."""
    return get_testing_interface().list_breakpoints()

def enable_breakpoint(filename, line, enabled=True):
    """Enable or disable a specific breakpoint."""
    return get_testing_interface().enable_breakpoint(filename, line, enabled)

def continue_execution():
    """Continue execution from a paused state."""
    return get_testing_interface().continue_execution()

def step_execution():
    """Execute one step and pause again."""
    return get_testing_interface().step_execution()

def get_current_location():
    """Get current execution location."""
    return get_testing_interface().get_current_location()

def get_call_stack():
    """Get current call stack information."""
    return get_testing_interface().get_call_stack()

def set_breakpoint_callback(callback):
    """Set callback function to be called when breakpoint is hit."""
    return get_testing_interface().set_breakpoint_callback(callback)

# Python Debugger Integration Functions
def enable_python_debugging():
    """Enable Python debugger integration for .rpy files."""
    return get_testing_interface().enable_python_debugging()

def disable_python_debugging():
    """Disable Python debugger integration."""
    return get_testing_interface().disable_python_debugging()

def start_debugpy_server(host='localhost', port=5678, wait_for_client=False):
    """Start debugpy server for DAP-compatible debuggers (VS Code, etc.)."""
    return get_testing_interface().start_debugpy_server(host, port, wait_for_client)

def stop_debugpy_server():
    """Stop debugpy server."""
    return get_testing_interface().stop_debugpy_server()

def start_pdb_debugging():
    """Start pdb debugging session."""
    return get_testing_interface().start_pdb_debugging()

def post_mortem_debug():
    """Start post-mortem debugging session."""
    return get_testing_interface().post_mortem_debug()

# Export main classes
TestingInterface = interface.TestingInterface
RenpyDebugger = debugger.RenpyDebugger

# Register CLI commands
cli.register_commands()

# Register CLI commands
cli.register_commands()
