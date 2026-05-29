# Copyright 2004-2025 Tom Rothamel <pytom@bishoujo.us>
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
Layered Image Inspector for Ren'Py Debugger.

This module provides APIs to inspect and manipulate layered images,
enabling IDE visualization and debugging of:
- Available layered images and their structure
- Current attribute states
- Layer visibility and conditions
- Live attribute toggling
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class LayerInfo:
    """Information about a single layer in a layered image."""
    name: str
    layer_type: str  # "always", "group", "attribute", "condition", "if"
    is_visible: bool
    is_default: bool
    conditions: List[str]  # Conditions that control visibility
    attributes: List[str]  # Attributes this layer responds to
    image_name: Optional[str]  # The actual image displayable
    transform: Optional[str]  # Applied transform name
    children: List["LayerInfo"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "layerType": self.layer_type,
            "isVisible": self.is_visible,
            "isDefault": self.is_default,
            "conditions": self.conditions,
            "attributes": self.attributes,
            "imageName": self.image_name,
            "transform": self.transform,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class AttributeInfo:
    """Information about an attribute in a layered image."""
    name: str
    group: Optional[str]
    is_active: bool
    is_default: bool
    conflicts_with: List[str]  # Other attributes in the same group

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "group": self.group,
            "isActive": self.is_active,
            "isDefault": self.is_default,
            "conflictsWith": self.conflicts_with,
        }


@dataclass
class LayeredImageInfo:
    """Complete information about a layered image."""
    name: str
    image_name: Tuple[str, ...]  # The full image name tuple
    attributes: List[AttributeInfo]
    groups: Dict[str, List[str]]  # group_name -> list of attribute names
    layers: List[LayerInfo]
    current_attributes: Set[str]  # Currently active attributes
    definition_file: Optional[str]
    definition_line: Optional[int]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "imageName": list(self.image_name),
            "attributes": [a.to_dict() for a in self.attributes],
            "groups": self.groups,
            "layers": [l.to_dict() for l in self.layers],
            "currentAttributes": list(self.current_attributes),
            "definitionFile": self.definition_file,
            "definitionLine": self.definition_line,
        }


