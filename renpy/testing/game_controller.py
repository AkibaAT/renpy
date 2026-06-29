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
            choices = self._get_current_choices()

            if isinstance(choice, int):
                if 0 <= choice < len(choices):
                    if self._invoke_choice_action(choices[choice]):
                        return True

                return self._select_choice_by_number_key(choice)

            elif isinstance(choice, str):
                for choice_data in choices:
                    if choice_data.get('label') == choice:
                        return self._invoke_choice_action(choice_data)
            
            return False
            
        except Exception:
            return False

    def _get_current_choices(self):
        if self.testing_interface:
            return self.testing_interface.get_choices()

        from . import state_inspector
        inspector = state_inspector.StateInspector()
        return inspector.get_choices()

    def _select_choice_by_number_key(self, choice):
        try:
            if not isinstance(choice, int) or choice < 0 or choice >= 9:
                return False

            key = pygame.K_1 + choice
            event = pygame.event.Event(pygame.KEYDOWN, {'key': key})
            pygame.event.post(event)

            event = pygame.event.Event(pygame.KEYUP, {'key': key})
            pygame.event.post(event)

            return True
        except Exception:
            return False

    def _invoke_choice_action(self, choice_data):
        if not choice_data or not choice_data.get('enabled', True):
            return False

        action = self._find_action_for_choice(choice_data)
        if action is None:
            return False

        return self._run_action(action)

    def _find_action_for_choice(self, choice_data):
        label = choice_data.get('label')
        screen_name = choice_data.get('screen')

        if not label:
            return None

        try:
            scene_lists = renpy.exports.scene_lists()
            if not scene_lists or not hasattr(scene_lists, 'layers'):
                return None

            for layer_list in scene_lists.layers.values():
                for sle in layer_list:
                    displayable = getattr(sle, 'displayable', None)
                    if displayable is None:
                        continue

                    current_screen = getattr(displayable, 'screen_name', None)
                    if isinstance(current_screen, tuple):
                        current_screen = current_screen[0]

                    if screen_name and current_screen != screen_name:
                        continue

                    action = self._find_action_in_screen_scope(displayable, label)
                    if action is not None:
                        return action

                    action = self._find_button_action_recursive(displayable, label)
                    if action is not None:
                        return action
        except Exception:
            return None

        return None

    def _find_action_in_screen_scope(self, displayable, label):
        try:
            scope = getattr(displayable, 'scope', None)
            if not scope:
                return None

            for item in scope.get('items') or []:
                if not hasattr(item, 'caption') or not hasattr(item, 'action'):
                    continue

                if str(item.caption).strip() == str(label).strip():
                    return item.action
        except Exception:
            pass

        return None

    def _find_button_action_recursive(self, widget, target_label):
        try:
            text = self._extract_widget_text(widget)
            if text and text.strip() == str(target_label).strip():
                for attr in ['clicked', 'action', 'activate']:
                    if hasattr(widget, attr):
                        action = getattr(widget, attr)
                        if action:
                            return action

            if hasattr(widget, 'child') and widget.child:
                result = self._find_button_action_recursive(widget.child, target_label)
                if result:
                    return result

            if hasattr(widget, 'children') and widget.children:
                for child in widget.children:
                    result = self._find_button_action_recursive(child, target_label)
                    if result:
                        return result
        except Exception:
            pass

        return None

    def _extract_widget_text(self, widget):
        try:
            if hasattr(widget, 'text') and widget.text:
                return str(widget.text)

            if hasattr(widget, 'child') and widget.child:
                child_text = self._extract_widget_text(widget.child)
                if child_text:
                    return child_text

            if hasattr(widget, 'children') and widget.children:
                for child in widget.children:
                    child_text = self._extract_widget_text(child)
                    if child_text:
                        return child_text
        except Exception:
            pass

        return None

    def _run_action(self, action):
        try:
            if hasattr(action, 'get_sensitive') and action.get_sensitive() is False:
                return False
        except Exception:
            pass

        def run():
            import renpy.display.behavior
            renpy.display.behavior.run(action)

        return self._run_in_main_thread(run)

    def _run_in_main_thread(self, callable_):
        try:
            import threading

            if threading.current_thread().name == "MainThread":
                callable_()
                return True

            result = {'completed': False, 'exception': None}

            def wrapper():
                try:
                    callable_()
                except Exception as e:
                    result['exception'] = e
                finally:
                    result['completed'] = True

            from renpy.exports.platformexports import invoke_in_main_thread
            invoke_in_main_thread(wrapper)

            timeout = 5.0
            started = time.time()
            while not result['completed']:
                if time.time() - started > timeout:
                    return False
                time.sleep(0.01)

            return result['exception'] is None
        except Exception:
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
