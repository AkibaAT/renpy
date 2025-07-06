#!/usr/bin/env python3
"""
Simple Ren'Py Debugging Launcher

This script makes it trivial to debug Ren'Py games with VSCode.
Just run: python renpy_debug.py mygame
"""

import sys
import os
import subprocess

def main():
    if len(sys.argv) < 2:
        print("Usage: python renpy_debug.py <game_directory> [port]")
        print("Example: python renpy_debug.py mygame")
        print("         python renpy_debug.py mygame 5679")
        sys.exit(1)
    
    game_dir = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 5678
    
    # Check if game directory exists
    if not os.path.exists(game_dir):
        print(f"Error: Game directory '{game_dir}' not found")
        sys.exit(1)
    
    print(f"🎮 Starting Ren'Py with VSCode debugging enabled")
    print(f"📁 Game: {game_dir}")
    print(f"🔌 Port: {port}")
    print()
    print("VSCode Setup:")
    print("1. Open your game folder in VSCode")
    print("2. Open any .rpy file")  
    print("3. Set breakpoints directly in .rpy files")
    print("4. Press Ctrl+Shift+P and run 'Python: Attach'")
    print(f"5. Enter localhost:{port} when prompted")
    print("6. Your breakpoints will work!")
    print()
    
    # Create the debug init script
    debug_script = f"""
# Auto-generated debugging setup
init -1000 python:
    try:
        from renpy.testing.debugger import enable_vscode_debugging
        print("🐛 Enabling VSCode debugging...")
        enable_vscode_debugging(port={port}, wait_for_client=False)
        print("✅ VSCode debugging ready!")
    except Exception as e:
        print(f"❌ Could not enable debugging: {{e}}")
        print("Make sure debugpy is installed: pip install debugpy")
"""
    
    # Write debug script to game directory
    debug_file = os.path.join(game_dir, "_renpy_debug.rpy")
    with open(debug_file, 'w') as f:
        f.write(debug_script)
    
    try:
        # Launch Ren'Py
        if os.name == 'nt':  # Windows
            renpy_cmd = 'renpy.exe'
        else:  # Linux/Mac
            renpy_cmd = './renpy.sh'
        
        subprocess.run([renpy_cmd, game_dir], check=True)
    
    except KeyboardInterrupt:
        print("\n🛑 Debugging session ended")
    except FileNotFoundError:
        print("❌ Could not find Ren'Py executable")
        print("Make sure you're running this from the Ren'Py directory")
    finally:
        # Clean up debug file
        try:
            os.remove(debug_file)
        except:
            pass

if __name__ == "__main__":
    main()