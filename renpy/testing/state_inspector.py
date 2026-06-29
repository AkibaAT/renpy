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
            'available_tags': [],
            'showing_tags': [],
            'available_transforms': [],
            'audio_channels': [],
            'audio_files': {},
            'transitions': [],
            'detailed_screens': []
        }

        try:
            context = renpy.game.context()
            if context and hasattr(context, 'scene_lists'):
                context_scene_lists = context.scene_lists

                if hasattr(context_scene_lists, 'shown') and context_scene_lists.shown:
                    shown = context_scene_lists.shown
                    if hasattr(shown, 'images'):
                        for layer, images in shown.images.items():
                            for tag, image_info in images.items():
                                scene_info['shown_images'].append({
                                    'layer': layer,
                                    'tag': tag,
                                    'name': image_info.get('name', ''),
                                    'zorder': image_info.get('zorder', 0)
                                })

                if hasattr(context_scene_lists, 'layers'):
                    for layer_name, layer_contents in context_scene_lists.layers.items():
                        scene_info['scene_lists'][layer_name] = len(layer_contents)
        except Exception:
            pass

        try:
            scene_lists = renpy.exports.scene_lists()
            if scene_lists and hasattr(scene_lists, 'layers'):
                for layer_name, layer_list in scene_lists.layers.items():
                    scene_info['scene_lists'].setdefault(layer_name, len(layer_list))

                    for sle in layer_list:
                        displayable = getattr(sle, 'displayable', None)
                        if displayable is None:
                            continue

                        screen_name = self._get_screen_name(displayable)
                        if screen_name and screen_name not in scene_info['active_screens']:
                            scene_info['active_screens'].append(screen_name)

                        if hasattr(sle, 'tag') and hasattr(sle, 'name'):
                            image_info = {
                                'tag': sle.tag,
                                'name': sle.name,
                                'layer': layer_name
                            }

                            if hasattr(sle, 'zorder'):
                                image_info['zorder'] = sle.zorder

                            if hasattr(displayable, 'child') and hasattr(displayable.child, 'name'):
                                image_info['image_name'] = str(displayable.child.name)

                            self._extract_display_properties(displayable, sle, image_info)
                            scene_info['shown_images'].append(image_info)
        except Exception:
            pass

        scene_info['audio_info'] = self._get_audio_info()

        try:
            scene_info['detailed_screens'] = self._get_detailed_screen_info()
        except Exception:
            scene_info['detailed_screens'] = []

        try:
            if hasattr(renpy, 'get_available_image_tags'):
                scene_info['available_tags'] = [
                    tag for tag in renpy.get_available_image_tags()
                    if not str(tag).startswith("_")
                ]

            if hasattr(renpy, 'get_showing_tags'):
                scene_info['showing_tags'] = list(renpy.get_showing_tags())
        except Exception:
            pass

        try:
            import store.director as director
            scene_info['available_transforms'] = list(getattr(director, 'transforms', ['left', 'center', 'right']))
            scene_info['transitions'] = list(getattr(director, 'transitions', ['dissolve', 'pixellate']))
            scene_info['audio_channels'] = list(getattr(director, 'audio_channels', ['music', 'sound', 'audio']))
            scene_info['audio_files'] = getattr(director, 'audio_files', {})
        except Exception:
            scene_info['available_transforms'] = ['left', 'center', 'right']
            scene_info['transitions'] = ['dissolve', 'pixellate']
            scene_info['audio_channels'] = ['music', 'sound', 'audio']
            scene_info['audio_files'] = {}

        return scene_info

    def get_image_attributes(self, tag):
        """
        Get available attributes for a specific image tag.

        Args:
            tag (str): The image tag to get attributes for

        Returns:
            list: List of available attributes for the tag
        """
        try:
            if not tag or not hasattr(renpy, 'get_ordered_image_attributes'):
                return []
            return list(renpy.get_ordered_image_attributes(tag, []))
        except Exception:
            return []

    def get_behind_tags(self, exclude_tag=None):
        """
        Get tags that can be used for behind positioning.

        Args:
            exclude_tag (str): Optional tag to exclude from the result

        Returns:
            list: List of currently showing non-background tags
        """
        try:
            if not hasattr(renpy, 'get_showing_tags'):
                return []

            rv = []
            for tag in renpy.get_showing_tags():
                if tag == 'bg' or tag == exclude_tag:
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
        Get available menu and screen choices.

        Returns:
            list: List of available choices.
        """
        try:
            choices = []

            scene_lists = renpy.exports.scene_lists()
            if scene_lists and hasattr(scene_lists, 'layers'):
                for layer_name, layer_list in scene_lists.layers.items():
                    for sle in layer_list:
                        displayable = getattr(sle, 'displayable', None)
                        if displayable is None:
                            continue

                        screen_name = self._get_screen_name(displayable)
                        if not screen_name:
                            continue

                        if hasattr(displayable, 'scope') and 'items' in displayable.scope:
                            for item in displayable.scope.get('items') or []:
                                if not hasattr(item, 'caption') or not hasattr(item, 'action'):
                                    continue

                                action_value = getattr(item, 'action')
                                choices.append({
                                    'label': str(item.caption),
                                    'action': str(action_value),
                                    'screen': screen_name,
                                    'layer': layer_name,
                                    'type': type(item).__name__,
                                    'action_attr': 'action',
                                    'enabled': self._check_widget_enabled(item, action_value)
                                })

                        if hasattr(displayable, 'child'):
                            choices.extend(self._extract_screen_choices(displayable, screen_name, layer_name))

            return self._dedupe_choices(choices)
        except Exception:
            return []

    def _extract_screen_choices(self, screen_displayable, screen_name, layer_name=None):
        """
        Extract choices from a screen's widget tree.
        """
        choices = []
        try:
            def find_buttons(widget):
                found = []
                if widget is None:
                    return found

                widget_type = type(widget).__name__
                action_attr = None
                action_value = None

                for attr in ['clicked', 'action', 'activate', 'hovered']:
                    if hasattr(widget, attr):
                        value = getattr(widget, attr)
                        if value:
                            action_attr = attr
                            action_value = value
                            break

                text = self._extract_widget_text(widget)

                if text and action_attr:
                    found.append({
                        'label': text,
                        'action': str(action_value),
                        'screen': screen_name,
                        'layer': layer_name,
                        'type': widget_type,
                        'action_attr': action_attr,
                        'enabled': self._check_widget_enabled(widget, action_value),
                        'sensitive': getattr(widget, 'sensitive', None),
                        'selected': getattr(widget, 'selected', None)
                    })

                elif text and self._is_button_like(widget):
                    found.append({
                        'label': text,
                        'action': 'none',
                        'screen': screen_name,
                        'layer': layer_name,
                        'type': widget_type,
                        'action_attr': 'detected_by_type',
                        'enabled': self._check_widget_enabled(widget, None),
                        'sensitive': getattr(widget, 'sensitive', None),
                        'selected': getattr(widget, 'selected', None)
                    })

                if hasattr(widget, 'children') and widget.children:
                    for child in widget.children:
                        found.extend(find_buttons(child))
                elif hasattr(widget, 'child') and widget.child:
                    found.extend(find_buttons(widget.child))

                return found

            if getattr(screen_displayable, 'child', None):
                choices = find_buttons(screen_displayable.child)

        except Exception:
            pass

        return choices

    def _extract_widget_text(self, widget):
        """
        Extract text from a widget using common Ren'Py displayable shapes.
        """
        try:
            text = None

            if hasattr(widget, 'children') and widget.children:
                for child in widget.children:
                    text = self._extract_widget_text(child)
                    if text:
                        break

            if not text and hasattr(widget, 'text') and widget.text:
                text = widget.text

            if not text and hasattr(widget, 'child') and widget.child:
                text = self._extract_widget_text(widget.child)

            if not text:
                for attr in ['label', 'caption', 'title', 'name']:
                    if hasattr(widget, attr):
                        value = getattr(widget, attr)
                        if value:
                            text = value
                            break

            if isinstance(text, (list, tuple)) and text:
                text = text[0]

            if text is not None:
                text = str(text).strip()
                if text:
                    return text

        except Exception:
            pass

        return None

    def _check_widget_enabled(self, widget, action_value):
        """
        Check if a widget/action appears sensitive enough to invoke.
        """
        try:
            if hasattr(widget, 'sensitive') and widget.sensitive is not None and not widget.sensitive:
                return False

            if getattr(widget, 'focusable', None) is False:
                return False

            if hasattr(widget, 'enabled') and not getattr(widget, 'enabled'):
                return False

            if hasattr(widget, 'disabled') and getattr(widget, 'disabled'):
                return False

            if action_value and hasattr(action_value, 'get_sensitive'):
                try:
                    if action_value.get_sensitive() is False:
                        return False
                except Exception:
                    pass

            return True
        except Exception:
            return True

    def _dedupe_choices(self, choices):
        rv = []
        seen = set()

        for choice in choices:
            key = (
                choice.get('screen'),
                choice.get('label'),
                choice.get('action'),
                choice.get('type')
            )
            if key in seen:
                continue

            choice['index'] = len(rv)
            seen.add(key)
            rv.append(choice)

        return rv

    def get_ui_interactables(self):
        """
        Get all UI interactables (buttons, clickable elements).

        Returns:
            list: List of interactable UI elements with their properties
        """
        try:
            interactables = []

            try:
                import renpy.display.focus as focus

                for i, focus_item in enumerate(getattr(focus, 'focus_list', []) or []):
                    widget = getattr(focus_item, 'widget', None)
                    if widget is None:
                        continue

                    widget_info = {
                        'index': i,
                        'type': type(widget).__name__,
                        'focusable': True
                    }

                    if hasattr(focus_item, 'x') and hasattr(focus_item, 'y'):
                        widget_info['bounds'] = {
                            'x': focus_item.x,
                            'y': focus_item.y,
                            'w': getattr(focus_item, 'w', 0),
                            'h': getattr(focus_item, 'h', 0)
                        }

                    text = self._extract_widget_text(widget)
                    if text:
                        widget_info['text'] = text

                    for attr in ['clicked', 'action', 'activate', 'hovered']:
                        if hasattr(widget, attr):
                            action_value = getattr(widget, attr)
                            if action_value:
                                widget_info[attr] = str(action_value)
                                widget_info['enabled'] = self._check_widget_enabled(widget, action_value)
                                break

                    if hasattr(focus_item, 'screen'):
                        widget_info['screen'] = str(focus_item.screen)

                    interactables.append(widget_info)
            except Exception:
                pass

            if not interactables:
                scene_lists = renpy.exports.scene_lists()
                if scene_lists and hasattr(scene_lists, 'layers'):
                    for layer_name, layer_list in scene_lists.layers.items():
                        for sle in layer_list:
                            displayable = getattr(sle, 'displayable', None)
                            if displayable is None:
                                continue

                            screen_name = self._get_screen_name(displayable)
                            if not screen_name:
                                continue

                            interactables.extend(
                                self._extract_screen_widgets_from_displayable(displayable, screen_name, layer_name)
                            )

            return self._dedupe_interactables(interactables)
        except Exception:
            return []

    def get_interactables(self):
        """Alias for external tools that use the shorter name."""
        return self.get_ui_interactables()

    def _extract_screen_widgets_from_displayable(self, screen_displayable, screen_name, layer_name=None):
        widgets = []

        try:
            def traverse_widgets(widget, depth=0):
                action_info = {}

                for attr in ['clicked', 'action', 'activate', 'hovered']:
                    if hasattr(widget, attr):
                        action_value = getattr(widget, attr)
                        if action_value:
                            action_info[attr] = str(action_value)

                if action_info:
                    widget_info = {
                        'type': type(widget).__name__,
                        'screen': screen_name,
                        'layer': layer_name,
                        'actions': action_info,
                        'enabled': self._check_widget_enabled(widget, None)
                    }

                    text = self._extract_widget_text(widget)
                    if text:
                        widget_info['text'] = text

                    widgets.append(widget_info)

                if hasattr(widget, 'children') and widget.children:
                    for child in widget.children:
                        if child:
                            traverse_widgets(child, depth + 1)
                elif hasattr(widget, 'child') and widget.child:
                    traverse_widgets(widget.child, depth + 1)

            if hasattr(screen_displayable, 'child') and screen_displayable.child:
                traverse_widgets(screen_displayable.child)
            elif hasattr(screen_displayable, 'children') and screen_displayable.children:
                for child in screen_displayable.children:
                    if child:
                        traverse_widgets(child)
            else:
                traverse_widgets(screen_displayable)
        except Exception:
            pass

        return widgets

    def _dedupe_interactables(self, interactables):
        rv = []
        seen = set()

        for item in interactables:
            key = (
                item.get('screen'),
                item.get('text'),
                item.get('type'),
                str(item.get('actions') or item.get('clicked') or item.get('action') or item.get('activate'))
            )
            if key in seen:
                continue

            item['index'] = len(rv)
            seen.add(key)
            rv.append(item)

        return rv

    def _is_button_like(self, widget):
        widget_type = type(widget).__name__.lower()
        return any(indicator in widget_type for indicator in ['button', 'textbutton', 'imagebutton', 'hotspot', 'choice'])

    def _extract_display_properties(self, displayable, sle, image_info):
        """
        Extract positioning, sizing, and transform information from a displayable.
        """
        transform_info = self._get_transform_properties(displayable, sle)

        try:
            child = getattr(displayable, 'child', None)
            if child is not None:
                for attr in ['xpos', 'ypos', 'xalign', 'yalign', 'zoom', 'alpha', 'rotate']:
                    if hasattr(child, attr):
                        value = getattr(child, attr)
                        if value is not None:
                            transform_info['child_' + attr] = value
        except Exception:
            pass

        if transform_info:
            image_info['transform'] = transform_info

    def _get_transform_properties(self, displayable, sle=None):
        """
        Extract transform/positioning properties from a displayable.
        """
        transform = {}

        try:
            for prop in ['xpos', 'ypos', 'xalign', 'yalign', 'xanchor', 'yanchor',
                         'width', 'height', 'xsize', 'ysize', 'zoom', 'alpha',
                         'rotate', 'xoffset', 'yoffset']:
                if hasattr(displayable, prop):
                    value = getattr(displayable, prop)
                    if value is not None:
                        transform[prop] = value

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

    def _get_detailed_screen_info(self):
        """
        Get screen content details for external visual tools.
        """
        detailed_screens = []

        try:
            scene_lists = renpy.exports.scene_lists()
            if not scene_lists or not hasattr(scene_lists, 'layers'):
                return detailed_screens

            for layer_name, layer_list in scene_lists.layers.items():
                for i, sle in enumerate(layer_list):
                    screen_detail = self._analyze_screen_sle(sle, i, layer_name)
                    if screen_detail:
                        detailed_screens.append(screen_detail)
        except Exception:
            pass

        return detailed_screens

    def _analyze_screen_sle(self, sle, index, layer_name=None):
        try:
            displayable = getattr(sle, 'displayable', None)
            if displayable is None:
                return None

            screen_name = self._get_screen_name(displayable)
            if not screen_name:
                return None

            screen_info = {
                'screen_name': screen_name,
                'layer': layer_name,
                'index': index,
                'type': type(displayable).__name__,
                'transform': self._get_transform_properties(displayable, sle),
                'visual_elements': []
            }

            if hasattr(displayable, 'child') and displayable.child:
                screen_info['content_type'] = type(displayable.child).__name__
                screen_info['visual_elements'] = self._extract_visual_elements(displayable.child)

            return screen_info
        except Exception:
            return None

    def _extract_visual_elements(self, container):
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
        try:
            element_type = type(element).__name__
            info = {
                'index': index,
                'type': element_type
            }

            if 'Image' in element_type:
                if hasattr(element, 'filename'):
                    info['filename'] = element.filename
                if hasattr(element, 'name'):
                    info['name'] = str(element.name)
                if hasattr(element, 'image'):
                    info['image'] = str(element.image)

            elif 'Text' in element_type and hasattr(element, 'text'):
                info['text'] = str(element.text)[:100]

            if hasattr(element, 'style') and element.style:
                background = getattr(element.style, 'background', None)
                if background:
                    info['style_background'] = str(background)

            transform = self._get_transform_properties(element)
            if transform:
                info['transform'] = transform

            meaningful_keys = ['filename', 'name', 'image', 'text', 'style_background']
            if any(key in info for key in meaningful_keys):
                return info
        except Exception:
            pass

        return None

    def _get_audio_info(self):
        audio_info = {
            'music': None,
            'sound': [],
            'voice': None
        }

        for channel in ['music', 'sound', 'voice']:
            try:
                playing = None
                if hasattr(renpy, 'music'):
                    playing = renpy.music.get_playing(channel=channel)
                elif hasattr(renpy, 'audio') and hasattr(renpy.audio, 'music'):
                    playing = renpy.audio.music.get_playing(channel=channel)

                if not playing:
                    continue

                entry = {
                    'filename': playing,
                    'channel': channel
                }

                if channel == 'sound':
                    audio_info['sound'].append(entry)
                else:
                    audio_info[channel] = entry
            except Exception:
                pass

        return audio_info

    def _get_screen_name(self, displayable):
        try:
            screen_name = getattr(displayable, 'screen_name', None)
            if isinstance(screen_name, tuple):
                screen_name = screen_name[0]
            return screen_name
        except Exception:
            return None
    
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
