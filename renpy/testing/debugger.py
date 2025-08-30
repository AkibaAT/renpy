# Copyright 2004-2025 Tom Rothamel <pytom@bishoujo.us>
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
Ren'Py Script Debugger

A complete debugging solution for .rpy visual novel scripts that supports:
- Breakpoints in .rpy script statements (say, menu, label, jump, etc.)
- Breakpoints in Python blocks within .rpy files
- Variable inspection and modification
- Step-by-step execution
- Call stack inspection
- IDE integration via Debug Adapter Protocol
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import sys
import os
import threading
import time
import tempfile
import inspect
import linecache
import renpy


class RenpyDebugger(object):
    """
    Complete debugger for Ren'Py visual novel scripts.
    
    Handles both .rpy script statements and Python code blocks within .rpy files.
    """
    
    def __init__(self):
        # Breakpoints: {filename: {line_number: breakpoint_info}}
        self.breakpoints = {}
        
        # Data breakpoints: {variable_name: data_breakpoint_info}
        self.data_breakpoints = {}
        self.variable_snapshots = {}  # Track variable values
        self.data_breakpoint_enabled = False
        self.pending_data_breakpoint = None  # Stores info about triggered data breakpoint
        
        # Debug state
        self.enabled = False
        self.paused = False
        self.step_mode = False
        self.step_type = None  # 'in', 'over', 'out'
        self.step_depth = None
        self.step_origin = None  # (file, line)
        self.last_break_reason = 'breakpoint'
        
        # Current execution context
        self.current_node = None
        self.current_file = None
        self.current_line = None
        self.current_type = None  # 'script' or 'python'
        
        # Synchronization
        self.pause_event = threading.Event()
        self.pause_lock = threading.RLock()

        # Optional callback registered by native DAP server to observe pauses
        self.pause_listener = None
        
        # Python debugging
        self.python_enabled = False
        self.original_py_exec = None
        self.original_trace = None
        
        # VSCode/debugpy integration
        self.debugpy_enabled = False
        self.debugpy_port = None
        self.source_mapping = {}  # Map .rpy files to virtual Python files
        self.virtual_files_dir = None
        
        # Reload state management
        self.saved_state = None
        self.is_reloading = False
        
        
    def enable(self):
        """Enable the debugger."""
        self.enabled = True
        self._patch_python_execution()
        print("Ren'Py debugger enabled")
        
    def disable(self):
        """Disable the debugger."""
        self.enabled = False
        self.paused = False
        self.pending_data_breakpoint = None  # Clear any pending data breakpoints
        self.pause_event.set()
        self._unpatch_python_execution()
        self.disable_python_debugging()
        print("Ren'Py debugger disabled")
        
    def enable_python_debugging(self):
        """Enable debugging of Python blocks within .rpy files."""
        if not self.python_enabled:
            self.python_enabled = True
            self.original_trace = sys.gettrace()
            sys.settrace(self._trace_function)
            print("Python debugging enabled for .rpy files")
            
    def disable_python_debugging(self):
        """Disable Python debugging."""
        if self.python_enabled:
            self.python_enabled = False
            sys.settrace(self.original_trace)
            self.original_trace = None
            print("Python debugging disabled")
    
    def prepare_for_reload(self):
        """Prepare debugger for script reload by saving state and cleaning up."""
        if not self.enabled:
            return
            
        self.is_reloading = True
        
        # Save current debugger state
        self.saved_state = {
            'breakpoints': self._deep_copy_breakpoints(),
            'enabled': self.enabled,
            'python_enabled': self.python_enabled,
            'debugpy_enabled': self.debugpy_enabled,
            'debugpy_port': self.debugpy_port,
            'source_mapping': self.source_mapping.copy(),
            'virtual_files_dir': self.virtual_files_dir
        }
        
        # Clean up debugging hooks
        self._handle_restart_cleanup()
        print("Debugger prepared for script reload")
    
    def restore_after_reload(self):
        """Restore debugger state after script reload."""
        if not self.is_reloading or not self.saved_state:
            return
            
        # Restore breakpoints and settings
        self.breakpoints = self.saved_state.get('breakpoints', {})
        self.source_mapping = self.saved_state.get('source_mapping', {})
        self.virtual_files_dir = self.saved_state.get('virtual_files_dir', None)
        
        was_enabled = self.saved_state.get('enabled', False)
        was_python_enabled = self.saved_state.get('python_enabled', False)
        was_debugpy_enabled = self.saved_state.get('debugpy_enabled', False)
        debugpy_port = self.saved_state.get('debugpy_port', None)
        
        # Validate and update source mappings
        self._validate_source_mappings()
        
        # Re-enable if it was enabled before
        if was_enabled:
            self.enable()
            if was_python_enabled:
                self.enable_python_debugging()
            if was_debugpy_enabled and debugpy_port:
                self._restore_debugpy_connection(debugpy_port)
        
        # Clear reload state
        self.saved_state = None
        self.is_reloading = False
        print("Debugger state restored after script reload")
    
    def _handle_restart_cleanup(self):
        """Clean up debugging state before script reload."""
        # Release any waiting threads
        if self.paused:
            self.paused = False
            self.pause_event.set()
        
        # Unpatch Python execution
        self._unpatch_python_execution()
        
        # Restore original trace function
        if self.python_enabled and self.original_trace is not None:
            sys.settrace(self.original_trace)
        
        # Clear current execution context
        self.current_node = None
        self.current_file = None
        self.current_line = None
        self.current_type = None
        self.pending_data_breakpoint = None  # Clear any pending data breakpoints
        
        # Reset state flags but keep configuration
        self.enabled = False
        self.python_enabled = False
    
    def enable_vscode_debugging(self, port=5678, wait_for_client=False):
        """
        Enable VSCode debugging via debugpy with direct .rpy file support.
        
        Args:
            port (int): Port for debugpy server
            wait_for_client (bool): Whether to wait for VSCode to attach
            
        Returns:
            bool: True if successful
        """
        try:
            import debugpy
            
            if self.debugpy_enabled:
                print(f"debugpy already enabled on port {self.debugpy_port}")
                return True
            
            # Patch os module for debugpy compatibility
            import os
            if not hasattr(os, '__file__'):
                import sysconfig
                stdlib_path = sysconfig.get_path('stdlib')
                os.__file__ = os.path.join(stdlib_path, 'os.py')
                
            # Start debugpy server
            debugpy.listen(("localhost", port))
            self.debugpy_enabled = True
            self.debugpy_port = port
            
            print(f"debugpy server started on localhost:{port}")
            print("VSCode Debugging Setup:")
            print("1. Open your .rpy files in VSCode")
            print("2. Set breakpoints directly in .rpy files")
            print("3. Run 'Python: Attach' and connect to localhost:{port}")
            print("4. Breakpoints in .rpy files will work automatically!")
            
            if wait_for_client:
                print("Waiting for VSCode to attach...")
                debugpy.wait_for_client()
                print("VSCode attached!")
            
            # Enable direct .rpy file debugging
            self._setup_direct_rpy_debugging()
            
            return True
            
        except ImportError:
            print("debugpy not available. Install with: pip install debugpy")
            return False
        except Exception as e:
            print(f"Failed to start debugpy: {e}")
            return False
    
    def disable_vscode_debugging(self):
        """Disable VSCode debugging."""
        if self.debugpy_enabled:
            try:
                import debugpy
                # debugpy doesn't have a clean way to stop the server
                # but we can mark it as disabled
                self.debugpy_enabled = False
                self.debugpy_port = None
                print("debugpy integration disabled")
            except ImportError:
                pass
    
    
    
    def _setup_direct_rpy_debugging(self):
        """Set up direct .rpy file debugging without virtual files."""
        # Register .rpy files with linecache so debugpy can read them
        self._register_rpy_files_with_linecache()
        
        # Set up custom trace function for .rpy breakpoints
        self._install_rpy_trace_function()
        
        print("Direct .rpy file debugging enabled - set breakpoints directly in .rpy files!")
    
    def _register_rpy_files_with_linecache(self):
        """Register .rpy files with Python's linecache so debugpy can read them."""
        try:
            import glob
            
            # Find all .rpy files
            game_dir = renpy.config.gamedir or 'game'
            if os.path.exists(game_dir):
                rpy_files = glob.glob(os.path.join(game_dir, "*.rpy"))
                
                for rpy_file in rpy_files:
                    # Add to linecache so debugpy can read the source
                    linecache.checkcache(rpy_file)
                    
                    # Pre-load the file content
                    with open(rpy_file, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        linecache.cache[rpy_file] = (
                            len(lines),
                            None,
                            lines,
                            rpy_file
                        )
                
                print(f"Registered {len(rpy_files)} .rpy files for debugging")
                
        except Exception as e:
            print(f"Warning: Could not register .rpy files: {e}")
    
    def _install_rpy_trace_function(self):
        """Install trace function that handles .rpy file breakpoints."""
        def rpy_trace(frame, event, arg):
            if event == 'line' and self.debugpy_enabled:
                filename = frame.f_code.co_filename
                
                # Check if this is a .rpy file
                if filename.endswith('.rpy'):
                    line_no = frame.f_lineno
                    
                    # Check for breakpoints
                    if self._has_breakpoint(filename, line_no):
                        # Trigger debugpy breakpoint
                        import debugpy
                        debugpy.breakpoint()
                        
            return rpy_trace
        
        # Install the trace function
        sys.settrace(rpy_trace)
    
    def _has_breakpoint(self, filename, line_no):
        """Check if there's a breakpoint at the given location."""
        basename = os.path.basename(filename)
        return (basename in self.breakpoints and 
                line_no in self.breakpoints[basename])
    
    def _setup_source_mapping(self):
        """Set up source mapping for .rpy files to make them debuggable in VSCode."""
        if self.virtual_files_dir is None:
            self.virtual_files_dir = tempfile.mkdtemp(prefix="renpy_debug_")
            print(f"Created virtual files directory: {self.virtual_files_dir}")
    
    def _create_virtual_python_file(self, rpy_filename):
        """
        Create a virtual Python file that represents a .rpy file for debugging.
        
        This allows VSCode to set breakpoints in .rpy files by creating
        corresponding .py files with the same content.
        """
        if not self.virtual_files_dir:
            self._setup_source_mapping()
            
        # Create virtual .py filename
        virtual_filename = rpy_filename.replace('.rpy', '_rpy_debug.py')
        virtual_path = os.path.join(self.virtual_files_dir, virtual_filename)
        
        # Check if already created
        if virtual_path in self.source_mapping.values():
            return virtual_path
            
        try:
            # Find and read the .rpy file
            rpy_content = self._read_rpy_file(rpy_filename)
            if rpy_content:
                # Create virtual Python file with same line numbers
                virtual_content = self._convert_rpy_to_debuggable_python(rpy_content, rpy_filename)
                
                with open(virtual_path, 'w', encoding='utf-8') as f:
                    f.write(virtual_content)
                
                # Store mapping
                self.source_mapping[rpy_filename] = virtual_path
                
                # Add to linecache so debugger can find it
                linecache.checkcache(virtual_path)
                
                print(f"Created virtual Python file: {virtual_path}")
                return virtual_path
                
        except Exception as e:
            print(f"Failed to create virtual file for {rpy_filename}: {e}")
            
        return None
    
    def _read_rpy_file(self, filename):
        """Read content from a .rpy file."""
        try:
            full_path = None
            
            if renpy.config.gamedir:
                full_path = os.path.join(renpy.config.gamedir, filename)
                
            if not full_path or not os.path.exists(full_path):
                for search_dir in ['.', 'game', renpy.config.basedir]:
                    if search_dir:
                        test_path = os.path.join(search_dir, filename)
                        if os.path.exists(test_path):
                            full_path = test_path
                            break
                            
            if full_path and os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    return f.read()
                    
        except Exception:
            pass
            
        return None
    
    def _convert_rpy_to_debuggable_python(self, rpy_content, filename):
        """
        Convert .rpy content to Python code that can be debugged.
        
        This creates a Python file where:
        - Each .rpy line becomes a Python comment or equivalent
        - Breakpoints can be set on the equivalent lines
        - Line numbers match between .rpy and .py files
        """
        lines = rpy_content.split('\n')
        python_lines = []
        
        python_lines.append(f'# Virtual Python file for debugging {filename}')
        python_lines.append('# This file is auto-generated for VSCode debugging support')
        python_lines.append('')
        
        for i, line in enumerate(lines, 1):
            # Convert .rpy line to debuggable Python
            if line.strip().startswith('label '):
                # Label becomes a function
                label_name = line.strip().split()[1].rstrip(':')
                python_lines.append(f'def {label_name}():  # {line.strip()}')
            elif line.strip().startswith('python:'):
                python_lines.append('# Python block start')
            elif line.strip().startswith('$'):
                # Python statement
                python_code = line.strip()[1:].strip()
                python_lines.append(f'{python_code}  # Ren\'Py: {line.strip()}')
            elif line.strip().startswith('#'):
                # Comment
                python_lines.append(line)
            elif line.strip() == '':
                # Empty line
                python_lines.append('')
            else:
                # Regular .rpy statement - make it a debuggable Python line
                escaped_line = line.replace('"', '\\"')
                python_lines.append(f'renpy_statement = "{escaped_line}"  # {line.strip()}')
        
        # Add a main execution function that can be called for debugging
        python_lines.append('')
        python_lines.append('def _debug_execution_point(line_number, statement_type="script"):')
        python_lines.append('    """Breakpoint function for Ren\'Py debugging."""')
        python_lines.append('    import renpy.testing.debugger as debugger')
        python_lines.append('    # This is where VSCode breakpoints will actually pause')
        python_lines.append('    pass')
        
        return '\n'.join(python_lines)
    
    def set_breakpoint(self, filename, line_number, condition=None):
        """
        Set a breakpoint in a .rpy file.
        
        Args:
            filename (str): .rpy filename
            line_number (int): Line number
            condition (str, optional): Python expression for conditional breakpoint
            
        Returns:
            bool: True if successful
        """
        filename = os.path.basename(filename)
        if not filename.endswith('.rpy'):
            filename += '.rpy'
            
        if filename not in self.breakpoints:
            self.breakpoints[filename] = {}
            
        self.breakpoints[filename][line_number] = {
            'condition': condition,
            'enabled': True,
            'hit_count': 0
        }
        
        print(f"Breakpoint set at {filename}:{line_number}")
        return True
        
    def clear_breakpoint(self, filename, line_number):
        """Clear a specific breakpoint."""
        filename = os.path.basename(filename)
        if not filename.endswith('.rpy'):
            filename += '.rpy'
            
        if filename in self.breakpoints and line_number in self.breakpoints[filename]:
            del self.breakpoints[filename][line_number]
            if not self.breakpoints[filename]:
                del self.breakpoints[filename]
            print(f"Breakpoint cleared at {filename}:{line_number}")
            return True
        return False
        
    def clear_all_breakpoints(self, filename=None):
        """Clear all breakpoints, optionally for a specific file."""
        if filename:
            filename = os.path.basename(filename)
            if not filename.endswith('.rpy'):
                filename += '.rpy'
            if filename in self.breakpoints:
                del self.breakpoints[filename]
                print(f"All breakpoints cleared in {filename}")
        else:
            self.breakpoints.clear()
            print("All breakpoints cleared")
    
    def list_breakpoints(self):
        """Get list of all breakpoints."""
        result = []
        for filename, file_breakpoints in self.breakpoints.items():
            for line_number, bp_info in file_breakpoints.items():
                result.append({
                    'filename': filename,
                    'line': line_number,
                    'condition': bp_info['condition'],
                    'enabled': bp_info['enabled'],
                    'hit_count': bp_info['hit_count']
                })
        return result
    
    def check_script_breakpoint(self, node):
        """
        Check if we should break on a .rpy script statement.
        Called from the execution loop.
        """
        if not self.enabled:
            return
            
        self.current_node = node
        self.current_file = os.path.basename(node.filename)
        self.current_line = node.linenumber
        self.current_type = 'script'
        
        # Debug output for pending data breakpoints
        if self.pending_data_breakpoint:
            print(f"🔍 Processing pending data breakpoint at {self.current_file}:{self.current_line}")
        
        # Handle different IDE debugging
        if self.debugpy_enabled:
            self._handle_vscode_breakpoint(node)
        elif self._should_break():
            self._pause_execution(self.last_break_reason)
    
    def _handle_vscode_breakpoint(self, node):
        """Handle breakpoint checking when VSCode debugging is enabled."""
        try:
            import debugpy
            
            # Check if we should break (including pending data breakpoints)
            should_break = self._should_break()
            
            if should_break:
                # Get the .rpy file path
                rpy_file_path = self._get_full_rpy_path(self.current_file)
                
                if rpy_file_path:
                    # If it's a data breakpoint, handle it specially
                    if self.pending_data_breakpoint:
                        self._handle_data_breakpoint_pause()
                        return
                    
                    # Create code object that appears to be from the .rpy file
                    code_str = f"# Ren'Py execution point\npass  # Line {self.current_line}: {type(node).__name__}"
                    
                    try:
                        # Compile with the .rpy filename so debugger sees it correctly
                        code = compile(code_str, rpy_file_path, 'exec', dont_inherit=True)
                        
                        # Execute this code - debugpy will see it as executing from the .rpy file
                        exec(code, {
                            '__file__': rpy_file_path,
                            '__name__': f"renpy_{self.current_file}",
                            'renpy_node': node,
                            'renpy_context': self._create_debug_context()
                        })
                        
                    except Exception as compile_error:
                        # If compilation fails, fall back to debugpy.breakpoint()
                        debugpy.breakpoint()
                else:
                    # Fallback to programmatic breakpoint
                    debugpy.breakpoint()
                
        except ImportError:
            # Fallback to custom breakpoints
            if self._should_break():
                self._pause_execution("Breakpoint")
        except Exception as e:
            print(f"VSCode debugging error: {e}")
            # Fallback to custom breakpoints
            if self._should_break():
                self._pause_execution("Breakpoint")
    
    def _get_full_rpy_path(self, filename):
        """Get the full path to a .rpy file."""
        try:
            # Try game directory first
            if renpy.config.gamedir:
                full_path = os.path.join(renpy.config.gamedir, filename)
                if os.path.exists(full_path):
                    return os.path.abspath(full_path)
            
            # Try other common locations
            for search_dir in ['.', 'game', renpy.config.basedir]:
                if search_dir:
                    test_path = os.path.join(search_dir, filename)
                    if os.path.exists(test_path):
                        return os.path.abspath(test_path)
                        
        except Exception:
            pass
            
        return None
    
    def _create_debug_context(self):
        """Create debugging context with Ren'Py variables."""
        context = {
            'current_file': self.current_file,
            'current_line': self.current_line,
            'node_type': type(self.current_node).__name__ if self.current_node else None,
        }
        
        # Add Ren'Py variables
        try:
            context['renpy_store'] = dict(renpy.store.__dict__)
            if hasattr(renpy.game, 'persistent'):
                context['persistent'] = dict(renpy.game.persistent.__dict__)
        except Exception:
            pass
            
        return context
    
    
    def _debug_execution_point(self, line_number, statement_type="script"):
        """
        Execution point that VSCode debugger can see and break on.
        This function is called when a .rpy statement executes.
        """
        # Store current debugging context
        self._vscode_context = {
            'line_number': line_number,
            'statement_type': statement_type,
            'current_file': self.current_file,
            'current_node': self.current_node,
            'variables': self.get_variables()
        }
        
        # This is where VSCode breakpoints will actually pause execution
        # The debugger can inspect self._vscode_context to see Ren'Py state
        pass
    
    def continue_execution(self):
        """Continue execution from a paused state."""
        with self.pause_lock:
            self.paused = False
            self.step_mode = False
            self.step_type = None
            self.step_depth = None
            self.step_origin = None
            self.pause_event.set()
        print("Continuing execution...")
        
    def step_execution(self, mode='in'):
        """Execute one step and pause again. mode: 'in', 'over', or 'out'"""
        with self.pause_lock:
            self.paused = False
            self.step_mode = True
            self.step_type = mode
            self.step_depth = self._current_call_depth()
            self.step_origin = (self.current_file, self.current_line)
            self.pause_event.set()
        print(f"Stepping ({mode})...")

    def step_in(self):
        self.step_execution('in')

    def step_over(self):
        self.step_execution('over')

    def step_out(self):
        self.step_execution('out')
    
    def get_current_state(self):
        """Get current debugging state."""
        return {
            'enabled': self.enabled,
            'python_enabled': self.python_enabled,
            'paused': self.paused,
            'current_file': self.current_file,
            'current_line': self.current_line,
            'current_type': self.current_type,
            'node_type': type(self.current_node).__name__ if self.current_node else None
        }
    
    def get_variables(self):
        """Get current game variables."""
        variables = {}
        
        try:
            # Ren'Py store variables
            for name, value in renpy.store.__dict__.items():
                if not name.startswith('_'):
                    try:
                        variables[name] = str(value)
                    except Exception:
                        variables[name] = f"<{type(value).__name__}>"
                        
            # Persistent variables
            if hasattr(renpy.game, 'persistent'):
                for name, value in renpy.game.persistent.__dict__.items():
                    if not name.startswith('_'):
                        try:
                            variables[f"persistent.{name}"] = str(value)
                        except Exception:
                            variables[f"persistent.{name}"] = f"<{type(value).__name__}>"
                            
        except Exception as e:
            variables['error'] = str(e)
            
        return variables
    
    # ===== DATA BREAKPOINTS =====
    
    def add_data_breakpoint(self, variable_name, condition="change", access_type="write"):
        """
        Add a data breakpoint that triggers when a variable changes.
        
        Args:
            variable_name (str): Name of variable to watch (e.g., "health", "persistent.score")
            condition (str): Condition for breaking:
                - "change": Break on any value change (default)
                - "increase": Break when value increases
                - "decrease": Break when value decreases
                - "equals:VALUE": Break when value equals VALUE
                - "gt:VALUE": Break when value greater than VALUE
                - "lt:VALUE": Break when value less than VALUE
            access_type (str): "read", "write", or "both" (currently only "write" supported)
            
        Returns:
            int: Data breakpoint ID
        """
        if not self.enabled:
            raise RuntimeError("Debugger must be enabled to add data breakpoints")
        
        bp_id = len(self.data_breakpoints) + 1
        
        self.data_breakpoints[variable_name] = {
            'id': bp_id,
            'variable_name': variable_name,
            'condition': condition,
            'access_type': access_type,
            'enabled': True,
            'hit_count': 0,
            'last_value': None,
            'created_at': time.time()
        }
        
        # Take initial snapshot of the variable
        current_value = self._get_variable_value(variable_name)
        self.variable_snapshots[variable_name] = current_value
        self.data_breakpoints[variable_name]['last_value'] = current_value
        
        # Enable data breakpoint monitoring
        if not self.data_breakpoint_enabled:
            self._enable_data_breakpoint_monitoring()
        
        # Verify debugpy status
        if self.debugpy_enabled:
            print(f"Data breakpoint {bp_id} added for '{variable_name}' (condition: {condition}) - debugpy active")
        else:
            print(f"Data breakpoint {bp_id} added for '{variable_name}' (condition: {condition}) - custom debugger mode")
        print(f"Current value: {current_value}")
        
        return bp_id
    
    def remove_data_breakpoint(self, variable_name):
        """Remove a data breakpoint by variable name."""
        if variable_name in self.data_breakpoints:
            bp_id = self.data_breakpoints[variable_name]['id']
            del self.data_breakpoints[variable_name]
            if variable_name in self.variable_snapshots:
                del self.variable_snapshots[variable_name]
            
            # Disable monitoring if no data breakpoints remain
            if not self.data_breakpoints:
                self._disable_data_breakpoint_monitoring()
            
            print(f"Data breakpoint {bp_id} for '{variable_name}' removed")
            return True
        return False
    
    def list_data_breakpoints(self):
        """List all active data breakpoints."""
        if not self.data_breakpoints:
            return []
        
        breakpoints = []
        for var_name, bp_info in self.data_breakpoints.items():
            current_value = self._get_variable_value(var_name)
            breakpoints.append({
                'id': bp_info['id'],
                'variable_name': var_name,
                'condition': bp_info['condition'],
                'enabled': bp_info['enabled'],
                'hit_count': bp_info['hit_count'],
                'current_value': current_value,
                'last_value': bp_info['last_value']
            })
        return breakpoints
    
    def _enable_data_breakpoint_monitoring(self):
        """Enable variable change monitoring."""
        self.data_breakpoint_enabled = True
        
        # Patch store access to monitor variable changes
        self._patch_store_access()
        
        print("Data breakpoint monitoring enabled")
    
    def _disable_data_breakpoint_monitoring(self):
        """Disable variable change monitoring."""
        self.data_breakpoint_enabled = False
        self._unpatch_store_access()
        print("Data breakpoint monitoring disabled")
    
    def _patch_store_access(self):
        """Patch renpy.store to monitor variable changes."""
        if hasattr(self, '_original_store_setattr'):
            return  # Already patched
        
        # Store original methods - StoreModule only has __setattr__
        # Both $ variable = value and direct assignment use __setattr__
        self._original_store_setattr = renpy.store.__class__.__setattr__
        self._original_persistent_setattr = None
        
        if hasattr(renpy.game, 'persistent') and renpy.game.persistent:
            self._original_persistent_setattr = renpy.game.persistent.__class__.__setattr__
        
        debugger_ref = self
        

        def patched_store_setattr(store_self, name, value):
            """Patch for all store variable assignments ($ variable = value and direct)."""
            # Call original setattr first
            debugger_ref._original_store_setattr(store_self, name, value)

            # Check for data breakpoints after setting the value
            if debugger_ref.data_breakpoint_enabled and not name.startswith('_'):
                should_break = debugger_ref._check_data_breakpoint_and_return_break_status(name, value)

                # Trigger breakpoint if needed - this will break at the correct .rpy location
                if should_break:
                    print(f"🔍 Data breakpoint triggered: {name} = {value}")
                    old_value = debugger_ref.variable_snapshots.get(name)
                    debugger_ref._trigger_data_breakpoint_here(name, old_value, value)
        
        def patched_persistent_setattr(persistent_self, name, value):
            """Patch for persistent variable changes."""
            # Call original setattr first
            debugger_ref._original_persistent_setattr(persistent_self, name, value)

            # Check for data breakpoints after setting the value
            if debugger_ref.data_breakpoint_enabled and not name.startswith('_'):
                should_break = debugger_ref._check_data_breakpoint_and_return_break_status(f"persistent.{name}", value)

                # Trigger breakpoint if needed - this will break at the correct .rpy location
                if should_break:
                    print(f"🔍 Data breakpoint triggered: persistent.{name} = {value}")
                    old_value = debugger_ref.variable_snapshots.get(f"persistent.{name}")
                    debugger_ref._trigger_data_breakpoint_here(f"persistent.{name}", old_value, value)
        
        # Apply patches
        renpy.store.__class__.__setattr__ = patched_store_setattr

        if self._original_persistent_setattr:
            renpy.game.persistent.__class__.__setattr__ = patched_persistent_setattr

        print(f"Store patching applied: __setattr__ patched")
    
    def _unpatch_store_access(self):
        """Restore original store access methods."""
            
        if hasattr(self, '_original_store_setattr'):
            renpy.store.__class__.__setattr__ = self._original_store_setattr
            del self._original_store_setattr
        
        if hasattr(self, '_original_persistent_setattr') and self._original_persistent_setattr:
            renpy.game.persistent.__class__.__setattr__ = self._original_persistent_setattr
            del self._original_persistent_setattr
        
        print("Store patching removed")
    
    def _get_variable_value(self, variable_name):
        """Get the current value of a variable."""
        try:
            if variable_name.startswith('persistent.'):
                var_name = variable_name[11:]  # Remove 'persistent.' prefix
                if hasattr(renpy.game, 'persistent'):
                    return getattr(renpy.game.persistent, var_name, None)
            else:
                return getattr(renpy.store, variable_name, None)
        except Exception:
            return None
    
    def _check_data_breakpoint(self, variable_name, new_value):
        """Check if a variable change should trigger a data breakpoint."""
        # Check direct variable name
        self._check_single_data_breakpoint(variable_name, new_value)
        
        # Also check persistent.variable_name format
        if not variable_name.startswith('persistent.'):
            persistent_name = f"persistent.{variable_name}"
            if persistent_name in self.data_breakpoints:
                self._check_single_data_breakpoint(persistent_name, new_value)
    
    def _check_single_data_breakpoint(self, variable_name, new_value):
        """Check a single data breakpoint for triggering."""
        if variable_name not in self.data_breakpoints:
            return
        
        bp_info = self.data_breakpoints[variable_name]
        if not bp_info['enabled']:
            return
        
        old_value = bp_info['last_value']
        condition = bp_info['condition']
        
        should_break = False
        break_reason = ""
        
        try:
            # Check condition
            if condition == "change":
                should_break = (old_value != new_value)
                break_reason = f"Variable '{variable_name}' changed: {old_value} → {new_value}"
            
            elif condition == "increase":
                if old_value is not None and new_value is not None:
                    try:
                        should_break = (float(new_value) > float(old_value))
                        break_reason = f"Variable '{variable_name}' increased: {old_value} → {new_value}"
                    except (ValueError, TypeError):
                        pass
            
            elif condition == "decrease":
                if old_value is not None and new_value is not None:
                    try:
                        should_break = (float(new_value) < float(old_value))
                        break_reason = f"Variable '{variable_name}' decreased: {old_value} → {new_value}"
                    except (ValueError, TypeError):
                        pass
            
            elif condition.startswith("equals:"):
                target_value = condition[7:]  # Remove 'equals:' prefix
                should_break = (str(new_value) == target_value)
                break_reason = f"Variable '{variable_name}' equals {target_value}: {new_value}"
            
            elif condition.startswith("gt:"):
                target_value = condition[3:]  # Remove 'gt:' prefix
                try:
                    should_break = (float(new_value) > float(target_value))
                    break_reason = f"Variable '{variable_name}' > {target_value}: {new_value}"
                except (ValueError, TypeError):
                    pass
            
            elif condition.startswith("lt:"):
                target_value = condition[3:]  # Remove 'lt:' prefix
                try:
                    should_break = (float(new_value) < float(target_value))
                    break_reason = f"Variable '{variable_name}' < {target_value}: {new_value}"
                except (ValueError, TypeError):
                    pass
            
            if should_break:
                # Update hit count and last value
                bp_info['hit_count'] += 1
                bp_info['last_value'] = new_value
                self.variable_snapshots[variable_name] = new_value
                
                # Breakpoint is now triggered directly in the patched __setattr__ methods
                # This just updates the hit count and logs the event
                print(f"\n🔴 DATA BREAKPOINT HIT: {break_reason}")
                print(f"   Variable: {variable_name}")
                print(f"   Old value: {old_value}")
                print(f"   New value: {new_value}")
            else:
                # Update last value even if not breaking
                bp_info['last_value'] = new_value
                self.variable_snapshots[variable_name] = new_value
                
        except Exception as e:
            print(f"Error checking data breakpoint for '{variable_name}': {e}")

    def _check_data_breakpoint_and_return_break_status(self, variable_name, new_value):
        """
        Check data breakpoints for a variable and return True if a breakpoint should trigger.
        This is similar to _check_data_breakpoint but returns the break status instead of triggering.
        """
        try:
            if variable_name not in self.data_breakpoints:
                return False

            bp_info = self.data_breakpoints[variable_name]
            condition = bp_info['condition']

            # Get old value from snapshot or current value
            old_value = self.variable_snapshots.get(variable_name)
            if old_value is None:
                # Try to get current value from store
                if variable_name.startswith('persistent.'):
                    actual_var = variable_name[11:]  # Remove 'persistent.' prefix
                    if hasattr(renpy.game, 'persistent'):
                        old_value = getattr(renpy.game.persistent, actual_var, None)
                else:
                    old_value = getattr(renpy.store, variable_name, None)

            # Check if breakpoint condition is met
            should_break = False
            break_reason = ""

            if condition == "change":
                # For change conditions, we need to compare against the actual last observed value
                # not just the old_value from this call
                actual_last_value = self.variable_snapshots.get(variable_name)
                should_break = actual_last_value != new_value
                break_reason = f"{variable_name} changed from {actual_last_value} to {new_value}"
            elif condition == "increase":
                # For increase conditions, compare against the last observed value
                actual_last_value = self.variable_snapshots.get(variable_name)
                should_break = (actual_last_value is not None and new_value is not None and
                               isinstance(actual_last_value, (int, float)) and isinstance(new_value, (int, float)) and
                               new_value > actual_last_value)
                break_reason = f"{variable_name} increased from {actual_last_value} to {new_value}"
            elif condition == "decrease":
                # For decrease conditions, compare against the last observed value
                actual_last_value = self.variable_snapshots.get(variable_name)
                should_break = (actual_last_value is not None and new_value is not None and
                               isinstance(actual_last_value, (int, float)) and isinstance(new_value, (int, float)) and
                               new_value < actual_last_value)
                break_reason = f"{variable_name} decreased from {actual_last_value} to {new_value}"
            elif condition.startswith("equals:"):
                target_value = condition[7:]  # Remove "equals:" prefix
                actual_last_value = self.variable_snapshots.get(variable_name)
                try:
                    if isinstance(new_value, (int, float)):
                        target_value = type(new_value)(target_value)
                    # Only break if value changed AND now equals target
                    should_break = new_value == target_value and actual_last_value != new_value
                    break_reason = f"{variable_name} equals {target_value}"
                except (ValueError, TypeError):
                    should_break = str(new_value) == target_value and str(actual_last_value) != str(new_value)
                    break_reason = f"{variable_name} equals '{target_value}'"
            elif condition.startswith("gt:"):
                target_value = condition[3:]  # Remove "gt:" prefix
                actual_last_value = self.variable_snapshots.get(variable_name)
                try:
                    if isinstance(new_value, (int, float)):
                        target_value = type(new_value)(target_value)
                        # Only break if crossing the threshold (wasn't > target before, but is now)
                        was_above_threshold = (actual_last_value is not None and 
                                             isinstance(actual_last_value, (int, float)) and 
                                             actual_last_value > target_value)
                        is_above_threshold = new_value > target_value
                        should_break = is_above_threshold and not was_above_threshold
                        break_reason = f"{variable_name} crossed threshold > {target_value} (value: {new_value})"
                except (ValueError, TypeError):
                    pass
            elif condition.startswith("lt:"):
                target_value = condition[3:]  # Remove "lt:" prefix
                actual_last_value = self.variable_snapshots.get(variable_name)
                try:
                    if isinstance(new_value, (int, float)):
                        target_value = type(new_value)(target_value)
                        # Only break if crossing the threshold (wasn't < target before, but is now)
                        was_below_threshold = (actual_last_value is not None and 
                                             isinstance(actual_last_value, (int, float)) and 
                                             actual_last_value < target_value)
                        is_below_threshold = new_value < target_value
                        should_break = is_below_threshold and not was_below_threshold
                        break_reason = f"{variable_name} crossed threshold < {target_value} (value: {new_value})"
                except (ValueError, TypeError):
                    pass

            if should_break:
                # Update hit count and last value
                bp_info['hit_count'] += 1
                bp_info['last_value'] = new_value
                self.variable_snapshots[variable_name] = new_value

                # Log the breakpoint hit
                print(f"\n🔴 DATA BREAKPOINT HIT: {break_reason}")
                print(f"   Variable: {variable_name}")
                print(f"   Old value: {old_value}")
                print(f"   New value: {new_value}")

                return True
            else:
                # Update last value even if not breaking
                bp_info['last_value'] = new_value
                self.variable_snapshots[variable_name] = new_value
                return False

        except Exception as e:
            print(f"Error checking data breakpoint for '{variable_name}': {e}")
            return False

    def _should_trigger_data_breakpoint(self, variable_name, old_value, new_value):
        """
        Check if a data breakpoint should trigger for the given variable change.
        Returns True if a breakpoint should trigger, False otherwise.
        """
        if variable_name not in self.data_breakpoints:
            return False

        bp_info = self.data_breakpoints[variable_name]
        condition = bp_info['condition']

        try:
            if condition == "change":
                return old_value != new_value
            elif condition == "increase":
                return (old_value is not None and new_value is not None and
                       new_value > old_value)
            elif condition == "decrease":
                return (old_value is not None and new_value is not None and
                       new_value < old_value)
            elif condition.startswith("equals:"):
                target_value = condition[7:]  # Remove "equals:" prefix
                try:
                    # Try to convert to the same type as new_value
                    if isinstance(new_value, (int, float)):
                        target_value = type(new_value)(target_value)
                    return new_value == target_value
                except (ValueError, TypeError):
                    return str(new_value) == target_value
            elif condition.startswith("gt:"):
                target_value = condition[3:]  # Remove "gt:" prefix
                try:
                    if isinstance(new_value, (int, float)):
                        target_value = type(new_value)(target_value)
                        return new_value > target_value
                except (ValueError, TypeError):
                    pass
                return False
            elif condition.startswith("lt:"):
                target_value = condition[3:]  # Remove "lt:" prefix
                try:
                    if isinstance(new_value, (int, float)):
                        target_value = type(new_value)(target_value)
                        return new_value < target_value
                except (ValueError, TypeError):
                    pass
                return False
            else:
                # Unknown condition
                return False

        except Exception as e:
            print(f"Error evaluating data breakpoint condition '{condition}': {e}")
            return False

    def _trigger_data_breakpoint_here(self, variable_name, old_value, new_value):
        """
        Trigger a data breakpoint immediately with proper .rpy context.
        This tries to find the current .rpy context and break there directly.
        """
        # Prevent duplicate triggers for the same variable change
        if (self.pending_data_breakpoint and 
            self.pending_data_breakpoint.get('variable_name') == variable_name and
            self.pending_data_breakpoint.get('new_value') == new_value):
            return  # Already have a pending breakpoint for this change

        # Try to get current .rpy execution context
        current_rpy_file, current_rpy_line = self._find_current_rpy_context()
        
        # Also try a more thorough approach to find the exact line
        exact_file, exact_line = self._find_exact_assignment_line()
        
        # Use the more specific line if we found it
        if exact_file and exact_line:
            current_rpy_file, current_rpy_line = exact_file, exact_line
            print(f"🎯 Found exact assignment line: {exact_file}:{exact_line}")
        elif current_rpy_file and current_rpy_line:
            print(f"🔍 Using general context: {current_rpy_file}:{current_rpy_line}")
        
        if current_rpy_file and current_rpy_line:
            # We have .rpy context, trigger breakpoint immediately
            print(f"\n{'='*60}")
            print(f"🔍 DATA BREAKPOINT HIT")
            print(f"📁 File: {current_rpy_file}")
            print(f"📍 Line: {current_rpy_line}")
            print(f"🔄 Variable: {variable_name}")
            print(f"📊 Change: {old_value} → {new_value}")
            print(f"{'='*60}\n")
            
            # Update current context for debugger
            self.current_file = current_rpy_file
            self.current_line = current_rpy_line
            self.current_type = 'script'
            
            # Trigger VSCode breakpoint immediately
            if self.debugpy_enabled:
                self._trigger_immediate_vscode_breakpoint(variable_name, old_value, new_value)
            else:
                # Store for custom debugging
                self.pending_data_breakpoint = {
                    'variable_name': variable_name,
                    'old_value': old_value,
                    'new_value': new_value,
                    'breakpoint_type': 'data_breakpoint'
                }
                self._custom_data_breakpoint_pause(self.pending_data_breakpoint)
        else:
            # No .rpy context found, defer to next script statement
            self.pending_data_breakpoint = {
                'variable_name': variable_name,
                'old_value': old_value,
                'new_value': new_value,
                'breakpoint_type': 'data_breakpoint'
            }
            
            print(f"\n{'='*60}")
            print(f"🔍 DATA BREAKPOINT TRIGGERED")
            print(f"🔄 Variable: {variable_name}")
            print(f"📊 Change: {old_value} → {new_value}")
            print(f"⏳ Will break on next script statement...")
            print(f"{'='*60}\n")

    def _find_current_rpy_context(self):
        """
        Find the current .rpy execution context using stack inspection to find the exact line.
        Returns (filename, line_number) or (None, None) if not found.
        """
        # First try stack inspection to find the exact line where the variable was changed
        try:
            import inspect
            current_frame = inspect.currentframe()
            try:
                frame = current_frame
                best_rpy_location = None
                
                while frame:
                    frame = frame.f_back
                    if frame is None:
                        break

                    filename = frame.f_code.co_filename

                    # Skip debugger frames
                    if ('debugger.py' in filename or 'testing/' in filename):
                        continue

                    # Direct .rpy files (best case - this is what we want!)
                    if filename.endswith('.rpy'):
                        # This is likely the exact line where the variable assignment happened
                        return os.path.basename(filename), frame.f_lineno

                    # Ren'Py execution frames - look for node information
                    if ('ast.py' in filename or 'script.py' in filename or 'python.py' in filename):
                        try:
                            frame_locals = frame.f_locals
                            node = frame_locals.get('node')
                            if node and hasattr(node, 'filename') and hasattr(node, 'linenumber'):
                                # Store this as a fallback, but keep looking for direct .rpy frames
                                best_rpy_location = (os.path.basename(node.filename), node.linenumber)
                        except Exception:
                            pass

                # If we didn't find a direct .rpy frame, use the best node information we found
                if best_rpy_location:
                    return best_rpy_location

            finally:
                del current_frame
        except Exception:
            pass

        # Fallback to current debugger context (but this might be the label line)
        if (hasattr(self, 'current_file') and hasattr(self, 'current_line') and 
            self.current_file and self.current_line and self.current_file.endswith('.rpy')):
            # Add some debugging info to see what we're getting
            print(f"🔍 Using debugger context: {self.current_file}:{self.current_line}")
            return self.current_file, self.current_line
        
        # Last resort: try current node context
        if (hasattr(self, 'current_node') and self.current_node and
            hasattr(self.current_node, 'filename') and hasattr(self.current_node, 'linenumber')):
            print(f"🔍 Using node context: {os.path.basename(self.current_node.filename)}:{self.current_node.linenumber}")
            return os.path.basename(self.current_node.filename), self.current_node.linenumber

        return None, None

    def _find_exact_assignment_line(self):
        """
        Try to find the exact line where the variable assignment happened by looking
        for frames that show Python execution within .rpy files.
        """
        try:
            import inspect
            current_frame = inspect.currentframe()
            try:
                frame = current_frame
                frame_info = []
                
                # Collect information about all frames
                while frame:
                    frame = frame.f_back
                    if frame is None:
                        break

                    filename = frame.f_code.co_filename
                    line_no = frame.f_lineno
                    
                    # Debug: collect frame info
                    frame_info.append(f"{os.path.basename(filename)}:{line_no}")
                    
                    # Skip debugger frames
                    if ('debugger.py' in filename or 'testing/' in filename):
                        continue

                    # Look for Python execution frames that might correspond to $ statements
                    if ('python.py' in filename or 'execution.py' in filename or 'ast.py' in filename):
                        # Try to find the .rpy context from frame locals
                        try:
                            frame_locals = frame.f_locals
                            
                            # Look for execution context indicators
                            if 'node' in frame_locals:
                                node = frame_locals['node']
                                if hasattr(node, 'filename') and hasattr(node, 'linenumber'):
                                    rpy_file = os.path.basename(node.filename)
                                    if rpy_file.endswith('.rpy'):
                                        # Check if this looks like a Python statement node ($ variable = value)
                                        node_type = type(node).__name__ if hasattr(node, '__class__') else 'unknown'
                                        if 'Python' in node_type or 'Statement' in node_type:
                                            print(f"🎯 Found {node_type} node at {rpy_file}:{node.linenumber}")
                                            return rpy_file, node.linenumber
                                        else:
                                            print(f"🔍 Found {node_type} node at {rpy_file}:{node.linenumber}")
                            
                            # Look for other context clues
                            if 'filename' in frame_locals and 'linenumber' in frame_locals:
                                filename_val = frame_locals['filename']
                                line_val = frame_locals['linenumber']
                                if filename_val and str(filename_val).endswith('.rpy'):
                                    return os.path.basename(filename_val), line_val
                            
                            # Look for self.filename and self.linenumber (might be in a node object)
                            if 'self' in frame_locals:
                                self_obj = frame_locals['self']
                                if (hasattr(self_obj, 'filename') and hasattr(self_obj, 'linenumber') and
                                    str(self_obj.filename).endswith('.rpy')):
                                    return os.path.basename(self_obj.filename), self_obj.linenumber
                                    
                        except Exception:
                            pass

                print(f"🔍 Frame analysis: {' -> '.join(frame_info[:8])}")

            finally:
                del current_frame
        except Exception as e:
            print(f"Error in exact line detection: {e}")

        return None, None

    def _trigger_immediate_vscode_breakpoint(self, variable_name, old_value, new_value):
        """
        Trigger an immediate VSCode breakpoint with proper .rpy file context.
        Uses the same approach as regular breakpoints to create a fake frame from the .rpy file.
        """
        try:
            import debugpy
            import sys
            
            # Get full path to .rpy file
            rpy_file_path = self._get_full_rpy_path(self.current_file)
            
            if rpy_file_path:
                # Store debugging context
                debug_context = {
                    'variable_name': variable_name,
                    'old_value': old_value,
                    'new_value': new_value,
                    'breakpoint_type': 'data_breakpoint',
                    'rpy_file': self.current_file,
                    'rpy_line': self.current_line
                }

                # Make context available globally
                if not hasattr(sys, '_renpy_data_breakpoint_context'):
                    sys._renpy_data_breakpoint_context = {}
                sys._renpy_data_breakpoint_context.update(debug_context)

                print(f"💡 In the debugger, you can:")
                print(f"   • Inspect '{variable_name}' (current value: {new_value})")
                print(f"   • Check 'sys._renpy_data_breakpoint_context' for full context")
                print(f"   • View all variables with the Variables panel")

                # Show source line if available
                source_line = self._get_source_line(self.current_file, self.current_line)
                if source_line:
                    print(f"📝 Source: {source_line.strip()}")

                # Create a fake execution context that appears to be from the .rpy file
                # This is the same approach used in _handle_vscode_breakpoint for regular breakpoints
                try:
                    # Create code that includes the breakpoint call and will be executed "from" the .rpy file
                    # This is the key: we put debugpy.breakpoint() inside the code that's compiled with .rpy as source
                    # We need to pad the code to the correct line number
                    target_line = self.current_line
                    padding_lines = '\n' * (target_line - 1) if target_line > 1 else ''
                    
                    code_str = f'''{padding_lines}import debugpy; debugpy.breakpoint()  # Data breakpoint: {variable_name} changed from {old_value} to {new_value}'''
                    
                    # Compile with the .rpy filename so debugger sees it correctly
                    code = compile(code_str, rpy_file_path, 'exec', dont_inherit=True)
                    
                    # Create execution context with debugging variables
                    exec_globals = {
                        '__file__': rpy_file_path,
                        '__name__': f"renpy_{self.current_file}",
                        'data_breakpoint_info': debug_context,
                        variable_name: new_value,  # Make the changed variable available
                        'rpy_file': rpy_file_path,
                        'rpy_line': self.current_line
                    }
                    
                    # Add all current Ren'Py store variables to the context
                    try:
                        exec_globals.update(renpy.store.__dict__)
                    except:
                        pass
                    
                    # Execute this code - the debugpy.breakpoint() call inside will appear 
                    # to be called from the .rpy file location!
                    exec(code, exec_globals)
                    
                except Exception as compile_error:
                    print(f"Failed to create .rpy execution context: {compile_error}")
                    # Fallback to regular breakpoint
                    debugpy.breakpoint()
            else:
                print(f"❌ Could not find full path for {self.current_file}")
                debugpy.breakpoint()  # Fallback breakpoint
                
        except ImportError:
            print("❌ debugpy not available")
        except Exception as e:
            print(f"Error triggering immediate VSCode breakpoint: {e}")
            import traceback
            traceback.print_exc()

    def _find_source_location_for_data_breakpoint(self):
        """
        Find the .rpy file and line number where a variable assignment happened.
        Returns (filename, line_number) or (None, None) if not found.
        """
        try:
            import inspect

            # First try to use the current debugging context if available
            if hasattr(self, 'current_file') and hasattr(self, 'current_line'):
                if self.current_file and self.current_line and self.current_file.endswith('.rpy'):
                    return self.current_file, self.current_line

            # Walk up the stack to find the .rpy file or Ren'Py execution frame
            current_frame = inspect.currentframe()
            try:
                frame = current_frame
                rpy_frame = None
                renpy_execution_frame = None
                
                while frame:
                    frame = frame.f_back
                    if frame is None:
                        break

                    filename = frame.f_code.co_filename

                    # Skip debugger frames to avoid stopping at debugger code
                    if ('debugger.py' in filename or 
                        'testing/' in filename or
                        '__pycache__' in filename):
                        continue

                    # Direct .rpy files (best case)
                    if filename.endswith('.rpy'):
                        rpy_frame = (os.path.basename(filename), frame.f_lineno)
                        break

                    # Ren'Py script execution frames (next best case)
                    if ('ast.py' in filename or 'script.py' in filename or 
                        'python.py' in filename or 'execution.py' in filename):
                        if renpy_execution_frame is None:
                            renpy_execution_frame = frame

                # Return direct .rpy frame if found
                if rpy_frame:
                    return rpy_frame

                # Try to extract .rpy context from Ren'Py execution frame
                if renpy_execution_frame:
                    # Look for Ren'Py context in frame locals/globals
                    try:
                        frame_locals = renpy_execution_frame.f_locals
                        frame_globals = renpy_execution_frame.f_globals
                        
                        # Try to find node information in frame
                        node = frame_locals.get('node') or frame_globals.get('node')
                        if node and hasattr(node, 'filename') and hasattr(node, 'linenumber'):
                            return os.path.basename(node.filename), node.linenumber
                            
                        # Try to find current execution context
                        if hasattr(self, 'current_node') and self.current_node:
                            if hasattr(self.current_node, 'filename') and hasattr(self.current_node, 'linenumber'):
                                return os.path.basename(self.current_node.filename), self.current_node.linenumber
                                
                    except Exception:
                        pass

            finally:
                del current_frame  # Prevent reference cycles

        except Exception as e:
            print(f"Error finding source location: {e}")

        return None, None

    def get_call_stack(self):
        """Get current call stack."""
        stack = []
        
        try:
            # Current location
            if self.current_node:
                stack.append({
                    'filename': self.current_file,
                    'line': self.current_line,
                    'function': type(self.current_node).__name__,
                    'type': self.current_type
                })
                
            # Ren'Py call stack
            if renpy.game.context:
                context = renpy.game.context()
                for call_site in context.call_location_stack:
                    try:
                        node = renpy.game.script.lookup(call_site)
                        stack.append({
                            'filename': os.path.basename(node.filename),
                            'line': node.linenumber,
                            'function': str(node.name) if node.name else 'unknown',
                            'type': 'call'
                        })
                    except Exception:
                        pass
                        
        except Exception as e:
            stack.append({'error': str(e)})
            
        return stack

    def _current_call_depth(self):
        try:
            if renpy.game.context:
                return len(renpy.game.context().call_location_stack)
        except Exception:
            pass
        return 0
    
    def _should_break(self):
        """Check if we should break at the current location."""
        # Handle pending data breakpoints first
        if self.pending_data_breakpoint:
            return True
            
        # Handle step mode with depth semantics
        if self.step_mode:
            depth = self._current_call_depth()
            origin_file, origin_line = self.step_origin if self.step_origin else (None, None)
            changed = (self.current_file, self.current_line) != (origin_file, origin_line)
            should = False
            if self.step_type == 'in':
                should = changed
            elif self.step_type == 'over':
                should = changed and (depth is not None and self.step_depth is not None and depth <= self.step_depth)
            elif self.step_type == 'out':
                should = (depth is not None and self.step_depth is not None and depth < self.step_depth)
            else:
                should = changed

            if should:
                self.step_mode = False
                self.last_break_reason = 'step'
                return True
            else:
                return False
            
        # Check breakpoints
        if self.current_file in self.breakpoints:
            if self.current_line in self.breakpoints[self.current_file]:
                bp_info = self.breakpoints[self.current_file][self.current_line]
                
                if not bp_info['enabled']:
                    return False
                    
                # Check condition if present
                if bp_info['condition']:
                    try:
                        result = renpy.python.py_eval(bp_info['condition'])
                        if not result:
                            return False
                    except Exception as e:
                        print(f"Breakpoint condition error: {e}")
                        
                # Increment hit count
                bp_info['hit_count'] += 1
                self.last_break_reason = 'breakpoint'
                return True
                
        return False
    
    def _pause_execution(self, reason):
        """Pause execution and wait for debug commands."""
        # Handle data breakpoints
        if self.pending_data_breakpoint:
            self._handle_data_breakpoint_pause()
            return

        with self.pause_lock:
            self.paused = True
            self.pause_event.clear()

        # Notify DAP server if present
        try:
            if self.pause_listener:
                # Prefer the computed last_break_reason for DAP mapping
                pause_reason = (self.last_break_reason or reason or 'breakpoint')
                self.pause_listener(pause_reason, self.get_current_state())
        except Exception:
            pass

        print(f"\n=== EXECUTION PAUSED ===")
        print(f"Reason: {reason}")
        print(f"Type: {self.current_type}")
        print(f"Location: {self.current_file}:{self.current_line}")
        
        if self.current_node:
            print(f"Node: {type(self.current_node).__name__}")
            
        # Show source line if available
        source_line = self._get_source_line(self.current_file, self.current_line)
        if source_line:
            print(f"Source: {source_line.strip()}")
            
        # Wait for continue/step command
        self.pause_event.wait()
    
    def _handle_data_breakpoint_pause(self):
        """Handle pausing execution for a data breakpoint."""
        if not self.pending_data_breakpoint:
            return
            
        data_bp = self.pending_data_breakpoint
        self.pending_data_breakpoint = None  # Clear the pending breakpoint
        
        if self.debugpy_enabled:
            try:
                import debugpy
                import sys
                
                # Store comprehensive debugging context
                debug_context = {
                    'variable_name': data_bp['variable_name'],
                    'old_value': data_bp['old_value'],
                    'new_value': data_bp['new_value'],
                    'breakpoint_type': 'data_breakpoint',
                    'rpy_file': self.current_file,
                    'rpy_line': self.current_line
                }

                # Make context available globally for debugger access
                if not hasattr(sys, '_renpy_data_breakpoint_context'):
                    sys._renpy_data_breakpoint_context = {}
                sys._renpy_data_breakpoint_context.update(debug_context)

                # Print detailed debugging information
                print(f"\n{'='*60}")
                print(f"🔍 DATA BREAKPOINT HIT AT SOURCE LOCATION")
                print(f"📁 File: {self.current_file}")
                print(f"📍 Line: {self.current_line}")
                print(f"🔄 Variable: {data_bp['variable_name']}")
                print(f"📊 Change: {data_bp['old_value']} → {data_bp['new_value']}")
                
                # Show source line if available
                source_line = self._get_source_line(self.current_file, self.current_line)
                if source_line:
                    print(f"📝 Source: {source_line.strip()}")
                    
                print(f"{'='*60}")
                print(f"💡 In the debugger, you can:")
                print(f"   • Inspect '{data_bp['variable_name']}' (current value: {data_bp['new_value']})")
                print(f"   • Check 'sys._renpy_data_breakpoint_context' for full context")
                print(f"   • View all variables with the Variables panel")
                print(f"{'='*60}\n")

                # Trigger the debugger breakpoint at the current .rpy location
                debugpy.breakpoint()
                
            except ImportError:
                print("❌ debugpy not available, using custom pause")
                self._custom_data_breakpoint_pause(data_bp)
            except Exception as e:
                print(f"Error triggering VSCode data breakpoint: {e}")
                self._custom_data_breakpoint_pause(data_bp)
        else:
            self._custom_data_breakpoint_pause(data_bp)
    
    def _custom_data_breakpoint_pause(self, data_bp):
        """Handle data breakpoint pause for non-VSCode debugging."""
        with self.pause_lock:
            self.paused = True
            self.pause_event.clear()

        # Notify DAP server if present
        try:
            if self.pause_listener:
                self.pause_listener("data_breakpoint", self.get_current_state())
        except Exception:
            pass
            
        print(f"\n=== DATA BREAKPOINT PAUSED ===")
        print(f"Variable: {data_bp['variable_name']}")
        print(f"Change: {data_bp['old_value']} → {data_bp['new_value']}")
        print(f"Location: {self.current_file}:{self.current_line}")
        
        if self.current_node:
            print(f"Node: {type(self.current_node).__name__}")
            
        # Show source line if available
        source_line = self._get_source_line(self.current_file, self.current_line)
        if source_line:
            print(f"Source: {source_line.strip()}")
            
        print("Use continue_execution() or step() to proceed")
        
        # Wait for continue/step command
        self.pause_event.wait()
    
    def _patch_python_execution(self):
        """Patch Python execution to enable debugging of Python blocks."""
        if self.original_py_exec is not None:
            return  # Already patched
            
        self.original_py_exec = renpy.python.py_exec_bytecode
        
        def patched_py_exec_bytecode(bytecode, hide=False, globals=None, locals=None, store="store"):
            # Capture variable state before execution for data breakpoints
            pre_execution_vars = {}
            if self.data_breakpoint_enabled:
                # Capture current values of watched variables
                for var_name in self.data_breakpoints.keys():
                    if var_name.startswith('persistent.'):
                        actual_var = var_name[11:]  # Remove 'persistent.' prefix
                        if hasattr(renpy.game, 'persistent'):
                            pre_execution_vars[var_name] = getattr(renpy.game.persistent, actual_var, None)
                    else:
                        pre_execution_vars[var_name] = getattr(renpy.store, var_name, None)
            
            # Check for breakpoints in Python code
            if self.enabled and self.python_enabled:
                # Try to extract source info from bytecode
                source_info = self._get_python_source_info(bytecode)
                if source_info:
                    self.current_file = source_info['filename']
                    self.current_line = source_info['line']
                    self.current_type = 'python'
                    
                    if self._should_break():
                        self._pause_execution("Breakpoint")
            
            # Call original function
            result = self.original_py_exec(bytecode, hide, globals, locals, store)
            
            # Check for data breakpoints after execution
            if self.data_breakpoint_enabled:
                # Check if any watched variables changed
                for var_name in self.data_breakpoints.keys():
                    old_value = pre_execution_vars.get(var_name)
                    if var_name.startswith('persistent.'):
                        actual_var = var_name[11:]  # Remove 'persistent.' prefix
                        if hasattr(renpy.game, 'persistent'):
                            new_value = getattr(renpy.game.persistent, actual_var, None)
                        else:
                            new_value = None
                    else:
                        new_value = getattr(renpy.store, var_name, None)
                    
                    # Check if value changed
                    if old_value != new_value:
                        print(f"🔍 Python execution changed {var_name}: {old_value} → {new_value}")
                        should_break = self._check_data_breakpoint_and_return_break_status(var_name, new_value)

                        # Trigger breakpoint if needed - this will break at the correct .rpy location
                        if should_break:
                            print(f"🔍 Data breakpoint triggered in Python execution: {var_name} = {new_value}")
                            self._trigger_data_breakpoint_here(var_name, old_value, new_value)
            
            return result
        
        renpy.python.py_exec_bytecode = patched_py_exec_bytecode
    
    def _unpatch_python_execution(self):
        """Restore original Python execution."""
        if self.original_py_exec is not None:
            renpy.python.py_exec_bytecode = self.original_py_exec
            self.original_py_exec = None
    
    def _trace_function(self, frame, event, arg):
        """Trace function for Python debugging."""
        if event == 'line' and self.enabled and self.python_enabled:
            # Check if this is .rpy Python code
            filename = frame.f_code.co_filename
            if filename.endswith('.rpy'):
                self.current_file = os.path.basename(filename)
                self.current_line = frame.f_lineno
                self.current_type = 'python'
                
                if self._should_break():
                    self._pause_execution(self.last_break_reason)
                    
        # Call original trace function
        if self.original_trace:
            return self.original_trace(frame, event, arg)
            
        return self._trace_function
    
    def _get_python_source_info(self, bytecode):
        """Extract source info from Python bytecode."""
        try:
            if hasattr(bytecode, 'co_filename') and hasattr(bytecode, 'co_firstlineno'):
                filename = bytecode.co_filename
                if filename.endswith('.rpy'):
                    return {
                        'filename': os.path.basename(filename),
                        'line': bytecode.co_firstlineno
                    }
        except Exception:
            pass
        return None
    
    def _get_source_line(self, filename, line_number):
        """Get source line from .rpy file."""
        try:
            # Find the .rpy file
            full_path = None
            
            if renpy.config.gamedir:
                full_path = os.path.join(renpy.config.gamedir, filename)
                
            if not full_path or not os.path.exists(full_path):
                for search_dir in ['.', 'game', renpy.config.basedir]:
                    if search_dir:
                        test_path = os.path.join(search_dir, filename)
                        if os.path.exists(test_path):
                            full_path = test_path
                            break
                            
            if full_path and os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if 1 <= line_number <= len(lines):
                        return lines[line_number - 1]
                        
        except Exception:
            pass
            
        return None
    
    def _deep_copy_breakpoints(self):
        """Create a deep copy of breakpoints for state preservation."""
        copy = {}
        for filename, line_map in self.breakpoints.items():
            copy[filename] = {}
            for line, bp_info in line_map.items():
                copy[filename][line] = {
                    'enabled': bp_info['enabled'],
                    'condition': bp_info['condition'],
                    'hit_count': bp_info['hit_count']
                }
        return copy
    
    def _restore_debugpy_connection(self, port):
        """Attempt to restore debugpy connection after reload."""
        try:
            # Don't restart if already connected
            if self.debugpy_enabled:
                return
                
            self.enable_vscode_debugging(port, wait_for_client=False)
            print(f"Debugpy connection restored on port {port}")
        except Exception as e:
            print(f"Failed to restore debugpy connection: {e}")
    
    def _validate_source_mappings(self):
        """Validate and update source mappings after script reload."""
        if not self.source_mapping:
            return
            
        # Check if mapped files still exist and update if necessary
        invalid_mappings = []
        for rpy_file, virtual_file in self.source_mapping.items():
            if not os.path.exists(rpy_file):
                invalid_mappings.append(rpy_file)
                continue
                
            # Update virtual file content if rpy file changed
            if os.path.exists(virtual_file):
                try:
                    rpy_mtime = os.path.getmtime(rpy_file)
                    virtual_mtime = os.path.getmtime(virtual_file)
                    if rpy_mtime > virtual_mtime:
                        self._update_virtual_file_content(rpy_file, virtual_file)
                except Exception as e:
                    print(f"Error updating virtual file {virtual_file}: {e}")
        
        # Remove invalid mappings
        for rpy_file in invalid_mappings:
            del self.source_mapping[rpy_file]
    
    def _update_virtual_file_content(self, rpy_file, virtual_file):
        """Update virtual file content to match rpy file after reload."""
        try:
            with open(rpy_file, 'r', encoding='utf-8') as f:
                rpy_content = f.read()
            
            # Convert rpy content to debuggable Python
            python_content = self._convert_rpy_to_debuggable_python(rpy_content)
            
            with open(virtual_file, 'w', encoding='utf-8') as f:
                f.write(python_content)
                
        except Exception as e:
            print(f"Failed to update virtual file {virtual_file}: {e}")


# Global debugger instance
_debugger = None
# Indicates if the native DAP debugger is running
native_debug_enabled = False

def get_debugger():
    """Get the global debugger instance."""
    global _debugger
    if _debugger is None:
        _debugger = RenpyDebugger()
    return _debugger

# Public API
def enable():
    """Enable the debugger."""
    get_debugger().enable()

def disable():
    """Disable the debugger."""
    get_debugger().disable()

def enable_python():
    """Enable Python debugging for .rpy Python blocks."""
    get_debugger().enable_python_debugging()

def disable_python():
    """Disable Python debugging."""
    get_debugger().disable_python_debugging()

def set_breakpoint(filename, line_number, condition=None):
    """Set a breakpoint in a .rpy file."""
    return get_debugger().set_breakpoint(filename, line_number, condition)

def clear_breakpoint(filename, line_number):
    """Clear a breakpoint."""
    return get_debugger().clear_breakpoint(filename, line_number)

def clear_all_breakpoints(filename=None):
    """Clear all breakpoints."""
    get_debugger().clear_all_breakpoints(filename)

def list_breakpoints():
    """List all breakpoints."""
    return get_debugger().list_breakpoints()

def continue_execution():
    """Continue execution from a breakpoint."""
    get_debugger().continue_execution()

def step():
    """Step one statement."""
    get_debugger().step_in()

def step_in():
    """Step into."""
    get_debugger().step_in()

def step_over():
    """Step over."""
    get_debugger().step_over()

def step_out():
    """Step out."""
    get_debugger().step_out()

def get_state():
    """Get current debugging state."""
    return get_debugger().get_current_state()

def get_variables():
    """Get current variables."""
    return get_debugger().get_variables()

def get_call_stack():
    """Get call stack."""
    return get_debugger().get_call_stack()

def check_breakpoint(node):
    """Check for breakpoints (called from execution loop)."""
    get_debugger().check_script_breakpoint(node)

def enable_vscode_debugging(port=5678, wait_for_client=False):
    """Enable VSCode debugging via debugpy."""
    return get_debugger().enable_vscode_debugging(port, wait_for_client)

def disable_vscode_debugging():
    """Disable VSCode debugging."""
    get_debugger().disable_vscode_debugging()

def is_vscode_debugging_enabled():
    """Check if VSCode debugging is enabled."""
    return get_debugger().debugpy_enabled

def get_virtual_files_directory():
    """Get the directory containing virtual Python files for .rpy debugging."""
    debugger = get_debugger()
    return debugger.virtual_files_dir

def create_virtual_file(rpy_filename):
    """Create virtual Python file for a .rpy file."""
    return get_debugger()._create_virtual_python_file(rpy_filename)

# ===== DATA BREAKPOINT API =====

def add_data_breakpoint(variable_name, condition="change", access_type="write"):
    """
    Add a data breakpoint that triggers when a variable changes.
    
    Args:
        variable_name (str): Name of variable to watch (e.g., "health", "persistent.score")
        condition (str): Condition for breaking:
            - "change": Break on any value change (default)
            - "increase": Break when value increases
            - "decrease": Break when value decreases  
            - "equals:VALUE": Break when value equals VALUE
            - "gt:VALUE": Break when value greater than VALUE
            - "lt:VALUE": Break when value less than VALUE
        access_type (str): "read", "write", or "both" (currently only "write" supported)
        
    Returns:
        int: Data breakpoint ID
        
    Example:
        # Break when health changes
        add_data_breakpoint("health")
        
        # Break when score increases
        add_data_breakpoint("persistent.score", "increase")
        
        # Break when money reaches exactly 1000
        add_data_breakpoint("money", "equals:1000")
    """
    return get_debugger().add_data_breakpoint(variable_name, condition, access_type)

def remove_data_breakpoint(variable_name):
    """Remove a data breakpoint by variable name."""
    return get_debugger().remove_data_breakpoint(variable_name)

def list_data_breakpoints():
    """List all active data breakpoints with their current status."""
    return get_debugger().list_data_breakpoints()

def clear_all_data_breakpoints():
    """Remove all data breakpoints."""
    debugger = get_debugger()
    removed_count = 0
    for var_name in list(debugger.data_breakpoints.keys()):
        if debugger.remove_data_breakpoint(var_name):
            removed_count += 1
    print(f"Removed {removed_count} data breakpoints")
    return removed_count

def test_debugpy_connection():
    """Test if debugpy is properly connected and can trigger breakpoints."""
    debugger = get_debugger()
    if not debugger.debugpy_enabled:
        print("❌ debugpy is not enabled. Enable with:")
        print("   dbg.enable_vscode_debugging(5678)")
        return False
    
    try:
        import debugpy
        print("✅ debugpy is available and enabled")
        print(f"   Port: {debugger.debugpy_port}")
        
        # Test if we can trigger a simple breakpoint
        response = input("Test debugpy breakpoint now? (y/n): ")
        if response.lower() == 'y':
            print("🔴 Triggering test breakpoint - VSCode should pause now...")
            debugpy.breakpoint()
            print("✅ Test breakpoint completed")
        
        return True
    except ImportError:
        print("❌ debugpy is not available. Install with: pip install debugpy")
        return False
    except Exception as e:
        print(f"❌ debugpy error: {e}")
        return False

def test_variable_patching():
    """Test if variable change detection is working."""
    debugger = get_debugger()
    
    print("\n=== Testing Variable Change Detection ===")
    print(f"Debugger enabled: {debugger.enabled}")
    print(f"Data breakpoint monitoring: {debugger.data_breakpoint_enabled}")
    print(f"Store patching active: {hasattr(debugger, '_original_store_setattr')}")
    
    # Test direct store assignment
    print("\nTesting direct store assignment...")
    try:
        renpy.store.test_direct = 999
        print("Direct assignment completed")
    except Exception as e:
        print(f"Direct assignment failed: {e}")
    
    # Test dictionary assignment (this is what $ variable = value uses)
    print("\nTesting dictionary assignment...")
    try:
        renpy.store['test_dict'] = 888
        print("Dictionary assignment completed")
    except Exception as e:
        print(f"Dictionary assignment failed: {e}")
    
    return True

def test_data_breakpoint_flow():
    """Test the complete data breakpoint flow with debugging output."""
    debugger = get_debugger()
    
    print("\n=== Testing Data Breakpoint Flow ===")
    
    # Enable debugger if not already enabled
    if not debugger.enabled:
        debugger.enable()
    
    # Add a test data breakpoint
    print("Adding data breakpoint for 'flow_test_var'...")
    add_data_breakpoint("flow_test_var", "change")
    
    print(f"Data breakpoints: {list(debugger.data_breakpoints.keys())}")
    print(f"Pending breakpoint: {debugger.pending_data_breakpoint}")
    
    # Test variable change
    print("Changing variable...")
    renpy.store.flow_test_var = 123
    
    print(f"After change - Pending breakpoint: {debugger.pending_data_breakpoint}")
    
    # Simulate script execution check
    print("Simulating script execution check...")
    if debugger.pending_data_breakpoint:
        print("✅ Pending data breakpoint detected!")
        print(f"Should break: {debugger._should_break()}")
    else:
        print("❌ No pending data breakpoint found")
    
    return True
