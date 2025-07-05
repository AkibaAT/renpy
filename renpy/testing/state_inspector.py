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
State Inspector

This module provides functionality to inspect the current state of a Ren'Py game,
including variables, scene information, dialogue state, and available choices.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
import copy


class StateInspector(object):
    """
    Provides methods to inspect the current game state.
    """
    
    def __init__(self):
        """Initialize the state inspector."""
        pass
    
    def get_full_state(self):
        """
        Get comprehensive information about the current game state.
        
        Returns:
            dict: Dictionary containing all available state information
        """
        return {
            'label': self.get_current_label(),
            'variables': self.get_variables(),
            'scene_info': self.get_scene_info(),
            'dialogue_info': self.get_dialogue_info(),
            'choices': self.get_choices(),
            'context_info': self.get_context_info(),
            'rollback_info': self.get_rollback_info()
        }
    
    def get_current_label(self):
        """
        Get the current label/scene name.
        
        Returns:
            str or None: Current label name, or None if not available
        """
        try:
            context = renpy.game.context()
            if context and context.current:
                node = renpy.game.script.lookup(context.current)
                if hasattr(node, 'name'):
                    return node.name
                return str(context.current)
            return None
        except Exception:
            return None
    
    def get_variables(self):
        """
        Get current game variables from the store.

        Returns:
            dict: Dictionary of variable names to values
        """
        try:
            variables = {}

            # Get variables from the main store
            if hasattr(renpy, 'store') and hasattr(renpy.store, 'store'):
                store_dict = renpy.store.store.__dict__
                for name, value in store_dict.items():
                    # Skip private/internal variables and modules, but include _preferences
                    if (not name.startswith('_') or name == '_preferences') and not hasattr(value, '__module__'):
                        try:
                            # Try to serialize the value to ensure it's accessible
                            copy.deepcopy(value)
                            variables[name] = value
                        except Exception:
                            # If we can't serialize it, store a string representation
                            variables[name] = str(value)

            # Also add preferences as a separate entry for easier access
            if hasattr(renpy.store, '_preferences'):
                try:
                    # Convert preferences object to a dictionary
                    prefs = renpy.store._preferences
                    preferences_dict = {}

                    # Get all preference attributes
                    for attr_name in dir(prefs):
                        if not attr_name.startswith('_'):
                            try:
                                attr_value = getattr(prefs, attr_name)
                                # Skip methods and functions
                                if not callable(attr_value):
                                    preferences_dict[attr_name] = attr_value
                            except Exception:
                                pass

                    variables['preferences'] = preferences_dict
                except Exception:
                    pass

            return variables
        except Exception:
            return {}
    
    def get_scene_info(self):
        """
        Get current scene and screen information.

        Returns:
            dict: Dictionary containing scene and screen information
        """
        try:
            scene_info = {
                'shown_images': [],
                'active_screens': [],
                'scene_lists': {},
                'audio_info': {
                    'music': None,
                    'sound': [],
                    'voice': None
                },
                'debug_info': []
            }

            # Debug logging
            print("[DEBUG] get_scene_info() called")

            # Get current context and scene lists
            context = renpy.game.context()
            print(f"[DEBUG] context: {context}")
            if context and hasattr(context, 'scene_lists'):
                scene_lists = context.scene_lists
                print(f"[DEBUG] context.scene_lists: {scene_lists}")

                # Get shown images
                if hasattr(scene_lists, 'shown') and scene_lists.shown:
                    print(f"[DEBUG] scene_lists.shown: {scene_lists.shown}")
                    print(f"[DEBUG] scene_lists.shown attributes: {dir(scene_lists.shown)}")
                    # Try to access shown images properly
                    if hasattr(scene_lists.shown, 'images'):
                        for layer, images in scene_lists.shown.images.items():
                            for tag, image_info in images.items():
                                scene_info['shown_images'].append({
                                    'layer': layer,
                                    'tag': tag,
                                    'name': image_info.get('name', ''),
                                    'zorder': image_info.get('zorder', 0)
                                })
                    else:
                        print("[DEBUG] scene_lists.shown has no 'images' attribute")

                # Get layer information
                if hasattr(scene_lists, 'layers'):
                    print(f"[DEBUG] scene_lists.layers keys: {list(scene_lists.layers.keys())}")
                    for layer_name, layer_contents in scene_lists.layers.items():
                        scene_info['scene_lists'][layer_name] = len(layer_contents)
                        print(f"[DEBUG] layer {layer_name}: {len(layer_contents)} items")

            # Get active screens and images using scene_lists
            scene_lists = renpy.exports.scene_lists()
            print(f"[DEBUG] renpy.exports.scene_lists(): {scene_lists}")
            if scene_lists and hasattr(scene_lists, 'layers'):
                print(f"[DEBUG] scene_lists.layers: {list(scene_lists.layers.keys())}")
                for layer_name, layer_list in scene_lists.layers.items():
                    print(f"[DEBUG] checking layer {layer_name}: {len(layer_list)} items")
                    # Layer is a list of SLE (Scene List Entry) objects
                    for i, sle in enumerate(layer_list):
                        print(f"[DEBUG] SLE {i}: {sle}")
                        print(f"[DEBUG] SLE {i} type: {type(sle)}")

                        # Get the displayable from the SLE
                        if hasattr(sle, 'displayable'):
                            displayable = sle.displayable
                            print(f"[DEBUG] SLE {i} displayable: {displayable}")
                            print(f"[DEBUG] displayable type: {type(displayable)}")

                            # Check if this is a screen displayable
                            if hasattr(displayable, 'screen_name'):
                                screen_name = displayable.screen_name
                                print(f"[DEBUG] found screen: {screen_name}")
                                if isinstance(screen_name, tuple):
                                    screen_name = screen_name[0]
                                scene_info['active_screens'].append(screen_name)

                            # Check if this is an image (has tag and name attributes from SLE)
                            if hasattr(sle, 'tag') and hasattr(sle, 'name'):
                                tag = sle.tag
                                name = sle.name
                                print(f"[DEBUG] found image - tag: {tag}, name: {name}")

                                # Get additional image info
                                image_info = {
                                    'tag': tag,
                                    'name': name,
                                    'layer': layer_name
                                }

                                # Try to get zorder if available
                                if hasattr(sle, 'zorder'):
                                    image_info['zorder'] = sle.zorder

                                # Try to get transform info if available
                                if hasattr(displayable, 'child') and hasattr(displayable.child, 'name'):
                                    image_info['image_name'] = str(displayable.child.name)

                                scene_info['shown_images'].append(image_info)
                            else:
                                print(f"[DEBUG] SLE {i} has no tag/name (not an image)")
                        else:
                            print(f"[DEBUG] SLE {i} has no displayable attribute")
            else:
                print("[DEBUG] No scene_lists or no layers")

            # Get audio information
            try:
                print("[DEBUG] Getting audio information")

                # Try different ways to access the audio system
                audio_found = False

                # Method 1: Try renpy.music directly
                if hasattr(renpy, 'music'):
                    print(f"[DEBUG] renpy.music available: True")
                    try:
                        music_playing = renpy.music.get_playing(channel='music')
                        if music_playing:
                            scene_info['audio_info']['music'] = {
                                'filename': music_playing,
                                'channel': 'music'
                            }
                            audio_found = True
                            print(f"[DEBUG] music playing via renpy.music: {music_playing}")
                    except Exception as e:
                        print(f"[DEBUG] error with renpy.music: {e}")
                else:
                    print("[DEBUG] renpy.music not available")

                # Method 2: Try accessing through renpy.audio
                if not audio_found and hasattr(renpy, 'audio'):
                    print("[DEBUG] trying renpy.audio")
                    try:
                        if hasattr(renpy.audio, 'music') and hasattr(renpy.audio.music, 'get_playing'):
                            music_playing = renpy.audio.music.get_playing()
                            if music_playing:
                                scene_info['audio_info']['music'] = {
                                    'filename': music_playing,
                                    'channel': 'music'
                                }
                                audio_found = True
                                print(f"[DEBUG] music playing via renpy.audio.music: {music_playing}")
                    except Exception as e:
                        print(f"[DEBUG] error with renpy.audio: {e}")

                # Method 3: Try accessing through renpy.exports
                if not audio_found:
                    print("[DEBUG] trying renpy.exports for audio")
                    try:
                        # Check if there are any audio-related exports
                        audio_exports = [attr for attr in dir(renpy.exports) if 'music' in attr.lower() or 'audio' in attr.lower() or 'sound' in attr.lower()]
                        print(f"[DEBUG] audio-related exports: {audio_exports}")

                        # Try some common audio function names
                        for func_name in ['music_get_playing', 'get_playing_music', 'audio_get_playing']:
                            if hasattr(renpy.exports, func_name):
                                try:
                                    result = getattr(renpy.exports, func_name)()
                                    if result:
                                        scene_info['audio_info']['music'] = {
                                            'filename': result,
                                            'channel': 'music'
                                        }
                                        audio_found = True
                                        print(f"[DEBUG] music playing via {func_name}: {result}")
                                        break
                                except Exception as e:
                                    print(f"[DEBUG] error with {func_name}: {e}")
                    except Exception as e:
                        print(f"[DEBUG] error with renpy.exports audio: {e}")

                # Method 4: Try accessing the audio system through the store
                if not audio_found:
                    print("[DEBUG] trying store access for audio")
                    try:
                        import store
                        if hasattr(store, 'renpy') and hasattr(store.renpy, 'music'):
                            music_playing = store.renpy.music.get_playing(channel='music')
                            if music_playing:
                                scene_info['audio_info']['music'] = {
                                    'filename': music_playing,
                                    'channel': 'music'
                                }
                                audio_found = True
                                print(f"[DEBUG] music playing via store.renpy.music: {music_playing}")
                    except Exception as e:
                        print(f"[DEBUG] error with store audio: {e}")

                if not audio_found:
                    print("[DEBUG] no audio system found or no music playing")

            except Exception as e:
                print(f"[DEBUG] error getting audio info: {e}")
                import traceback
                print(f"[DEBUG] traceback: {traceback.format_exc()}")

            print(f"[DEBUG] final scene_info: {scene_info}")
            return scene_info
        except Exception as e:
            print(f"[DEBUG] Exception in get_scene_info: {e}")
            import traceback
            traceback.print_exc()
            return {'shown_images': [], 'active_screens': [], 'scene_lists': {}}
    
    def get_dialogue_info(self):
        """
        Get current dialogue information.

        Returns:
            dict: Dictionary containing dialogue state information
        """
        try:
            dialogue_info = {
                'current_statement': None,
                'statement_type': None,
                'who': None,
                'what': None,
                'filename': None,
                'linenumber': None
            }

            context = renpy.game.context()
            if context and context.current:
                node = renpy.game.script.lookup(context.current)
                if node:
                    dialogue_info['current_statement'] = str(node)
                    dialogue_info['statement_type'] = type(node).__name__
                    dialogue_info['filename'] = getattr(node, 'filename', None)
                    dialogue_info['linenumber'] = getattr(node, 'linenumber', None)

                    # For Say statements, get who and what
                    if hasattr(node, 'who') and hasattr(node, 'what'):
                        dialogue_info['who'] = node.who
                        dialogue_info['what'] = node.what

            # Also check for last displayed dialogue (more reliable for current content)
            try:
                last_say = renpy.exports.last_say()
                if last_say and last_say.what:
                    dialogue_info['who'] = str(last_say.who) if last_say.who else None
                    dialogue_info['what'] = last_say.what
            except Exception:
                pass

            return dialogue_info
        except Exception:
            return {'current_statement': None, 'statement_type': None,
                   'who': None, 'what': None, 'filename': None, 'linenumber': None}
    
    def get_choices(self):
        """
        Get available menu choices if currently in a menu.

        Returns:
            list: List of available choices, each as a dict with 'label' and 'value'
        """
        try:
            choices = []

            print("[DEBUG] get_choices() called")

            # Check for active screens that might contain choices
            scene_lists = renpy.exports.scene_lists()
            print(f"[DEBUG] scene_lists: {scene_lists}")
            if scene_lists and hasattr(scene_lists, 'layers'):
                print(f"[DEBUG] scene_lists.layers: {list(scene_lists.layers.keys())}")
                # Look through all layers for screen displayables
                for layer_name, layer_list in scene_lists.layers.items():
                    print(f"[DEBUG] checking layer {layer_name}: {len(layer_list)} items")
                    # Layer is a list of SLE (Scene List Entry) objects
                    for i, sle in enumerate(layer_list):
                        print(f"[DEBUG] SLE {i}: {sle}")

                        # Get the displayable from the SLE
                        if hasattr(sle, 'displayable'):
                            displayable = sle.displayable
                            print(f"[DEBUG] SLE {i} displayable: {displayable}")

                            # Check if this is a screen displayable
                            if hasattr(displayable, 'screen_name'):
                                screen_name = displayable.screen_name
                                if isinstance(screen_name, tuple):
                                    screen_name = screen_name[0]
                                print(f"[DEBUG] found screen displayable: {screen_name}")

                                # Check if this screen has scope with items (like choice screens)
                                if hasattr(displayable, 'scope'):
                                    print(f"[DEBUG] screen {screen_name} scope keys: {list(displayable.scope.keys())}")
                                    if 'items' in displayable.scope:
                                        items = displayable.scope['items']
                                        print(f"[DEBUG] found {len(items)} items in scope")
                                        if items:
                                            for j, item in enumerate(items):
                                                print(f"[DEBUG] item {j}: {item}")
                                                if hasattr(item, 'caption') and hasattr(item, 'action'):
                                                    choices.append({
                                                        'label': str(item.caption),
                                                        'action': str(item.action),
                                                        'screen': screen_name
                                                    })
                                else:
                                    print(f"[DEBUG] screen {screen_name} has no scope")

                                # For tutorial screen, try to extract textbutton choices
                                if screen_name == 'tutorials' and hasattr(displayable, 'child'):
                                    print(f"[DEBUG] extracting choices from tutorials screen")
                                    extracted = self._extract_screen_choices(displayable, screen_name)
                                    print(f"[DEBUG] extracted {len(extracted)} choices")
                                    choices.extend(extracted)
                            else:
                                print(f"[DEBUG] displayable has no screen_name")
                        else:
                            print(f"[DEBUG] SLE {i} has no displayable attribute")
            else:
                print("[DEBUG] No scene_lists or no layers")

            print(f"[DEBUG] final choices: {choices}")
            return choices
        except Exception as e:
            print(f"[DEBUG] Exception in get_choices: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _extract_screen_choices(self, screen_displayable, screen_name):
        """
        Extract choices from a screen's widget tree.

        Args:
            screen_displayable: The screen displayable to examine
            screen_name: Name of the screen

        Returns:
            list: List of choice dictionaries
        """
        choices = []
        try:
            # Recursively search for button-like widgets
            def find_buttons(widget):
                found = []
                if widget is None:
                    return found

                # Check if this widget is a button with text and action
                if hasattr(widget, 'clicked') and widget.clicked:
                    # Try to get button text
                    text = None
                    if hasattr(widget, 'children'):
                        for child in widget.children:
                            if hasattr(child, 'text'):
                                text = str(child.text)
                                break

                    if text:
                        found.append({
                            'label': text,
                            'action': str(widget.clicked),
                            'screen': screen_name
                        })

                # Recursively check children
                if hasattr(widget, 'children'):
                    for child in widget.children:
                        found.extend(find_buttons(child))
                elif hasattr(widget, 'child'):
                    found.extend(find_buttons(widget.child))

                return found

            if screen_displayable.child:
                choices = find_buttons(screen_displayable.child)

        except Exception:
            pass

        return choices
    
    def get_context_info(self):
        """
        Get information about the current execution context.
        
        Returns:
            dict: Dictionary containing context information
        """
        try:
            context_info = {
                'context_depth': 0,
                'call_stack': [],
                'return_stack': [],
                'abnormal': False,
                'interacting': False
            }
            
            if renpy.game.contexts:
                context_info['context_depth'] = len(renpy.game.contexts)
                
                context = renpy.game.context()
                if context:
                    context_info['abnormal'] = getattr(context, 'abnormal', False)
                    context_info['interacting'] = getattr(context, 'interacting', False)
                    
                    # Get call stack information
                    if hasattr(context, 'return_stack'):
                        context_info['return_stack'] = [str(item) for item in context.return_stack]
                    
                    if hasattr(context, 'call_location_stack'):
                        context_info['call_stack'] = [str(item) for item in context.call_location_stack]
            
            return context_info
        except Exception:
            return {'context_depth': 0, 'call_stack': [], 'return_stack': [], 
                   'abnormal': False, 'interacting': False}
    
    def get_rollback_info(self):
        """
        Get information about the rollback system state.
        
        Returns:
            dict: Dictionary containing rollback information
        """
        try:
            rollback_info = {
                'can_rollback': False,
                'rollback_length': 0,
                'current_checkpoint': 0
            }
            
            if hasattr(renpy.game, 'log') and renpy.game.log:
                log = renpy.game.log
                rollback_info['rollback_length'] = len(getattr(log, 'log', []))
                rollback_info['can_rollback'] = rollback_info['rollback_length'] > 0
                
                # Count checkpoints
                checkpoint_count = 0
                for entry in getattr(log, 'log', []):
                    if getattr(entry, 'checkpoint', False) or getattr(entry, 'hard_checkpoint', False):
                        checkpoint_count += 1
                rollback_info['current_checkpoint'] = checkpoint_count
            
            return rollback_info
        except Exception:
            return {'can_rollback': False, 'rollback_length': 0, 'current_checkpoint': 0}
