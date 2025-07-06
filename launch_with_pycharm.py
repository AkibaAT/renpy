#!/usr/bin/env python3
"""
Launch Ren'Py game with PyCharm debugging enabled

This script sets up PyCharm debugging and launches a Ren'Py game.
"""

import sys
import os
import subprocess

def create_debug_rpy(game_dir, port=12345):
    """Create a .rpy file that enables PyCharm debugging"""
    
    debug_content = f'''# PyCharm Debug Auto-Setup
# This file is auto-generated

init -1000 python:
    try:
        # Add our virtual environment to Python path
        import sys
        import os
        
        venv_path = os.path.join(config.basedir, "renpy_debug_env", "lib", "python3.12", "site-packages")
        if os.path.exists(venv_path) and venv_path not in sys.path:
            sys.path.insert(0, venv_path)
        
        # Enable PyCharm debugging
        print("🐛 Setting up PyCharm debugging...")
        from renpy.testing.debugger import enable_pycharm_debugging
        
        success = enable_pycharm_debugging(port={port})
        if success:
            print("✅ PyCharm debugging enabled!")
            print("🎮 Set breakpoints in .rpy files in PyCharm and they'll work!")
        else:
            print("❌ Could not connect to PyCharm")
            print("Make sure PyCharm Debug Server is running on port {port}")
            
    except Exception as e:
        print(f"❌ PyCharm debug setup failed: {{e}}")
        print("Make sure:")
        print("1. PyCharm Debug Server is running")
        print("2. pydevd-pycharm is installed")
        print("3. Virtual environment is set up correctly")
'''
    
    debug_file = os.path.join(game_dir, "game", "00_pycharm_debug.rpy")
    
    with open(debug_file, 'w') as f:
        f.write(debug_content)
    
    print(f"✅ Created debug setup: {debug_file}")
    return debug_file

def launch_game(game_dir, port=12345):
    """Launch Ren'Py game with PyCharm debugging"""
    
    if not os.path.exists(game_dir):
        print(f"❌ Game directory not found: {game_dir}")
        return False
    
    if not os.path.exists(os.path.join(game_dir, "game")):
        print(f"❌ Not a Ren'Py game directory: {game_dir}")
        return False
    
    print(f"🎮 Launching Ren'Py game with PyCharm debugging")
    print(f"📁 Game: {game_dir}")
    print(f"🔌 PyCharm server: 172.26.176.1:{port}")
    print()
    
    # Create debug setup file
    debug_file = create_debug_rpy(game_dir, port)
    
    try:
        # Check if virtual environment exists
        venv_dir = "./renpy_debug_env"
        venv_python = os.path.join(venv_dir, "bin", "python")
        
        if not os.path.exists(venv_dir):
            print("❌ Virtual environment not found. Please run:")
            print("python3 -m venv renpy_debug_env")
            print("source renpy_debug_env/bin/activate")
            print("pip install pydevd-pycharm")
            return False
        
        # Launch Ren'Py (debugging packages now installed in Ren'Py lib)
        print("🚀 Starting Ren'Py...")
        print("📦 PyCharm debugging packages installed in Ren'Py lib directory")
        
        # Use standard Ren'Py launcher
        subprocess.run(["./renpy.sh", game_dir], check=True)
        
    except KeyboardInterrupt:
        print("\\n🛑 Game stopped")
    except FileNotFoundError as e:
        print(f"❌ File not found: {e}")
        print("Make sure you're running from the Ren'Py directory")
    except Exception as e:
        print(f"❌ Error: {e}")
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
        print("Launch Ren'Py with PyCharm Debugging")
        print()
        print("Usage: python launch_with_pycharm.py <game_directory> [port]")
        print("Example: python launch_with_pycharm.py the_question")
        print("         python launch_with_pycharm.py tutorial 12345")
        print()
        print("Available games:")
        for item in os.listdir('.'):
            if os.path.isdir(item) and os.path.exists(os.path.join(item, 'game')):
                print(f"  - {item}")
        print()
        print("PyCharm Setup:")
        print("1. In PyCharm: Run → Edit Configurations...")
        print("2. Add Python Debug Server configuration")
        print("3. Set Host: 172.26.176.1, Port: 12345")
        print("4. Start the debug server (green bug icon)")
        print("5. Run this script - it will connect automatically")
        print("6. Set breakpoints in .rpy files and they'll work!")
        sys.exit(1)
    
    game_dir = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 12345
    
    launch_game(game_dir, port)

if __name__ == "__main__":
    main()