class LayeredImageInspector:
    """
    Provides inspection and manipulation of Ren'Py layered images.
    """

    def __init__(self):
        self._preview_overrides: Dict[str, Set[str]] = {}  # image_name -> set of forced attributes

    def get_layered_images(self) -> List[Dict[str, Any]]:
        """
        Get a list of all defined layered images.

        Returns:
            List of dicts with name, attribute count, and definition location.
        """
        try:
            import renpy

            if not hasattr(renpy, 'display') or not hasattr(renpy.display, 'image'):
                return []

            images = renpy.display.image.images
            layered_images = []

            for name, displayable in images.items():
                if self._is_layered_image(displayable):
                    info = self._get_basic_info(name, displayable)
                    if info:
                        layered_images.append(info)

            return sorted(layered_images, key=lambda x: x.get("name", ""))

        except Exception as e:
            print(f"[DAP] Error getting layered images: {e}")
            return []

    def _is_layered_image(self, displayable) -> bool:
        """Check if a displayable is a layered image."""
        try:
            import renpy
            if hasattr(renpy, 'layeredimage'):
                return isinstance(displayable, renpy.layeredimage.LayeredImage)
            return False
        except Exception:
            return False

    def _get_basic_info(self, name: Tuple[str, ...], displayable) -> Optional[dict]:
        """Get basic info about a layered image for listing."""
        try:
            # Count attributes
            attributes = self._extract_attributes(displayable)

            return {
                "name": " ".join(name),
                "imageName": list(name),
                "attributeCount": len(attributes),
                "groupCount": len(self._extract_groups(displayable)),
            }
        except Exception:
            return None

    def get_layered_image_details(self, image_name: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific layered image.

        Args:
            image_name: The image name (space-separated string or tuple).

        Returns:
            Detailed layered image info or None if not found.
        """
        try:
            import renpy

            # Parse image name
            if isinstance(image_name, str):
                name_tuple = tuple(image_name.split())
            else:
                name_tuple = tuple(image_name)

            # Find the image
            images = renpy.display.image.images
            displayable = images.get(name_tuple)

            if not displayable or not self._is_layered_image(displayable):
                # Try just the first part (base name)
                for key, disp in images.items():
                    if key[0] == name_tuple[0] and self._is_layered_image(disp):
                        displayable = disp
                        name_tuple = key
                        break

            if not displayable:
                return None

            # Extract full info
            info = self._extract_full_info(name_tuple, displayable)
            return info.to_dict() if info else None

        except Exception as e:
            print(f"[DAP] Error getting layered image details: {e}")
            return None

    def _extract_full_info(self, name: Tuple[str, ...], displayable) -> Optional[LayeredImageInfo]:
        """Extract complete information from a layered image."""
        try:
            attributes = self._extract_attributes(displayable)
            groups = self._extract_groups(displayable)
            layers = self._extract_layers(displayable)
            current = self._get_current_attributes(name, displayable)

            # Get definition location
            def_file = getattr(displayable, 'filename', None)
            def_line = getattr(displayable, 'linenumber', None)

            # Build attribute info list
            attr_infos = []
            for attr_name in attributes:
                group = None
                conflicts = []
                is_default = False

                # Find which group this attribute belongs to
                for g_name, g_attrs in groups.items():
                    if attr_name in g_attrs:
                        group = g_name
                        conflicts = [a for a in g_attrs if a != attr_name]
                        # First attribute in group is often default
                        is_default = g_attrs[0] == attr_name
                        break

                attr_infos.append(AttributeInfo(
                    name=attr_name,
                    group=group,
                    is_active=attr_name in current,
                    is_default=is_default,
                    conflicts_with=conflicts,
                ))

            return LayeredImageInfo(
                name=" ".join(name),
                image_name=name,
                attributes=attr_infos,
                groups=groups,
                layers=layers,
                current_attributes=current,
                definition_file=def_file,
                definition_line=def_line,
            )

        except Exception as e:
            print(f"[DAP] Error extracting layered image info: {e}")
            return None

    def _extract_attributes(self, displayable) -> List[str]:
        """Extract all attribute names from a layered image."""
        attributes = set()
        try:
            if hasattr(displayable, 'attributes'):
                # attributes is a dict mapping attribute name to layer info
                for attr in displayable.attributes.keys():
                    if isinstance(attr, str):
                        attributes.add(attr)

            # Also check the layers for attribute references
            if hasattr(displayable, 'layers'):
                for layer in displayable.layers:
                    attrs = self._get_layer_attributes(layer)
                    attributes.update(attrs)

        except Exception:
            pass

        return sorted(list(attributes))

    def _get_layer_attributes(self, layer) -> Set[str]:
        """Get attributes referenced by a layer."""
        attributes = set()
        try:
            layer_type = type(layer).__name__

            if layer_type == 'Attribute':
                if hasattr(layer, 'attribute'):
                    attributes.add(layer.attribute)

            elif layer_type == 'ConditionGroup':
                if hasattr(layer, 'conditions'):
                    for cond in layer.conditions:
                        if hasattr(cond, 'layers'):
                            for sublayer in cond.layers:
                                attributes.update(self._get_layer_attributes(sublayer))

            elif hasattr(layer, 'layers'):
                for sublayer in layer.layers:
                    attributes.update(self._get_layer_attributes(sublayer))

        except Exception:
            pass

        return attributes

    def _extract_groups(self, displayable) -> Dict[str, List[str]]:
        """Extract attribute groups from a layered image."""
        groups = {}
        try:
            if hasattr(displayable, 'attribute_to_groups'):
                # Reverse mapping: build group -> [attributes]
                attr_to_group = displayable.attribute_to_groups
                for attr, group_name in attr_to_group.items():
                    if group_name not in groups:
                        groups[group_name] = []
                    if attr not in groups[group_name]:
                        groups[group_name].append(attr)

            elif hasattr(displayable, 'groups'):
                # Direct group mapping
                for group_name, attrs in displayable.groups.items():
                    groups[group_name] = list(attrs) if attrs else []

        except Exception:
            pass

        return groups

    def _extract_layers(self, displayable) -> List[LayerInfo]:
        """Extract layer structure from a layered image."""
        layers = []
        try:
            if hasattr(displayable, 'layers'):
                for layer in displayable.layers:
                    layer_info = self._parse_layer(layer)
                    if layer_info:
                        layers.append(layer_info)
        except Exception:
            pass

        return layers

    def _parse_layer(self, layer) -> Optional[LayerInfo]:
        """Parse a single layer into LayerInfo."""
        try:
            layer_type = type(layer).__name__
            name = getattr(layer, 'name', None) or layer_type
            is_visible = True
            is_default = getattr(layer, 'default', False)
            conditions = []
            attributes = []
            image_name = None
            transform = None
            children = []

            if layer_type == 'Always':
                layer_type_str = "always"
                if hasattr(layer, 'displayable'):
                    image_name = self._get_displayable_name(layer.displayable)

            elif layer_type == 'Attribute':
                layer_type_str = "attribute"
                if hasattr(layer, 'attribute'):
                    attributes = [layer.attribute]
                    name = layer.attribute
                if hasattr(layer, 'displayable'):
                    image_name = self._get_displayable_name(layer.displayable)
                is_default = getattr(layer, 'default', False)

            elif layer_type == 'ConditionGroup' or layer_type == 'Condition':
                layer_type_str = "condition"
                if hasattr(layer, 'condition'):
                    conditions = [str(layer.condition)]
                if hasattr(layer, 'conditions'):
                    for cond in layer.conditions:
                        child = self._parse_layer(cond)
                        if child:
                            children.append(child)

            elif layer_type == 'Group':
                layer_type_str = "group"
                if hasattr(layer, 'group'):
                    name = layer.group
                if hasattr(layer, 'layers'):
                    for sublayer in layer.layers:
                        child = self._parse_layer(sublayer)
                        if child:
                            children.append(child)

            elif layer_type == 'If':
                layer_type_str = "if"
                if hasattr(layer, 'condition'):
                    conditions = [str(layer.condition)]
                if hasattr(layer, 'layers'):
                    for sublayer in layer.layers:
                        child = self._parse_layer(sublayer)
                        if child:
                            children.append(child)

            else:
                layer_type_str = layer_type.lower()

            # Get transform if present
            if hasattr(layer, 'transform') and layer.transform:
                transform = str(layer.transform)

            return LayerInfo(
                name=name,
                layer_type=layer_type_str,
                is_visible=is_visible,
                is_default=is_default,
                conditions=conditions,
                attributes=attributes,
                image_name=image_name,
                transform=transform,
                children=children,
            )

        except Exception as e:
            print(f"[DAP] Error parsing layer: {e}")
            return None

    def _get_displayable_name(self, displayable) -> Optional[str]:
        """Get a string representation of a displayable."""
        try:
            if displayable is None:
                return None
            if isinstance(displayable, str):
                return displayable
            if hasattr(displayable, 'name'):
                name = displayable.name
                if isinstance(name, tuple):
                    return " ".join(name)
                return str(name)
            return type(displayable).__name__
        except Exception:
            return None

    def _get_current_attributes(self, name: Tuple[str, ...], displayable) -> Set[str]:
        """Get currently active attributes for an image shown on screen."""
        current = set()
        try:
            import renpy

            # Check what's currently shown with this image
            # The additional parts of the name after the base are often attributes
            if len(name) > 1:
                current.update(name[1:])

            # Check the scene for active instances
            if hasattr(renpy, 'game') and hasattr(renpy.game, 'context'):
                ctx = renpy.game.context()
                if ctx and hasattr(ctx, 'scene_lists'):
                    scene_lists = ctx.scene_lists
                    if scene_lists:
                        # Check each layer for images with this base name
                        for layer_name in scene_lists.layers:
                            layer = scene_lists.layers.get(layer_name)
                            if layer and hasattr(layer, 'shown'):
                                for tag, shown in layer.shown.items():
                                    if tag == name[0]:
                                        # Get the full name being shown
                                        if hasattr(shown, 'name') and isinstance(shown.name, tuple):
                                            current.update(shown.name[1:])

        except Exception:
            pass

        return current

    def get_shown_layered_images(self) -> List[Dict[str, Any]]:
        """
        Get layered images currently shown on screen.

        Returns:
            List of currently displayed layered images with their active attributes.
        """
        try:
            import renpy

            shown = []

            if not hasattr(renpy, 'game') or not hasattr(renpy.game, 'context'):
                return shown

            ctx = renpy.game.context()
            if not ctx or not hasattr(ctx, 'scene_lists'):
                return shown

            scene_lists = ctx.scene_lists
            if not scene_lists:
                return shown

            images = renpy.display.image.images

            for layer_name in scene_lists.layers:
                layer = scene_lists.layers.get(layer_name)
                if not layer or not hasattr(layer, 'shown'):
                    continue

                for tag, (name, zorder, show_time) in layer.shown.items():
                    # Check if the base image is a layered image
                    base_name = (tag,) if isinstance(tag, str) else tag
                    displayable = images.get(base_name)

                    if displayable and self._is_layered_image(displayable):
                        # Get full shown name to extract attributes
                        full_name = name if isinstance(name, tuple) else (name,)
                        active_attrs = list(full_name[1:]) if len(full_name) > 1 else []

                        shown.append({
                            "tag": tag,
                            "layer": layer_name,
                            "baseName": " ".join(base_name),
                            "fullName": " ".join(full_name),
                            "activeAttributes": active_attrs,
                            "zorder": zorder,
                        })

            return shown

        except Exception as e:
            print(f"[DAP] Error getting shown layered images: {e}")
            return []

    def set_attribute(self, image_tag: str, attribute: str, enabled: bool) -> bool:
        """
        Toggle an attribute on a shown layered image.

        Args:
            image_tag: The tag of the shown image.
            attribute: The attribute to toggle.
            enabled: Whether to enable or disable the attribute.

        Returns:
            True if successful.
        """
        try:
            import renpy

            # Get current shown state
            ctx = renpy.game.context()
            if not ctx or not hasattr(ctx, 'scene_lists'):
                return False

            scene_lists = ctx.scene_lists

            # Find the image
            for layer_name in scene_lists.layers:
                layer = scene_lists.layers.get(layer_name)
                if not layer or not hasattr(layer, 'shown') or image_tag not in layer.shown:
                    continue

                name, zorder, show_time = layer.shown[image_tag]
                full_name = name if isinstance(name, tuple) else (name,)

                # Modify attributes
                current_attrs = set(full_name[1:]) if len(full_name) > 1 else set()

                if enabled:
                    current_attrs.add(attribute)
                else:
                    current_attrs.discard(attribute)

                # Build new name
                new_name = (full_name[0],) + tuple(sorted(current_attrs))

                # Update the shown image using renpy.show
                renpy.exports.show(
                    " ".join(new_name),
                    layer=layer_name,
                    zorder=zorder,
                )

                return True

            return False

        except Exception as e:
            print(f"[DAP] Error setting attribute: {e}")
            return False

    def preview_attributes(self, image_name: str, attributes: List[str]) -> bool:
        """
        Show a layered image with specific attributes for preview.

        Args:
            image_name: Base name of the layered image.
            attributes: List of attributes to show.

        Returns:
            True if successful.
        """
        try:
            import renpy

            # Build full image name
            parts = image_name.split() + attributes
            full_name = " ".join(parts)

            # Show on master layer
            renpy.exports.show(full_name)
            return True

        except Exception as e:
            print(f"[DAP] Error previewing attributes: {e}")
            return False


# Global instance
_inspector: Optional[LayeredImageInspector] = None


def get_inspector() -> LayeredImageInspector:
    """Get the global layered image inspector instance."""
    global _inspector
    if _inspector is None:
        _inspector = LayeredImageInspector()
    return _inspector
