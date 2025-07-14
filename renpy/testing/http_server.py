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
import atexit
import signal
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

# Global variable to track the HTTP server for cleanup
_global_http_server = None
_cleanup_in_progress = False

def _cleanup_http_server():
    """Cleanup function to stop HTTP server on exit."""
    global _global_http_server, _cleanup_in_progress

    # Prevent multiple cleanup attempts
    if _cleanup_in_progress:
        return

    if _global_http_server and _global_http_server.is_running():
        _cleanup_in_progress = True
        print("Shutting down HTTP server...")
        # Use force_stop for immediate brutal shutdown when main thread exits
        _global_http_server.force_stop()
        _cleanup_in_progress = False
    # Don't print "already stopped" message to reduce noise

def _signal_handler(signum, frame):
    """Handle interrupt signals for clean shutdown."""
    print("\nReceived interrupt signal, shutting down...")
    _cleanup_http_server()

def _register_shutdown_hooks():
    """Register shutdown hooks with Ren'Py's callback systems."""
    print("Registering HTTP server shutdown hooks...")

    # Register with Ren'Py's shutdown callbacks
    if hasattr(renpy, 'config'):
        # Only use quit_callbacks - this is the most reliable for actual quit
        if hasattr(renpy.config, 'quit_callbacks'):
            if _cleanup_http_server not in renpy.config.quit_callbacks:
                renpy.config.quit_callbacks.append(_cleanup_http_server)
                print("Registered quit_callback")

    # Don't use multiple hooks to avoid redundant cleanup calls

# Only register signal handlers for emergency cleanup
try:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
except (AttributeError, ValueError):
    # Some signals might not be available on all platforms
    pass


