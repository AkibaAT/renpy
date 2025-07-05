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
Command Line Interface for Testing

This module provides command line interfaces for the automated testing system.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
import json
import sys
from . import headless


def autotest_command():
    """
    Command to run a game in automated testing mode.
    """
    ap = renpy.arguments.ArgumentParser(description="Run game in automated testing mode.")

    ap.add_argument("--headless", action="store_true",
                   help="Run in headless mode (no display required)")
    ap.add_argument("--http-server", action="store_true",
                   help="Start HTTP API server for external control")
    ap.add_argument("--host", type=str, default="localhost",
                   help="HTTP server host (default: localhost)")
    ap.add_argument("--port", type=int, default=8080,
                   help="HTTP server port (default: 8080)")
    ap.add_argument("--script", type=str,
                   help="Python script to execute for testing")
    ap.add_argument("--steps", type=int, default=100,
                   help="Maximum number of steps to advance automatically")
    ap.add_argument("--delay", type=float, default=0.1,
                   help="Delay between automatic steps in seconds")
    ap.add_argument("--auto-advance", action="store_true",
                   help="Enable auto-advance mode (disabled by default)")
    ap.add_argument("--output", type=str,
                   help="File to write test results to")
    ap.add_argument("--format", choices=["json", "text"], default="json",
                   help="Output format for test results")
    
    args = ap.parse_args()
    
    # Enable headless mode if requested
    if args.headless:
        headless.enable_headless()
    
    # Configure for testing (with auto-advance only if explicitly requested)
    headless.configure_for_testing(enable_auto_advance=args.auto_advance)

    # Start HTTP server if requested
    if args.http_server:
        from . import get_testing_interface
        interface = get_testing_interface()
        if interface.start_http_server(args.host, args.port):
            print("HTTP API server started at http://{}:{}".format(args.host, args.port))
        else:
            print("Failed to start HTTP API server")

    # Set up auto-advance only if explicitly requested
    if hasattr(renpy.store, '_preferences') and args.auto_advance:
        renpy.store._preferences.afm_enable = True
        renpy.store._preferences.afm_time = args.delay
        print("Auto-advance enabled with delay: {} seconds".format(args.delay))
    
    # If a script is provided, execute it
    if args.script:
        try:
            with open(args.script, 'r') as f:
                script_content = f.read()
            exec(script_content)
        except Exception as e:
            print("Error executing test script: {}".format(e))
            return False
    
    # Run the game normally - the testing interface can be used from within
    return True


def inspect_command():
    """
    Command to inspect current game state.
    """
    ap = renpy.arguments.ArgumentParser(description="Inspect current game state.")
    
    ap.add_argument("--format", choices=["json", "text"], default="json",
                   help="Output format")
    ap.add_argument("--output", type=str,
                   help="File to write output to")
    ap.add_argument("--variables", action="store_true",
                   help="Include variable information")
    ap.add_argument("--scene", action="store_true",
                   help="Include scene information")
    ap.add_argument("--dialogue", action="store_true",
                   help="Include dialogue information")
    ap.add_argument("--all", action="store_true",
                   help="Include all available information")
    
    args = ap.parse_args()
    
    try:
        from . import get_testing_interface
        interface = get_testing_interface()
        
        # Determine what information to include
        if args.all:
            state_info = interface.inspect_state()
        else:
            state_info = {}
            if args.variables:
                state_info['variables'] = interface.get_variables()
            if args.scene:
                state_info['scene_info'] = interface.get_scene_info()
            if args.dialogue:
                state_info['dialogue_info'] = interface.get_dialogue_info()
            
            # If no specific options, include basic info
            if not any([args.variables, args.scene, args.dialogue]):
                state_info = {
                    'label': interface.get_current_label(),
                    'choices': interface.get_choices()
                }
        
        # Format output
        if args.format == "json":
            output = json.dumps(state_info, indent=2, default=str)
        else:
            output = _format_state_text(state_info)
        
        # Write output
        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
        else:
            print(output)
        
    except Exception as e:
        print("Error inspecting state: {}".format(e))
        return False
    
    return False  # Don't continue with normal game execution


def save_state_command():
    """
    Command to save current game state.
    """
    ap = renpy.arguments.ArgumentParser(description="Save current game state.")
    
    ap.add_argument("slot", help="Save slot name")
    ap.add_argument("--export", action="store_true",
                   help="Export state data to JSON file")
    ap.add_argument("--output", type=str,
                   help="File to write exported data to")
    
    args = ap.parse_args()
    
    try:
        from . import get_testing_interface
        interface = get_testing_interface()
        
        # Save the state
        slot_used = interface.save_state(args.slot)
        print("State saved to slot: {}".format(slot_used))
        
        # Export if requested
        if args.export:
            state_data = interface.export_state()
            
            output_file = args.output or "{}.json".format(args.slot)
            with open(output_file, 'w') as f:
                json.dump(state_data, f, indent=2, default=str)
            print("State exported to: {}".format(output_file))
        
    except Exception as e:
        print("Error saving state: {}".format(e))
        return False
    
    return False  # Don't continue with normal game execution


