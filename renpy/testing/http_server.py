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


API_ENDPOINTS = [
    ("GET", "/api/status", "Get server status and basic game information."),
    ("GET", "/api/state", "Get comprehensive game state."),
    ("GET", "/api/variables", "Get current game variables."),
    ("GET", "/api/scene", "Get scene and screen information."),
    ("GET", "/api/dialogue", "Get current dialogue information."),
    ("GET", "/api/choices", "Get available menu choices."),
    ("GET", "/api/interactables", "Get current interactable displayables."),
    ("GET", "/api/image-attributes", "Get known attributes for an image tag."),
    ("GET", "/api/behind-tags", "Get image tags available for behind clauses."),
    ("GET", "/api/saves", "List available testing save slots."),
    ("GET", "/api/screenshot", "Get a PNG screenshot of the current game."),
    ("POST", "/api/advance", "Advance dialogue or story progression."),
    ("POST", "/api/rollback", "Roll back a number of steps."),
    ("POST", "/api/choice", "Select a menu choice by index or text."),
    ("POST", "/api/jump", "Jump to a label."),
    ("POST", "/api/variable", "Set a store variable."),
    ("POST", "/api/save", "Save game state."),
    ("POST", "/api/load", "Load game state."),
    ("POST", "/api/click", "Send a mouse click."),
    ("POST", "/api/key", "Send a key press."),
    ("GET", "/docs", "Show API documentation."),
    ("GET", "/openapi.json", "Get the OpenAPI specification."),
]


def get_openapi_spec():
    """
    Returns a compact OpenAPI specification for the testing HTTP API.
    """

    paths = { }

    for method, path, summary in API_ENDPOINTS:
        method_key = method.lower()
        operation = {
            "summary": summary,
            "responses": {
                "200": {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                            },
                        },
                    },
                },
            },
        }

        if path == "/api/screenshot":
            operation["responses"]["200"]["content"] = {
                "image/png": {
                    "schema": {
                        "type": "string",
                        "format": "binary",
                    },
                },
            }

        if path == "/docs":
            operation["responses"]["200"]["content"] = {
                "text/html": {
                    "schema": {
                        "type": "string",
                    },
                },
            }

        if method == "POST":
            operation["requestBody"] = {
                "required": False,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                        },
                    },
                },
            }

        if path == "/api/image-attributes":
            operation["parameters"] = [
                {
                    "name": "tag",
                    "in": "query",
                    "required": True,
                    "schema": {
                        "type": "string",
                    },
                },
            ]

        if path == "/api/behind-tags":
            operation["parameters"] = [
                {
                    "name": "exclude",
                    "in": "query",
                    "required": False,
                    "schema": {
                        "type": "string",
                    },
                },
            ]

        paths.setdefault(path, { })[method_key] = operation

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Ren'Py Testing API",
            "version": "1.0.0",
            "description": "HTTP API for controlling and inspecting a running Ren'Py game.",
        },
        "servers": [
            {
                "url": "http://localhost:8080",
                "description": "Local testing server",
            },
        ],
        "paths": paths,
    }


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
            elif path == '/api/interactables':
                self._handle_get_interactables()
            elif path == '/api/image-attributes':
                self._handle_get_image_attributes(query_params)
            elif path == '/api/behind-tags':
                self._handle_get_behind_tags(query_params)
            elif path == '/api/saves':
                self._handle_list_saves()
            elif path == '/api/screenshot':
                self._handle_get_screenshot()
            elif path == '/docs' or path == '/swagger':
                self._handle_docs()
            elif path == '/openapi.json':
                self._handle_openapi_spec()
            else:
                self._send_error(404, "Endpoint not found")
                
        except Exception as e:
            self._send_error(500, str(e))

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()
    
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

    def _handle_get_interactables(self):
        """Handle interactables endpoint."""
        interactables = self.testing_interface.get_interactables()
        self._send_json_response({'interactables': interactables})

    def _handle_get_image_attributes(self, query_params):
        """Handle image attribute discovery endpoint."""
        tag = self._first_query_arg(query_params, 'tag')
        if not tag:
            self._send_error(400, "Missing 'tag' query parameter")
            return

        attributes = self.testing_interface.get_image_attributes(tag)
        self._send_json_response({'tag': tag, 'attributes': attributes})

    def _handle_get_behind_tags(self, query_params):
        """Handle behind tag discovery endpoint."""
        exclude = self._first_query_arg(query_params, 'exclude')
        tags = self.testing_interface.get_behind_tags(exclude)
        self._send_json_response({'tags': tags})
    
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
                self._send_cors_headers()
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

    def _handle_openapi_spec(self):
        """Handle OpenAPI spec endpoint."""
        spec = get_openapi_spec()
        host = self.headers.get('Host')

        if host:
            spec["servers"] = [
                {
                    "url": "http://{}".format(host),
                    "description": "Current testing server",
                },
            ]

        self._send_json_response(spec)

    def _handle_docs(self):
        """Handle API documentation endpoint."""
        rows = "\n".join(
            "        <tr><td>{}</td><td><code>{}</code></td><td>{}</td></tr>".format(method, path, summary)
            for method, path, summary in API_ENDPOINTS
            if path != "/docs"
        )

        html = """<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Ren'Py Testing API</title>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 2rem; line-height: 1.5; color: #20242a; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 1100px; }}
        th, td {{ border-bottom: 1px solid #d9dde3; padding: 0.5rem 0.75rem; text-align: left; vertical-align: top; }}
        th {{ background: #f4f6f8; }}
        code {{ background: #eef1f4; border-radius: 4px; padding: 0.1rem 0.25rem; }}
        a {{ color: #1b61b6; }}
    </style>
</head>
<body>
    <h1>Ren'Py Testing API</h1>
    <p>Use this local API to inspect and control the running game. The machine-readable spec is available at <a href="/openapi.json">/openapi.json</a>.</p>
    <table>
        <thead>
            <tr><th>Method</th><th>Path</th><th>Description</th></tr>
        </thead>
        <tbody>
{}
        </tbody>
    </table>
</body>
</html>
""".format(rows)

        self._send_text_response(html, "text/html; charset=utf-8")
    
    def _send_json_response(self, data):
        """Send JSON response."""
        response = json.dumps(data, default=str, indent=2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def _send_text_response(self, text, content_type):
        """Send text response."""
        response = text.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(response)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(response)
    
    def _send_error(self, code, message):
        """Send error response."""
        error_data = {'error': message, 'code': code}
        response = json.dumps(error_data)
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(response.encode('utf-8'))

    def _send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _first_query_arg(self, query_params, name):
        value = query_params.get(name)
        if not value:
            return None
        return value[0]
    
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
