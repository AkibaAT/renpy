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
Testing Interface Exports

This module exports testing interface functions to the main renpy namespace.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy.testing


def testing_interface():
    """
    :doc: testing
    
    Get the global testing interface instance.
    
    Returns:
        TestingInterface: The global testing interface instance
    """
    return renpy.testing.get_testing_interface()


def testing_inspect_state():
    """
    :doc: testing
    
    Get comprehensive information about the current game state.
    
    Returns:
        dict: Dictionary containing current game state information
    """
    return renpy.testing.inspect_state()


def testing_save_state(slot=None):
    """
    :doc: testing
    
    Save current game state to a testing slot.
    
    Args:
        slot (str, optional): Save slot name. If None, uses temporary slot.
        
    Returns:
        str: The slot name used for saving
    """
    return renpy.testing.save_state(slot)


def testing_load_state(slot):
    """
    :doc: testing
    
    Load game state from a testing slot.
    
    Args:
        slot (str): Save slot name to load from
        
    Returns:
        bool: True if load was successful
    """
    return renpy.testing.load_state(slot)


def testing_advance_dialogue():
    """
    :doc: testing
    
    Advance to the next dialogue/statement.
    
    Returns:
        bool: True if advancement was successful
    """
    return renpy.testing.advance_dialogue()


def testing_rollback(steps=1):
    """
    :doc: testing
    
    Roll back the specified number of steps.
    
    Args:
        steps (int): Number of steps to roll back
        
    Returns:
        bool: True if rollback was successful
    """
    return renpy.testing.rollback(steps)


def testing_select_choice(choice):
    """
    :doc: testing
    
    Select a menu choice by index or text.
    
    Args:
        choice (int or str): Choice index (0-based) or choice text
        
    Returns:
        bool: True if selection was successful
    """
    return renpy.testing.select_choice(choice)


def testing_get_choices():
    """
    :doc: testing
    
    Get available menu choices.
    
    Returns:
        list: List of available choices
    """
    return renpy.testing.get_choices()


def testing_get_current_label():
    """
    :doc: testing
    
    Get the current label/scene name.
    
    Returns:
        str or None: Current label name, or None if not available
    """
    return renpy.testing.get_current_label()


def testing_get_variables():
    """
    :doc: testing
    
    Get current game variables.
    
    Returns:
        dict: Dictionary of variable names to values
    """
    return renpy.testing.get_variables()


def testing_set_variable(name, value):
    """
    :doc: testing
    
    Set a game variable.
    
    Args:
        name (str): Variable name
        value: Variable value
        
    Returns:
        bool: True if variable was set successfully
    """
    return renpy.testing.set_variable(name, value)


def testing_start_http_server(host='localhost', port=8080):
    """
    :doc: testing
    
    Start the HTTP API server for external testing tools.
    
    Args:
        host (str): Host to bind to (default: localhost)
        port (int): Port to bind to (default: 8080)
        
    Returns:
        bool: True if server started successfully
    """
    return renpy.testing.start_http_server(host, port)


def testing_stop_http_server():
    """
    :doc: testing
    
    Stop the HTTP API server.
    
    Returns:
        bool: True if server stopped successfully
    """
    return renpy.testing.stop_http_server()


def testing_is_http_server_running():
    """
    :doc: testing
    
    Check if HTTP API server is running.
    
    Returns:
        bool: True if server is running
    """
    return renpy.testing.is_http_server_running()


def testing_get_http_server_url():
    """
    :doc: testing
    
    Get the HTTP API server URL.
    
    Returns:
        str: Server URL if running, None otherwise
    """
    return renpy.testing.get_http_server_url()


def testing_enable_headless():
    """
    :doc: testing
    
    Enable headless mode for automated testing.
    
    Returns:
        bool: True if headless mode was enabled successfully
    """
    return renpy.testing.enable_headless()


def testing_disable_headless():
    """
    :doc: testing
    
    Disable headless mode.
    
    Returns:
        bool: True if headless mode was disabled successfully
    """
    return renpy.testing.disable_headless()


def testing_is_headless():
    """
    :doc: testing
    
    Check if headless mode is currently enabled.
    
    Returns:
        bool: True if headless mode is enabled
    """
    return renpy.testing.is_headless()
