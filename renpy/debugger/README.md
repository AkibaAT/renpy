# Ren'Py DAP Debugger

This document describes the Debug Adapter Protocol (DAP) debugger for Ren'Py, which enables full debugging support in VSCode and other DAP-compatible IDEs.

## Table of Contents

1. [Setup](#setup)
2. [Basic Debugging](#basic-debugging)
3. [Breakpoints](#breakpoints)
4. [Conditional Breakpoints](#conditional-breakpoints)
5. [Function Breakpoints](#function-breakpoints)
6. [Logpoints](#logpoints)
7. [Exception Breakpoints](#exception-breakpoints)
8. [Variable Inspection](#variable-inspection)
9. [Watch Expressions](#watch-expressions)
10. [Hover Evaluation](#hover-evaluation)
11. [Debug Console](#debug-console)
12. [Inline Values](#inline-values)
13. [Step Back](#step-back)
14. [Run to Line](#run-to-line)
15. [Jump to Label](#jump-to-label)
16. [Scene Inspector](#scene-inspector)

---

## Setup

### Requirements

- Ren'Py 8.x or later with the debugger module
- VSCode with the Ren'Py Language extension

### Launch Configuration

Create a `.vscode/launch.json` file in your project:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "type": "renpy",
            "request": "launch",
            "name": "Ren'Py: Launch",
            "command": "run",
            "debugServer": true,
            "debugPort": 5678
        },
        {
            "type": "renpy",
            "request": "attach",
            "name": "Ren'Py: Attach",
            "host": "localhost",
            "port": 5678
        }
    ]
}
```

### Starting a Debug Session

1. Open your Ren'Py project in VSCode
2. Set the Ren'Py executable path in settings (`renpy.renpyExecutableLocation`)
3. Press F5 or click "Run and Debug" → "Ren'Py: Launch"

---

## Basic Debugging

### Features

- **Continue (F5)**: Resume execution until the next breakpoint
- **Pause (F6)**: Pause execution at the current line
- **Step Over (F10)**: Execute the current line and stop at the next line
- **Step Into (F11)**: Step into function/label calls
- **Step Out (Shift+F11)**: Step out of the current function/label
- **Stop (Shift+F5)**: Terminate the debug session

### Testing Instructions

1. Open a `.rpy` file in your project
2. Set a breakpoint on a dialogue line by clicking the gutter (left margin)
3. Start debugging with F5
4. Play the game until you reach the breakpoint
5. The game will pause and VSCode will highlight the current line
6. Use F10 to step through lines one at a time
7. Use F5 to continue to the next breakpoint

---

## Breakpoints

### Features

- Click in the editor gutter to set/remove breakpoints
- Breakpoints work on Ren'Py script lines (dialogue, menu, Python, etc.)
- Red dot indicates an active breakpoint
- Gray dot indicates a disabled breakpoint

### Testing Instructions

1. Open `script.rpy` in your project
2. Click in the gutter next to a `say` statement to set a breakpoint
3. Start debugging (F5)
4. Play the game - execution stops at the breakpoint
5. Verify the line is highlighted in the editor
6. Right-click the breakpoint to disable it
7. Continue (F5) - the disabled breakpoint is skipped

---

## Conditional Breakpoints

### Features

- Break only when a condition is true
- Support for hit count conditions (break after N hits)
- Uses Python expressions for conditions

### Setting a Conditional Breakpoint

1. Right-click on a breakpoint (or in the gutter)
2. Select "Edit Breakpoint..."
3. Choose "Expression" and enter a Python condition
4. Or choose "Hit Count" and enter a number

### Condition Examples

- `player_health < 50` - Break when health is low
- `len(inventory) > 5` - Break when inventory has more than 5 items
- `current_route == "bad"` - Break on specific route

### Testing Instructions

1. Add a breakpoint on a line inside a loop or frequently-executed code
2. Right-click the breakpoint → "Edit Breakpoint..."
3. Enter condition: `loop_counter > 3`
4. Start debugging
5. Verify the breakpoint only triggers when the condition is true
6. Test hit count: edit the breakpoint, set hit count to `5`
7. Verify it breaks on the 5th execution

---

## Function Breakpoints

### Features

- Break when entering a specific label (function)
- No need to know the file or line number
- Works with any label in your game
- Supports hit count conditions
- Useful for debugging specific scenes or routes

### Setting a Function Breakpoint

1. Open the "Breakpoints" panel in the Run and Debug sidebar
2. Click the "+" button next to "Function Breakpoints"
3. Enter a label name (e.g., `start`, `chapter_2`, `bad_ending`)

### Examples

- `start` - Break at the beginning of the game
- `say` - Break on custom say function
- `good_ending` - Break when entering the good ending
- `battle_scene` - Break when a battle starts

### Testing Instructions

1. Open the "Breakpoints" panel in the Debug sidebar
2. Click "+" next to "Function Breakpoints"
3. Enter `start` as the function name
4. Start debugging (F5)
5. Verify the debugger breaks at the `label start:` line
6. Add another function breakpoint for a label further in the game
7. Continue (F5) and verify it breaks when entering that label
8. Remove the function breakpoint and verify it no longer breaks
9. Test with an invalid label name - verify it shows as unverified

---

## Logpoints

### Features

- Log messages to the terminal without breaking execution
- Supports variable interpolation with `{expression}` syntax
- Useful for tracing without stopping the game

### Setting a Logpoint

1. Right-click in the gutter → "Add Logpoint..."
2. Enter a message with optional interpolations: `Player entered {current_label} with {player_health} HP`

### Testing Instructions

1. Right-click in the gutter on a line inside a loop
2. Select "Add Logpoint..."
3. Enter: `Loop iteration: {loop_counter}, value: {some_variable}`
4. Start debugging
5. Check the terminal where the game is running
6. Verify the log messages appear without breaking execution

---

## Exception Breakpoints

### Features

- **Raised Exceptions**: Break whenever any exception is raised
- **Uncaught Exceptions**: Break only on exceptions not caught by the game
- View exception details in the editor

### Enabling Exception Breakpoints

1. Open the "Breakpoints" panel in the Run and Debug sidebar
2. Check "Raised Exceptions" and/or "Uncaught Exceptions"

### Testing Instructions

1. Add code that raises an exception:
   ```renpy
   $ x = 1 / 0  # ZeroDivisionError
   ```
2. Enable "Raised Exceptions" in the Breakpoints panel
3. Start debugging and trigger the exception
4. Verify the debugger breaks at the exception line
5. Check the "Variables" panel for exception details
6. Disable "Raised Exceptions", enable only "Uncaught Exceptions"
7. Wrap the code in try/except - verify it doesn't break
8. Remove the try/except - verify it breaks again

---

## Variable Inspection

### Features

- **Locals**: Variables in the current scope
- **Globals**: Global game variables (store.*)
- **Expandable objects**: Click arrows to expand dicts, lists, objects
- **Modify variables**: Double-click a value to change it

### Scopes

| Scope | Description |
|-------|-------------|
| Locals | Variables defined in the current Python block or label |
| Store | Game variables (equivalent to `store.*`) |
| Persistent | Persistent data that survives game restarts |
| Renpy | Read-only Ren'Py engine state |

### Testing Instructions

1. Set a breakpoint after some variable assignments:
   ```renpy
   $ player_name = "Alice"
   $ inventory = ["sword", "shield"]
   $ player_stats = {"hp": 100, "mp": 50}
   ```
2. Start debugging and hit the breakpoint
3. Expand the "Variables" panel in the sidebar
4. Verify you see Locals and Store scopes
5. Expand the `inventory` list - verify you see indexed items
6. Expand `player_stats` dict - verify you see key-value pairs
7. Double-click `player_name` value, change to "Bob"
8. Continue execution - verify the change took effect

---

## Watch Expressions

### Features

- Add custom expressions to monitor
- Expressions are re-evaluated at each stop
- Supports complex expressions and function calls
- Expandable results for complex objects
- **Edit values directly** by double-clicking (for simple variables)

### Adding Watch Expressions

1. Open the "Watch" panel in the Run and Debug sidebar
2. Click the "+" button
3. Enter an expression (e.g., `len(inventory)`, `player.health`)

### Editing Watch Values

1. Add a simple variable to watch (e.g., `debug_health`)
2. Double-click the value in the Watch panel
3. Enter a new value and press Enter
4. The variable is updated immediately

Note: Editing works for simple variable names. Complex expressions like `len(inventory)` cannot be edited directly.

### Testing Instructions

1. Add these watch expressions:
   - `player_name`
   - `len(inventory)`
   - `player_stats.get("hp", 0)`
   - `"Health: " + str(player_health)`
2. Start debugging and hit a breakpoint
3. Verify all watch expressions show current values
4. Step through code that modifies variables
5. Verify watch expressions update automatically
6. Add an invalid expression (e.g., `undefined_var`)
7. Verify it shows an error message
8. **Test editing**: Add `debug_health` to watch
9. Double-click its value and change it to `50`
10. Verify the value updates and the change persists

---

## Hover Evaluation

### Features

- Hover over variables in the editor to see their values
- Works while paused at a breakpoint
- Shows type information and expandable preview

### Testing Instructions

1. Start debugging and pause at a breakpoint
2. Hover over a variable name in the editor
3. Verify a tooltip appears showing the variable's value
4. Hover over a complex object (list, dict)
5. Verify the tooltip shows a preview
6. Hover over an undefined variable
7. Verify no tooltip appears (or shows empty)

---

## Debug Console

### Features

- Evaluate Python expressions interactively
- Execute statements (assignments, function calls)
- Autocomplete for variables and Ren'Py API
- Results are displayed inline

### Using the Debug Console

1. Open the "Debug Console" panel (Ctrl+Shift+Y)
2. Type an expression and press Enter
3. The result appears below your input

### Expression Examples

```python
# View variables
player_name
len(inventory)

# Modify variables
player_health = 100
inventory.append("potion")

# Call functions
renpy.notify("Debug message")

# Complex expressions
[item for item in inventory if "sword" in item]
```

### Testing Instructions

1. Start debugging and pause at a breakpoint
2. Open Debug Console (Ctrl+Shift+Y)
3. Type `player_name` and press Enter - verify value shown
4. Type `1 + 1` and press Enter - verify shows `2`
5. Type `inventory` - verify list is shown and expandable
6. Type `player_health = 999` - verify shows "OK"
7. Check Variables panel - verify `player_health` is now 999
8. Type `renpy.version()` - verify Ren'Py version shown
9. Test autocomplete: type `renpy.` and wait for suggestions
10. Test autocomplete: type `play` and verify variable suggestions

---

## Inline Values

### Features

- Shows variable values directly in the editor while debugging
- Appears next to variable assignments and references
- Updates as you step through code

### Supported Patterns

- Python lines (`$ variable = value`)
- Default/define statements (`default player_name = "Alice"`)
- String interpolations (`[variable]` and `{variable}`)

### Testing Instructions

1. Open a file with Python code and variable assignments
2. Start debugging and pause at a breakpoint
3. Look for gray text showing values next to variables
4. Step through code with F10
5. Verify inline values update as variables change
6. Check that string interpolations show their values

---

## Step Back

### Features

- Go back to the previous statement using Ren'Py's rollback system
- Undo the effects of the last statement
- Useful for re-examining code you just stepped past
- Works with dialogue, menu choices, and Python statements

### Using Step Back

1. While paused at a breakpoint, click the "Step Back" button in the debug toolbar
2. Or use the keyboard shortcut (if configured)
3. Execution moves back to the previous checkpoint

### How It Works

Step Back uses Ren'Py's built-in rollback system, which creates checkpoints at key moments during gameplay. When you step back:

1. The game state is restored to the previous checkpoint
2. The debugger pauses at that location
3. Variable values are restored to their previous state

### Limitations

- Only works when rollback is available (some scenes may disable it)
- May skip multiple statements if no checkpoint exists between them
- Persistent data is not rolled back

### Testing Instructions

1. Start debugging and pause at a breakpoint
2. Step forward a few times with F10 (Step Over)
3. Click the "Step Back" button in the debug toolbar
4. Verify execution moves back to a previous line
5. Check that variable values are restored
6. Try stepping back multiple times
7. Verify the debugger shows "Cannot rollback" if rollback is unavailable

---

## Run to Line

### Features

- Run execution until reaching a specific line
- Skips all interactions (dialogue, menus) in between
- Available from context menu during debugging

### Using Run to Line

1. While paused, right-click on a target line
2. Select "Renpy: Run to Line"
3. Execution continues until reaching that line

### Testing Instructions

1. Start debugging and pause at an early breakpoint
2. Right-click on a line further in the script
3. Select "Renpy: Run to Line"
4. Verify the game runs (skipping dialogue) until that line
5. Verify execution pauses at the target line
6. Test on a line in a different label - verify it jumps there first

---

## Jump to Label

### Features

- Instantly jump to any label in the game
- Useful for testing specific scenes
- Available from context menu or command palette

### Using Jump to Label

1. **On a label line**: Right-click → "Renpy: Jump to Label" jumps directly
2. **On any other line**: Shows a picker with all available labels

### Testing Instructions

1. Start debugging and pause anywhere
2. Navigate to a line with `label some_label:`
3. Right-click → "Renpy: Jump to Label"
4. Verify execution jumps to that label immediately
5. Right-click on a non-label line
6. Select "Renpy: Jump to Label"
7. Verify a picker appears with all labels
8. Select a label and verify execution jumps there

---

## Scene Inspector

### Features

- Real-time view of the current scene state
- Shows images currently displayed (by layer)
- Shows audio currently playing (by channel)
- Shows current label and line number

### Accessing the Scene Inspector

1. Start a debug session
2. The "Scene Inspector" panel appears in the Debug sidebar
3. Use the refresh button to manually update

### Display Information

| Category | Information |
|----------|-------------|
| Location | Current label and line number |
| Images | Tag, attributes, layer, position |
| Audio | Channel name and currently playing file |

### Testing Instructions

1. Start debugging a game with images and music
2. Play until you see a scene with characters and background music
3. Pause at a breakpoint
4. Find "Scene Inspector" in the Debug sidebar
5. Verify it shows the current label and line
6. Expand "Images" - verify showing images are listed
7. Check image attributes and layer information
8. Expand "Audio" - verify playing music/sound is shown
9. Step through code that changes the scene
10. Click refresh - verify the Scene Inspector updates
11. Continue to a scene with different images
12. Verify the Scene Inspector reflects the new state

---

## Troubleshooting

### Debugger doesn't connect

1. Check that the Ren'Py executable path is set correctly
2. Verify port 5678 is not in use by another application
3. Check the Ren'Py console for error messages

### Breakpoints not hitting

1. Ensure breakpoints are on executable lines (not comments or empty lines)
2. Check that the file is part of the running game
3. Try restarting the debug session

### Variables not showing

1. Make sure you're paused at a breakpoint
2. Check that variables are defined in the current scope
3. Expand the correct scope (Locals vs Store)

### Scene Inspector empty

1. Ensure you're at a point where a scene is displayed
2. Try clicking the refresh button
3. Check the Debug Console for errors
