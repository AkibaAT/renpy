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
HTTP API Server for Testing Interface

This module provides an HTTP REST API server that allows external testing tools
to control and inspect a running Ren'Py game.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import json
import threading
import time
import socket
import hashlib
import base64
import struct
import uuid
import webbrowser
import os
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs
except ImportError:
    # Python 2 compatibility
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from urlparse import urlparse, parse_qs
    # For Python 2, we'll need to create our own threading version
    import SocketServer
    class ThreadingHTTPServer(SocketServer.ThreadingMixIn, HTTPServer):
        pass

import renpy


class TestingAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the testing API."""
    
    def __init__(self, testing_interface, *args, **kwargs):
        self.testing_interface = testing_interface
        super(TestingAPIHandler, self).__init__(*args, **kwargs)
    
    def do_GET(self):
        """Handle GET requests."""
        try:
            parsed_url = urlparse(self.path)
            path = parsed_url.path
            query_params = parse_qs(parsed_url.query)
            print(f"DEBUG: GET request for path: {path}")

            # Check for WebSocket upgrade request
            if self.headers.get('Upgrade', '').lower() == 'websocket' and path in ['/ws', '/websocket']:
                self._handle_websocket_upgrade()
                return
            
            if path == '/api/status':
                self._handle_status()
            elif path == '/api/state':
                self._handle_get_state()
            elif path == '/api/variables':
                self._handle_get_variables()
            elif path == '/api/scene':
                self._handle_get_scene()
            elif path == '/api/dialogue':
                self._handle_get_dialogue()
            elif path == '/api/choices':
                self._handle_get_choices()
            elif path == '/api/saves':
                self._handle_list_saves()
            elif path == '/api/screenshot':
                self._handle_get_screenshot()
            elif path == '/api/exec':
                self._handle_exec_code()
            elif path == '/api/interactables':
                self._handle_get_interactables()
            elif path == '/api/breakpoints':
                self._handle_list_breakpoints()
            elif path == '/api/debug/status':
                self._handle_debug_status()
            elif path == '/api/debug/location':
                self._handle_debug_location()
            elif path == '/api/debug/stack':
                self._handle_debug_stack()
            elif path == '/api/route/analyze':
                self._handle_route_analyze()
            elif path == '/api/route/graph':
                print("DEBUG: Routing to route graph handler")
                self._handle_route_graph()
            elif path == '/api/route/progress':
                self._handle_route_progress()
            elif path == '/api/route/wordcount':
                self._handle_route_wordcount()
            elif path == '/api/route/summary':
                self._handle_route_summary()
            elif path == '/api/route/requirements':
                self._handle_route_requirements()
            elif path == '/api/route/test':
                self._handle_route_test()
            elif path == '/visualizer':
                self._serve_route_visualizer()
            elif path == '/api/route/open-visualizer':
                self._open_route_visualizer()
            else:
                self._send_error(404, "Endpoint not found")
                
        except Exception as e:
            self._send_error(500, str(e))
    
    def do_POST(self):
        """Handle POST requests."""
        try:
            parsed_url = urlparse(self.path)
            path = parsed_url.path
            
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body) if body else {}
            
            if path == '/api/advance':
                self._handle_advance()
            elif path == '/api/rollback':
                self._handle_rollback(data)
            elif path == '/api/choice':
                self._handle_select_choice(data)
            elif path == '/api/jump':
                self._handle_jump(data)
            elif path == '/api/variable':
                self._handle_set_variable(data)
            elif path == '/api/save':
                self._handle_save_state(data)
            elif path == '/api/load':
                self._handle_load_state(data)
            elif path == '/api/click':
                self._handle_click(data)
            elif path == '/api/key':
                self._handle_key(data)
            elif path == '/api/exec':
                self._handle_exec_code(data)
            elif path == '/api/breakpoint/set':
                self._handle_set_breakpoint(data)
            elif path == '/api/breakpoint/clear':
                self._handle_clear_breakpoint(data)
            elif path == '/api/breakpoint/clear_all':
                self._handle_clear_all_breakpoints(data)
            elif path == '/api/breakpoint/enable':
                self._handle_enable_breakpoint(data)
            elif path == '/api/debug/continue':
                self._handle_debug_continue()
            elif path == '/api/debug/step':
                self._handle_debug_step()
            elif path == '/api/debug/enable':
                self._handle_debug_enable()
            elif path == '/api/debug/disable':
                self._handle_debug_disable()
            else:
                self._send_error(404, "Endpoint not found")
                
        except Exception as e:
            self._send_error(500, str(e))
    
    def _handle_status(self):
        """Handle status endpoint."""
        status = {
            'running': True,
            'interface_enabled': self.testing_interface.is_enabled(),
            'current_label': self.testing_interface.get_current_label(),
            'timestamp': time.time()
        }
        self._send_json_response(status)
    
    def _handle_get_state(self):
        """Handle full state inspection."""
        state = self.testing_interface.inspect_state()
        self._send_json_response(state)
    
    def _handle_get_variables(self):
        """Handle variables endpoint."""
        variables = self.testing_interface.get_variables()
        self._send_json_response({'variables': variables})
    
    def _handle_get_scene(self):
        """Handle scene info endpoint."""
        scene_info = self.testing_interface.get_scene_info()
        self._send_json_response({'scene_info': scene_info})
    
    def _handle_get_dialogue(self):
        """Handle dialogue info endpoint."""
        dialogue_info = self.testing_interface.get_dialogue_info()
        self._send_json_response({'dialogue_info': dialogue_info})
    
    def _handle_get_choices(self):
        """Handle choices endpoint."""
        choices = self.testing_interface.get_choices()
        self._send_json_response({'choices': choices})
    
    def _handle_get_interactables(self):
        """Handle UI interactables endpoint."""
        interactables = self.testing_interface.state_inspector.get_ui_interactables()
        self._send_json_response({'interactables': interactables})
    
    def _handle_list_saves(self):
        """Handle list saves endpoint."""
        saves = self.testing_interface.state_manager.list_saves()
        self._send_json_response({'saves': saves})

    def _handle_get_screenshot(self):
        """Handle GET /api/screenshot"""
        try:
            screenshot_data = self.testing_interface.take_screenshot()
            if screenshot_data:
                # Send PNG image data
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Length', str(len(screenshot_data)))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(screenshot_data)
            else:
                self._send_error(500, "Failed to take screenshot")
        except Exception as e:
            self._send_error(500, f"Screenshot error: {str(e)}")
    
    def _handle_advance(self):
        """Handle dialogue advancement."""
        success = self.testing_interface.advance_dialogue()
        self._send_json_response({'success': success})
    
    def _handle_rollback(self, data):
        """Handle rollback request."""
        steps = data.get('steps', 1)
        success = self.testing_interface.rollback(steps)
        self._send_json_response({'success': success})
    
    def _handle_select_choice(self, data):
        """Handle choice selection."""
        choice = data.get('choice')
        if choice is None:
            self._send_error(400, "Missing 'choice' parameter")
            return
        
        success = self.testing_interface.select_choice(choice)
        self._send_json_response({'success': success})
    
    def _handle_jump(self, data):
        """Handle label jump."""
        label = data.get('label')
        if not label:
            self._send_error(400, "Missing 'label' parameter")
            return
        
        success = self.testing_interface.jump_to_label(label)
        self._send_json_response({'success': success})
    
    def _handle_set_variable(self, data):
        """Handle variable setting."""
        name = data.get('name')
        value = data.get('value')
        
        if not name:
            self._send_error(400, "Missing 'name' parameter")
            return
        
        success = self.testing_interface.set_variable(name, value)
        self._send_json_response({'success': success})
    
    def _handle_save_state(self, data):
        """Handle state saving."""
        slot = data.get('slot')
        slot_used = self.testing_interface.save_state(slot)
        self._send_json_response({'success': True, 'slot': slot_used})
    
    def _handle_load_state(self, data):
        """Handle state loading."""
        slot = data.get('slot')
        if not slot:
            self._send_error(400, "Missing 'slot' parameter")
            return
        
        success = self.testing_interface.load_state(slot)
        self._send_json_response({'success': success})
    
    def _handle_click(self, data):
        """Handle mouse click."""
        x = data.get('x', 400)
        y = data.get('y', 300)
        button = data.get('button', 1)
        
        success = self.testing_interface.game_controller.send_click(x, y, button)
        self._send_json_response({'success': success})
    
    def _handle_key(self, data):
        """Handle key press."""
        key = data.get('key')
        if key is None:
            self._send_error(400, "Missing 'key' parameter")
            return
        
        success = self.testing_interface.game_controller.send_key(key)
        self._send_json_response({'success': success})
    
    def _handle_exec_code(self, data=None):
        """Handle custom code execution."""
        if data is None:
            # GET request - return documentation
            self._send_json_response({
                'endpoint': '/api/exec',
                'methods': ['POST'],
                'description': 'Execute custom Python code in the game context',
                'security_warning': 'This endpoint is for testing/debugging only. Use with caution and never expose in production.',
                'parameters': {
                    'code': 'Python code to execute (string)',
                    'mode': 'Optional: "eval" for expressions, "exec" for statements (default: "exec")'
                },
                'safety_notes': [
                    'Limited to safe built-in functions only',
                    'No file system access or imports allowed',
                    'Access to renpy and store modules provided',
                    'Intended for game state manipulation during testing'
                ],
                'examples': [
                    {'code': 'renpy.store.persistent.quick_menu = True', 'mode': 'exec'},
                    {'code': 'renpy.store.persistent.quick_menu', 'mode': 'eval'},
                    {'code': 'print("Hello from custom code!")'}
                ]
            })
            return
            
        # POST request - execute code
        code = data.get('code')
        if not code:
            self._send_error(400, "Missing 'code' parameter")
            return
            
        mode = data.get('mode', 'exec')
        if mode not in ['exec', 'eval']:
            self._send_error(400, "Invalid 'mode' parameter. Must be 'exec' or 'eval'")
            return
            
        try:
            # Execute code in a controlled environment
            result = self._execute_code_safely(code, mode)
            self._send_json_response({
                'success': True,
                'result': result,
                'mode': mode
            })
        except Exception as e:
            self._send_error(500, f"Code execution error: {str(e)}")
    
    def _execute_code_safely(self, code, mode):
        """
        Execute code safely in the game context.
        
        SECURITY CONSIDERATIONS:
        - Restricted builtins to prevent file system access, imports, etc.
        - No access to dangerous functions like open(), exec(), eval(), __import__()
        - Limited to safe data types and Ren'Py game manipulation
        - This is intended for testing/debugging, not production use
        
        Args:
            code (str): Python code to execute
            mode (str): Either 'exec' or 'eval'
            
        Returns:
            Result of code execution or success message
        """
        try:
            # Create a safe execution environment with access to renpy modules
            exec_globals = {
                'renpy': renpy,
                'store': renpy.store,
                '__builtins__': {
                    # Safe built-ins only - no file I/O, no imports, no dangerous functions
                    'len': len,
                    'str': str,
                    'int': int,
                    'float': float,
                    'bool': bool,
                    'list': list,
                    'dict': dict,
                    'tuple': tuple,
                    'set': set,
                    'range': range,
                    'enumerate': enumerate,
                    'zip': zip,
                    'min': min,
                    'max': max,
                    'sum': sum,
                    'sorted': sorted,
                    'reversed': reversed,
                    'print': print,
                    'type': type,
                    'hasattr': hasattr,
                    'getattr': getattr,
                    'setattr': setattr,
                    'isinstance': isinstance,
                    'issubclass': issubclass,
                    'chr': chr,
                    'ord': ord,
                    # Explicitly excluded dangerous functions:
                    # - open, file, input, raw_input (file I/O)
                    # - exec, eval, compile (__import__ (code execution)
                    # - globals, locals, vars (access to global state)
                    # - __import__, reload (module loading)
                    # - exit, quit (program termination)
                }
            }
            
            exec_locals = {}
            
            if mode == 'eval':
                # Evaluate expression and return result
                result = eval(code, exec_globals, exec_locals)
                # Convert result to string for JSON serialization
                if result is None:
                    return None
                elif isinstance(result, (str, int, float, bool, list, dict)):
                    return result
                else:
                    return str(result)
            else:
                # Execute statements
                exec(code, exec_globals, exec_locals)
                # Return any variables that were created
                if exec_locals:
                    # Filter out built-in variables
                    user_vars = {k: v for k, v in exec_locals.items() 
                               if not k.startswith('__')}
                    if user_vars:
                        # Convert to serializable format
                        return {k: str(v) for k, v in user_vars.items()}
                return "Code executed successfully"
                
        except Exception as e:
            raise Exception(f"Execution failed: {str(e)}")
    
    def _send_json_response(self, data):
        """Send JSON response."""
        response = json.dumps(data, default=str, indent=2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def _send_error(self, code, message):
        """Send error response."""
        error_data = {'error': message, 'code': code}
        response = json.dumps(error_data)
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))
    
    def log_message(self, format, *args):
        """Override to reduce logging noise."""
        pass
    
    # Breakpoint and Debug Handler Methods
    
    def _handle_list_breakpoints(self):
        """Handle GET /api/breakpoints - list all breakpoints."""
        from renpy.testing.breakpoint_manager import get_breakpoint_manager
        breakpoint_manager = get_breakpoint_manager()
        breakpoints = breakpoint_manager.list_breakpoints()
        self._send_json_response({'breakpoints': breakpoints})
    
    def _handle_set_breakpoint(self, data):
        """Handle POST /api/breakpoint/set - set a breakpoint."""
        filename = data.get('filename')
        line = data.get('line')
        condition = data.get('condition')
        
        if not filename or not line:
            self._send_error(400, "Missing 'filename' or 'line' parameter")
            return
        
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            success = breakpoint_manager.set_breakpoint(filename, int(line), condition)
            self._send_json_response({
                'success': success,
                'filename': filename,
                'line': int(line),
                'condition': condition
            })
        except Exception as e:
            self._send_error(500, f"Failed to set breakpoint: {str(e)}")
    
    def _handle_clear_breakpoint(self, data):
        """Handle POST /api/breakpoint/clear - clear a specific breakpoint."""
        filename = data.get('filename')
        line = data.get('line')
        
        if not filename or not line:
            self._send_error(400, "Missing 'filename' or 'line' parameter")
            return
        
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            success = breakpoint_manager.clear_breakpoint(filename, int(line))
            self._send_json_response({
                'success': success,
                'filename': filename,
                'line': int(line)
            })
        except Exception as e:
            self._send_error(500, f"Failed to clear breakpoint: {str(e)}")
    
    def _handle_clear_all_breakpoints(self, data):
        """Handle POST /api/breakpoint/clear_all - clear all breakpoints."""
        filename = data.get('filename')  # Optional - if provided, only clear for this file
        
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            breakpoint_manager.clear_all_breakpoints(filename)
            self._send_json_response({
                'success': True,
                'filename': filename
            })
        except Exception as e:
            self._send_error(500, f"Failed to clear breakpoints: {str(e)}")
    
    def _handle_enable_breakpoint(self, data):
        """Handle POST /api/breakpoint/enable - enable/disable a breakpoint."""
        filename = data.get('filename')
        line = data.get('line')
        enabled = data.get('enabled', True)
        
        if not filename or not line:
            self._send_error(400, "Missing 'filename' or 'line' parameter")
            return
        
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            success = breakpoint_manager.enable_breakpoint(filename, int(line), enabled)
            self._send_json_response({
                'success': success,
                'filename': filename,
                'line': int(line),
                'enabled': enabled
            })
        except Exception as e:
            self._send_error(500, f"Failed to enable/disable breakpoint: {str(e)}")
    
    def _handle_debug_status(self):
        """Handle GET /api/debug/status - get debug mode status."""
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            status = {
                'debug_mode': breakpoint_manager.is_debug_mode(),
                'paused': breakpoint_manager.is_paused(),
                'current_location': breakpoint_manager.get_current_location()
            }
            self._send_json_response(status)
        except Exception as e:
            self._send_error(500, f"Failed to get debug status: {str(e)}")
    
    def _handle_debug_location(self):
        """Handle GET /api/debug/location - get current execution location."""
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            location = breakpoint_manager.get_current_location()
            self._send_json_response(location)
        except Exception as e:
            self._send_error(500, f"Failed to get current location: {str(e)}")
    
    def _handle_debug_stack(self):
        """Handle GET /api/debug/stack - get call stack."""
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            stack = breakpoint_manager.get_call_stack()
            self._send_json_response({'stack': stack})
        except Exception as e:
            self._send_error(500, f"Failed to get call stack: {str(e)}")
    
    def _handle_debug_enable(self):
        """Handle POST /api/debug/enable - enable debug mode."""
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            breakpoint_manager.enable_debug_mode()
            self._send_json_response({'success': True, 'debug_mode': True})
        except Exception as e:
            self._send_error(500, f"Failed to enable debug mode: {str(e)}")
    
    def _handle_debug_disable(self):
        """Handle POST /api/debug/disable - disable debug mode."""
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            breakpoint_manager.disable_debug_mode()
            self._send_json_response({'success': True, 'debug_mode': False})
        except Exception as e:
            self._send_error(500, f"Failed to disable debug mode: {str(e)}")
    
    def _handle_debug_continue(self):
        """Handle POST /api/debug/continue - continue execution from breakpoint."""
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            breakpoint_manager.continue_execution()
            self._send_json_response({'success': True, 'action': 'continue'})
        except Exception as e:
            self._send_error(500, f"Failed to continue execution: {str(e)}")
    
    def _handle_debug_step(self):
        """Handle POST /api/debug/step - step one statement."""
        try:
            from renpy.testing.breakpoint_manager import get_breakpoint_manager
            breakpoint_manager = get_breakpoint_manager()
            breakpoint_manager.step_execution()
            self._send_json_response({'success': True, 'action': 'step'})
        except Exception as e:
            self._send_error(500, f"Failed to step execution: {str(e)}")

    # Route Analysis Handler Methods

    def _handle_route_analyze(self):
        """Handle GET /api/route/analyze - get complete route analysis."""
        try:
            from renpy.testing.route_analyzer import get_route_analyzer
            analyzer = get_route_analyzer()

            # Check for force refresh parameter
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            force_refresh = query_params.get('force_refresh', ['false'])[0].lower() == 'true'

            analysis_data = analyzer.analyze_script(force_refresh=force_refresh)
            self._send_json_response(analysis_data)
        except Exception as e:
            self._send_error(500, f"Failed to analyze routes: {str(e)}")

    def _handle_route_graph(self):
        """Handle GET /api/route/graph - get route graph data."""
        print("=== ROUTE GRAPH ENDPOINT CALLED ===")
        try:
            print("DEBUG: _handle_route_graph called")
            from renpy.testing.route_analyzer import get_route_analyzer
            analyzer = get_route_analyzer()
            print("DEBUG: Got route analyzer")

            analysis_data = analyzer.analyze_script()
            print(f"DEBUG: Analysis data keys: {list(analysis_data.keys()) if isinstance(analysis_data, dict) else 'not a dict'}")

            # Handle both possible data structures:
            # 1. Direct nodes/edges structure: {"nodes": [...], "edges": [...]}
            # 2. Nested structure: {"route_graph": {"nodes": [...], "edges": [...]}}
            if 'route_graph' in analysis_data:
                # Nested structure
                route_graph = analysis_data['route_graph']
                metadata = analysis_data.get('metadata', {})
            else:
                # Direct structure - create the expected nested structure
                route_graph = {
                    'nodes': analysis_data.get('nodes', []),
                    'edges': analysis_data.get('edges', [])
                }
                metadata = analysis_data.get('metadata', {})

            # Get summary statistics for metadata if not already present
            if not metadata or not metadata.get('total_labels'):
                summary_data = self._get_route_summary_data(analyzer)
                metadata = {
                    'total_labels': summary_data.get('total_labels', 0),
                    'total_choices': summary_data.get('total_choices', 0),
                    'total_words': summary_data.get('total_words', 0),
                    'total_menus': summary_data.get('total_menus', 0),
                    'nodes_count': len(route_graph.get('nodes', [])),
                    'edges_count': len(route_graph.get('edges', []))
                }

            print(f"DEBUG: Returning {len(route_graph.get('nodes', []))} nodes and {len(route_graph.get('edges', []))} edges")

            self._send_json_response({
                'route_graph': route_graph,
                'metadata': metadata
            })
        except Exception as e:
            print(f"DEBUG: Exception in _handle_route_graph: {e}")
            import traceback
            traceback.print_exc()
            self._send_error(500, f"Failed to get route graph: {str(e)}")

    def _get_route_summary_data(self, analyzer):
        """Get route summary statistics for metadata."""
        try:
            analysis_data = analyzer.analyze_script()

            # Count different types of nodes
            nodes = analysis_data.get('nodes', [])
            total_labels = sum(1 for node in nodes if node.get('type') == 'label')
            total_menus = sum(1 for node in nodes if node.get('type') == 'menu')

            # Count choices from edges
            edges = analysis_data.get('edges', [])
            total_choices = sum(1 for edge in edges if edge.get('type') == 'choice')

            return {
                'total_labels': total_labels,
                'total_menus': total_menus,
                'total_choices': total_choices,
                'total_words': 0,  # Word count not implemented yet
                'nodes_count': len(nodes),
                'edges_count': len(edges)
            }
        except Exception as e:
            print(f"DEBUG: Error getting summary data: {e}")
            return {
                'total_labels': 0,
                'total_menus': 0,
                'total_choices': 0,
                'total_words': 0,
                'nodes_count': 0,
                'edges_count': 0
            }

    def _handle_route_progress(self):
        """Handle GET /api/route/progress - get current progress information."""
        try:
            from renpy.testing.route_analyzer import get_route_analyzer
            analyzer = get_route_analyzer()

            # Ensure analysis is done first
            analyzer.analyze_script()
            progress_data = analyzer.get_current_progress()

            self._send_json_response(progress_data)
        except Exception as e:
            self._send_error(500, f"Failed to get route progress: {str(e)}")

    def _handle_route_wordcount(self):
        """Handle GET /api/route/wordcount - get word count data."""
        try:
            from renpy.testing.route_analyzer import get_route_analyzer
            analyzer = get_route_analyzer()

            analysis_data = analyzer.analyze_script()
            word_counts = analysis_data.get('word_counts', {})

            # Calculate additional metrics
            total_words = sum(word_counts.values()) if word_counts else 0
            estimated_reading_time = round(total_words / 200.0, 1)  # 200 words per minute

            self._send_json_response({
                'word_counts': word_counts,
                'total_words': total_words,
                'estimated_reading_time_minutes': estimated_reading_time,
                'labels_with_content': len([label for label, count in word_counts.items() if count > 0])
            })
        except Exception as e:
            self._send_error(500, f"Failed to get word counts: {str(e)}")

    def _handle_route_summary(self):
        """Handle GET /api/route/summary - get route summary information."""
        try:
            from renpy.testing.route_analyzer import get_route_analyzer
            analyzer = get_route_analyzer()

            # Ensure analysis is done first
            analyzer.analyze_script()
            summary_data = analyzer.get_route_summary()

            self._send_json_response(summary_data)
        except Exception as e:
            self._send_error(500, f"Failed to get route summary: {str(e)}")

    def _handle_route_requirements(self):
        """Handle GET /api/route/requirements - get choice requirements data."""
        try:
            from renpy.testing.route_analyzer import get_route_analyzer
            analyzer = get_route_analyzer()

            analysis_data = analyzer.analyze_script()
            requirements = analysis_data.get('choice_requirements', {})

            # Organize requirements by menu for easier consumption
            requirements_by_menu = {}
            for choice_id, req_data in requirements.items():
                menu_id = req_data.get('menu_id')
                if menu_id not in requirements_by_menu:
                    requirements_by_menu[menu_id] = []
                requirements_by_menu[menu_id].append(req_data)

            self._send_json_response({
                'choice_requirements': requirements,
                'requirements_by_menu': requirements_by_menu,
                'total_conditional_choices': len(requirements)
            })
        except Exception as e:
            self._send_error(500, f"Failed to get choice requirements: {str(e)}")

    def _handle_route_test(self):
        """Handle route test endpoint."""
        try:
            print("DEBUG: Route test endpoint called")

            # Test basic script access
            script = renpy.game.script
            print(f"DEBUG: Script object: {script}")
            print(f"DEBUG: Script type: {type(script)}")

            if script and hasattr(script, 'namemap'):
                namemap = script.namemap
                print(f"DEBUG: Namemap type: {type(namemap)}")
                print(f"DEBUG: Namemap length: {len(namemap) if namemap else 'None'}")

                if namemap:
                    # Write debug info to a file so we can see it
                    debug_info = []
                    debug_info.append("DEBUG: First 10 namemap keys:")
                    for i, key in enumerate(list(namemap.keys())[:10]):
                        debug_info.append(f"  {i}: {key} (type: {type(key)})")

                    # Look for string keys that don't start with underscore
                    string_keys = [k for k in namemap.keys() if isinstance(k, str) and not k.startswith('_')]
                    debug_info.append(f"DEBUG: Found {len(string_keys)} string keys not starting with '_'")
                    if string_keys:
                        debug_info.append("DEBUG: First 10 string keys:")
                        for i, key in enumerate(string_keys[:10]):
                            debug_info.append(f"  {i}: {key}")

                    # Write to file
                    try:
                        with open('/tmp/renpy_debug.txt', 'w') as f:
                            f.write('\n'.join(debug_info))
                        print("DEBUG: Wrote debug info to /tmp/renpy_debug.txt")
                    except Exception as e:
                        print(f"DEBUG: Failed to write debug file: {e}")

                    # Also print to console
                    for line in debug_info:
                        print(line)

            response = {
                "test": "success",
                "script_available": script is not None,
                "namemap_available": hasattr(script, 'namemap') if script else False,
                "namemap_length": len(script.namemap) if script and hasattr(script, 'namemap') and script.namemap else 0
            }

            self._send_json_response(response)
        except Exception as e:
            print(f"DEBUG: Route test error: {str(e)}")
            self._send_error(500, f"Route test error: {str(e)}")

    def _serve_route_visualizer(self):
        """Serve the route visualizer HTML page."""
        try:
            # Get the path to the HTML file
            import renpy
            visualizer_path = os.path.join(renpy.config.renpy_base, "renpy", "testing", "route_visualizer.html")

            if os.path.exists(visualizer_path):
                with open(visualizer_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()

                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                self.wfile.write(html_content.encode('utf-8'))
            else:
                self._send_error(404, "Route visualizer not found")
        except Exception as e:
            self._send_error(500, f"Failed to serve visualizer: {str(e)}")

    def _open_route_visualizer(self):
        """Open the route visualizer in the default browser."""
        try:
            # Get the server URL
            server_url = f"http://{self.server.server_address[0]}:{self.server.server_address[1]}"
            visualizer_url = f"{server_url}/visualizer"

            # Open in browser
            webbrowser.open(visualizer_url)

            self._send_json_response({
                'success': True,
                'url': visualizer_url,
                'message': 'Route visualizer opened in browser'
            })
        except Exception as e:
            self._send_error(500, f"Failed to open visualizer: {str(e)}")

    def _handle_websocket_upgrade(self):
        """Handle WebSocket upgrade request."""
        try:
            # Get WebSocket key from headers
            websocket_key = self.headers.get('Sec-WebSocket-Key')
            if not websocket_key:
                self.send_error(400, "Missing Sec-WebSocket-Key header")
                return
            
            # Generate WebSocket accept key
            magic_string = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
            accept_key = base64.b64encode(
                hashlib.sha1((websocket_key + magic_string).encode()).digest()
            ).decode()
            
            # Send WebSocket upgrade response
            self.send_response(101, "Switching Protocols")
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept_key)
            self.end_headers()
            
            # Register this WebSocket connection
            ws_connection = WebSocketConnection(self.request, self.testing_interface)
            if hasattr(self.testing_interface, 'websocket_server'):
                self.testing_interface.websocket_server.add_connection(ws_connection)
            
            # Handle WebSocket frames
            ws_connection.handle_frames()
            
        except Exception as e:
            print(f"WebSocket upgrade error: {e}")
            self.send_error(500, f"WebSocket upgrade failed: {str(e)}")


class WebSocketConnection(object):
    """Handles individual WebSocket connections."""
    
    def __init__(self, socket, testing_interface):
        self.socket = socket
        self.testing_interface = testing_interface
        self.closed = False
        self.client_id = str(uuid.uuid4())
        print(f"[WebSocket] New connection: {self.client_id}")
    
    def send_message(self, message):
        """Send a message to the WebSocket client."""
        if self.closed:
            return False
        
        try:
            # Convert message to JSON if it's not already a string
            if not isinstance(message, str):
                message = json.dumps(message, default=str)
            
            # Create WebSocket frame
            message_bytes = message.encode('utf-8')
            frame = self._create_frame(message_bytes)
            
            self.socket.send(frame)
            return True
        except Exception as e:
            print(f"[WebSocket] Send error for {self.client_id}: {e}")
            self.close()
            return False
    
    def _create_frame(self, payload):
        """Create a WebSocket frame for the payload."""
        # WebSocket frame format:
        # FIN=1, RSV=000, OPCODE=0001 (text frame)
        first_byte = 0x81  # FIN=1, OPCODE=1 (text)
        
        payload_length = len(payload)
        if payload_length < 126:
            frame = struct.pack('!BB', first_byte, payload_length)
        elif payload_length < 65536:
            frame = struct.pack('!BBH', first_byte, 126, payload_length)
        else:
            frame = struct.pack('!BBQ', first_byte, 127, payload_length)
        
        return frame + payload
    
    def handle_frames(self):
        """Handle incoming WebSocket frames."""
        try:
            while not self.closed:
                frame = self._read_frame()
                if frame is None:
                    break
                
                # Process frame (for now, just log it)
                print(f"[WebSocket] Received frame from {self.client_id}: {frame}")
                
        except Exception as e:
            print(f"[WebSocket] Frame handling error for {self.client_id}: {e}")
        finally:
            self.close()
    
    def _read_frame(self):
        """Read a WebSocket frame from the socket."""
        try:
            # Read first 2 bytes
            header = self.socket.recv(2)
            if len(header) < 2:
                return None
            
            first_byte, second_byte = struct.unpack('!BB', header)
            
            # Check if this is a close frame
            opcode = first_byte & 0x0F
            if opcode == 0x8:  # Close frame
                return None
            
            # Get payload length
            payload_length = second_byte & 0x7F
            masked = (second_byte & 0x80) == 0x80
            
            if payload_length == 126:
                length_data = self.socket.recv(2)
                payload_length = struct.unpack('!H', length_data)[0]
            elif payload_length == 127:
                length_data = self.socket.recv(8)
                payload_length = struct.unpack('!Q', length_data)[0]
            
            # Read mask if present
            mask = None
            if masked:
                mask = self.socket.recv(4)
            
            # Read payload
            payload = self.socket.recv(payload_length)
            
            # Unmask payload if needed
            if masked and mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            
            return payload.decode('utf-8')
            
        except Exception as e:
            print(f"[WebSocket] Read frame error: {e}")
            return None
    
    def close(self):
        """Close the WebSocket connection."""
        if not self.closed:
            self.closed = True
            try:
                self.socket.close()
            except:
                pass
            print(f"[WebSocket] Connection closed: {self.client_id}")


class WebSocketServer(object):
    """Manages WebSocket connections and broadcasts updates."""
    
    def __init__(self, testing_interface):
        self.testing_interface = testing_interface
        self.connections = []
        self.last_scene_state = None
        self.update_thread = None
        self.running = False
    
    def add_connection(self, connection):
        """Add a new WebSocket connection."""
        self.connections.append(connection)
        print(f"[WebSocket] Added connection. Total: {len(self.connections)}")
        
        # Send current state to new connection
        try:
            current_state = self.testing_interface.inspect_state()
            connection.send_message({
                'type': 'initial_state',
                'data': current_state
            })
        except Exception as e:
            print(f"[WebSocket] Error sending initial state: {e}")
    
    def remove_connection(self, connection):
        """Remove a WebSocket connection."""
        if connection in self.connections:
            self.connections.remove(connection)
            print(f"[WebSocket] Removed connection. Total: {len(self.connections)}")
    
    def broadcast_message(self, message):
        """Broadcast a message to all connected clients."""
        if not self.connections:
            return
        
        # Remove closed connections
        active_connections = []
        for conn in self.connections:
            if not conn.closed and conn.send_message(message):
                active_connections.append(conn)
            else:
                conn.close()
        
        self.connections = active_connections
    
    def start_monitoring(self):
        """Start monitoring scene changes and broadcasting updates."""
        if self.running:
            return
        
        self.running = True
        self.update_thread = threading.Thread(target=self._monitor_scene_changes)
        self.update_thread.daemon = True
        self.update_thread.start()
        print("[WebSocket] Started scene monitoring")
    
    def stop_monitoring(self):
        """Stop monitoring scene changes."""
        self.running = False
        if self.update_thread:
            self.update_thread.join(timeout=1.0)
        
        # Close all connections
        for conn in self.connections:
            conn.close()
        self.connections.clear()
        print("[WebSocket] Stopped scene monitoring")
    
    def _monitor_scene_changes(self):
        """Monitor for scene changes and broadcast updates."""
        while self.running:
            try:
                # Get current scene state
                current_state = self.testing_interface.inspect_state()
                
                # Create a simplified state hash for comparison
                state_hash = self._create_state_hash(current_state)
                
                # Check if state has changed
                if state_hash != self.last_scene_state:
                    self.last_scene_state = state_hash
                    
                    # Broadcast update to all clients
                    self.broadcast_message({
                        'type': 'scene_update',
                        'timestamp': time.time(),
                        'data': current_state
                    })
                
                time.sleep(0.5)  # Check for updates every 500ms
                
            except Exception as e:
                print(f"[WebSocket] Scene monitoring error: {e}")
                time.sleep(1.0)  # Wait longer on error
    
    def _create_state_hash(self, state):
        """Create a hash of the important state components for change detection."""
        try:
            # Extract key components that indicate scene changes
            hash_components = []
            
            if 'label' in state:
                hash_components.append(str(state['label']))
            
            if 'scene_info' in state and 'shown_images' in state['scene_info']:
                for img in state['scene_info']['shown_images']:
                    hash_components.append(f"{img.get('tag', '')}-{img.get('name', '')}")
            
            if 'scene_info' in state and 'active_screens' in state['scene_info']:
                hash_components.extend(state['scene_info']['active_screens'])
            
            # Create hash from components
            hash_string = '|'.join(hash_components)
            return hashlib.md5(hash_string.encode()).hexdigest()
            
        except Exception as e:
            print(f"[WebSocket] Error creating state hash: {e}")
            return str(time.time())  # Fallback to timestamp


class TestingHTTPServer(object):
    """HTTP server for the testing API."""
    
    def __init__(self, testing_interface, host='localhost', port=8080):
        self.testing_interface = testing_interface
        self.host = host
        self.port = port
        self.server = None
        self.server_thread = None
        self.running = False
        
        # Initialize WebSocket server
        self.websocket_server = WebSocketServer(testing_interface)
        # Attach websocket server to testing interface so handlers can access it
        testing_interface.websocket_server = self.websocket_server
    
    def start(self):
        """Start the HTTP server."""
        if self.running:
            return True
        
        try:
            # Create handler class with testing interface
            def handler_factory(*args, **kwargs):
                return TestingAPIHandler(self.testing_interface, *args, **kwargs)
            
            # Use ThreadingHTTPServer for concurrent request handling
            try:
                self.server = ThreadingHTTPServer((self.host, self.port), handler_factory)
                print("Using ThreadingHTTPServer for concurrent request handling")
            except NameError:
                # Fallback to regular HTTPServer if ThreadingHTTPServer not available
                self.server = HTTPServer((self.host, self.port), handler_factory)
                print("Warning: Using single-threaded HTTPServer (ThreadingHTTPServer not available)")
            self.server_thread = threading.Thread(target=self.server.serve_forever)
            self.server_thread.daemon = True
            self.server_thread.start()
            self.running = True
            
            # Start WebSocket monitoring
            self.websocket_server.start_monitoring()
            
            print("Testing API server started on http://{}:{}".format(self.host, self.port))
            print("WebSocket endpoint available at ws://{}:{}/ws".format(self.host, self.port))

            # Enable developer shortcuts
            try:
                from renpy.testing.dev_shortcuts import enable_dev_shortcuts, register_dev_actions
                enable_dev_shortcuts(self.port)
                register_dev_actions()
                print("")
                print("🎮 Developer Shortcuts Enabled:")
                print("  Ctrl+Shift+R - Open Route Visualizer")
                print("  Ctrl+Shift+D - Toggle Dev Shortcuts")
            except Exception as e:
                print("Failed to enable developer shortcuts: {}".format(e))

            return True
            
        except Exception as e:
            print("Failed to start testing API server: {}".format(e))
            return False
    
    def stop(self):
        """Stop the HTTP server."""
        if not self.running:
            return
        
        try:
            # Stop WebSocket monitoring
            self.websocket_server.stop_monitoring()
            
            if self.server:
                self.server.shutdown()
                self.server.server_close()
            
            if self.server_thread:
                self.server_thread.join(timeout=1.0)
            
            self.running = False
            print("Testing API server stopped")
            
        except Exception as e:
            print("Error stopping testing API server: {}".format(e))
    
    def is_running(self):
        """Check if server is running."""
        return self.running
    
    def get_url(self):
        """Get the server URL."""
        return "http://{}:{}".format(self.host, self.port)
