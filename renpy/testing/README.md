# Ren'Py Automated Testing Interface

This module provides comprehensive automated testing capabilities for Ren'Py visual novels, allowing external programs to programmatically control and inspect a running game.

## Features

### State Inspection
- Read current memory/variable stack
- Access current scene and screen information  
- Query game state (current label, dialogue, choices available, etc.)
- Get rollback information and context details

### State Management
- Save game state to specific slots or memory
- Load game state from saved slots
- Export/import state data for external analysis
- Manage temporary testing saves

### Game Control
- Advance dialogue/story progression
- Roll back to previous states
- Navigate through the game programmatically
- Select from available menu choices by index or text
- Skip animations/transitions for faster testing
- Send keyboard and mouse events

### Integration Options
- **HTTP API**: RESTful API server for language-agnostic external control
- **Python API**: Direct programmatic access for Python test scripts
- **Command Line Interface**: For shell scripts and external test automation tools
- **Headless Mode**: Run without display for automated testing environments

## Quick Start

### Starting the HTTP API Server

```bash
# Start game with HTTP API server
./renpy.sh mygame http_server --host localhost --port 8080

# Or start in headless mode
./renpy.sh mygame http_server --headless --port 8080
```

### Using the HTTP API

```bash
# Get current game state
curl http://localhost:8080/api/state

# Advance dialogue
curl -X POST http://localhost:8080/api/advance

# Select a choice
curl -X POST http://localhost:8080/api/choice \
  -H "Content-Type: application/json" \
  -d '{"choice": 0}'

# Set a variable
curl -X POST http://localhost:8080/api/variable \
  -H "Content-Type: application/json" \
  -d '{"name": "player_name", "value": "Test Player"}'

# Save state
curl -X POST http://localhost:8080/api/save \
  -H "Content-Type: application/json" \
  -d '{"slot": "test_save_1"}'
```

### Using the Python API

```python
import renpy

# Start the testing interface
interface = renpy.testing_interface()

# Start HTTP server
renpy.testing_start_http_server('localhost', 8080)

# Inspect current state
state = renpy.testing_inspect_state()
print("Current label:", state['label'])
print("Variables:", state['variables'])

# Control the game
renpy.testing_advance_dialogue()
choices = renpy.testing_get_choices()
if choices:
    renpy.testing_select_choice(0)

# Save and load states
slot = renpy.testing_save_state("checkpoint_1")
# ... do some testing ...
renpy.testing_load_state(slot)
```

## HTTP API Endpoints

### GET Endpoints (State Inspection)

- `GET /api/status` - Get server status and basic info
- `GET /api/state` - Get comprehensive game state
- `GET /api/variables` - Get current game variables
- `GET /api/scene` - Get scene and screen information
- `GET /api/dialogue` - Get current dialogue information
- `GET /api/choices` - Get available menu choices
- `GET /api/saves` - List available save slots

### POST Endpoints (Game Control)

- `POST /api/advance` - Advance dialogue/story
- `POST /api/rollback` - Roll back steps (body: `{"steps": N}`)
- `POST /api/choice` - Select choice (body: `{"choice": N}` or `{"choice": "text"}`)
- `POST /api/jump` - Jump to label (body: `{"label": "label_name"}`)
- `POST /api/variable` - Set variable (body: `{"name": "var", "value": val}`)
- `POST /api/save` - Save state (body: `{"slot": "slot_name"}`)
- `POST /api/load` - Load state (body: `{"slot": "slot_name"}`)
- `POST /api/click` - Send mouse click (body: `{"x": N, "y": N, "button": 1}`)
- `POST /api/key` - Send key press (body: `{"key": pygame_key_constant}`)

## Command Line Usage

### Available Commands

```bash
# Run game in automated testing mode
./renpy.sh mygame autotest --headless --http-server --port 8080

# Start HTTP API server
./renpy.sh mygame http_server --host 0.0.0.0 --port 8080

# Inspect current state
./renpy.sh mygame inspect --all --format json

# Save current state
./renpy.sh mygame save_state test_checkpoint --export

# Load state
./renpy.sh mygame load_state test_checkpoint
```

### Headless Mode

For automated testing environments without displays:

```bash
# Enable headless mode
./renpy.sh mygame autotest --headless

# Or via Python API
renpy.testing_enable_headless()
```

## Example Test Scripts

### Python Test Script

```python
#!/usr/bin/env python3
import requests
import time

# Test script using HTTP API
BASE_URL = "http://localhost:8080/api"

def test_game_flow():
    # Check server status
    response = requests.get(f"{BASE_URL}/status")
    assert response.status_code == 200
    
    # Get initial state
    state = requests.get(f"{BASE_URL}/state").json()
    print(f"Starting at label: {state['label']}")
    
    # Advance through some dialogue
    for i in range(5):
        response = requests.post(f"{BASE_URL}/advance")
        assert response.json()['success']
        time.sleep(0.1)
    
    # Check for choices
    choices = requests.get(f"{BASE_URL}/choices").json()['choices']
    if choices:
        # Select first choice
        response = requests.post(f"{BASE_URL}/choice", 
                               json={"choice": 0})
        assert response.json()['success']
    
    # Save checkpoint
    response = requests.post(f"{BASE_URL}/save", 
                           json={"slot": "test_checkpoint"})
    assert response.json()['success']
    
    print("Test completed successfully!")

if __name__ == "__main__":
    test_game_flow()
```

### Shell Script Test

```bash
#!/bin/bash
# Simple shell script test using curl

API_BASE="http://localhost:8080/api"

echo "Starting automated test..."

# Get initial status
curl -s "$API_BASE/status" | jq '.current_label'

# Advance dialogue 10 times
for i in {1..10}; do
    curl -s -X POST "$API_BASE/advance"
    sleep 0.1
done

# Check for choices and select first one
CHOICES=$(curl -s "$API_BASE/choices" | jq '.choices | length')
if [ "$CHOICES" -gt 0 ]; then
    curl -s -X POST "$API_BASE/choice" \
         -H "Content-Type: application/json" \
         -d '{"choice": 0}'
fi

echo "Test completed!"
```

## Integration with Test Frameworks

The HTTP API makes it easy to integrate with any testing framework:

- **pytest** (Python)
- **Jest** (JavaScript/Node.js)  
- **RSpec** (Ruby)
- **JUnit** (Java)
- **Postman** (API testing)
- **Newman** (Postman CLI)

## Error Handling

All API endpoints return JSON responses with error information:

```json
{
  "error": "Error message",
  "code": 400
}
```

Common HTTP status codes:
- `200` - Success
- `400` - Bad Request (missing parameters)
- `404` - Endpoint not found
- `500` - Internal server error

## Security Considerations

- The HTTP server is intended for testing environments only
- By default, it binds to localhost only
- No authentication is implemented
- Do not expose the testing API to untrusted networks
- Use firewall rules to restrict access in production testing environments
