#!/usr/bin/env python3
"""
Test PyCharm debugging connection
"""

def test_pycharm_connection(port=12345):
    print(f"Testing PyCharm connection on port {port}...")
    
    try:
        import pydevd_pycharm
        print("✅ pydevd_pycharm is installed")
    except ImportError:
        print("❌ pydevd_pycharm not found")
        print("Install with: pip install pydevd-pycharm")
        return False
    
    try:
        print(f"🔌 Attempting to connect to PyCharm on localhost:{port}")
        print("Make sure PyCharm Debug Server is running first!")
        
        # This should connect to PyCharm
        pydevd_pycharm.settrace(
            'localhost', 
            port=port, 
            stdoutToServer=True, 
            stderrToServer=True,
            suspend=True  # This will pause here if connected
        )
        
        print("✅ Connected to PyCharm!")
        print("If you see this message, PyCharm debugging is working!")
        
        # Set a variable that you can inspect in PyCharm
        test_variable = "Hello from Ren'Py debugging!"
        debug_info = {
            'status': 'connected',
            'port': port,
            'message': 'PyCharm debugging is working!'
        }
        
        # This line should trigger a breakpoint in PyCharm
        print("🐛 This line should pause in PyCharm debugger")
        
        return True
        
    except ConnectionRefusedError:
        print("❌ Connection refused - PyCharm Debug Server not running")
        print("Start PyCharm Debug Server first, then run this script")
        return False
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 12345
    test_pycharm_connection(port)