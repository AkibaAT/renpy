# Route Analyzer for Ren'Py

The Route Analyzer provides comprehensive analysis of Ren'Py visual novel scripts, enabling route visualization, progress tracking, and content analysis.

## Features

### 🗺️ Route Visualization
- **Route Graph**: Generate a graph showing all possible story paths
- **Choice Trees**: Map out branching dialogue and menu choices
- **Navigation Paths**: Track jumps, calls, and returns between labels

### 📊 Content Analysis
- **Word Count**: Calculate word counts for each scene/label
- **Reading Time**: Estimate reading time based on content length
- **Choice Requirements**: Analyze conditions needed to unlock choices

### 📍 Progress Tracking
- **Current Position**: Track player's current location in the story
- **Progress Percentage**: Calculate completion percentage
- **Remaining Content**: Estimate remaining reading time

## HTTP API Endpoints

Start the HTTP server with:
```bash
./renpy.sh your_game http_server --host localhost --port 8080
```

### Route Analysis Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/route/analyze` | GET | Complete route analysis (all data) |
| `/api/route/graph` | GET | Route graph with nodes and edges |
| `/api/route/progress` | GET | Current progress tracking |
| `/api/route/wordcount` | GET | Word count analysis |
| `/api/route/summary` | GET | Summary statistics |
| `/api/route/requirements` | GET | Choice requirements analysis |

### Example Usage

```bash
# Get complete route analysis
curl http://localhost:8080/api/route/analyze

# Get current progress
curl http://localhost:8080/api/route/progress

# Get route summary
curl http://localhost:8080/api/route/summary
```

### Response Format

#### Route Graph (`/api/route/graph`)
```json
{
  "route_graph": {
    "nodes": [
      {
        "id": "start",
        "type": "label",
        "name": "start",
        "filename": "script.rpy",
        "line": 10
      },
      {
        "id": "start_menu_1", 
        "type": "menu",
        "name": "Choice at start",
        "choices": [
          {
            "index": 0,
            "text": "Go left",
            "condition": null,
            "target": "left_path"
          }
        ]
      }
    ],
    "edges": [
      {
        "from": "start",
        "to": "start_menu_1", 
        "type": "sequence"
      },
      {
        "from": "start_menu_1",
        "to": "left_path",
        "type": "choice",
        "choice_index": 0,
        "choice_text": "Go left"
      }
    ]
  }
}
```

#### Progress Tracking (`/api/route/progress`)
```json
{
  "current_label": "chapter_2",
  "progress_percentage": 45.2,
  "estimated_remaining_words": 1250,
  "estimated_reading_time_minutes": 6.3,
  "total_words": 2500
}
```

#### Word Count Analysis (`/api/route/wordcount`)
```json
{
  "word_counts": {
    "start": 150,
    "chapter_1": 300,
    "chapter_2": 250
  },
  "total_words": 700,
  "estimated_reading_time_minutes": 3.5,
  "labels_with_content": 3
}
```

## Python API

### Direct Usage
```python
from renpy.testing.route_analyzer import get_route_analyzer

# Get analyzer instance
analyzer = get_route_analyzer()

# Analyze script
analysis = analyzer.analyze_script()

# Get current progress
progress = analyzer.get_current_progress()

# Get route summary
summary = analyzer.get_route_summary()
```

### Convenience Functions
```python
import renpy.testing as testing

# Analyze routes
analysis = testing.analyze_routes()

# Get route graph
graph = testing.get_route_graph()

# Get current progress
progress = testing.get_route_progress()

# Get word counts
words = testing.get_word_counts()

# Get choice requirements
requirements = testing.get_choice_requirements()

# Get summary
summary = testing.get_route_summary()

# Invalidate cache
testing.invalidate_route_cache()
```

## Testing

### In-Game Testing
Include the test script in your game:
```renpy
# Add to your script.rpy
init python:
    exec(open("renpy/testing/test_route_analyzer.rpy").read())

label start:
    jump test_route_analyzer
```

### HTTP Testing
1. Start your game with HTTP server:
   ```bash
   ./renpy.sh your_game http_server
   ```

2. Test endpoints:
   ```bash
   curl http://localhost:8080/api/route/analyze
   curl http://localhost:8080/api/route/progress
   ```

## Implementation Details

### Node Types
- **label**: Story labels/scenes
- **menu**: Choice menus

### Edge Types  
- **sequence**: Normal flow between statements
- **choice**: Player choice selection
- **jump**: Jump to another label
- **call**: Call another label (with return)

### Choice Conditions
The analyzer parses choice conditions to extract:
- Variable names referenced
- Comparison operators (==, !=, >, <, etc.)
- Required values
- Boolean logic (and, or, not)

### Word Counting
- Counts words in Say statements (dialogue)
- Counts words in menu choice text
- Removes Ren'Py markup ({tags}, [tags])
- Estimates reading time at 200 words/minute

### Progress Calculation
- Uses current label position
- Calculates reachable content from current position
- Estimates completion percentage
- Provides remaining reading time

## Performance Notes

- Analysis results are cached until invalidated
- Large scripts may take a few seconds to analyze initially
- Subsequent requests use cached data for fast response
- Use `force_refresh=true` parameter to force re-analysis

## Limitations

- Complex Python expressions in conditions may not parse perfectly
- Dynamic label generation not supported
- Assumes linear reading progression for time estimates
- Cache invalidation requires manual trigger or restart
