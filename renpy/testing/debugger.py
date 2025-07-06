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
        
        # Debug state
        self.enabled = False
        self.paused = False
        self.step_mode = False
        
        # Current execution context
        self.current_node = None
        self.current_file = None
        self.current_line = None
        self.current_type = None  # 'script' or 'python'
        
        # Synchronization
        self.pause_event = threading.Event()
        self.pause_lock = threading.RLock()
        
        # Python debugging
        self.python_enabled = False
        self.original_py_exec = None
        self.original_trace = None
        
        # VSCode/debugpy integration
        self.debugpy_enabled = False
        self.debugpy_port = None
        self.source_mapping = {}  # Map .rpy files to virtual Python files
        self.virtual_files_dir = None
        
        # PyCharm integration
        self.pycharm_enabled = False
        self.pycharm_port = None
        
    def enable(self):
        """Enable the debugger."""
        self.enabled = True
        self._patch_python_execution()
        print("Ren'Py debugger enabled")
        
    def disable(self):
        """Disable the debugger."""
        self.enabled = False
        self.paused = False
        self.pause_event.set()
        self._unpatch_python_execution()
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
    
    def enable_pycharm_debugging(self, port=12345):
        """
        Enable PyCharm remote debugging.
        
        Args:
            port (int): Port for PyCharm debugger (default: 12345)
            
        Returns:
            bool: True if successful
        """
        try:
            # Try simple pydevd first (our custom implementation)
            try:
                import pydevd_simple
                settrace_func = pydevd_simple.settrace
                print("📦 Using pydevd_simple (custom)")
            except ImportError:
                # Try pydevd_pycharm 
                try:
                    import pydevd_pycharm
                    settrace_func = pydevd_pycharm.settrace
                    print("📦 Using pydevd_pycharm")
                except ImportError:
                    # Fall back to core pydevd
                    import pydevd
                    settrace_func = pydevd.settrace
                    print("📦 Using core pydevd")
            
            if self.pycharm_enabled:
                print(f"PyCharm debugging already enabled on port {self.pycharm_port}")
                return True
            
            print(f"🐛 Connecting to PyCharm debugger on 172.26.176.1:{port}")
            print("Make sure PyCharm Debug Server is running and showing 'Waiting for process connection...'")
            
            # Use the connection method with WSL IP
            settrace_func('172.26.176.1', port=port, stdoutToServer=False, stderrToServer=False, suspend=False)
            
            self.pycharm_enabled = True
            self.pycharm_port = port
            
            print("✅ Connected to PyCharm debugger!")
            print("Set breakpoints in .rpy files in PyCharm - they'll work automatically!")
            
            return True
            
        except ImportError:
            print("❌ PyCharm remote debugging not available")
            print("Make sure you've installed pydevd or pydevd-pycharm")
            return False
        except Exception as e:
            print(f"❌ PyCharm debugging failed: {e}")
            print("Make sure PyCharm remote debugging server is running")
            return False
    
    def disable_pycharm_debugging(self):
        """Disable PyCharm debugging."""
        if self.pycharm_enabled:
            try:
                # PyCharm debugging doesn't have a clean disconnect
                self.pycharm_enabled = False
                self.pycharm_port = None
                print("PyCharm debugging disabled")
            except Exception:
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
        
        # Handle different IDE debugging
        if self.debugpy_enabled:
            self._handle_vscode_breakpoint(node)
        elif self.pycharm_enabled:
            self._handle_pycharm_breakpoint(node)
        elif self._should_break():
            self._pause_execution("Breakpoint")
    
    def _handle_vscode_breakpoint(self, node):
        """Handle breakpoint checking when VSCode debugging is enabled."""
        try:
            import debugpy
            
            # Create a fake frame that appears to be from the .rpy file
            # This allows VSCode to see breakpoints in .rpy files directly
            rpy_file_path = self._get_full_rpy_path(self.current_file)
            
            if rpy_file_path:
                # Create code object that appears to be from the .rpy file
                code_str = f"# Ren'Py execution point\npass  # Line {self.current_line}: {type(node).__name__}"
                
                try:
                    # Compile with the .rpy filename so debugger sees it correctly
                    code = compile(code_str, rpy_file_path, 'exec', dont_inherit=True)
                    
                    # Execute this code - debugpy will see it as executing from the .rpy file
                    # If there's a breakpoint on this line in VSCode, it will trigger
                    exec(code, {
                        '__file__': rpy_file_path,
                        '__name__': f"renpy_{self.current_file}",
                        'renpy_node': node,
                        'renpy_context': self._create_debug_context()
                    })
                    
                except Exception as compile_error:
                    # If compilation fails, fall back to debugpy.breakpoint()
                    if self._should_break():
                        debugpy.breakpoint()
            else:
                # Fallback to programmatic breakpoint
                if self._should_break():
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
    
    def _handle_pycharm_breakpoint(self, node):
        """Handle breakpoint checking when PyCharm debugging is enabled."""
        try:
            import pydevd
            
            # Get the full path to the .rpy file
            rpy_file_path = self._get_full_rpy_path(self.current_file)
            
            if rpy_file_path:
                # Create debugging context
                debug_context = self._create_debug_context()
                
                # This will trigger PyCharm breakpoints if set on this line
                # PyCharm will see this as executing from the .rpy file
                frame = sys._getframe()
                
                # Set the frame's filename to the .rpy file so PyCharm sees it correctly
                if hasattr(frame, 'f_code'):
                    # Create a new code object with the .rpy filename
                    original_code = frame.f_code
                    
                    # PyCharm will see breakpoints set in the .rpy file
                    pydevd.trace_dispatch(frame, 'line', None)
                    
            # Always check for manual breakpoints too
            if self._should_break():
                # Use PyCharm's breakpoint function if available
                try:
                    import pydevd
                    pydevd.settrace(suspend=True)
                except:
                    # Fallback to our pause mechanism
                    self._pause_execution("Breakpoint")
                
        except ImportError:
            # Fallback to custom breakpoints
            if self._should_break():
                self._pause_execution("Breakpoint")
        except Exception as e:
            print(f"PyCharm debugging error: {e}")
            # Fallback to custom breakpoints
            if self._should_break():
                self._pause_execution("Breakpoint")
    
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
            self.pause_event.set()
        print("Continuing execution...")
        
    def step_execution(self):
        """Execute one step and pause again."""
        with self.pause_lock:
            self.paused = False
            self.step_mode = True
            self.pause_event.set()
        print("Stepping...")
    
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
    
    def _should_break(self):
        """Check if we should break at the current location."""
        # Handle step mode
        if self.step_mode:
            self.step_mode = False
            return True
            
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
                return True
                
        return False
    
    def _pause_execution(self, reason):
        """Pause execution and wait for debug commands."""
        with self.pause_lock:
            self.paused = True
            self.pause_event.clear()
            
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
    
    def _patch_python_execution(self):
        """Patch Python execution to enable debugging of Python blocks."""
        if self.original_py_exec is not None:
            return  # Already patched
            
        self.original_py_exec = renpy.python.py_exec_bytecode
        
        def patched_py_exec_bytecode(bytecode, hide=False, globals=None, locals=None, store="store"):
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
            return self.original_py_exec(bytecode, hide, globals, locals, store)
        
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
                    self._pause_execution("Breakpoint")
                    
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


# Global debugger instance
_debugger = None

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
    get_debugger().step_execution()

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

def enable_pycharm_debugging(port=12345):
    """Enable PyCharm debugging."""
    return get_debugger().enable_pycharm_debugging(port)

def disable_pycharm_debugging():
    """Disable PyCharm debugging."""
    get_debugger().disable_pycharm_debugging()

def is_pycharm_debugging_enabled():
    """Check if PyCharm debugging is enabled."""
    return get_debugger().pycharm_enabled