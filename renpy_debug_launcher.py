#!/usr/bin/env python3
"""
Ren'Py + PyCharm Debug Launcher

This script launches Ren'Py games with PyCharm debugging enabled.
"""

import sys
import os
import subprocess
import tempfile

def create_debug_init_script(game_dir, host='172.26.176.1', port=12345):
    """Create a debug initialization script for the game"""
    
    debug_content = f'''# PyCharm Debug Integration
# This file is auto-generated - do not edit manually

init -1000 python:
    import sys
    import os
    
    # Add our venv to path so we can import pydevd
    venv_path = os.path.join(os.path.dirname(config.basedir), "renpy_debug_env", "lib", "python3.12", "site-packages")
    if os.path.exists(venv_path) and venv_path not in sys.path:
        sys.path.insert(0, venv_path)
    
    try:
        print("🐛 Initializing PyCharm debugging...")
        import pydevd
        
        # Set environment to reduce warnings
        os.environ['PYDEVD_DISABLE_FILE_VALIDATION'] = '1'
        
        # Connect to PyCharm
        pydevd.settrace(
            host='{host}',
            port={port},
            stdoutToServer=False,  # Keep stdout local
            stderrToServer=False,  # Keep stderr local
            suspend=False,
            trace_only_current_thread=False
        )
        
        print("✅ Connected to PyCharm debugger on {host}:{port}")
        print("🎮 You can now set breakpoints in .rpy files!")
        
        # Store debug info for later use
        store._debug_enabled = True
        store._debug_host = '{host}'
        store._debug_port = {port}
        
    except ImportError as e:
        print("❌ PyCharm debugging not available:", e)
        print("Make sure pydevd is installed in the virtual environment")
        store._debug_enabled = False
    except Exception as e:
        print("❌ Failed to connect to PyCharm:", e)
        print("Make sure PyCharm Debug Server is running")
        store._debug_enabled = False

# Debug helper functions
init python:
    def debug_breakpoint(label="breakpoint"):
        """Set a breakpoint in Ren'Py code"""
        if hasattr(store, '_debug_enabled') and store._debug_enabled:
            print(f"🎯 Debug breakpoint: {{label}}")
            # This line will trigger the debugger
            x = 42  # <-- Breakpoint here
            
    def debug_vars(**kwargs):
        """Print debug variables"""
        if hasattr(store, '_debug_enabled') and store._debug_enabled:
            print("🔍 Debug variables:")
            for key, value in kwargs.items():
                print(f"  {{key}} = {{value}}")
'''
    
    debug_file = os.path.join(game_dir, "game", "00_pycharm_debug.rpy")
    
    with open(debug_file, 'w') as f:
        f.write(debug_content)
    
    print(f"✅ Created debug script: {debug_file}")
    return debug_file

def launch_renpy_with_debug(game_dir, host='172.26.176.1', port=12345):
    """Launch Ren'Py with PyCharm debugging enabled"""
    
    if not os.path.exists(game_dir):
        print(f"❌ Game directory not found: {game_dir}")
        return False
    
    print(f"🎮 Launching Ren'Py with PyCharm debugging")
    print(f"📁 Game: {game_dir}")
    print(f"🔌 Debug server: {host}:{port}")
    
    # Create debug initialization script
    debug_file = create_debug_init_script(game_dir, host, port)
    
    try:
        # Use our virtual environment Python
        venv_python = os.path.join(os.path.dirname(__file__), "renpy_debug_env", "bin", "python")
        
        # Launch Ren'Py
        renpy_script = os.path.join(os.path.dirname(__file__), "renpy.py")
        
        print("🚀 Starting Ren'Py...")
        print(f"Command: {venv_python} {renpy_script} {game_dir}")
        
        # Set environment to use our venv
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.join(os.path.dirname(__file__), "renpy_debug_env", "lib", "python3.12", "site-packages")
        
        subprocess.run([venv_python, renpy_script, game_dir], env=env, check=True)
        
    except KeyboardInterrupt:
        print("\\n🛑 Debugging session ended")
    except FileNotFoundError as e:
        print(f"❌ Could not find required files: {e}")
        print("Make sure you're running this from the Ren'Py directory")
    except Exception as e:
        print(f"❌ Error launching Ren'Py: {e}")
    finally:
        # Clean up debug file
        try:
            os.remove(debug_file)
            print("🧹 Cleaned up debug files")
        except:
            pass

def main():
    """Main function"""
    
    if len(sys.argv) < 2:
        print("Usage: python renpy_debug_launcher.py <game_directory> [host] [port]")
        print("Example: python renpy_debug_launcher.py the_question")
        print("         python renpy_debug_launcher.py the_question 172.26.176.1 12345")
        print()
        print("Available games:")
        for item in os.listdir('.'):
            if os.path.isdir(item) and os.path.exists(os.path.join(item, 'game')):
                print(f"  - {item}")
        sys.exit(1)
    
    game_dir = sys.argv[1]
    host = sys.argv[2] if len(sys.argv) > 2 else '172.26.176.1'
    port = int(sys.argv[3]) if len(sys.argv) > 3 else 12345
    
    print("=== Ren'Py + PyCharm Debug Launcher ===")
    print()
    print("PyCharm Setup Instructions:")
    print("1. In PyCharm: Run → Edit Configurations...")
    print("2. Click '+' → Python → Python Debug Server")
    print(f"3. Set Host: {host}")
    print(f"4. Set Port: {port}")
    print("5. Click 'OK' then click the Debug button")
    print("6. PyCharm should show 'Waiting for process connection...'")
    print("7. This script will connect automatically")
    print()
    
    launch_renpy_with_debug(game_dir, host, port)

if __name__ == "__main__":
    main()