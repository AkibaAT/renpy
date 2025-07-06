#!/usr/bin/env python3
"""
PyCharm Ren'Py Debugging Launcher

This script makes it easy to debug Ren'Py games with PyCharm.
"""

import sys
import os
import subprocess

def main():
    if len(sys.argv) < 2:
        print("Usage: python renpy_pycharm.py <game_directory> [port]")
        print("Example: python renpy_pycharm.py mygame")
        print("         python renpy_pycharm.py mygame 12345")
        sys.exit(1)
    
    game_dir = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 12345
    
    # Check if game directory exists
    if not os.path.exists(game_dir):
        print(f"Error: Game directory '{game_dir}' not found")
        sys.exit(1)
    
    print(f"🎮 Starting Ren'Py with PyCharm debugging enabled")
    print(f"📁 Game: {game_dir}")
    print(f"🔌 Port: {port}")
    print()
    print("PyCharm Setup:")
    print("1. Install: pip install pydevd-pycharm~=251.26927.74")
    print("2. In PyCharm: Run → Edit Configurations...")
    print("3. Click '+' → Python → Python Debug Server")
    print(f"4. Set Port: {port}")
    print("5. Set Host: localhost")
    print("6. Click 'OK' then click the Debug button (green bug icon)")
    print("7. PyCharm should show 'Waiting for process connection...'")
    print("8. Then run this script - it will connect automatically")
    print("9. Open .rpy files in PyCharm and set breakpoints directly!")
    print()
    
    # Create the debug init script
    debug_script = f"""
# Auto-generated PyCharm debugging setup
init -1000 python:
    try:
        from renpy.testing.debugger import enable_pycharm_debugging
        print("🐛 Connecting to PyCharm debugger...")
        success = enable_pycharm_debugging(port={port})
        if success:
            print("✅ PyCharm debugging ready!")
        else:
            print("❌ Could not connect to PyCharm")
            print("Make sure PyCharm Debug Server is running on port {port}")
    except Exception as e:
        print(f"❌ Could not enable debugging: {{e}}")
        print("Make sure pydevd-pycharm is installed: pip install pydevd-pycharm~=251.26927.74")
"""
    
    # Write debug script to game directory
    debug_file = os.path.join(game_dir, "_pycharm_debug.rpy")
    with open(debug_file, 'w') as f:
        f.write(debug_script)
    
    try:
        # Launch Ren'Py
        if os.name == 'nt':  # Windows
            renpy_cmd = 'renpy.exe'
        else:  # Linux/Mac
            renpy_cmd = './renpy.sh'
        
        print("🚀 Launching Ren'Py...")
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