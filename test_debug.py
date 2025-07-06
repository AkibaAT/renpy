#!/usr/bin/env python3
"""
Quick test to verify debugpy setup works
"""

def test_debugpy():
    try:
        import debugpy
        print("✅ debugpy is installed")
        
        # Start server
        debugpy.listen(("localhost", 5678))
        print("✅ debugpy server started on localhost:5678")
        print()
        print("Now in VSCode:")
        print("1. Press Ctrl+Shift+D (Debug panel)")
        print("2. Click 'Attach to Ren'Py' and press play")
        print("3. Set a breakpoint on the line below")
        print("4. Press Enter here to trigger the breakpoint")
        
        input("Press Enter to trigger breakpoint...")
        
        # This line should trigger a breakpoint if VSCode is attached
        breakpoint_test = "This should pause if debugger is attached"
        debugpy.breakpoint()  # Force a breakpoint
        
        print("✅ Debugging test complete!")
        
    except ImportError:
        print("❌ debugpy not installed. Run: pip install debugpy")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    test_debugpy()