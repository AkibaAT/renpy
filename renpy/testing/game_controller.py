# Copyright 2004-2024 Tom Rothamel <pytom@bishoujo.us>
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""
Game Controller

This module provides functionality to programmatically control game progression,
including dialogue advancement, rollback, menu selection, and navigation.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
import pygame
import time


class GameController(object):
    """
    Provides methods to programmatically control game progression.
    """
    
    def __init__(self, testing_interface=None):
        """Initialize the game controller."""
        self._auto_advance_enabled = False
        self._auto_advance_delay = 0.1
        self._skip_transitions = False
        self.testing_interface = testing_interface
    
    def advance_dialogue(self):
        """
        Advance to the next dialogue/statement.
        
        Returns:
            bool: True if advancement was successful
        """
        try:
            # Post a click event to advance dialogue
            event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, 
                                     {'button': 1, 'pos': (400, 300)})
            pygame.event.post(event)
            
            event = pygame.event.Event(pygame.MOUSEBUTTONUP, 
                                     {'button': 1, 'pos': (400, 300)})
            pygame.event.post(event)
            
            return True
            
        except Exception:
            return False
    
    def rollback(self, steps=1):
        """
        Roll back the specified number of steps.
        
        Args:
            steps (int): Number of steps to roll back
            
        Returns:
            bool: True if rollback was successful
        """
        try:
            if not hasattr(renpy.game, 'log') or not renpy.game.log:
                return False
            
            # Use Ren'Py's rollback functionality
            renpy.game.log.rollback(steps, force=False)
            return True
            
        except Exception:
            return False
    
    def select_choice(self, choice):
        """
        Select a menu choice.
        
        Args:
            choice (int or str): Choice index (0-based) or choice text
            
        Returns:
            bool: True if selection was successful
        """
        # Get current choices from the testing interface
        if self.testing_interface:
            choices = self.testing_interface.get_choices()
        else:
            # Fallback if no testing interface available
            from . import state_inspector
            inspector = state_inspector.StateInspector()
            choices = inspector.get_choices()
        print(f"[DEBUG] Found {len(choices)} choices available")

        if isinstance(choice, int):
            # Select by index
            if 0 <= choice < len(choices):
                choice_data = choices[choice]
                print(f"[DEBUG] Selected choice {choice}: {choice_data.get('label', 'unknown')}")
                return self._invoke_choice_action(choice_data)
            else:
                print(f"[DEBUG] Choice index {choice} out of range (0-{len(choices)-1})")
                return False

        elif isinstance(choice, str):
            # Select by text - find matching choice
            for choice_data in choices:
                if choice_data.get('label') == choice:
                    return self._invoke_choice_action(choice_data)
            print(f"[DEBUG] Choice with label '{choice}' not found")
            return False

        return False
    
    def _invoke_choice_action(self, choice_data):
        """
        Invoke the action for a specific choice.

        Args:
            choice_data (dict): Choice information including action

        Returns:
            bool: True if action was successfully invoked
        """
        # Check if choice is enabled
        if not choice_data.get('enabled', True):
            print(f"[DEBUG] Choice '{choice_data.get('label')}' is disabled")
            return False

        action_str = choice_data.get('action', '')
        label = choice_data.get('label', 'unknown')

        print(f"[DEBUG] Attempting to invoke action for '{label}': {action_str}")

        # Method 1: Try to invoke the action directly by finding the actual action object
        if self._invoke_action_object(choice_data):
            print(f"[DEBUG] Successfully invoked action object for '{label}'")
            return True

        # Method 2: Try using mouse click on the button location as fallback
        print(f"[DEBUG] Falling back to mouse click for '{label}'")
        return self._click_choice_button(choice_data)

    def _invoke_action_object(self, choice_data):
        """
        Try to invoke the action object directly by finding it in the UI system.

        Args:
            choice_data (dict): Choice information including action

        Returns:
            bool: True if action was successfully invoked
        """
        action_str = choice_data.get('action', '')
        label = choice_data.get('label', 'unknown')
        screen_name = choice_data.get('screen', '')

        print(f"[DEBUG] Looking for action object for '{label}' in screen '{screen_name}'")

        # Method 1: Try to find the action object in the current screen's displayables
        action_obj = self._find_action_in_screen(screen_name, label)

        if action_obj:
            print(f"[DEBUG] Found action object in screen: {action_obj}")

            # Check if the action is sensitive (enabled)
            if hasattr(action_obj, 'get_sensitive'):
                if not action_obj.get_sensitive():
                    print(f"[DEBUG] Action is not sensitive (disabled)")
                    return False

            # Invoke the action using renpy.display.behavior.run
            import renpy.display.behavior
            print(f"[DEBUG] Invoking action using renpy.display.behavior.run")
            result = renpy.display.behavior.run(action_obj)
            print(f"[DEBUG] Action result: {result}")
            return True

        # Method 2: Try to create the action object based on the class name
        return self._create_and_invoke_action(action_str, label)

    def _find_action_in_screen(self, screen_name, button_label):
        """
        Find the action object for a button in the specified screen.

        Args:
            screen_name (str): Name of the screen to search
            button_label (str): Label of the button to find

        Returns:
            Action object or None if not found
        """
        try:
            import renpy

            # Get the current scene lists
            scene_lists = renpy.exports.scene_lists()
            if not scene_lists or not hasattr(scene_lists, 'layers'):
                return None

            # Search through all layers for the screen
            for layer_name, layer_list in scene_lists.layers.items():
                for sle in layer_list:
                    if hasattr(sle, 'displayable'):
                        displayable = sle.displayable

                        # Check if this is the screen we're looking for
                        if hasattr(displayable, 'screen_name'):
                            current_screen_name = displayable.screen_name
                            if isinstance(current_screen_name, tuple):
                                current_screen_name = current_screen_name[0]

                            if current_screen_name == screen_name:
                                # Search for the button with matching label
                                action = self._find_button_action_recursive(displayable, button_label)
                                if action:
                                    return action

            return None

        except Exception as e:
            print(f"[DEBUG] Error finding action in screen: {e}")
            return None

    def _find_button_action_recursive(self, widget, target_label):
        """
        Recursively search for a button with the target label and return its action.

        Args:
            widget: The widget to search
            target_label (str): The label to match

        Returns:
            Action object or None if not found
        """
        try:
            # Check if this widget has text that matches our target
            text = self._extract_widget_text(widget)
            if text and text.strip() == target_label.strip():
                # Check for action attributes
                for attr in ['clicked', 'action', 'activate']:
                    if hasattr(widget, attr):
                        action = getattr(widget, attr)
                        if action:
                            return action

            # Recursively search child widgets
            if hasattr(widget, 'child') and widget.child:
                result = self._find_button_action_recursive(widget.child, target_label)
                if result:
                    return result

            if hasattr(widget, 'children'):
                for child in widget.children:
                    result = self._find_button_action_recursive(child, target_label)
                    if result:
                        return result

            return None

        except Exception:
            return None

    def _extract_widget_text(self, widget):
        """
        Extract text from a widget using various methods.

        Args:
            widget: The widget to extract text from

        Returns:
            str or None: The extracted text
        """
        try:
            # Method 1: Direct text attribute
            if hasattr(widget, 'text'):
                text = widget.text
                if isinstance(text, str):
                    return text
                elif hasattr(text, 'text'):
                    return str(text.text)
                else:
                    return str(text)

            # Method 2: Child text widget
            if hasattr(widget, 'child') and widget.child:
                child_text = self._extract_widget_text(widget.child)
                if child_text:
                    return child_text

            # Method 3: Children text widgets
            if hasattr(widget, 'children'):
                for child in widget.children:
                    child_text = self._extract_widget_text(child)
                    if child_text:
                        return child_text

            return None

        except Exception:
            return None

    def _create_and_invoke_action(self, action_str, label):
        """
        Try to create and invoke an action based on the action string.

        Args:
            action_str (str): String representation of the action
            label (str): Button label for context

        Returns:
            bool: True if action was successfully invoked
        """
        import re
        import renpy
        import threading

        # Parse the action string to extract class name
        match = re.match(r'<store\.(\w+) object at', action_str)
        if not match:
            print(f"[DEBUG] Could not parse action class from: {action_str}")
            return False

        class_name = match.group(1)
        print(f"[DEBUG] Attempting to create {class_name} action for '{label}'")

        # Create appropriate action based on class name
        if class_name == 'Start':
            action = renpy.store.Start()
        elif class_name == 'Quit':
            action = renpy.store.Quit(confirm=False)  # Skip confirmation for testing
        elif class_name == 'ShowMenu':
            # Try to determine which menu based on the label
            if label.lower() in ['load', 'continue']:
                action = renpy.store.ShowMenu('load')
            elif label.lower() in ['save']:
                action = renpy.store.ShowMenu('save')
            elif label.lower() in ['preferences', 'prefs', 'options']:
                action = renpy.store.ShowMenu('preferences')
            elif label.lower() in ['about']:
                action = renpy.store.ShowMenu('about')
            elif label.lower() in ['help']:
                action = renpy.store.ShowMenu('help')
            else:
                print(f"[DEBUG] Unknown ShowMenu target for label '{label}'")
                return False
        else:
            print(f"[DEBUG] Unknown action class: {class_name}")
            return False

        print(f"[DEBUG] Created action: {action}")

        # Instead of executing the action directly, try to simulate a button click
        # This should work better because button clicks are processed by the main execution loop
        print(f"[DEBUG] Attempting to simulate button click for {class_name} action")

        # Try to find the button in the UI and simulate a click
        if self._simulate_button_click(action, label):
            print(f"[DEBUG] Successfully simulated button click for '{label}'")
            return True

        # Fallback: try direct action execution
        print(f"[DEBUG] Button click simulation failed, trying direct action execution")

        # Check if we're in the main thread
        if threading.current_thread().name == "MainThread":
            # We're in the main thread, execute directly
            print(f"[DEBUG] Executing action in main thread")
            result = renpy.display.behavior.run(action)
            print(f"[DEBUG] Action result: {result}")
            return True
        else:
            # We're in a different thread (likely HTTP server thread)
            # Use invoke_in_main_thread to execute in the main thread
            print(f"[DEBUG] Not in main thread, invoking action in main thread...")

            result_container = {'result': None, 'exception': None, 'completed': False}

            def action_wrapper():
                try:
                    result_container['result'] = renpy.display.behavior.run(action)
                    print(f"[DEBUG] Action executed in main thread, result: {result_container['result']}")
                except Exception as e:
                    result_container['exception'] = e
                    print(f"[DEBUG] Action exception in main thread: {e}")
                finally:
                    result_container['completed'] = True

            # Invoke in main thread
            from renpy.exports.platformexports import invoke_in_main_thread
            invoke_in_main_thread(action_wrapper)

            # Wait for completion (with timeout)
            import time
            timeout = 5.0  # 5 second timeout
            start_time = time.time()

            while not result_container['completed']:
                if time.time() - start_time > timeout:
                    print(f"[DEBUG] Action timeout waiting for main thread")
                    return False
                time.sleep(0.01)  # Small sleep to avoid busy waiting

            if result_container['exception']:
                # Re-raise any exception from the main thread
                print(f"[DEBUG] Exception from main thread - re-raising: {result_container['exception']}")
                raise result_container['exception']

            print(f"[DEBUG] Action completed successfully in main thread")
            return True

    def _simulate_button_click(self, action, label):
        """
        Try to simulate a button click by finding the button in the UI and triggering it.

        Args:
            action: The action object to execute
            label (str): The button label

        Returns:
            bool: True if button click was simulated successfully
        """
        try:
            import renpy

            # For Start action, try to queue a "button_select" event to simulate clicking the Start button
            if hasattr(action, '__class__') and action.__class__.__name__ == 'Start':
                print(f"[DEBUG] Simulating Start action by queueing button_select event")

                # Try different approaches to start the game

                # Method 1: Queue a button_select event to simulate clicking the focused button
                renpy.exports.queue_event("button_select")
                print(f"[DEBUG] Queued button_select event")
                return True

            # For other actions, we can't easily simulate them
            return False

        except Exception as e:
            print(f"[DEBUG] Error simulating button click: {e}")
            return False

    def _click_choice_button(self, choice_data):
        """
        Try to click on the button using mouse simulation.
        
        Args:
            choice_data (dict): Choice information
            
        Returns:
            bool: True if click was attempted
        """
        try:
            label = choice_data.get('label', '')
            print(f"[DEBUG] Attempting to activate '{label}' button")
            
            # For quick menu items, right-click is the most reliable way to access the game menu
            # This should open the appropriate screen for most quick menu actions
            if choice_data.get('screen') == 'quick_menu':
                print(f"[DEBUG] Quick menu item '{label}' - using right-click")
                
                # Right-click usually opens the game menu which includes save/load/preferences
                event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {
                    'button': 3,  # Right mouse button
                    'pos': (640, 360)  # Center of typical screen
                })
                pygame.event.post(event)
                return True
            
            # For other screens, try keyboard shortcuts first
            shortcuts = {
                'History': ord('h'),
                'Save': ord('s'),
                'Auto': ord('a'),
                'Skip': 306,  # LCTRL key
                'Prefs': ord('p'),
                'Q.Save': 293,  # F5
                'Q.Load': 297,  # F9
            }
            
            if label in shortcuts:
                key = shortcuts[label]
                print(f"[DEBUG] Using keyboard shortcut for '{label}': {key}")
                event = pygame.event.Event(pygame.KEYDOWN, {'key': key})
                pygame.event.post(event)
                return True
            
            # Fallback: try left-click in center of screen
            print(f"[DEBUG] No specific method for '{label}', trying left-click")
            event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {
                'button': 1,  # Left mouse button
                'pos': (640, 360)  # Center of typical screen
            })
            pygame.event.post(event)
            return True
            
        except Exception as e:
            print(f"[DEBUG] Error clicking choice button: {e}")
            return False
    
    def jump_to_label(self, label):
        """
        Jump to a specific label.
        
        Args:
            label (str): Label name to jump to
            
        Returns:
            bool: True if jump was successful
        """
        try:
            if not renpy.game.script.has_label(label):
                return False
            
            # Use Ren'Py's jump functionality
            renpy.jump(label)
            return True
            
        except Exception:
            return False
    
    def call_label(self, label):
        """
        Call a specific label (can return).
        
        Args:
            label (str): Label name to call
            
        Returns:
            bool: True if call was successful
        """
        try:
            if not renpy.game.script.has_label(label):
                return False
            
            # Use Ren'Py's call functionality
            renpy.call(label)
            return True
            
        except Exception:
            return False
    
    def set_variable(self, name, value):
        """
        Set a game variable.

        Args:
            name (str): Variable name (supports dotted notation like "_preferences.volumes.music")
            value: Variable value

        Returns:
            bool: True if variable was set successfully
        """
        try:
            if hasattr(renpy, 'store') and hasattr(renpy.store, 'store'):
                # Handle dotted attribute names like "_preferences.volumes.music"
                if '.' in name:
                    parts = name.split('.')
                    obj = renpy.store.store

                    # Navigate to the parent object
                    for part in parts[:-1]:
                        if hasattr(obj, part):
                            obj = getattr(obj, part)
                        elif hasattr(obj, '__getitem__') and hasattr(obj, '__setitem__'):
                            # Handle dictionary-like objects
                            try:
                                obj = obj[part]
                            except (KeyError, TypeError):
                                return False
                        else:
                            return False

                    # Set the final attribute/key
                    final_attr = parts[-1]
                    if hasattr(obj, final_attr):
                        # Object attribute
                        setattr(obj, final_attr, value)
                        return True
                    elif hasattr(obj, '__getitem__') and hasattr(obj, '__setitem__'):
                        # Dictionary-like object
                        try:
                            obj[final_attr] = value
                            return True
                        except (KeyError, TypeError):
                            return False
                    else:
                        return False
                else:
                    # Simple attribute name
                    setattr(renpy.store.store, name, value)
                    return True
            return False

        except Exception:
            return False
    
    def get_variable(self, name):
        """
        Get a game variable value.
        
        Args:
            name (str): Variable name
            
        Returns:
            The variable value, or None if not found
        """
        try:
            if hasattr(renpy, 'store') and hasattr(renpy.store, 'store'):
                return getattr(renpy.store.store, name, None)
            return None
            
        except Exception:
            return None
    
    def skip_transitions(self, enable=True):
        """
        Enable or disable transition skipping for faster testing.
        
        Args:
            enable (bool): Whether to skip transitions
        """
        self._skip_transitions = enable
        
        # Set Ren'Py config to skip transitions
        if enable:
            renpy.config.skipping = "fast"
            renpy.config.fast_skipping = True
        else:
            renpy.config.skipping = None
            renpy.config.fast_skipping = False
    
    def set_auto_advance(self, enable=True, delay=0.1):
        """
        Enable or disable automatic dialogue advancement.
        
        Args:
            enable (bool): Whether to auto-advance
            delay (float): Delay between advances in seconds
        """
        self._auto_advance_enabled = enable
        self._auto_advance_delay = delay
        
        if enable:
            # Enable auto-forward mode
            renpy.store._preferences.afm_enable = True
            renpy.store._preferences.afm_time = delay
        else:
            renpy.store._preferences.afm_enable = False
    
    def send_key(self, key):
        """
        Send a keyboard event.
        
        Args:
            key (int): Pygame key constant
            
        Returns:
            bool: True if key was sent successfully
        """
        try:
            event = pygame.event.Event(pygame.KEYDOWN, {'key': key})
            pygame.event.post(event)
            
            event = pygame.event.Event(pygame.KEYUP, {'key': key})
            pygame.event.post(event)
            
            return True
            
        except Exception:
            return False
    
    def send_click(self, x, y, button=1):
        """
        Send a mouse click event.
        
        Args:
            x (int): X coordinate
            y (int): Y coordinate
            button (int): Mouse button (1=left, 2=middle, 3=right)
            
        Returns:
            bool: True if click was sent successfully
        """
        try:
            event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, 
                                     {'button': button, 'pos': (x, y)})
            pygame.event.post(event)
            
            event = pygame.event.Event(pygame.MOUSEBUTTONUP, 
                                     {'button': button, 'pos': (x, y)})
            pygame.event.post(event)
            
            return True
            
        except Exception:
            return False
    
    def wait(self, seconds):
        """
        Wait for a specified amount of time.
        
        Args:
            seconds (float): Time to wait in seconds
        """
        time.sleep(seconds)
    
    def is_interacting(self):
        """
        Check if the game is currently waiting for user interaction.
        
        Returns:
            bool: True if game is waiting for interaction
        """
        try:
            context = renpy.game.context()
            return getattr(context, 'interacting', False) if context else False
        except Exception:
            return False
    
    def force_redraw(self):
        """
        Force a screen redraw.
        
        Returns:
            bool: True if redraw was successful
        """
        try:
            if hasattr(renpy.game, 'interface') and renpy.game.interface:
                renpy.game.interface.restart_interaction = True
                return True
            return False
        except Exception:
            return False
