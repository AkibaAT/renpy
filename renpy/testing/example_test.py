#!/usr/bin/env python3
"""
Example Test Script for Ren'Py Testing Interface

This script demonstrates how to use the HTTP API to automate testing
of a Ren'Py visual novel.
"""

import requests
import json
import time
import sys


class RenpyTestClient:
    """Client for interacting with Ren'Py testing HTTP API."""
    
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url.rstrip('/')
        self.api_url = f"{self.base_url}/api"
    
    def get_status(self):
        """Get server status."""
        response = requests.get(f"{self.api_url}/status")
        response.raise_for_status()
        return response.json()
    
    def get_state(self):
        """Get full game state."""
        response = requests.get(f"{self.api_url}/state")
        response.raise_for_status()
        return response.json()
    
    def get_variables(self):
        """Get game variables."""
        response = requests.get(f"{self.api_url}/variables")
        response.raise_for_status()
        return response.json()['variables']
    
    def get_choices(self):
        """Get available choices."""
        response = requests.get(f"{self.api_url}/choices")
        response.raise_for_status()
        return response.json()['choices']
    
    def advance(self):
        """Advance dialogue."""
        response = requests.post(f"{self.api_url}/advance")
        response.raise_for_status()
        return response.json()['success']
    
    def rollback(self, steps=1):
        """Roll back steps."""
        response = requests.post(f"{self.api_url}/rollback", 
                               json={"steps": steps})
        response.raise_for_status()
        return response.json()['success']
    
    def select_choice(self, choice):
        """Select a choice by index or text."""
        response = requests.post(f"{self.api_url}/choice", 
                               json={"choice": choice})
        response.raise_for_status()
        return response.json()['success']
    
    def set_variable(self, name, value):
        """Set a game variable."""
        response = requests.post(f"{self.api_url}/variable", 
                               json={"name": name, "value": value})
        response.raise_for_status()
        return response.json()['success']
    
    def save_state(self, slot):
        """Save game state."""
        response = requests.post(f"{self.api_url}/save", 
                               json={"slot": slot})
        response.raise_for_status()
        return response.json()['slot']
    
    def load_state(self, slot):
        """Load game state."""
        response = requests.post(f"{self.api_url}/load", 
                               json={"slot": slot})
        response.raise_for_status()
        return response.json()['success']
    
    def jump_to_label(self, label):
        """Jump to a specific label."""
        response = requests.post(f"{self.api_url}/jump", 
                               json={"label": label})
        response.raise_for_status()
        return response.json()['success']


def test_basic_functionality(client):
    """Test basic game functionality."""
    print("Testing basic functionality...")
    
    # Check server status
    status = client.get_status()
    print(f"Server running: {status['running']}")
    print(f"Current label: {status['current_label']}")
    
    # Get initial state
    state = client.get_state()
    initial_label = state['label']
    print(f"Starting at label: {initial_label}")
    
    # Test variable access
    variables = client.get_variables()
    print(f"Found {len(variables)} variables")
    
    # Test variable setting
    client.set_variable("test_var", "test_value")
    updated_vars = client.get_variables()
    assert updated_vars.get("test_var") == "test_value"
    print("Variable setting: PASS")
    
    return True


def test_dialogue_advancement(client):
    """Test dialogue advancement and rollback."""
    print("\nTesting dialogue advancement...")
    
    initial_state = client.get_state()
    initial_label = initial_state['label']
    
    # Advance dialogue several times
    advances = 0
    for i in range(10):
        if client.advance():
            advances += 1
            time.sleep(0.1)  # Small delay to allow processing
        else:
            break
    
    print(f"Advanced {advances} times")
    
    # Check if we moved
    current_state = client.get_state()
    current_label = current_state['label']
    
    if current_label != initial_label:
        print(f"Moved from {initial_label} to {current_label}")
    
    # Test rollback
    if advances > 0:
        rollback_steps = min(3, advances)
        if client.rollback(rollback_steps):
            print(f"Rollback {rollback_steps} steps: PASS")
        else:
            print("Rollback: FAIL")
    
    return True


def test_choice_selection(client):
    """Test menu choice selection."""
    print("\nTesting choice selection...")
    
    # Advance until we find choices
    max_attempts = 50
    for i in range(max_attempts):
        choices = client.get_choices()
        if choices:
            print(f"Found {len(choices)} choices:")
            for j, choice in enumerate(choices):
                print(f"  {j}: {choice}")
            
            # Select the first choice
            if client.select_choice(0):
                print("Choice selection: PASS")
                return True
            else:
                print("Choice selection: FAIL")
                return False
        
        # Advance to find choices
        if not client.advance():
            break
        time.sleep(0.1)
    
    print("No choices found in first 50 advances")
    return True


def test_save_load(client):
    """Test save and load functionality."""
    print("\nTesting save/load functionality...")
    
    # Save current state
    test_slot = "automated_test_save"
    saved_slot = client.save_state(test_slot)
    print(f"Saved to slot: {saved_slot}")
    
    # Get current state for comparison
    saved_state = client.get_state()
    saved_variables = client.get_variables()
    
    # Make some changes
    client.set_variable("test_save_var", "modified")
    client.advance()
    client.advance()
    
    # Load the saved state
    if client.load_state(test_slot):
        print("Load state: PASS")
        
        # Verify state was restored
        restored_state = client.get_state()
        restored_variables = client.get_variables()
        
        if (restored_state['label'] == saved_state['label'] and
            restored_variables.get("test_save_var") != "modified"):
            print("State restoration: PASS")
        else:
            print("State restoration: FAIL")
    else:
        print("Load state: FAIL")
    
    return True


def run_comprehensive_test():
    """Run a comprehensive test suite."""
    print("Starting Ren'Py Automated Test Suite")
    print("=" * 50)
    
    try:
        client = RenpyTestClient()
        
        # Test connection
        try:
            status = client.get_status()
            print(f"Connected to Ren'Py testing server")
        except requests.exceptions.ConnectionError:
            print("ERROR: Cannot connect to Ren'Py testing server")
            print("Make sure the game is running with: renpy.sh game http_server")
            return False
        
        # Run test suites
        tests = [
            test_basic_functionality,
            test_dialogue_advancement,
            test_choice_selection,
            test_save_load,
        ]
        
        passed = 0
        for test_func in tests:
            try:
                if test_func(client):
                    passed += 1
                    print(f"{test_func.__name__}: PASS")
                else:
                    print(f"{test_func.__name__}: FAIL")
            except Exception as e:
                print(f"{test_func.__name__}: ERROR - {e}")
        
        print("\n" + "=" * 50)
        print(f"Test Results: {passed}/{len(tests)} tests passed")
        
        return passed == len(tests)
        
    except Exception as e:
        print(f"Test suite failed with error: {e}")
        return False


if __name__ == "__main__":
    success = run_comprehensive_test()
    sys.exit(0 if success else 1)