def load_state_command():
    """
    Command to load game state.
    """
    ap = renpy.arguments.ArgumentParser(description="Load game state.")
    
    ap.add_argument("slot", help="Save slot name to load")
    ap.add_argument("--import", dest="import_file", type=str,
                   help="Import state data from JSON file")
    
    args = ap.parse_args()
    
    try:
        from . import get_testing_interface
        interface = get_testing_interface()
        
        # Import if requested
        if args.import_file:
            with open(args.import_file, 'r') as f:
                state_data = json.load(f)
            
            if interface.import_state(state_data):
                print("State imported from: {}".format(args.import_file))
            else:
                print("Failed to import state from: {}".format(args.import_file))
                return False
        
        # Load the state
        if interface.load_state(args.slot):
            print("State loaded from slot: {}".format(args.slot))
        else:
            print("Failed to load state from slot: {}".format(args.slot))
            return False
        
    except Exception as e:
        print("Error loading state: {}".format(e))
        return False
    
    return True  # Continue with normal game execution


def http_server_command():
    """
    Command to start HTTP API server for external testing control.
    """
    ap = renpy.arguments.ArgumentParser(description="Start HTTP API server for testing.")

    ap.add_argument("--host", type=str, default="localhost",
                   help="Host to bind to (default: localhost)")
    ap.add_argument("--port", type=int, default=8080,
                   help="Port to bind to (default: 8080)")
    ap.add_argument("--headless", action="store_true",
                   help="Run in headless mode")

    args = ap.parse_args()

    # Enable headless mode if requested
    if args.headless:
        headless.enable_headless()

    # Configure for testing (auto-advance disabled by default for HTTP server)
    headless.configure_for_testing(enable_auto_advance=False)

    try:
        from . import get_testing_interface
        interface = get_testing_interface()

        if interface.start_http_server(args.host, args.port):
            print("HTTP API server started at http://{}:{}".format(args.host, args.port))
            print("API endpoints available:")
            print("  GET  /api/status     - Get server status")
            print("  GET  /api/state      - Get full game state")
            print("  GET  /api/variables  - Get game variables")
            print("  GET  /api/scene      - Get scene information")
            print("  GET  /api/dialogue   - Get dialogue information")
            print("  GET  /api/choices    - Get available choices")
            print("  POST /api/advance    - Advance dialogue")
            print("  POST /api/rollback   - Roll back (body: {\"steps\": N})")
            print("  POST /api/choice     - Select choice (body: {\"choice\": N})")
            print("  POST /api/jump       - Jump to label (body: {\"label\": \"name\"})")
            print("  POST /api/variable   - Set variable (body: {\"name\": \"var\", \"value\": val})")
            print("  POST /api/save       - Save state (body: {\"slot\": \"name\"})")
            print("  POST /api/load       - Load state (body: {\"slot\": \"name\"})")
            print("  POST /api/click      - Send click (body: {\"x\": N, \"y\": N})")
            print("  POST /api/key        - Send key (body: {\"key\": N})")
            print("\nServer will run until game exits...")
        else:
            print("Failed to start HTTP API server")
            return False

    except Exception as e:
        print("Error starting HTTP server: {}".format(e))
        return False

    return True  # Continue with normal game execution


def _format_state_text(state_info):
    """
    Format state information as human-readable text.
    
    Args:
        state_info (dict): State information dictionary
        
    Returns:
        str: Formatted text representation
    """
    lines = []
    
    if 'label' in state_info:
        lines.append("Current Label: {}".format(state_info['label']))
    
    if 'variables' in state_info:
        lines.append("\nVariables:")
        for name, value in state_info['variables'].items():
            lines.append("  {} = {}".format(name, repr(value)))
    
    if 'scene_info' in state_info:
        scene = state_info['scene_info']
        lines.append("\nScene Information:")
        lines.append("  Active Screens: {}".format(", ".join(scene.get('active_screens', []))))
        lines.append("  Shown Images: {}".format(len(scene.get('shown_images', []))))
    
    if 'dialogue_info' in state_info:
        dialogue = state_info['dialogue_info']
        lines.append("\nDialogue Information:")
        lines.append("  Statement Type: {}".format(dialogue.get('statement_type', 'None')))
        if dialogue.get('who'):
            lines.append("  Who: {}".format(dialogue['who']))
        if dialogue.get('what'):
            lines.append("  What: {}".format(dialogue['what']))
    
    if 'choices' in state_info:
        choices = state_info['choices']
        if choices:
            lines.append("\nAvailable Choices:")
            for i, choice in enumerate(choices):
                lines.append("  {}: {}".format(i, choice))
        else:
            lines.append("\nNo choices available")
    
    return "\n".join(lines)


# Register commands with Ren'Py
def register_commands():
    """Register all testing commands with Ren'Py's argument system."""
    renpy.arguments.register_command("autotest", autotest_command, uses_display=True)
    renpy.arguments.register_command("http_server", http_server_command, uses_display=True)
    renpy.arguments.register_command("inspect", inspect_command, uses_display=False)
    renpy.arguments.register_command("save_state", save_state_command, uses_display=False)
    renpy.arguments.register_command("load_state", load_state_command, uses_display=True)
