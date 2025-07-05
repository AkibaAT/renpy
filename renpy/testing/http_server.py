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
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
    from urllib.parse import urlparse, parse_qs
except ImportError:
    # Python 2 compatibility
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from urlparse import urlparse, parse_qs

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


class TestingHTTPServer(object):
    """HTTP server for the testing API."""
    
    def __init__(self, testing_interface, host='localhost', port=8080):
        self.testing_interface = testing_interface
        self.host = host
        self.port = port
        self.server = None
        self.server_thread = None
        self.running = False
    
    def start(self):
        """Start the HTTP server."""
        if self.running:
            return True
        
        try:
            # Create handler class with testing interface
            def handler_factory(*args, **kwargs):
                return TestingAPIHandler(self.testing_interface, *args, **kwargs)
            
            self.server = HTTPServer((self.host, self.port), handler_factory)
            self.server_thread = threading.Thread(target=self.server.serve_forever)
            self.server_thread.daemon = True
            self.server_thread.start()
            self.running = True
            
            print("Testing API server started on http://{}:{}".format(self.host, self.port))
            return True
            
        except Exception as e:
            print("Failed to start testing API server: {}".format(e))
            return False
    
    def stop(self):
        """Stop the HTTP server."""
        if not self.running:
            return
        
        try:
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
