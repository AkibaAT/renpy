#!/usr/bin/env python3
"""
Test PyCharm debugging setup
"""

def test_pycharm_connection(port=12345, host='localhost'):
    """Test connection to PyCharm debugger"""
    
    print(f"🔍 Testing PyCharm connection on {host}:{port}")
    
    # Test socket connection first
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((host, port))
        sock.close()
        
        if result == 0:
            print(f"✅ PyCharm is listening on {host}:{port}")
            
            # Try to connect with pydevd
            try:
                import pydevd
                print("📦 Attempting to connect with pydevd...")
                
                pydevd.settrace(
                    host, 
                    port=port, 
                    stdoutToServer=True, 
                    stderrToServer=True,
                    suspend=False
                )
                print("✅ Connected successfully!")
                
                # Test breakpoint
                print("🎯 Setting test breakpoint...")
                x = 42
                print(f"Value at breakpoint: {x}")
                
                return True
                
            except Exception as e:
                print(f"❌ Connection failed: {e}")
                return False
                
        else:
            print(f"❌ Nothing listening on {host}:{port}")
            print("To set up PyCharm Debug Server:")
            print("1. In PyCharm: Run → Edit Configurations...")
            print("2. Click '+' → Python → Python Debug Server")
            print(f"3. Set Port: {port}")
            print("4. Set Host: localhost")
            print("5. Click 'OK' then click the Debug button (green bug icon)")
            print("6. PyCharm should show 'Waiting for process connection...'")
            print("7. Then run this script again")
            return False
            
    except Exception as e:
        print(f"❌ Socket test failed: {e}")
        return False

def main():
    """Main test function"""
    
    print("=== PyCharm Debug Connection Test ===")
    print("Virtual environment:", __file__)
    
    # Test different ports
    ports = [12345, 5678, 9999]
    
    for port in ports:
        print(f"\n--- Testing port {port} ---")
        if test_pycharm_connection(port):
            print(f"🎉 Success! Connected on port {port}")
            break
        else:
            print(f"❌ Failed to connect on port {port}")
    else:
        print("\n❌ Could not connect to PyCharm on any port")
        print("Make sure PyCharm Debug Server is running")

if __name__ == "__main__":
    main()