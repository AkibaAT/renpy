#!/usr/bin/env python3
"""
PyCharm Debugging Setup for Ren'Py

This enables PyCharm's remote debugging for Ren'Py games.
"""

def setup_pycharm_debugging(port=12345):
    """
    Set up PyCharm remote debugging.
    
    Args:
        port (int): Port for PyCharm debugger (default: 12345)
    """
    try:
        # PyCharm remote debugging
        import pydevd_pycharm
        
        print(f"🐛 Connecting to PyCharm debugger on localhost:{port}")
        
        # Connect to PyCharm debugger
        pydevd_pycharm.settrace(
            'localhost', 
            port=port, 
            stdoutToServer=True, 
            stderrToServer=True,
            suspend=False  # Don't pause immediately
        )
        
        print("✅ Connected to PyCharm debugger!")
        return True
        
    except ImportError:
        print("❌ PyCharm debugging not available")
        print("Make sure you've set up remote debugging in PyCharm")
        return False
    except Exception as e:
        print(f"❌ PyCharm debugging failed: {e}")
        return False

def enable_renpy_pycharm_debugging(port=12345):
    """Enable PyCharm debugging for Ren'Py with direct .rpy support."""
    try:
        from renpy.testing.debugger import get_debugger
        
        debugger = get_debugger()
        debugger.enable()
        
        # Set up PyCharm connection
        if setup_pycharm_debugging(port):
            debugger.pycharm_enabled = True
            debugger.pycharm_port = port
            
            print("🎮 Ren'Py + PyCharm debugging ready!")
            print("Set breakpoints in .rpy files in PyCharm and they'll work!")
            
            return True
        else:
            print("Falling back to standard debugging...")
            return False
            
    except Exception as e:
        print(f"Error setting up Ren'Py debugging: {e}")
        return False

if __name__ == "__main__":
    enable_renpy_pycharm_debugging()