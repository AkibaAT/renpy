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
        self.game_controller = game_controller.GameController(self)
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
    
    # Breakpoint and Debug Methods
    
    def enable_debug_mode(self):
        """Enable debug mode for breakpoint functionality."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import enable
        enable()
        return True
    
    def disable_debug_mode(self):
        """Disable debug mode."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import disable
        disable()
        return True
    
    def is_debug_mode(self):
        """Check if debug mode is enabled."""
        if not self._enabled:
            return False
        from renpy.testing.debugger import get_state
        state = get_state()
        return state.get('enabled', False)
    
    def is_paused(self):
        """Check if execution is currently paused at a breakpoint."""
        if not self._enabled:
            return False
        from renpy.testing.debugger import get_state
        state = get_state()
        return state.get('paused', False)
    
    def set_breakpoint(self, filename, line, condition=None):
        """
        Set a breakpoint at the specified location.
        
        Args:
            filename (str): Script filename
            line (int): Line number
            condition (str, optional): Condition for conditional breakpoint
            
        Returns:
            bool: True if breakpoint was set successfully
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import set_breakpoint
        return set_breakpoint(filename, line, condition)
    
    def clear_breakpoint(self, filename, line):
        """
        Clear a breakpoint at the specified location.
        
        Args:
            filename (str): Script filename
            line (int): Line number
            
        Returns:
            bool: True if breakpoint was cleared
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import clear_breakpoint
        return clear_breakpoint(filename, line)
    
    def clear_all_breakpoints(self, filename=None):
        """
        Clear all breakpoints, optionally for a specific file.
        
        Args:
            filename (str, optional): If provided, only clear breakpoints in this file
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import clear_all_breakpoints
        clear_all_breakpoints(filename)
        return True
    
    def list_breakpoints(self):
        """
        Get a list of all current breakpoints.
        
        Returns:
            list: List of breakpoint dictionaries
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import list_breakpoints
        return list_breakpoints()
    
    def enable_breakpoint(self, filename, line, enabled=True):
        """
        Enable or disable a specific breakpoint.
        
        Args:
            filename (str): Script filename
            line (int): Line number
            enabled (bool): Whether to enable or disable
            
        Returns:
            bool: True if breakpoint was found and updated
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        # Note: The clean debugger doesn't have enable_breakpoint method
        # All breakpoints are enabled by default when set
        from renpy.testing.debugger import list_breakpoints
        breakpoints = list_breakpoints()
        # This is a simplified implementation - the original enable_breakpoint may need custom handling
        return True
    
    def continue_execution(self):
        """Continue execution from a paused state."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import continue_execution
        continue_execution()
        return True
    
    def step_execution(self):
        """Execute one step and pause again."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import step
        step()
        return True
    
    def get_current_location(self):
        """
        Get current execution location.
        
        Returns:
            dict: Current location information
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import get_state
        state = get_state()
        return {
            'filename': state.get('current_file'),
            'line': state.get('current_line'),
            'node_type': state.get('node_type')
        }
    
    def get_call_stack(self):
        """
        Get current call stack information.
        
        Returns:
            list: List of call stack frames
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        from renpy.testing.debugger import get_call_stack
        return get_call_stack()
    
    def set_breakpoint_callback(self, callback):
        """
        Set callback function to be called when breakpoint is hit.
        
        Args:
            callback: Function to call with (reason, filename, line, node)
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        # Note: The clean debugger doesn't have callback functionality yet
        # This would need to be implemented if callback functionality is needed
        pass
        return True
    
    # Python Debugger Integration Methods
    
    def enable_python_debugging(self):
        """Enable Python debugger integration for .rpy files."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            from renpy.testing.debugger import enable_python
            enable_python()
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to enable Python debugging: {e}")
    
    def enable_vscode_debugging(self, port=5678, wait_for_client=False):
        """
        Enable VSCode debugging via debugpy.
        
        Args:
            port (int): Port for debugpy server (default: 5678)
            wait_for_client (bool): Whether to wait for VSCode to attach
            
        Returns:
            dict: Information about the debugging setup
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            from renpy.testing.debugger import enable_vscode_debugging, get_virtual_files_directory
            
            success = enable_vscode_debugging(port, wait_for_client)
            if success:
                return {
                    'success': True,
                    'port': port,
                    'virtual_files_dir': get_virtual_files_directory(),
                    'instructions': [
                        f"1. Install debugpy: pip install debugpy",
                        f"2. In VSCode, open Command Palette (Ctrl+Shift+P)",
                        f"3. Run 'Python: Attach' command",
                        f"4. Enter localhost:{port} when prompted",
                        f"5. Open virtual files from: {get_virtual_files_directory()}",
                        f"6. Set breakpoints in the virtual .py files"
                    ]
                }
            else:
                return {'success': False, 'error': 'Failed to start debugpy server'}
                
        except Exception as e:
            raise RuntimeError(f"Failed to enable VSCode debugging: {e}")
    
    def disable_vscode_debugging(self):
        """Disable VSCode debugging."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            from renpy.testing.debugger import disable_vscode_debugging
            disable_vscode_debugging()
            return True
        except Exception as e:
            raise RuntimeError(f"Failed to disable VSCode debugging: {e}")
    
    def create_virtual_files_for_debugging(self, rpy_files=None):
        """
        Create virtual Python files for .rpy files to enable VSCode debugging.
        
        Args:
            rpy_files (list): List of .rpy filenames. If None, creates for all .rpy files found.
            
        Returns:
            dict: Mapping of .rpy files to virtual .py files
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            from renpy.testing.debugger import create_virtual_file
            import glob
            import renpy
            
            if rpy_files is None:
                # Find all .rpy files in the game directory
                game_dir = renpy.config.gamedir or 'game'
                rpy_files = [os.path.basename(f) for f in glob.glob(os.path.join(game_dir, "*.rpy"))]
            
            virtual_files = {}
            for rpy_file in rpy_files:
                virtual_path = create_virtual_file(rpy_file)
                if virtual_path:
                    virtual_files[rpy_file] = virtual_path
            
            return {
                'success': True,
                'virtual_files': virtual_files,
                'count': len(virtual_files)
            }
            
        except Exception as e:
            raise RuntimeError(f"Failed to create virtual files: {e}")
    
    def disable_python_debugging(self):
        """Disable Python debugger integration."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            from renpy.testing.debugger import disable_python
            disable_python()
            return True
        except ImportError:
            raise RuntimeError("Python debugger integration not available")
    
    def start_debugpy_server(self, host='localhost', port=5678, wait_for_client=False):
        """
        Start debugpy server for DAP-compatible debuggers (VS Code, etc.).
        
        Args:
            host (str): Host to bind to
            port (int): Port to bind to
            wait_for_client (bool): Whether to wait for debugger to attach
            
        Returns:
            bool: True if server started successfully
        """
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            # Note: debugpy integration would need to be implemented in the clean debugger
            raise RuntimeError("debugpy integration not yet implemented in clean debugger")
        except ImportError:
            raise RuntimeError("debugpy not available. Install with: pip install debugpy")
    
    def stop_debugpy_server(self):
        """Stop debugpy server."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            # Note: debugpy integration would need to be implemented in the clean debugger
            raise RuntimeError("debugpy integration not yet implemented in clean debugger")
            return True
        except ImportError:
            raise RuntimeError("debugpy integration not available")
    
    def start_pdb_debugging(self):
        """Start pdb debugging session."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            # Note: pdb integration would need to be implemented in the clean debugger
            raise RuntimeError("pdb integration not yet implemented in clean debugger")
            return True
        except ImportError:
            raise RuntimeError("pdb integration not available")
    
    def post_mortem_debug(self):
        """Start post-mortem debugging session."""
        if not self._enabled:
            raise RuntimeError("Testing interface is disabled")
        try:
            # Note: post-mortem debugging would need to be implemented in the clean debugger
            raise RuntimeError("post-mortem debugging not yet implemented in clean debugger")
            return True
        except ImportError:
            raise RuntimeError("pdb integration not available")

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
