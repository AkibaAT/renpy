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
Core Testing Interface

This module provides the main TestingInterface class that coordinates
all testing functionality.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
from . import state_inspector
from . import state_manager
from . import game_controller
from . import http_server


class TestingInterface(object):
    """
    Main interface for automated testing of Ren'Py games.
    
    This class provides comprehensive access to game state inspection,
    state management, and game control functionality.
    """
    
    def __init__(self):
        """Initialize the testing interface."""
        self.state_inspector = state_inspector.StateInspector()
        self.state_manager = state_manager.StateManager()
        self.game_controller = game_controller.GameController()
        self.http_server = http_server.TestingHTTPServer(self)
        self._enabled = True
    
    def is_enabled(self):
        """Check if testing interface is enabled."""
        return self._enabled
    
    def enable(self):
        """Enable the testing interface."""
        self._enabled = True
    
    def disable(self):
        """Disable the testing interface."""
        self._enabled = False
    
    # State Inspection Methods
    
    def inspect_state(self):
        """
        Get comprehensive information about the current game state.
        
        Returns:
            dict: Dictionary containing current game state information
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_inspector.get_full_state()
    
    def get_current_label(self):
        """Get the current label/scene name."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_inspector.get_current_label()
    
    def get_variables(self):
        """Get current game variables."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_inspector.get_variables()
    
    def get_scene_info(self):
        """Get current scene and screen information."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_inspector.get_scene_info()
    
    def get_dialogue_info(self):
        """Get current dialogue information."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_inspector.get_dialogue_info()
    
    def get_choices(self):
        """Get available menu choices."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_inspector.get_choices()
    
    # State Management Methods
    
    def save_state(self, slot=None):
        """
        Save current game state.
        
        Args:
            slot (str, optional): Save slot name. If None, uses temporary slot.
            
        Returns:
            str: The slot name used for saving
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_manager.save_state(slot)
    
    def load_state(self, slot):
        """
        Load game state from slot.
        
        Args:
            slot (str): Save slot name to load from
            
        Returns:
            bool: True if load was successful
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_manager.load_state(slot)
    
    def export_state(self):
        """
        Export current state data for external analysis.
        
        Returns:
            dict: Serializable state data
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_manager.export_state()
    
    def import_state(self, state_data):
        """
        Import state data from external source.
        
        Args:
            state_data (dict): State data to import
            
        Returns:
            bool: True if import was successful
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.state_manager.import_state(state_data)
    
    # Game Control Methods
    
    def advance_dialogue(self):
        """
        Advance to the next dialogue/statement.
        
        Returns:
            bool: True if advancement was successful
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.game_controller.advance_dialogue()
    
    def rollback(self, steps=1):
        """
        Roll back the specified number of steps.
        
        Args:
            steps (int): Number of steps to roll back
            
        Returns:
            bool: True if rollback was successful
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.game_controller.rollback(steps)
    
    def select_choice(self, choice):
        """
        Select a menu choice.
        
        Args:
            choice (int or str): Choice index (0-based) or choice text
            
        Returns:
            bool: True if selection was successful
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.game_controller.select_choice(choice)
    
    def jump_to_label(self, label):
        """
        Jump to a specific label.
        
        Args:
            label (str): Label name to jump to
            
        Returns:
            bool: True if jump was successful
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.game_controller.jump_to_label(label)
    
    def set_variable(self, name, value):
        """
        Set a game variable.
        
        Args:
            name (str): Variable name
            value: Variable value
            
        Returns:
            bool: True if variable was set successfully
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        return self.game_controller.set_variable(name, value)
    
    def skip_transitions(self, enable=True):
        """
        Enable or disable transition skipping for faster testing.
        
        Args:
            enable (bool): Whether to skip transitions
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        self.game_controller.skip_transitions(enable)
    
    def set_auto_advance(self, enable=True, delay=0.1):
        """
        Enable or disable automatic dialogue advancement.

        Args:
            enable (bool): Whether to auto-advance
            delay (float): Delay between advances in seconds
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        self.game_controller.set_auto_advance(enable, delay)

    # HTTP Server Methods

    def start_http_server(self, host='localhost', port=8080):
        """
        Start the HTTP API server for external testing tools.

        Args:
            host (str): Host to bind to (default: localhost)
            port (int): Port to bind to (default: 8080)

        Returns:
            bool: True if server started successfully
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")

        self.http_server.host = host
        self.http_server.port = port
        return self.http_server.start()

    def stop_http_server(self):
        """
        Stop the HTTP API server.

        Returns:
            bool: True if server stopped successfully
        """
        self.http_server.stop()
        return True

    def is_http_server_running(self):
        """
        Check if HTTP API server is running.

        Returns:
            bool: True if server is running
        """
        return self.http_server.is_running()

    def get_http_server_url(self):
        """
        Get the HTTP API server URL.

        Returns:
            str: Server URL if running, None otherwise
        """
        if self.http_server.is_running():
            return self.http_server.get_url()
        return None

    def take_screenshot(self):
        """
        Take a screenshot of the current game screen.

        Returns:
            bytes: PNG image data, or None if screenshot failed
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")

        try:
            import threading

            print(f"[DEBUG] Taking screenshot from thread: {threading.current_thread().name}")

            # Check if we're in the main thread
            if threading.current_thread().name == "MainThread":
                # We're already in the main thread, call directly
                return self._take_screenshot_main_thread()
            else:
                # We're in a different thread (likely HTTP server thread)
                # Use invoke_in_main_thread to execute in the main thread
                print("[DEBUG] Not in main thread, invoking in main thread...")

                result_container = {'result': None, 'exception': None, 'completed': False}

                def screenshot_wrapper():
                    try:
                        result_container['result'] = self._take_screenshot_main_thread()
                    except Exception as e:
                        result_container['exception'] = e
                    finally:
                        result_container['completed'] = True

                # Invoke in main thread
                from renpy.exports.platformexports import invoke_in_main_thread
                invoke_in_main_thread(screenshot_wrapper)

                # Wait for completion (with timeout)
                import time
                timeout = 5.0  # 5 second timeout
                start_time = time.time()

                while not result_container['completed']:
                    if time.time() - start_time > timeout:
                        print("[DEBUG] Screenshot timeout waiting for main thread")
                        return None
                    time.sleep(0.01)  # Small sleep to avoid busy waiting

                if result_container['exception']:
                    print(f"[DEBUG] Screenshot exception in main thread: {result_container['exception']}")
                    return None

                return result_container['result']

        except Exception as e:
            print(f"[DEBUG] Screenshot error: {e}")
            import traceback
            print(f"[DEBUG] Screenshot traceback: {traceback.format_exc()}")
            return None

    def _take_screenshot_main_thread(self):
        """
        Internal method to take screenshot - must be called from main thread.

        Returns:
            bytes: PNG image data, or None if screenshot failed
        """
        try:
            import renpy.exports.displayexports as renpydisplay
            print("[DEBUG] Taking screenshot in main thread using Ren'Py's official API...")

            try:
                print("[DEBUG] Using renpy.exports.displayexports.screenshot_to_bytes()...")

                png_data = renpydisplay.screenshot_to_bytes(None)

                if png_data:
                    print(f"[DEBUG] Screenshot captured via screenshot_to_bytes(): {len(png_data)} bytes")
                    return png_data
                else:
                    print("[DEBUG] screenshot_to_bytes() returned no data")

            except Exception as e:
                print(f"[DEBUG] screenshot_to_bytes() method failed: {e}")
                import traceback
                print(f"[DEBUG] Traceback: {traceback.format_exc()}")

            return None

        except Exception as e:
            print(f"[DEBUG] Screenshot error in main thread: {e}")
            import traceback
            print(f"[DEBUG] Screenshot traceback: {traceback.format_exc()}")
            return None
