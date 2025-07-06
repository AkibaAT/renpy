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
        try:
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
            
        except Exception as e:
            print(f"[DEBUG] Error in select_choice: {e}")
            return False
    
    def _invoke_choice_action(self, choice_data):
        """
        Invoke the action for a specific choice.
        
        Args:
            choice_data (dict): Choice information including action
            
        Returns:
            bool: True if action was successfully invoked
        """
        try:
            # Check if choice is enabled
            if not choice_data.get('enabled', True):
                print(f"[DEBUG] Choice '{choice_data.get('label')}' is disabled")
                return False
            
            action_str = choice_data.get('action', '')
            label = choice_data.get('label', 'unknown')
            
            print(f"[DEBUG] Attempting to invoke action for '{label}': {action_str}")
            
            # Method 1: Try to invoke the action directly if we can parse it
            if 'store.' in action_str:
                try:
                    # Extract the action object reference and try to access it
                    # This is a complex approach - let's try a simpler method first
                    pass
                except Exception as e:
                    print(f"[DEBUG] Could not directly invoke action: {e}")
            
            # Method 2: Try using mouse click on the button location
            # This is more reliable for UI buttons
            return self._click_choice_button(choice_data)
            
        except Exception as e:
            print(f"[DEBUG] Error invoking choice action: {e}")
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
