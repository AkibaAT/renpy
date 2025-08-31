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
        Get current scene and screen information using Interactive Director APIs.

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
                'debug_info': [],
                # Interactive Director compatible data
                'available_tags': [],
                'showing_tags': [],
                'available_transforms': [],
                'audio_channels': [],
                'audio_files': {},
                'transitions': []
            }

            # Get current context and scene lists
            context = renpy.game.context()
            if context and hasattr(context, 'scene_lists'):
                scene_lists = context.scene_lists

                # Get shown images
                if hasattr(scene_lists, 'shown') and scene_lists.shown:
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

                # Get layer information
                if hasattr(scene_lists, 'layers'):
                    for layer_name, layer_contents in scene_lists.layers.items():
                        scene_info['scene_lists'][layer_name] = len(layer_contents)

            # Get active screens and images using scene_lists
            scene_lists = renpy.exports.scene_lists()
            if scene_lists and hasattr(scene_lists, 'layers'):
                for layer_name, layer_list in scene_lists.layers.items():
                    # Layer is a list of SLE (Scene List Entry) objects
                    for i, sle in enumerate(layer_list):
                        # Get the displayable from the SLE
                        if hasattr(sle, 'displayable'):
                            displayable = sle.displayable

                            # Check if this is a screen displayable
                            if hasattr(displayable, 'screen_name'):
                                screen_name = displayable.screen_name
                                if isinstance(screen_name, tuple):
                                    screen_name = screen_name[0]
                                scene_info['active_screens'].append(screen_name)

                            # Check if this is an image (has tag and name attributes from SLE)
                            if hasattr(sle, 'tag') and hasattr(sle, 'name'):
                                tag = sle.tag
                                name = sle.name

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

                                # Extract positioning and sizing information
                                self._extract_display_properties(displayable, sle, image_info)

                                scene_info['shown_images'].append(image_info)

            # Get audio information
            try:
                # Try different ways to access the audio system
                audio_found = False

                # Method 1: Try renpy.music directly
                if hasattr(renpy, 'music'):
                    try:
                        music_playing = renpy.music.get_playing(channel='music')
                        if music_playing:
                            scene_info['audio_info']['music'] = {
                                'filename': music_playing,
                                'channel': 'music'
                            }
                            audio_found = True
                    except Exception:
                        pass

                # Method 2: Try accessing through renpy.audio
                if not audio_found and hasattr(renpy, 'audio'):
                    try:
                        if hasattr(renpy.audio, 'music') and hasattr(renpy.audio.music, 'get_playing'):
                            music_playing = renpy.audio.music.get_playing()
                            if music_playing:
                                scene_info['audio_info']['music'] = {
                                    'filename': music_playing,
                                    'channel': 'music'
                                }
                                audio_found = True
                    except Exception:
                        pass

                # Method 3: Try accessing through renpy.exports
                if not audio_found:
                    try:
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
                                        break
                                except Exception:
                                    pass
                    except Exception:
                        pass

                # Method 4: Try accessing the audio system through the store
                if not audio_found:
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
                    except Exception:
                        pass

            except Exception:
                pass

            # Add detailed screen content analysis
            try:
                detailed_screens = self._get_detailed_screen_info()
                if detailed_screens:
                    scene_info['detailed_screens'] = detailed_screens
            except Exception:
                pass

            # Add Interactive Director compatible data
            try:
                # Get available image tags (same as interactive director)
                scene_info['available_tags'] = [
                    tag for tag in renpy.get_available_image_tags()
                    if not tag.startswith("_")
                ]

                # Get currently showing tags
                scene_info['showing_tags'] = list(renpy.get_showing_tags())

                # Get available transforms (from director module if available)
                try:
                    import store.director as director
                    scene_info['available_transforms'] = getattr(director, 'transforms', ['left', 'center', 'right'])
                    scene_info['transitions'] = getattr(director, 'transitions', ['dissolve', 'pixellate'])
                    scene_info['audio_channels'] = getattr(director, 'audio_channels', ['music', 'sound', 'audio'])
                    scene_info['audio_files'] = getattr(director, 'audio_files', {})
                except Exception:
                    # Fallback defaults
                    scene_info['available_transforms'] = ['left', 'center', 'right']
                    scene_info['transitions'] = ['dissolve', 'pixellate']
                    scene_info['audio_channels'] = ['music', 'sound', 'audio']
                    scene_info['audio_files'] = {}

            except Exception:
                # Ensure we have at least empty lists
                scene_info['available_tags'] = []
                scene_info['showing_tags'] = []
                scene_info['available_transforms'] = []
                scene_info['transitions'] = []
                scene_info['audio_channels'] = []
                scene_info['audio_files'] = {}

            return scene_info
        except Exception as e:
            return {'shown_images': [], 'active_screens': [], 'scene_lists': {}}

    def get_image_attributes(self, tag):
        """
        Get available attributes for a specific image tag.

        Args:
            tag (str): The image tag to get attributes for

        Returns:
            list: List of available attributes for the tag
        """
        try:
            if not tag:
                return []
            return renpy.get_ordered_image_attributes(tag, [])
        except Exception:
            return []

    def get_behind_tags(self, exclude_tag=None):
        """
        Get list of tags that can be used for 'behind' positioning.

        Args:
            exclude_tag (str): Tag to exclude from the list

        Returns:
            list: List of tags that can be used for behind positioning
        """
        try:
            showing_tags = renpy.get_showing_tags()
            scene_tags = {'bg'}  # Common scene tags

            rv = []
            for tag in showing_tags:
                if tag in scene_tags:
                    continue
                if tag == exclude_tag:
                    continue
                rv.append(tag)

            return rv
        except Exception:
            return []
    
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

            # print("[DEBUG] get_choices() called")  # Reduce debug output for performance

            # Check for active screens that might contain choices
            scene_lists = renpy.exports.scene_lists()
            # print(f"[DEBUG] scene_lists: {scene_lists}")  # Reduce debug output
            if scene_lists and hasattr(scene_lists, 'layers'):
                # print(f"[DEBUG] scene_lists.layers: {list(scene_lists.layers.keys())}")  # Reduce debug output
                # Look through all layers for screen displayables
                for layer_name, layer_list in scene_lists.layers.items():
                    # print(f"[DEBUG] checking layer {layer_name}: {len(layer_list)} items")  # Reduce debug output
                    # Layer is a list of SLE (Scene List Entry) objects
                    for i, sle in enumerate(layer_list):
                        # print(f"[DEBUG] SLE {i}: {sle}")  # Reduce debug output

                        # Get the displayable from the SLE
                        if hasattr(sle, 'displayable'):
                            displayable = sle.displayable
                            # print(f"[DEBUG] SLE {i} displayable: {displayable}")  # Reduce debug output

                            # Check if this is a screen displayable
                            if hasattr(displayable, 'screen_name'):
                                screen_name = displayable.screen_name
                                if isinstance(screen_name, tuple):
                                    screen_name = screen_name[0]
                                # print(f"[DEBUG] found screen displayable: {screen_name}")  # Reduce debug output

                                # Extract screen background and visual elements
                                screen_info = {
                                    'tag': f'screen_{screen_name}',
                                    'name': [screen_name],
                                    'layer': layer_name,
                                    'type': 'screen'
                                }
                                
                                # Try to get screen background information
                                self._extract_screen_background(displayable, screen_info)
                                
                                # Extract positioning and sizing information for the screen
                                self._extract_display_properties(displayable, sle, screen_info)
                                
                                # Extract all visual content from within the screen
                                screen_content = []
                                self._extract_screen_content(displayable, screen_content)
                                if screen_content:
                                    screen_info['content'] = screen_content
                                
                                # This was incorrectly trying to append to scene_info in get_choices()
                                # Remove this line as it doesn't belong here

                                # Check if this screen has scope with items (like choice screens)
                                if hasattr(displayable, 'scope'):
                                    # print(f"[DEBUG] screen {screen_name} scope keys: {list(displayable.scope.keys())}")  # Reduce debug output
                                    if 'items' in displayable.scope:
                                        items = displayable.scope['items']
                                        # print(f"[DEBUG] found {len(items)} items in scope")  # Reduce debug output
                                        if items:
                                            for j, item in enumerate(items):
                                                # print(f"[DEBUG] item {j}: {item}")  # Reduce debug output
                                                if hasattr(item, 'caption') and hasattr(item, 'action'):
                                                    choices.append({
                                                        'label': str(item.caption),
                                                        'action': str(item.action),
                                                        'screen': screen_name
                                                    })
                                # else:
                                #     print(f"[DEBUG] screen {screen_name} has no scope")  # Reduce debug output

                                # For all screens with widgets, try to extract textbutton choices
                                if hasattr(displayable, 'child'):
                                    # print(f"[DEBUG] extracting choices from {screen_name} screen")  # Reduce debug output
                                    extracted = self._extract_screen_choices(displayable, screen_name)
                                    # print(f"[DEBUG] extracted {len(extracted)} choices")  # Reduce debug output
                                    choices.extend(extracted)
                            # else:
                            #     print(f"[DEBUG] displayable has no screen_name")  # Reduce debug output
                        # else:
                        #     print(f"[DEBUG] SLE {i} has no displayable attribute")  # Reduce debug output
            # else:
            #     print("[DEBUG] No scene_lists or no layers")  # Reduce debug output

            # print(f"[DEBUG] final choices: {choices}")  # Reduce debug output
            return choices
        except Exception:
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

                widget_type = type(widget).__name__
                
                # Generic button detection - look for any widget with a click action
                is_clickable = False
                action_attr = None
                
                # Check for various click/action attributes
                for attr in ['clicked', 'action', 'activate', 'hovered']:
                    if hasattr(widget, attr):
                        action_value = getattr(widget, attr)
                        if action_value:  # Only if the action is not None/empty
                            is_clickable = True
                            action_attr = attr
                            break
                
                if is_clickable:
                    # Try to get button text using multiple methods
                    text = self._extract_widget_text(widget)
                    
                    if text:
                        action_value = getattr(widget, action_attr)
                        
                        # Check if the button is actually clickable/enabled
                        is_enabled = self._check_widget_enabled(widget, action_value)
                        
                        choice_data = {
                            'label': text,
                            'action': str(action_value),
                            'screen': screen_name,
                            'type': widget_type,
                            'action_attr': action_attr,
                            'enabled': is_enabled
                        }
                        
                        # Add additional state information if available
                        if hasattr(widget, 'sensitive'):
                            choice_data['sensitive'] = widget.sensitive
                        if hasattr(widget, 'selected'):
                            choice_data['selected'] = widget.selected
                            
                        found.append(choice_data)
                        # status = "enabled" if is_enabled else "disabled"
                        # print(f"[DEBUG] found {widget_type}: {text} -> {action_value} ({status})")  # Reduce debug output

                # Also check for specific Ren'Py button types by class name
                button_indicators = ['button', 'textbutton', 'imagebutton', 'hotspot', 'choice']
                if any(indicator in widget_type.lower() for indicator in button_indicators):
                    # print(f"[DEBUG] detected button-type widget: {widget_type}")  # Reduce debug output
                    
                    # Even if no direct action, might still be clickable
                    if not is_clickable:
                        text = self._extract_widget_text(widget)
                        if text:
                            # Check if this button-type widget is enabled
                            is_enabled = self._check_widget_enabled(widget, None)
                            
                            choice_data = {
                                'label': text,
                                'action': 'none',
                                'screen': screen_name,
                                'type': widget_type,
                                'action_attr': 'detected_by_type',
                                'enabled': is_enabled
                            }
                            
                            # Add additional state information if available
                            if hasattr(widget, 'sensitive'):
                                choice_data['sensitive'] = widget.sensitive
                            if hasattr(widget, 'selected'):
                                choice_data['selected'] = widget.selected
                                
                            found.append(choice_data)

                # Recursively check children
                if hasattr(widget, 'children') and widget.children:
                    for child in widget.children:
                        found.extend(find_buttons(child))
                elif hasattr(widget, 'child') and widget.child:
                    found.extend(find_buttons(widget.child))

                return found

            if screen_displayable.child:
                choices = find_buttons(screen_displayable.child)

        except Exception:
            pass

        return choices
    
    def _extract_widget_text(self, widget):
        """
        Extract text from a widget using multiple methods.
        
        Args:
            widget: The widget to extract text from
            
        Returns:
            str or None: The extracted text, or None if no text found
        """
        text = None
        
        # Method 1: Check children for text widgets
        if hasattr(widget, 'children') and widget.children:
            for child in widget.children:
                if hasattr(child, 'text') and child.text:
                    text = child.text
                    break
                # Also check for nested text in child's children
                elif hasattr(child, 'children') and child.children:
                    for grandchild in child.children:
                        if hasattr(grandchild, 'text') and grandchild.text:
                            text = grandchild.text
                            break
                    if text:
                        break
        
        # Method 2: Check if widget itself has text
        if not text and hasattr(widget, 'text') and widget.text:
            text = widget.text
        
        # Method 3: Check child.text
        if not text and hasattr(widget, 'child') and widget.child:
            if hasattr(widget.child, 'text') and widget.child.text:
                text = widget.child.text
            # Also check child's children
            elif hasattr(widget.child, 'children') and widget.child.children:
                for grandchild in widget.child.children:
                    if hasattr(grandchild, 'text') and grandchild.text:
                        text = grandchild.text
                        break
        
        # Method 4: Check for label or caption attributes
        if not text:
            for attr in ['label', 'caption', 'title', 'name']:
                if hasattr(widget, attr):
                    attr_value = getattr(widget, attr)
                    if attr_value:
                        text = attr_value
                        break
        
        # Normalize text format (handle lists/tuples)
        if text:
            if isinstance(text, (list, tuple)) and len(text) > 0:
                text = str(text[0])
            else:
                text = str(text)
            
            # Clean up the text
            text = text.strip()
            if text:
                return text
        
        return None
    
    def _extract_display_properties(self, displayable, sle, image_info):
        """
        Extract positioning, sizing, and transform information from a displayable.
        
        Args:
            displayable: The displayable object
            sle: The scene list entry
            image_info: Dictionary to add properties to
        """
        try:
            # Initialize transform/positioning info
            transform_info = {}
            
            # Try to get position information
            if hasattr(displayable, 'xpos'):
                transform_info['xpos'] = displayable.xpos
            if hasattr(displayable, 'ypos'):
                transform_info['ypos'] = displayable.ypos
            if hasattr(displayable, 'xanchor'):
                transform_info['xanchor'] = displayable.xanchor
            if hasattr(displayable, 'yanchor'):
                transform_info['yanchor'] = displayable.yanchor
            
            # Try to get size information
            if hasattr(displayable, 'width'):
                transform_info['width'] = displayable.width
            if hasattr(displayable, 'height'):
                transform_info['height'] = displayable.height
            if hasattr(displayable, 'xsize'):
                transform_info['xsize'] = displayable.xsize
            if hasattr(displayable, 'ysize'):
                transform_info['ysize'] = displayable.ysize
            
            # Try to get transform properties
            if hasattr(displayable, 'xalign'):
                transform_info['xalign'] = displayable.xalign
            if hasattr(displayable, 'yalign'):
                transform_info['yalign'] = displayable.yalign
            if hasattr(displayable, 'zoom'):
                transform_info['zoom'] = displayable.zoom
            if hasattr(displayable, 'alpha'):
                transform_info['alpha'] = displayable.alpha
            if hasattr(displayable, 'rotate'):
                transform_info['rotate'] = displayable.rotate
                
            # Try to get offset information  
            if hasattr(displayable, 'xoffset'):
                transform_info['xoffset'] = displayable.xoffset
            if hasattr(displayable, 'yoffset'):
                transform_info['yoffset'] = displayable.yoffset
            
            # Try to get the actual rendered size and position from the SLE
            if hasattr(sle, 'x'):
                transform_info['rendered_x'] = sle.x
            if hasattr(sle, 'y'):
                transform_info['rendered_y'] = sle.y
            if hasattr(sle, 'w'):
                transform_info['rendered_width'] = sle.w
            if hasattr(sle, 'h'):
                transform_info['rendered_height'] = sle.h
                
            # Check for transform matrices or complex transforms
            if hasattr(displayable, 'st') and hasattr(displayable, 'at'):
                transform_info['state_time'] = getattr(displayable, 'st', None)
                transform_info['animation_time'] = getattr(displayable, 'at', None)
                
            # Look for child displayables that might have transform info
            if hasattr(displayable, 'child'):
                child = displayable.child
                child_transform = {}
                
                for attr in ['xpos', 'ypos', 'xalign', 'yalign', 'zoom', 'alpha', 'rotate']:
                    if hasattr(child, attr):
                        value = getattr(child, attr)
                        if value is not None:
                            child_transform[f'child_{attr}'] = value
                            
                if child_transform:
                    transform_info.update(child_transform)
            
            # Only add transform_info if we found any properties
            if transform_info:
                image_info['transform'] = transform_info
                
        except Exception:
            # Don't fail the entire operation if we can't get transform info
            pass
            pass

    def _extract_screen_background(self, screen_displayable, screen_info):
        """
        Extract background information from a screen displayable.
        
        Args:
            screen_displayable: The screen displayable object
            screen_info: Dictionary to add background info to
        """
        try:
            background_info = {}
            
            # Check for direct background properties
            if hasattr(screen_displayable, 'background'):
                bg = screen_displayable.background
                if bg:
                    background_info['background'] = str(bg)
            
            # Check if the screen has a child that might be the background
            if hasattr(screen_displayable, 'child'):
                child = screen_displayable.child
                if child:
                    # Look for background in child displayables
                    self._search_displayable_tree_for_images(child, background_info, 'screen_content')
            
            # Check the screen's style for background information
            if hasattr(screen_displayable, 'style'):
                style = screen_displayable.style
                if style and hasattr(style, 'background'):
                    if style.background:
                        background_info['style_background'] = str(style.background)
            
            if background_info:
                screen_info['background_info'] = background_info
                
        except Exception:
            pass

    def _search_displayable_tree_for_images(self, displayable, info_dict, prefix=''):
        """
        Recursively search a displayable tree for image content.
        
        Args:
            displayable: The displayable to search
            info_dict: Dictionary to add findings to
            prefix: Prefix for keys in the info_dict
        """
        try:
            if not displayable:
                return
                
            # Check if this displayable has image-like properties
            displayable_type = type(displayable).__name__
            
            # Look for image displayables
            if 'Image' in displayable_type:
                if hasattr(displayable, 'filename'):
                    info_dict[f'{prefix}_image_file'] = displayable.filename
                elif hasattr(displayable, 'name'):
                    info_dict[f'{prefix}_image_name'] = str(displayable.name)
            
            # Look for background styles
            if hasattr(displayable, 'style') and displayable.style:
                if hasattr(displayable.style, 'background') and displayable.style.background:
                    info_dict[f'{prefix}_background'] = str(displayable.style.background)
            
            # Search children recursively
            if hasattr(displayable, 'children'):
                for i, child in enumerate(displayable.children or []):
                    self._search_displayable_tree_for_images(child, info_dict, f'{prefix}_child_{i}')
            elif hasattr(displayable, 'child') and displayable.child:
                self._search_displayable_tree_for_images(displayable.child, info_dict, f'{prefix}_child')
                
        except Exception:
            pass

    def _extract_screen_content(self, screen_displayable, content_list, depth=0, max_depth=10):
        """
        Extract all visual content from within a screen displayable.
        
        Args:
            screen_displayable: The screen displayable to examine
            content_list: List to append content items to
            depth: Current recursion depth
            max_depth: Maximum recursion depth to prevent infinite loops
        """
        try:
            if depth > max_depth:
                return
                
            if not screen_displayable:
                return
                
            # Get the main child of the screen
            if hasattr(screen_displayable, 'child') and screen_displayable.child:
                self._traverse_displayable_hierarchy(screen_displayable.child, content_list, depth + 1, max_depth)
                
        except Exception:
            pass

    def _traverse_displayable_hierarchy(self, displayable, content_list, depth=0, max_depth=10):
        """
        Recursively traverse a displayable hierarchy to find all visual content.
        
        Args:
            displayable: The displayable to examine
            content_list: List to append found content to
            depth: Current recursion depth
            max_depth: Maximum recursion depth
        """
        try:
            if depth > max_depth or not displayable:
                return
                
            displayable_type = type(displayable).__name__
            content_item = {
                'type': displayable_type,
                'depth': depth
            }
            
            # Check for image-related displayables
            if 'Image' in displayable_type:
                if hasattr(displayable, 'filename'):
                    content_item['filename'] = displayable.filename
                if hasattr(displayable, 'name'):
                    content_item['image_name'] = str(displayable.name)
                if hasattr(displayable, 'image'):
                    content_item['image'] = str(displayable.image)
                content_list.append(content_item)
                
            # Check for text displayables
            elif 'Text' in displayable_type:
                if hasattr(displayable, 'text'):
                    content_item['text'] = str(displayable.text)[:100]  # Limit text length
                content_list.append(content_item)
                
            # Check for background in styles
            if hasattr(displayable, 'style') and displayable.style:
                if hasattr(displayable.style, 'background') and displayable.style.background:
                    content_item['style_background'] = str(displayable.style.background)
                    if 'style_background' in content_item:
                        content_list.append(content_item)
            
            # Check for transform/positioning properties
            transform_props = {}
            for prop in ['xpos', 'ypos', 'xalign', 'yalign', 'zoom', 'alpha', 'rotate']:
                if hasattr(displayable, prop):
                    value = getattr(displayable, prop)
                    if value is not None:
                        transform_props[prop] = value
            
            if transform_props:
                content_item['transform'] = transform_props
                
            # Only add to list if we found meaningful content
            meaningful_keys = ['filename', 'image_name', 'image', 'text', 'style_background', 'transform']
            if any(key in content_item for key in meaningful_keys):
                if content_item not in content_list:  # Avoid duplicates
                    content_list.append(content_item)
            
            # Recursively check children
            if hasattr(displayable, 'children') and displayable.children:
                for child in displayable.children:
                    self._traverse_displayable_hierarchy(child, content_list, depth + 1, max_depth)
            elif hasattr(displayable, 'child') and displayable.child:
                self._traverse_displayable_hierarchy(displayable.child, content_list, depth + 1, max_depth)
                
        except Exception:
            pass

    def _get_detailed_screen_info(self):
        """
        Get detailed information about screen content including backgrounds and visual elements.
        
        Returns:
            list: List of detailed screen information
        """
        try:
            detailed_screens = []

            # Get scene lists
            scene_lists = renpy.exports.scene_lists()
            if not scene_lists or not hasattr(scene_lists, 'layers'):
                return detailed_screens

            # Process screens layer
            if 'screens' in scene_lists.layers:
                screens_layer = scene_lists.layers['screens']
                
                for i, sle in enumerate(screens_layer):
                    screen_detail = self._analyze_screen_sle(sle, i)
                    if screen_detail:
                        detailed_screens.append(screen_detail)
            
            return detailed_screens
            
        except Exception:
            return []

    def _analyze_screen_sle(self, sle, index):
        """
        Analyze a single screen SLE (Scene List Entry) for detailed content.
        
        Args:
            sle: The scene list entry
            index: Index in the layer
            
        Returns:
            dict: Detailed screen information or None
        """
        try:
            if not hasattr(sle, 'displayable'):
                return None
                
            displayable = sle.displayable
            if not hasattr(displayable, 'screen_name'):
                return None
                
            screen_name = displayable.screen_name
            if isinstance(screen_name, tuple):
                screen_name = screen_name[0]
                
            screen_info = {
                'screen_name': screen_name,
                'index': index,
                'type': type(displayable).__name__,
                'visual_elements': []
            }

            # Extract transform properties of the screen itself
            screen_info['transform'] = self._get_transform_properties(displayable, sle)

            # Analyze screen content
            if hasattr(displayable, 'child') and displayable.child:
                screen_info['content_type'] = type(displayable.child).__name__

                # Extract visual elements from the screen's content
                visual_elements = self._extract_visual_elements(displayable.child)
                screen_info['visual_elements'] = visual_elements

            return screen_info

        except Exception:
            return None

    def _extract_visual_elements(self, container):
        """
        Extract visual elements (images, backgrounds, etc.) from a container.
        
        Args:
            container: The container displayable to analyze
            
        Returns:
            list: List of visual element information
        """
        elements = []
        try:
            if hasattr(container, 'children') and container.children:
                for i, child in enumerate(container.children):
                    element = self._analyze_visual_element(child, i)
                    if element:
                        elements.append(element)
            elif hasattr(container, 'child') and container.child:
                element = self._analyze_visual_element(container.child, 0)
                if element:
                    elements.append(element)

        except Exception:
            pass

        return elements

    def _analyze_visual_element(self, element, index):
        """
        Analyze a single visual element.
        
        Args:
            element: The displayable element
            index: Element index
            
        Returns:
            dict: Element information or None
        """
        try:
            element_type = type(element).__name__
            info = {
                'index': index,
                'type': element_type
            }
            
            # Check for image properties
            if 'Image' in element_type:
                if hasattr(element, 'filename'):
                    info['filename'] = element.filename
                if hasattr(element, 'name'):
                    info['name'] = str(element.name)
                if hasattr(element, 'image'):
                    info['image'] = str(element.image)
                    
            # Check for text properties
            elif 'Text' in element_type:
                if hasattr(element, 'text'):
                    info['text'] = str(element.text)[:100]  # Limit length
                    
            # Check for background in style
            if hasattr(element, 'style') and element.style:
                if hasattr(element.style, 'background') and element.style.background:
                    info['style_background'] = str(element.style.background)
                    
            # Get transform properties
            transform = self._get_transform_properties(element)
            if transform:
                info['transform'] = transform
                
            # Only return if we found meaningful content
            meaningful_keys = ['filename', 'name', 'image', 'text', 'style_background']
            if any(key in info for key in meaningful_keys):
                return info
                
            return None
            
        except Exception:
            return None

    def _get_transform_properties(self, displayable, sle=None):
        """
        Extract transform/positioning properties from a displayable.
        
        Args:
            displayable: The displayable to examine
            sle: Optional scene list entry for rendered properties
            
        Returns:
            dict: Transform properties
        """
        transform = {}
        try:
            # Position properties
            for prop in ['xpos', 'ypos', 'xalign', 'yalign', 'xanchor', 'yanchor']:
                if hasattr(displayable, prop):
                    value = getattr(displayable, prop)
                    if value is not None:
                        transform[prop] = value
                        
            # Size properties
            for prop in ['width', 'height', 'xsize', 'ysize']:
                if hasattr(displayable, prop):
                    value = getattr(displayable, prop)
                    if value is not None:
                        transform[prop] = value
                        
            # Visual properties
            for prop in ['zoom', 'alpha', 'rotate']:
                if hasattr(displayable, prop):
                    value = getattr(displayable, prop)
                    if value is not None:
                        transform[prop] = value
                        
            # Offset properties
            for prop in ['xoffset', 'yoffset']:
                if hasattr(displayable, prop):
                    value = getattr(displayable, prop)
                    if value is not None:
                        transform[prop] = value
                        
            # Rendered properties from SLE
            if sle:
                for prop, attr in [('rendered_x', 'x'), ('rendered_y', 'y'), 
                                 ('rendered_width', 'w'), ('rendered_height', 'h')]:
                    if hasattr(sle, attr):
                        value = getattr(sle, attr)
                        if value is not None:
                            transform[prop] = value
                            
        except Exception:
            pass

        return transform

    def _check_widget_enabled(self, widget, action_value):
        """
        Check if a widget is actually enabled/clickable.
        
        Args:
            widget: The widget to check
            action_value: The action associated with the widget
            
        Returns:
            bool: True if the widget is enabled and clickable
        """
        try:
            # Check widget's sensitive attribute (Ren'Py standard)
            if hasattr(widget, 'sensitive') and widget.sensitive is not None:
                if not widget.sensitive:
                    # print(f"[DEBUG] widget not sensitive: {widget.sensitive}")  # Reduce debug output
                    return False
                # else:
                #     print(f"[DEBUG] widget is sensitive: {widget.sensitive}")  # Reduce debug output
            
            # Check if widget is focusable/enabled (only if explicitly set to False)
            if hasattr(widget, 'focusable') and widget.focusable is not None:
                if widget.focusable is False:
                    return False
            
            # Check for disabled/enabled attributes
            for attr in ['enabled', 'disabled']:
                if hasattr(widget, attr):
                    value = getattr(widget, attr)
                    if attr == 'enabled' and not value:
                        return False
                    elif attr == 'disabled' and value:
                        return False
            
            # Check if action is actually callable/valid
            if action_value:
                # Check for Ren'Py action validity using get_sensitive method
                try:
                    if hasattr(action_value, 'get_sensitive'):
                        try:
                            sensitive = action_value.get_sensitive()
                            # print(f"[DEBUG] action.get_sensitive() = {sensitive} for {action_value}")  # Reduce debug output
                            if sensitive is False:  # Explicitly False, not just falsy
                                # print(f"[DEBUG] action not sensitive: {action_value}")  # Reduce debug output
                                return False
                        except Exception as e:
                            # print(f"[DEBUG] error calling get_sensitive(): {e}")  # Reduce debug output
                            # If get_sensitive() fails, assume enabled
                            pass
                            
                except Exception:
                    # If we can't determine, assume it's enabled
                    pass
                    pass
            
            # If we get here and haven't found any reason it's disabled, assume enabled
            return True
            
        except Exception:
            # Default to enabled if we can't determine
            pass
            return True
    
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
    
    def get_ui_interactables(self):
        """
        Get all UI interactables (buttons, clickable elements) using the focus system.
        
        Returns:
            list: List of interactable UI elements with their properties
        """
        try:
            interactables = []
            
            # Method 1: Use focus system to get all focusable elements
            try:
                import renpy.display.focus as focus
                
                # Get current focus list
                if hasattr(focus, 'focus_list') and focus.focus_list:
                    for i, focus_item in enumerate(focus.focus_list):
                        if hasattr(focus_item, 'widget') and focus_item.widget:
                            widget = focus_item.widget
                            widget_info = {
                                'index': i,
                                'type': type(widget).__name__,
                                'focusable': True
                            }
                            
                            # Get bounding box if available
                            if hasattr(focus_item, 'x') and hasattr(focus_item, 'y'):
                                widget_info['bounds'] = {
                                    'x': focus_item.x,
                                    'y': focus_item.y,
                                    'w': getattr(focus_item, 'w', 0),
                                    'h': getattr(focus_item, 'h', 0)
                                }
                            
                            # Get text content
                            text = self._extract_widget_text(widget)
                            if text:
                                widget_info['text'] = text
                            
                            # Get action/click handlers
                            for attr in ['clicked', 'action', 'activate', 'hovered']:
                                if hasattr(widget, attr):
                                    action_value = getattr(widget, attr)
                                    if action_value:
                                        widget_info[attr] = str(action_value)
                                        break
                            
                            # Get screen context if available
                            if hasattr(focus_item, 'screen'):
                                widget_info['screen'] = str(focus_item.screen)
                                
                            interactables.append(widget_info)
                
                # Method 2: Also check renpy.display.screen for active screens
                if hasattr(renpy.display, 'screen'):
                    screen_module = renpy.display.screen
                    if hasattr(screen_module, 'screens'):
                        active_screens = screen_module.screens
                        for screen_name, screen_obj in active_screens.items():
                            # Try to extract widgets from screen
                            screen_widgets = self._extract_screen_widgets(screen_obj, screen_name)
                            interactables.extend(screen_widgets)
                            
            except Exception:
                pass

            # Method 3: Fall back to scene_lists method if focus system didn't work
            if not interactables:
                scene_lists = renpy.exports.scene_lists()
                if scene_lists and hasattr(scene_lists, 'layers'):
                    for layer_name, layer_list in scene_lists.layers.items():
                        if layer_name == 'screens':  # Focus on screens layer
                            for sle in layer_list:
                                if hasattr(sle, 'displayable'):
                                    displayable = sle.displayable
                                    if hasattr(displayable, 'screen_name'):
                                        screen_name = displayable.screen_name
                                        if isinstance(screen_name, tuple):
                                            screen_name = screen_name[0]
                                        screen_widgets = self._extract_screen_widgets_from_displayable(displayable, screen_name)
                                        interactables.extend(screen_widgets)

            return interactables

        except Exception:
            return []
    
    def _extract_screen_widgets(self, screen_obj, screen_name):
        """Extract widgets from a screen object."""
        widgets = []
        try:
            # This would need to be implemented based on the actual screen object structure
            # For now, return empty list as we'll use the displayable method
            pass
        except Exception:
            pass
        return widgets
    
    def _extract_screen_widgets_from_displayable(self, screen_displayable, screen_name):
        """Extract interactive widgets from a screen displayable."""
        widgets = []
        try:
            def traverse_widgets(widget, depth=0):
                widget_type = type(widget).__name__

                # Check if this widget is interactive
                is_interactive = False
                action_info = {}

                for attr in ['clicked', 'action', 'activate', 'hovered']:
                    if hasattr(widget, attr):
                        action_value = getattr(widget, attr)
                        if action_value:
                            is_interactive = True
                            action_info[attr] = str(action_value)
                
                if is_interactive:
                    widget_info = {
                        'type': widget_type,
                        'screen': screen_name,
                        'actions': action_info
                    }
                    
                    # Get text content
                    text = self._extract_widget_text(widget)
                    if text:
                        widget_info['text'] = text
                    
                    # Get enabled/sensitive state
                    if hasattr(widget, 'sensitive'):
                        widget_info['enabled'] = widget.sensitive
                    
                    widgets.append(widget_info)
                
                # Recursively check children
                if hasattr(widget, 'children') and widget.children:
                    for child in widget.children:
                        if child:
                            traverse_widgets(child, depth + 1)
                elif hasattr(widget, 'child') and widget.child:
                    traverse_widgets(widget.child, depth + 1)
            
            # Start traversal from the screen displayable
            if hasattr(screen_displayable, 'child'):
                traverse_widgets(screen_displayable.child)
            elif hasattr(screen_displayable, 'children'):
                for child in screen_displayable.children:
                    if child:
                        traverse_widgets(child)
            else:
                traverse_widgets(screen_displayable)
                
        except Exception:
            pass

        return widgets
