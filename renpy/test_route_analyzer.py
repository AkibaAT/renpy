#!/usr/bin/env python

"""
Test script for Route Analyzer functionality.

This script tests the route analyzer implementation by creating a simple
test script and analyzing it.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals

import sys
import os

# Add the renpy directory to the path so we can import renpy modules
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_route_analyzer():
    """Test the route analyzer functionality."""
    print("Testing Route Analyzer...")
    
    try:
        # Import the route analyzer
        from testing.route_analyzer import RouteAnalyzer
        
        print("✓ Route analyzer imported successfully")
        
        # Create an instance
        analyzer = RouteAnalyzer()
        print("✓ Route analyzer instance created")
        
        # Test basic functionality without a loaded script
        print("\nTesting without loaded script:")
        
        # This should handle the case gracefully
        result = analyzer.analyze_script()
        print(f"✓ Analysis result: {type(result)}")
        
        if 'error' in result:
            print(f"  Expected error: {result['error']}")
        else:
            print(f"  Nodes: {len(result.get('route_graph', {}).get('nodes', []))}")
            print(f"  Edges: {len(result.get('route_graph', {}).get('edges', []))}")
        
        # Test progress tracking
        progress = analyzer.get_current_progress()
        print(f"✓ Progress tracking: {type(progress)}")
        
        # Test route summary
        summary = analyzer.get_route_summary()
        print(f"✓ Route summary: {type(summary)}")
        
        # Test cache invalidation
        analyzer.invalidate_cache()
        print("✓ Cache invalidation works")
        
        print("\n✅ All basic tests passed!")
        return True
        
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Test error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_http_endpoints():
    """Test that HTTP endpoints can be imported."""
    print("\nTesting HTTP endpoint integration...")
    
    try:
        # Test that we can import the HTTP server with our new endpoints
        from testing.http_server import TestingAPIHandler
        
        print("✓ HTTP server with route endpoints imported successfully")
        
        # Check that the handler has our new methods
        handler_methods = [method for method in dir(TestingAPIHandler) 
                          if method.startswith('_handle_route_')]
        
        expected_methods = [
            '_handle_route_analyze',
            '_handle_route_graph', 
            '_handle_route_progress',
            '_handle_route_wordcount',
            '_handle_route_summary',
            '_handle_route_requirements'
        ]
        
        for method in expected_methods:
            if hasattr(TestingAPIHandler, method):
                print(f"✓ Found endpoint handler: {method}")
            else:
                print(f"❌ Missing endpoint handler: {method}")
                return False
        
        print("✅ All HTTP endpoint handlers found!")
        return True
        
    except ImportError as e:
        print(f"❌ HTTP endpoint import error: {e}")
        return False
    except Exception as e:
        print(f"❌ HTTP endpoint test error: {e}")
        return False

def test_testing_interface_integration():
    """Test integration with the testing interface."""
    print("\nTesting testing interface integration...")
    
    try:
        # Test that we can import the testing module with route analyzer
        import testing
        
        print("✓ Testing module imported successfully")
        
        # Check for route analysis convenience functions
        route_functions = [
            'analyze_routes',
            'get_route_graph',
            'get_route_progress', 
            'get_word_counts',
            'get_choice_requirements',
            'get_route_summary',
            'invalidate_route_cache'
        ]
        
        for func_name in route_functions:
            if hasattr(testing, func_name):
                print(f"✓ Found convenience function: {func_name}")
            else:
                print(f"❌ Missing convenience function: {func_name}")
                return False
        
        print("✅ All convenience functions found!")
        return True
        
    except ImportError as e:
        print(f"❌ Testing interface import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Testing interface test error: {e}")
        return False

def main():
    """Run all tests."""
    print("=" * 60)
    print("Route Analyzer Test Suite")
    print("=" * 60)
    
    tests = [
        test_route_analyzer,
        test_http_endpoints,
        test_testing_interface_integration
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} failed with exception: {e}")
    
    print("\n" + "=" * 60)
    print(f"Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