def get_openapi_spec():
    """Generate OpenAPI 3.0 specification for the Ren'Py debugging API."""
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Ren'Py Debugging API",
            "description": "HTTP API for debugging and testing Ren'Py visual novels during development. Provides endpoints for game state inspection, control, debugging, and route analysis.",
            "version": "1.0.0",
            "contact": {
                "name": "Ren'Py Development",
                "url": "https://www.renpy.org"
            }
        },
        "servers": [
            {
                "url": "http://localhost:8080",
                "description": "Local development server"
            }
        ],
        "tags": [
            {
                "name": "status",
                "description": "Server and game status information"
            },
            {
                "name": "state",
                "description": "Game state inspection and variables"
            },
            {
                "name": "control",
                "description": "Game control and navigation"
            },
            {
                "name": "debugging",
                "description": "Debugging features and breakpoints"
            },
            {
                "name": "route-analysis",
                "description": "Route analysis and visualization"
            },
            {
                "name": "utilities",
                "description": "Utility functions like screenshots and code execution"
            }
        ],
        "paths": {
            "/api/status": {
                "get": {
                    "tags": ["status"],
                    "summary": "Get server status",
                    "description": "Returns basic server status and project information",
                    "responses": {
                        "200": {
                            "description": "Server status information",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string", "example": "running"},
                                            "version": {"type": "string", "example": "1.0.0"},
                                            "project_path": {"type": "string", "nullable": True},
                                            "project_name": {"type": "string", "nullable": True}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/state": {
                "get": {
                    "tags": ["state"],
                    "summary": "Get full game state",
                    "description": "Returns comprehensive game state information including current context, variables, and scene data",
                    "responses": {
                        "200": {
                            "description": "Complete game state",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "context": {"type": "object"},
                                            "variables": {"type": "object"},
                                            "scene_info": {"type": "object"},
                                            "dialogue_info": {"type": "object"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/variables": {
                "get": {
                    "tags": ["state"],
                    "summary": "Get game variables",
                    "description": "Returns current game variables including store variables and preferences",
                    "responses": {
                        "200": {
                            "description": "Game variables",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "variables": {
                                                "type": "object",
                                                "additionalProperties": True
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/scene": {
                "get": {
                    "tags": ["state"],
                    "summary": "Get scene information",
                    "description": "Returns current scene and screen information",
                    "responses": {
                        "200": {
                            "description": "Scene information",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "scene_info": {"type": "object"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/dialogue": {
                "get": {
                    "tags": ["state"],
                    "summary": "Get dialogue information",
                    "description": "Returns current dialogue state and text",
                    "responses": {
                        "200": {
                            "description": "Dialogue information",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "dialogue_info": {"type": "object"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/choices": {
                "get": {
                    "tags": ["state"],
                    "summary": "Get available choices",
                    "description": "Returns currently available menu choices",
                    "responses": {
                        "200": {
                            "description": "Available choices",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "choices": {
                                                "type": "array",
                                                "items": {"type": "object"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/saves": {
                "get": {
                    "tags": ["state"],
                    "summary": "List save slots",
                    "description": "Returns available save slots",
                    "responses": {
                        "200": {
                            "description": "Save slots",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "saves": {
                                                "type": "array",
                                                "items": {"type": "object"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/interactables": {
                "get": {
                    "tags": ["state"],
                    "summary": "Get UI interactables",
                    "description": "Returns currently interactable UI elements",
                    "responses": {
                        "200": {
                            "description": "UI interactables",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "interactables": {
                                                "type": "array",
                                                "items": {"type": "object"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/advance": {
                "post": {
                    "tags": ["control"],
                    "summary": "Advance dialogue",
                    "description": "Advances the dialogue to the next statement",
                    "responses": {
                        "200": {
                            "description": "Advance result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        }
                    }
                }
            },
            "/api/rollback": {
                "post": {
                    "tags": ["control"],
                    "summary": "Roll back dialogue",
                    "description": "Rolls back the dialogue by specified number of steps",
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "steps": {
                                            "type": "integer",
                                            "default": 1,
                                            "description": "Number of steps to roll back"
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Rollback result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        }
                    }
                }
            },
            "/api/choice": {
                "post": {
                    "tags": ["control"],
                    "summary": "Select a choice",
                    "description": "Selects a choice from the current menu",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "choice": {
                                            "type": "integer",
                                            "description": "Index of the choice to select"
                                        }
                                    },
                                    "required": ["choice"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Choice selection result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"}
                    }
                }
            },
            "/api/jump": {
                "post": {
                    "tags": ["control"],
                    "summary": "Jump to label",
                    "description": "Jumps to a specific label in the script",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "label": {
                                            "type": "string",
                                            "description": "Name of the label to jump to"
                                        }
                                    },
                                    "required": ["label"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Jump result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"}
                    }
                }
            },
            "/api/variable": {
                "post": {
                    "tags": ["control"],
                    "summary": "Set variable",
                    "description": "Sets a game variable to a specific value",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "name": {
                                            "type": "string",
                                            "description": "Name of the variable to set"
                                        },
                                        "value": {
                                            "description": "Value to set (any JSON type)"
                                        }
                                    },
                                    "required": ["name"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Variable set result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"}
                    }
                }
            },
            "/api/breakpoints": {
                "get": {
                    "tags": ["debugging"],
                    "summary": "List breakpoints",
                    "description": "Returns all currently set breakpoints",
                    "responses": {
                        "200": {
                            "description": "List of breakpoints",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "breakpoints": {
                                                "type": "array",
                                                "items": {"type": "object"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/breakpoint/set": {
                "post": {
                    "tags": ["debugging"],
                    "summary": "Set breakpoint",
                    "description": "Sets a breakpoint at specified file and line",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "filename": {"type": "string", "description": "File to set breakpoint in"},
                                        "line": {"type": "integer", "description": "Line number for breakpoint"},
                                        "condition": {"type": "string", "description": "Optional condition for breakpoint"}
                                    },
                                    "required": ["filename", "line"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Breakpoint set result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "filename": {"type": "string"},
                                            "line": {"type": "integer"},
                                            "condition": {"type": "string", "nullable": True}
                                        }
                                    }
                                }
                            }
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"},
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/debug/status": {
                "get": {
                    "tags": ["debugging"],
                    "summary": "Get debug status",
                    "description": "Returns current debugging mode status",
                    "responses": {
                        "200": {
                            "description": "Debug status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "debug_mode": {"type": "boolean"},
                                            "paused": {"type": "boolean"},
                                            "current_location": {"type": "object", "nullable": True}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/route/analyze": {
                "get": {
                    "tags": ["route-analysis"],
                    "summary": "Complete route analysis",
                    "description": "Returns comprehensive route analysis including nodes, edges, and metadata",
                    "parameters": [
                        {
                            "name": "force_refresh",
                            "in": "query",
                            "description": "Force refresh of analysis cache",
                            "required": False,
                            "schema": {
                                "type": "boolean",
                                "default": False
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Complete route analysis data",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "nodes": {"type": "array", "items": {"type": "object"}},
                                            "edges": {"type": "array", "items": {"type": "object"}},
                                            "metadata": {"type": "object"},
                                            "choice_requirements": {"type": "object"}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/route/graph": {
                "get": {
                    "tags": ["route-analysis"],
                    "summary": "Route graph data",
                    "description": "Returns route graph with nodes and edges for visualization",
                    "responses": {
                        "200": {
                            "description": "Route graph data",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "route_graph": {
                                                "type": "object",
                                                "properties": {
                                                    "nodes": {"type": "array", "items": {"type": "object"}},
                                                    "edges": {"type": "array", "items": {"type": "object"}}
                                                }
                                            },
                                            "metadata": {"type": "object"}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/route/progress": {
                "get": {
                    "tags": ["route-analysis"],
                    "summary": "Current progress tracking",
                    "description": "Returns current player progress through the story",
                    "responses": {
                        "200": {
                            "description": "Progress information",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "current_label": {"type": "string"},
                                            "progress_percentage": {"type": "number"},
                                            "words_seen": {"type": "integer"},
                                            "total_words": {"type": "integer"}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/route/wordcount": {
                "get": {
                    "tags": ["route-analysis"],
                    "summary": "Word count analysis",
                    "description": "Returns word count data for all labels",
                    "parameters": [
                        {
                            "name": "force_refresh",
                            "in": "query",
                            "description": "Force refresh of word count cache",
                            "required": False,
                            "schema": {
                                "type": "boolean",
                                "default": False
                            }
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Word count data",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "word_counts": {"type": "object"},
                                            "total_words": {"type": "integer"},
                                            "estimated_reading_time_minutes": {"type": "number"},
                                            "labels_with_content": {"type": "integer"},
                                            "cache_refreshed": {"type": "boolean"}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/route/summary": {
                "get": {
                    "tags": ["route-analysis"],
                    "summary": "Route summary statistics",
                    "description": "Returns summary statistics about the story routes",
                    "responses": {
                        "200": {
                            "description": "Route summary data",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "total_labels": {"type": "integer"},
                                            "total_menus": {"type": "integer"},
                                            "total_choices": {"type": "integer"},
                                            "conditional_choices": {"type": "integer"}
                                        }
                                    }
                                }
                            }
                        },
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/save": {
                "post": {
                    "tags": ["control"],
                    "summary": "Save game state",
                    "description": "Saves the current game state to a slot",
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "slot": {"type": "string", "description": "Save slot name (optional)"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Save result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "slot": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/api/load": {
                "post": {
                    "tags": ["control"],
                    "summary": "Load game state",
                    "description": "Loads a saved game state from a slot",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "slot": {"type": "string", "description": "Save slot name to load"}
                                    },
                                    "required": ["slot"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Load result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"}
                    }
                }
            },
            "/api/click": {
                "post": {
                    "tags": ["utilities"],
                    "summary": "Send mouse click",
                    "description": "Sends a mouse click at specified coordinates",
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "x": {"type": "integer", "default": 400, "description": "X coordinate"},
                                        "y": {"type": "integer", "default": 300, "description": "Y coordinate"},
                                        "button": {"type": "integer", "default": 1, "description": "Mouse button (1=left, 2=middle, 3=right)"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Click result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        }
                    }
                }
            },
            "/api/key": {
                "post": {
                    "tags": ["utilities"],
                    "summary": "Send key press",
                    "description": "Sends a key press event",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "key": {"type": "string", "description": "Key to press"}
                                    },
                                    "required": ["key"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Key press result",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Success"}
                                }
                            }
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"}
                    }
                }
            },
            "/api/screenshot": {
                "get": {
                    "tags": ["utilities"],
                    "summary": "Take screenshot",
                    "description": "Takes a screenshot of the current game state",
                    "responses": {
                        "200": {
                            "description": "Screenshot image",
                            "content": {
                                "image/png": {
                                    "schema": {
                                        "type": "string",
                                        "format": "binary"
                                    }
                                }
                            }
                        },
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            },
            "/api/exec": {
                "get": {
                    "tags": ["utilities"],
                    "summary": "Get exec endpoint documentation",
                    "description": "Returns documentation for the code execution endpoint",
                    "responses": {
                        "200": {
                            "description": "Endpoint documentation",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "endpoint": {"type": "string"},
                                            "methods": {"type": "array", "items": {"type": "string"}},
                                            "description": {"type": "string"},
                                            "security_warning": {"type": "string"},
                                            "parameters": {"type": "object"},
                                            "capabilities": {"type": "array", "items": {"type": "string"}}
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
                "post": {
                    "tags": ["utilities"],
                    "summary": "Execute Python code",
                    "description": "Executes custom Python code in the game context. **WARNING: This provides full Python execution capabilities and should only be used in trusted development environments.**",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "code": {"type": "string", "description": "Python code to execute"},
                                        "mode": {
                                            "type": "string",
                                            "enum": ["exec", "eval"],
                                            "default": "exec",
                                            "description": "Execution mode: 'exec' for statements, 'eval' for expressions"
                                        }
                                    },
                                    "required": ["code"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Code execution result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "result": {"description": "Execution result (any type)"},
                                            "mode": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "400": {"$ref": "#/components/responses/BadRequest"},
                        "500": {"$ref": "#/components/responses/InternalServerError"}
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Error": {
                    "type": "object",
                    "properties": {
                        "error": {"type": "string"},
                        "code": {"type": "integer"}
                    },
                    "required": ["error", "code"]
                },
                "Success": {
                    "type": "object",
                    "properties": {
                        "success": {"type": "boolean"}
                    },
                    "required": ["success"]
                }
            },
            "responses": {
                "BadRequest": {
                    "description": "Bad request - missing or invalid parameters",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"}
                        }
                    }
                },
                "NotFound": {
                    "description": "Endpoint not found",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"}
                        }
                    }
                },
                "InternalServerError": {
                    "description": "Internal server error",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Error"}
                        }
                    }
                }
            }
        }
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
            elif path == '/api/route/cache-status':
                self._handle_route_cache_status()
            elif path == '/visualizer':
                self._serve_route_visualizer()
            elif path == '/api/route/open-visualizer':
                self._open_route_visualizer()
            elif path == '/docs' or path == '/swagger':
                self._serve_swagger_ui()
            elif path == '/openapi.json':
                self._serve_openapi_spec()
            else:
                self._send_error(404, "Endpoint not found")
                
        except Exception as e:
            self._send_error(500, str(e))

    def do_OPTIONS(self):
        """Handle OPTIONS requests for CORS preflight."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '86400')
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
        # Get project information
        project_path = None
        project_name = None
        try:
            import renpy
            if hasattr(renpy, 'config') and hasattr(renpy.config, 'gamedir'):
                project_path = renpy.config.gamedir
                if project_path:
                    # Get the parent directory (project root) from the game directory
                    import os
                    project_path = os.path.dirname(project_path)
                    project_name = os.path.basename(project_path)
        except:
            pass

        status = {
            'running': True,
            'interface_enabled': self.testing_interface.is_enabled(),
            'current_label': self.testing_interface.get_current_label(),
            'timestamp': time.time(),
            'project_path': project_path,
            'project_name': project_name
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
                'description': 'Execute custom Python code in the game context with full capabilities',
                'security_warning': 'This endpoint provides FULL Python execution including imports, file I/O, and system access. Use only in trusted development environments. NEVER expose in production.',
                'parameters': {
                    'code': 'Python code to execute (string)',
                    'mode': 'Optional: "eval" for expressions, "exec" for statements (default: "exec")'
                },
                'capabilities': [
                    'Full Python execution with all built-in functions',
                    'Import any Python module (import statements allowed)',
                    'File system access (open, read, write files)',
                    'Network access and system calls',
                    'Access to renpy and store modules',
                    'Pre-imported common modules: sys, os, json, time, datetime, re, math, random'
                ],
                'examples': [
                    {'code': 'import requests; print("Requests available")', 'mode': 'exec'},
                    {'code': 'renpy.store.persistent.quick_menu = True', 'mode': 'exec'},
                    {'code': 'renpy.store.persistent.quick_menu', 'mode': 'eval'},
                    {'code': 'print("Hello from custom code!")', 'mode': 'exec'},
                    {'code': 'os.getcwd()', 'mode': 'eval'},
                    {'code': 'with open("debug.txt", "w") as f: f.write("Debug info")', 'mode': 'exec'},
                    {'code': '[x**2 for x in range(5)]', 'mode': 'eval'}
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
        Execute code in the game context with full Python capabilities.

        SECURITY CONSIDERATIONS:
        - This endpoint provides full Python execution capabilities including imports
        - Intended for testing/debugging environments only
        - Should not be exposed in production environments
        - Access to file system, network, and all Python modules is allowed
        - Use with caution and only in trusted development environments

        Args:
            code (str): Python code to execute
            mode (str): Either 'exec' or 'eval'

        Returns:
            Result of code execution or success message
        """
        try:
            # Create execution environment with full Python capabilities
            # Include commonly used modules for convenience
            import sys
            import os
            import json
            import time
            import datetime
            import re
            import math
            import random

            exec_globals = {
                # Core Python modules
                '__builtins__': __builtins__,
                '__import__': __import__,

                # Ren'Py specific
                'renpy': renpy,
                'store': renpy.store,

                # Common Python modules (pre-imported for convenience)
                'sys': sys,
                'os': os,
                'json': json,
                'time': time,
                'datetime': datetime,
                're': re,
                'math': math,
                'random': random,

                # Additional useful functions
                'print': print,
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
                'type': type,
                'hasattr': hasattr,
                'getattr': getattr,
                'setattr': setattr,
                'delattr': delattr,
                'isinstance': isinstance,
                'issubclass': issubclass,
                'chr': chr,
                'ord': ord,
                'abs': abs,
                'round': round,
                'pow': pow,
                'divmod': divmod,
                'hex': hex,
                'oct': oct,
                'bin': bin,
                'format': format,
                'repr': repr,
                'ascii': ascii,
                'vars': vars,
                'dir': dir,
                'id': id,
                'hash': hash,
                'callable': callable,
                'iter': iter,
                'next': next,
                'filter': filter,
                'map': map,
                'any': any,
                'all': all,
                'open': open,
                'exec': exec,
                'eval': eval,
                'compile': compile,
                'globals': globals,
                'locals': locals,
            }

            exec_locals = {}

            if mode == 'eval':
                # Evaluate expression and return result
                result = eval(code, exec_globals, exec_locals)
                # Convert result to JSON-serializable format
                return self._serialize_result(result)
            else:
                # Execute statements
                exec(code, exec_globals, exec_locals)
                # Return any variables that were created
                if exec_locals:
                    # Filter out built-in variables and modules, but include functions
                    user_vars = {}
                    for k, v in exec_locals.items():
                        if not k.startswith('__') and k not in exec_globals:
                            user_vars[k] = v

                    if user_vars:
                        # Convert to serializable format
                        return {k: self._serialize_result(v) for k, v in user_vars.items()}
                return "Code executed successfully"

        except Exception as e:
            raise Exception(f"Execution failed: {str(e)}")

    def _serialize_result(self, result):
        """
        Convert execution result to JSON-serializable format.

        Args:
            result: The result to serialize

        Returns:
            JSON-serializable representation of the result
        """
        if result is None:
            return None
        elif isinstance(result, (str, int, float, bool)):
            return result
        elif isinstance(result, (list, tuple)):
            try:
                return [self._serialize_result(item) for item in result]
            except:
                return str(result)
        elif isinstance(result, dict):
            try:
                return {str(k): self._serialize_result(v) for k, v in result.items()}
            except:
                return str(result)
        elif callable(result):
            # For functions and callable objects
            try:
                return {
                    '__type__': 'function' if hasattr(result, '__name__') else 'callable',
                    '__name__': getattr(result, '__name__', 'unknown'),
                    '__module__': getattr(result, '__module__', 'unknown'),
                    '__doc__': getattr(result, '__doc__', None),
                    '__str__': str(result),
                    '__repr__': repr(result)
                }
            except:
                return str(result)
        elif hasattr(result, '__dict__'):
            # For objects with attributes, try to serialize their dict representation
            try:
                return {
                    '__type__': type(result).__name__,
                    '__module__': getattr(type(result), '__module__', 'unknown'),
                    '__str__': str(result),
                    '__repr__': repr(result)
                }
            except:
                return str(result)
        else:
            # Fallback to string representation
            return str(result)
    
    def _send_json_response(self, data):
        """Send JSON response."""
        response = json.dumps(data, default=str, indent=2)
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
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
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
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

            # Ensure metadata includes node and edge counts
            if not metadata.get('nodes_count'):
                metadata['nodes_count'] = len(route_graph.get('nodes', []))
            if not metadata.get('edges_count'):
                metadata['edges_count'] = len(route_graph.get('edges', []))
            
            # Only get summary data if we don't have essential metadata
            if not metadata or not metadata.get('total_labels'):
                summary_data = self._get_route_summary_data(analyzer)
                # Preserve existing word count if we have it
                existing_word_count = metadata.get('total_words', 0) if metadata else 0
                summary_word_count = summary_data.get('total_words', 0)
                
                metadata = {
                    'total_labels': summary_data.get('total_labels', 0),
                    'total_choices': summary_data.get('total_choices', 0),
                    'total_words': existing_word_count if existing_word_count > 0 else summary_word_count,
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

            # Get word counts from analysis data
            total_words = analysis_data.get('metadata', {}).get('total_words', 0)
            
            return {
                'total_labels': total_labels,
                'total_menus': total_menus,
                'total_choices': total_choices,
                'total_words': total_words,
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

            # Check for force refresh parameter to ensure fresh word counts
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            force_refresh = query_params.get('force_refresh', ['false'])[0].lower() == 'true'

            if force_refresh:
                # Specifically invalidate word count cache
                analyzer.invalidate_word_count_cache()

            analysis_data = analyzer.analyze_script(force_refresh=force_refresh)
            word_counts = analysis_data.get('word_counts', {})

            # Calculate additional metrics
            total_words = sum(word_counts.values()) if word_counts else 0
            estimated_reading_time = round(total_words / 200.0, 1)  # 200 words per minute

            self._send_json_response({
                'word_counts': word_counts,
                'total_words': total_words,
                'estimated_reading_time_minutes': estimated_reading_time,
                'labels_with_content': len([label for label, count in word_counts.items() if count > 0]),
                'cache_refreshed': force_refresh
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

    def _handle_route_cache_status(self):
        """Handle GET /api/route/cache-status - get cache status information."""
        try:
            from renpy.testing.route_analyzer import get_route_analyzer

            analyzer = get_route_analyzer()
            cache_status = analyzer.get_cache_status()

            self._send_json_response(cache_status)
        except Exception as e:
            self._send_error(500, f"Failed to get cache status: {str(e)}")

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

    def _serve_openapi_spec(self):
        """Serve the OpenAPI 3.0 specification as JSON."""
        try:
            spec = get_openapi_spec()
            # Update the server URL to match the current request
            host = self.headers.get('Host', f"{self.server.server_address[0]}:{self.server.server_address[1]}")
            spec['servers'] = [
                {
                    "url": f"http://{host}",
                    "description": "Local development server"
                }
            ]
            self._send_json_response(spec)
        except Exception as e:
            self._send_error(500, f"Failed to serve OpenAPI spec: {str(e)}")

    def _serve_swagger_ui(self):
        """Serve the Swagger UI HTML page."""
        try:
            # Use relative URL to avoid CORS issues
            openapi_url = "./openapi.json"

            swagger_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Ren'Py Debugging API - Swagger UI</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@4.15.5/swagger-ui.css" />
    <style>
        html {{
            box-sizing: border-box;
            overflow: -moz-scrollbars-vertical;
            overflow-y: scroll;
        }}
        *, *:before, *:after {{
            box-sizing: inherit;
        }}
        body {{
            margin:0;
            background: #fafafa;
        }}
        .swagger-ui .topbar {{
            background-color: #2c3e50;
        }}
        .swagger-ui .topbar .download-url-wrapper .select-label {{
            color: #fff;
        }}
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@4.15.5/swagger-ui-bundle.js"></script>
    <script src="https://unpkg.com/swagger-ui-dist@4.15.5/swagger-ui-standalone-preset.js"></script>
    <script>
        window.onload = function() {{
            const ui = SwaggerUIBundle({{
                url: '{openapi_url}',
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIStandalonePreset
                ],
                plugins: [
                    SwaggerUIBundle.plugins.DownloadUrl
                ],
                layout: "StandaloneLayout",
                tryItOutEnabled: true,
                requestInterceptor: function(request) {{
                    // Add CORS headers for local development
                    request.headers['Access-Control-Allow-Origin'] = '*';
                    return request;
                }},
                responseInterceptor: function(response) {{
                    return response;
                }}
            }});
        }};
    </script>
</body>
</html>"""

            # Send HTML response
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(swagger_html)))
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
            self.end_headers()
            self.wfile.write(swagger_html.encode('utf-8'))

        except Exception as e:
            self._send_error(500, f"Failed to serve Swagger UI: {str(e)}")

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
        self.update_thread.daemon = True  # Use daemon threads so they don't prevent main process exit
        self.update_thread.start()
        print("[WebSocket] Started scene monitoring")
    
    def stop_monitoring(self):
        """Stop monitoring scene changes."""
        self.running = False

        # Close all connections first
        for conn in self.connections:
            try:
                conn.close()
            except:
                pass
        self.connections.clear()

        # Wait for update thread to finish, but don't hang
        if self.update_thread and self.update_thread.is_alive():
            self.update_thread.join(timeout=0.5)  # Shorter timeout to prevent hanging
            if self.update_thread.is_alive():
                print("[WebSocket] Warning: Update thread did not stop cleanly")

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
                
                time.sleep(1.0)  # Check for updates every 1 second (reduced frequency)

            except Exception as e:
                print(f"[WebSocket] Scene monitoring error: {e}")
                time.sleep(2.0)  # Wait longer on error
    
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
        global _global_http_server
        if self.running:
            return True

        try:
            # Register this server globally for cleanup
            _global_http_server = self

            # Register shutdown hooks with Ren'Py
            _register_shutdown_hooks()

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
            self.server_thread.daemon = True  # Use daemon threads so they don't prevent main process exit
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
            self.running = False  # Set this first to prevent new operations

            # Stop WebSocket monitoring
            self.websocket_server.stop_monitoring()

            # Shutdown server
            if self.server:
                self.server.shutdown()
                self.server.server_close()

            # Wait for server thread to finish, but don't hang forever
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=1.0)  # Shorter timeout to prevent hanging
                if self.server_thread.is_alive():
                    print("Warning: Server thread did not stop cleanly")

            print("Testing API server stopped")

        except Exception as e:
            print("Error stopping testing API server: {}".format(e))

    def force_stop(self):
        """Force stop the HTTP server with brutal immediate shutdown."""
        if not self.running:
            return

        try:
            print("Force stopping HTTP server...")
            self.running = False

            # Stop WebSocket monitoring immediately - don't wait for anything
            try:
                self.websocket_server.stop_monitoring()
            except Exception:
                pass

            # Brutally shutdown the server - ignore all errors
            if self.server:
                try:
                    self.server.shutdown()
                except Exception:
                    pass
                try:
                    self.server.server_close()
                except Exception:
                    pass

            # Mark threads as None so they can be garbage collected
            self.server_thread = None

            print("HTTP API server force stopped")

        except Exception as e:
            print("Error force stopping HTTP server: {}".format(e))
    
    def is_running(self):
        """Check if server is running."""
        return self.running
    
    def get_url(self):
        """Get the server URL."""
        return "http://{}:{}".format(self.host, self.port)
