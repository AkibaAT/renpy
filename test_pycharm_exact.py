#\!/usr/bin/env python3
"""
Test PyCharm connection with proper protocol handling
"""

import sys
import time

def test_pycharm_connection(host='172.26.176.1', port=12345):
    """Test PyCharm connection with proper error handling"""
    
    print(f"Connecting to PyCharm on {host}:{port}")
    
    try:
        import pydevd
        
        # Set environment to reduce warnings
        import os
        os.environ['PYDEVD_DISABLE_FILE_VALIDATION'] = '1'
        
        print("Attempting PyCharm connection...")
        
        # Try connection with minimal settings
        pydevd.settrace(
            host=host,
            port=port,
            stdoutToServer=False,  # Keep stdout local to avoid protocol issues
            stderrToServer=False,  # Keep stderr local to avoid protocol issues
            suspend=False,
            trace_only_current_thread=False
        )
        
        print("Connected to PyCharm debugger!")
        
        # Simple test with breakpoint
        print("Setting test breakpoint...")
        x = 42
        y = x * 2  # <- This line should be debuggable
        print(f"Test values: x={x}, y={y}")
        
        # Keep connection alive briefly
        time.sleep(2)
        
        print("Debug session completed successfully!")
        return True
        
    except ImportError as e:
        print(f"Import error: {e}")
        return False
    except ConnectionRefusedError as e:
        print(f"Connection refused: {e}")
        return False
    except Exception as e:
        print(f"Connection error: {e}")
        return False

def main():
    """Main test function"""
    
    print("=== PyCharm Debug Connection Test ===")
    
    # Test with the WSL IP
    if test_pycharm_connection('172.26.176.1', 12345):
        print("Success!")
    else:
        print("Failed to connect")
        print("\nTroubleshooting:")
        print("1. Make sure PyCharm Debug Server is running")
        print("2. Check that the port matches (default: 12345)")
        print("3. Verify the IP address 172.26.176.1 is correct")
        print("4. Try different stdoutToServer/stderrToServer settings")

if __name__ == "__main__":
    main()