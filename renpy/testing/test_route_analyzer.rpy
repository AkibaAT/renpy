# Test script for Route Analyzer functionality
# This can be included in a Ren'Py game to test the route analyzer

init python:
    def test_route_analyzer():
        """Test the route analyzer functionality within a Ren'Py game."""
        print("=" * 60)
        print("Testing Route Analyzer in Ren'Py Environment")
        print("=" * 60)
        
        try:
            # Import the route analyzer
            from renpy.testing.route_analyzer import get_route_analyzer
            
            print("✓ Route analyzer imported successfully")
            
            # Get the analyzer instance
            analyzer = get_route_analyzer()
            print("✓ Route analyzer instance obtained")
            
            # Test script analysis
            print("\nTesting script analysis...")
            analysis_data = analyzer.analyze_script(force_refresh=True)
            
            if 'error' in analysis_data:
                print(f"❌ Analysis error: {analysis_data['error']}")
                return False
            
            # Check route graph
            route_graph = analysis_data.get('route_graph', {})
            nodes = route_graph.get('nodes', [])
            edges = route_graph.get('edges', [])
            
            print(f"✓ Found {len(nodes)} nodes in route graph")
            print(f"✓ Found {len(edges)} edges in route graph")
            
            # Show some sample nodes
            label_nodes = [n for n in nodes if n.get('type') == 'label']
            menu_nodes = [n for n in nodes if n.get('type') == 'menu']
            
            print(f"  - Label nodes: {len(label_nodes)}")
            print(f"  - Menu nodes: {len(menu_nodes)}")
            
            if label_nodes:
                print(f"  - Sample label: {label_nodes[0].get('name', 'unknown')}")
            
            if menu_nodes:
                menu = menu_nodes[0]
                print(f"  - Sample menu: {menu.get('name', 'unknown')} with {len(menu.get('choices', []))} choices")
            
            # Test word counts
            word_counts = analysis_data.get('word_counts', {})
            print(f"✓ Word count analysis for {len(word_counts)} labels")
            
            total_words = sum(word_counts.values()) if word_counts else 0
            print(f"  - Total words: {total_words}")
            
            if word_counts:
                # Show top 3 labels by word count
                sorted_labels = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:3]
                print("  - Top labels by word count:")
                for label, count in sorted_labels:
                    print(f"    * {label}: {count} words")
            
            # Test choice requirements
            requirements = analysis_data.get('choice_requirements', {})
            print(f"✓ Choice requirements analysis for {len(requirements)} conditional choices")
            
            if requirements:
                # Show a sample requirement
                sample_req = list(requirements.values())[0]
                print(f"  - Sample requirement: {sample_req.get('choice_text', 'unknown')}")
                print(f"    Condition: {sample_req.get('condition', 'none')}")
            
            # Test progress tracking
            print("\nTesting progress tracking...")
            progress = analyzer.get_current_progress()
            
            print(f"✓ Current label: {progress.get('current_label', 'unknown')}")
            print(f"✓ Progress: {progress.get('progress_percentage', 0)}%")
            print(f"✓ Remaining words: {progress.get('estimated_remaining_words', 0)}")
            print(f"✓ Estimated reading time: {progress.get('estimated_reading_time_minutes', 0)} minutes")
            
            # Test route summary
            print("\nTesting route summary...")
            summary = analyzer.get_route_summary()
            
            print(f"✓ Total labels: {summary.get('total_labels', 0)}")
            print(f"✓ Total menus: {summary.get('total_menus', 0)}")
            print(f"✓ Total choices: {summary.get('total_choices', 0)}")
            print(f"✓ Total jumps: {summary.get('total_jumps', 0)}")
            print(f"✓ Total calls: {summary.get('total_calls', 0)}")
            print(f"✓ Estimated reading time: {summary.get('estimated_reading_time_minutes', 0)} minutes")
            
            print("\n✅ All route analyzer tests passed!")
            return True
            
        except Exception as e:
            print(f"❌ Test error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def test_http_endpoints():
        """Test the HTTP API endpoints."""
        print("\n" + "=" * 60)
        print("Testing HTTP API Endpoints")
        print("=" * 60)
        
        try:
            # Import testing interface
            import renpy.testing as testing
            
            # Get testing interface
            interface = testing.get_testing_interface()
            
            # Start HTTP server
            print("Starting HTTP server...")
            if interface.start_http_server('localhost', 8080):
                print("✓ HTTP server started on http://localhost:8080")
                
                # List available endpoints
                print("\nRoute analysis endpoints available:")
                endpoints = [
                    "/api/route/analyze",
                    "/api/route/graph", 
                    "/api/route/progress",
                    "/api/route/wordcount",
                    "/api/route/summary",
                    "/api/route/requirements"
                ]
                
                for endpoint in endpoints:
                    print(f"  ✓ {endpoint}")
                
                print("\nHTTP server is running. You can test endpoints with:")
                print("  curl http://localhost:8080/api/route/analyze")
                print("  curl http://localhost:8080/api/route/progress")
                print("  curl http://localhost:8080/api/route/summary")
                
                return True
            else:
                print("❌ Failed to start HTTP server")
                return False
                
        except Exception as e:
            print(f"❌ HTTP endpoint test error: {e}")
            import traceback
            traceback.print_exc()
            return False

# Define a label to run the tests
label test_route_analyzer:
    "Starting Route Analyzer Tests..."
    
    python:
        # Run the tests
        analyzer_success = test_route_analyzer()
        http_success = test_http_endpoints()
        
        if analyzer_success and http_success:
            test_result = "All tests passed! ✅"
        else:
            test_result = "Some tests failed! ❌"
    
    "[test_result]"
    
    "Check the console output for detailed test results."
    
    menu:
        "What would you like to do?"
        
        "Test route analysis again":
            jump test_route_analyzer
            
        "Continue with game":
            return
            
        "Exit":
            $ renpy.quit()

# Add a simple test script structure
label start:
    "Welcome to the Route Analyzer Test Game!"
    
    menu:
        "What would you like to do?"
        
        "Run route analyzer tests":
            jump test_route_analyzer
            
        "Test basic dialogue":
            jump test_dialogue
            
        "Test choices":
            jump test_choices

label test_dialogue:
    "This is a test dialogue scene."
    "It has multiple lines of dialogue to test word counting."
    "The route analyzer should be able to count these words."
    
    menu:
        "Continue?"
        
        "Yes":
            jump test_choices
            
        "Go back to start":
            jump start

label test_choices:
    "This scene tests choice analysis."
    
    $ test_var = True
    
    menu:
        "Choose an option:"
        
        "Simple choice":
            "You chose the simple option."
            
        "Conditional choice" if test_var:
            "You chose the conditional option."
            
        "Another conditional" if test_var and True:
            "You chose the complex conditional option."
    
    "Choice testing complete."
    jump start
