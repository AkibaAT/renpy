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
Route Visualizer Keyboard Shortcut

This module adds a keyboard shortcut to open the route visualizer in a browser.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
import requests
import webbrowser

def open_route_visualizer():
    """Open the route visualizer in the default browser."""
    try:
        # Check if HTTP server is running by trying to access the API
        try:
            response = requests.get('http://localhost:8081/api/status', timeout=1)
            if response.status_code == 200:
                # Server is running, open the visualizer
                visualizer_url = 'http://localhost:8081/visualizer'
                webbrowser.open(visualizer_url)
                renpy.notify("Route visualizer opened in browser!")
                return
        except requests.exceptions.RequestException:
            pass
        
        # Try alternative ports
        for port in [8080, 8082, 8083]:
            try:
                response = requests.get(f'http://localhost:{port}/api/status', timeout=1)
                if response.status_code == 200:
                    visualizer_url = f'http://localhost:{port}/visualizer'
                    webbrowser.open(visualizer_url)
                    renpy.notify(f"Route visualizer opened in browser (port {port})!")
                    return
            except requests.exceptions.RequestException:
                continue
        
        # No server found
        renpy.notify("HTTP server not running. Start game with 'http_server' argument.")
        
    except Exception as e:
        renpy.notify(f"Failed to open route visualizer: {str(e)}")

def init_route_visualizer_keymap():
    """Initialize the route visualizer keyboard shortcut."""
    try:
        # Add the keymap entry for F12 key
        if 'route_visualizer' not in renpy.config.keymap:
            renpy.config.keymap['route_visualizer'] = ['K_F12']
        
        # Create a keymap object that calls our function
        route_visualizer_keymap = renpy.Keymap(
            route_visualizer=open_route_visualizer
        )
        
        # Add to the underlay so it's available everywhere
        if route_visualizer_keymap not in renpy.config.underlay:
            renpy.config.underlay.append(route_visualizer_keymap)
            
        print("Route visualizer keymap initialized (F12 key)")
        
    except Exception as e:
        print(f"Failed to initialize route visualizer keymap: {e}")

# Initialize when this module is imported
try:
    init_route_visualizer_keymap()
except Exception as e:
    print(f"Error during route visualizer keymap initialization: {e}")
