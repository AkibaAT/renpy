#!/usr/bin/env python3
"""
Robust PyCharm debugging that tries multiple connection methods
"""

def connect_to_pycharm(port=12345, host='localhost'):
    """Try multiple ways to connect to PyCharm."""
    
    print(f"🔍 Trying to connect to PyCharm on {host}:{port}")
    
    # Method 1: pydevd_pycharm (most common)
    try:
        import pydevd_pycharm
        print("📦 Using pydevd_pycharm")
        
        pydevd_pycharm.settrace(
            host, 
            port=port, 
            stdoutToServer=True, 
            stderrToServer=True,
            suspend=False
        )
        print("✅ Connected via pydevd_pycharm!")
        return True
        
    except ImportError:
        print("⚠️  pydevd_pycharm not available")
    except ConnectionRefusedError:
        print("❌ pydevd_pycharm: Connection refused")
    except Exception as e:
        print(f"❌ pydevd_pycharm failed: {e}")
    
    # Method 2: Direct pydevd
    try:
        import pydevd
        print("📦 Using pydevd directly")
        
        pydevd.settrace(
            host, 
            port=port, 
            stdoutToServer=True, 
            stderrToServer=True,
            suspend=False
        )
        print("✅ Connected via pydevd!")
        return True
        
    except ImportError:
        print("⚠️  pydevd not available")
    except ConnectionRefusedError:
        print("❌ pydevd: Connection refused")
    except Exception as e:
        print(f"❌ pydevd failed: {e}")
    
    # Method 3: Socket test to see if PyCharm is listening
    try:
        import socket
        print("🔌 Testing if PyCharm is listening...")
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"✅ PyCharm is listening on {host}:{port}")
            print("❌ But Python debugging packages can't connect")
            print("Try different PyCharm debug server settings")
        else:
            print(f"❌ Nothing listening on {host}:{port}")
            print("Make sure PyCharm Debug Server is running")
            
    except Exception as e:
        print(f"❌ Socket test failed: {e}")
    
    return False

def setup_renpy_debugging_with_fallback():
    """Set up Ren'Py debugging with PyCharm, falling back to basic debugging."""
    
    try:
        from renpy.testing.debugger import get_debugger, enable
        
        debugger = get_debugger()
        enable()
        
        # Try to connect to PyCharm
        if connect_to_pycharm():
            debugger.pycharm_enabled = True
            print("🎮 Ren'Py + PyCharm debugging enabled!")
        else:
            print("⚠️  PyCharm connection failed, using basic debugging")
            print("You can still set breakpoints programmatically")
            
    except Exception as e:
        print(f"❌ Ren'Py debugging setup failed: {e}")

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 12345
    
    print("=== PyCharm Connection Test ===")
    connect_to_pycharm(port)
    
    print("\n=== Ren'Py Integration Test ===")
    setup_renpy_debugging_with_fallback()