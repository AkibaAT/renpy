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
Developer Shortcuts for Ren'Py Testing Interface

This module provides keyboard shortcuts for developers during game testing,
including shortcuts to open the route visualizer and other debugging tools.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
import threading

# Try to import requests, fallback to urllib if not available
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    import urllib.request
    import urllib.error
    HAS_REQUESTS = False

# Global flag to track if shortcuts are enabled
shortcuts_enabled = False
http_server_port = None

def enable_dev_shortcuts(port=None):
    """Enable developer shortcuts."""
    global shortcuts_enabled, http_server_port
    shortcuts_enabled = True
    http_server_port = port or 8081
    
    # Register the keymap
    renpy.config.keymap['dev_route_visualizer'] = ['ctrl_shift_R']
    renpy.config.keymap['dev_toggle_shortcuts'] = ['ctrl_shift_D']
    
    print(f"[DEV] Developer shortcuts enabled. Press Ctrl+Shift+R to open route visualizer.")

def disable_dev_shortcuts():
    """Disable developer shortcuts."""
    global shortcuts_enabled
    shortcuts_enabled = False
    
    # Remove the keymap entries
    if 'dev_route_visualizer' in renpy.config.keymap:
        del renpy.config.keymap['dev_route_visualizer']
    if 'dev_toggle_shortcuts' in renpy.config.keymap:
        del renpy.config.keymap['dev_toggle_shortcuts']
    
    print("[DEV] Developer shortcuts disabled.")

def open_route_visualizer():
    """Open the route visualizer in the browser."""
    if not shortcuts_enabled:
        return
    
    try:
        # Make a request to the API to open the visualizer
        url = f"http://localhost:{http_server_port}/api/route/open-visualizer"
        
        def make_request():
            try:
                if HAS_REQUESTS:
                    response = requests.get(url, timeout=2)
                    if response.status_code == 200:
                        data = response.json()
                        print(f"[DEV] Route visualizer opened: {data.get('url', 'Unknown URL')}")
                    else:
                        print(f"[DEV] Failed to open route visualizer: HTTP {response.status_code}")
                else:
                    # Fallback to urllib
                    req = urllib.request.Request(url)
                    with urllib.request.urlopen(req, timeout=2) as response:
                        if response.getcode() == 200:
                            import json
                            data = json.loads(response.read().decode('utf-8'))
                            print(f"[DEV] Route visualizer opened: {data.get('url', 'Unknown URL')}")
                        else:
                            print(f"[DEV] Failed to open route visualizer: HTTP {response.getcode()}")
            except Exception as e:
                print(f"[DEV] Failed to open route visualizer: {e}")
        
        # Make the request in a separate thread to avoid blocking the game
        thread = threading.Thread(target=make_request, daemon=True)
        thread.start()
        
    except Exception as e:
        print(f"[DEV] Error setting up route visualizer request: {e}")

def toggle_dev_shortcuts():
    """Toggle developer shortcuts on/off."""
    global shortcuts_enabled
    if shortcuts_enabled:
        disable_dev_shortcuts()
    else:
        enable_dev_shortcuts()

# Screen action classes for the shortcuts
class OpenRouteVisualizerAction(renpy.Action):
    """Action to open the route visualizer."""
    
    def __call__(self):
        open_route_visualizer()
        return True
    
    def get_sensitive(self):
        return shortcuts_enabled

class ToggleDevShortcutsAction(renpy.Action):
    """Action to toggle developer shortcuts."""
    
    def __call__(self):
        toggle_dev_shortcuts()
        return True
    
    def get_sensitive(self):
        return True

# Register the actions with Ren'Py
def register_dev_actions():
    """Register developer actions with Ren'Py."""
    try:
        # Create a keymap for dev shortcuts
        dev_keymap = renpy.Keymap(
            dev_route_visualizer=OpenRouteVisualizerAction(),
            dev_toggle_shortcuts=ToggleDevShortcutsAction()
        )

        # Add to the underlay so it works globally
        if not hasattr(renpy.config, 'underlay'):
            renpy.config.underlay = []

        renpy.config.underlay.append(dev_keymap)
        print("[DEV] Developer actions registered successfully")

    except Exception as e:
        print(f"[DEV] Failed to register dev actions: {e}")

# Auto-initialization
def init_dev_shortcuts():
    """Initialize developer shortcuts if HTTP server is running."""
    try:
        # Check if we're in developer mode or if HTTP server is enabled
        if renpy.config.developer or hasattr(renpy, 'testing_interface'):
            # Try to detect if HTTP server is running
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                result = sock.connect_ex(('localhost', 8081))
                if result == 0:
                    # HTTP server is running, enable shortcuts
                    enable_dev_shortcuts(8081)
                    register_dev_actions()
            finally:
                sock.close()
                
    except Exception as e:
        print(f"[DEV] Failed to initialize dev shortcuts: {e}")

# Call initialization when module is imported
if renpy.config.developer:
    init_dev_shortcuts()
