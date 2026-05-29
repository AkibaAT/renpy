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
Save File Inspector for Ren'Py Debugger.

This module provides APIs to inspect and compare save files,
enabling IDE visualization of:
- List of save files with metadata
- Save file contents (variables, execution position)
- Comparison between saves to see what changed
- Persistent data across saves
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SaveSlotInfo:
    """Basic information about a save slot."""
    slot_name: str
    slot_number: Optional[int]
    is_auto: bool
    is_quick: bool
    timestamp: float
    formatted_time: str
    screenshot_path: Optional[str]
    save_name: Optional[str]  # User-provided save name
    current_label: Optional[str]
    playtime: Optional[str]

    def to_dict(self) -> dict:
        return {
            "slotName": self.slot_name,
            "slotNumber": self.slot_number,
            "isAuto": self.is_auto,
            "isQuick": self.is_quick,
            "timestamp": self.timestamp,
            "formattedTime": self.formatted_time,
            "screenshotPath": self.screenshot_path,
            "saveName": self.save_name,
            "currentLabel": self.current_label,
            "playtime": self.playtime,
        }


@dataclass
class SaveVariable:
    """A variable stored in a save file."""
    name: str
    store: str
    value: Any
    value_repr: str
    value_type: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "store": self.store,
            "value": self.value_repr,
            "valueType": self.value_type,
        }


@dataclass
class RollbackEntry:
    """A rollback entry from a save file."""
    index: int
    is_hard_checkpoint: bool
    filename: Optional[str]
    line: int
    statement_text: Optional[str]

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "isHardCheckpoint": self.is_hard_checkpoint,
            "filename": self.filename,
            "line": self.line,
            "statementText": self.statement_text,
        }


@dataclass
class SaveDetails:
    """Detailed contents of a save file."""
    slot_info: SaveSlotInfo
    variables: List[SaveVariable]
    current_node: Optional[str]
    current_label: Optional[str]
    return_stack: List[str]
    rollback_count: int
    rollback_history: List[RollbackEntry]
    game_version: Optional[str]
    renpy_version: Optional[str]

    def to_dict(self) -> dict:
        return {
            "slotInfo": self.slot_info.to_dict(),
            "variables": [v.to_dict() for v in self.variables],
            "currentNode": self.current_node,
            "currentLabel": self.current_label,
            "returnStack": self.return_stack,
            "rollbackCount": self.rollback_count,
            "rollbackHistory": [r.to_dict() for r in self.rollback_history],
            "gameVersion": self.game_version,
            "renpyVersion": self.renpy_version,
        }


@dataclass
class SaveComparison:
    """Comparison between two saves."""
    slot_a: str
    slot_b: str
    added_variables: List[SaveVariable]
    removed_variables: List[SaveVariable]
    changed_variables: List[Dict[str, Any]]  # {name, store, oldValue, newValue}
    position_changed: bool
    old_position: Optional[str]
    new_position: Optional[str]

    def to_dict(self) -> dict:
        return {
            "slotA": self.slot_a,
            "slotB": self.slot_b,
            "addedVariables": [v.to_dict() for v in self.added_variables],
            "removedVariables": [v.to_dict() for v in self.removed_variables],
            "changedVariables": self.changed_variables,
            "positionChanged": self.position_changed,
            "oldPosition": self.old_position,
            "newPosition": self.new_position,
        }


class SaveInspector:
    """
    Provides inspection and comparison of Ren'Py save files.
    """

    def __init__(self):
        self._cache: Dict[str, SaveDetails] = {}
        self._cache_time: Dict[str, float] = {}

    def list_saves(self) -> List[Dict[str, Any]]:
        """
        Get a list of all save files.

        Returns:
            List of SaveSlotInfo dicts.
        """
        try:
            import renpy

            saves = []

            # Use Ren'Py's built-in list_slots() function
            # This returns all non-empty save slots
            if hasattr(renpy.loadsave, 'list_slots'):
                slots = renpy.loadsave.list_slots()

                for slot_name in slots:
                    try:
                        info = self._get_slot_info(slot_name)
                        if info:
                            saves.append(info.to_dict())
                    except Exception:
                        continue

            # Sort by timestamp, newest first
            saves.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            return saves

        except Exception:
            return []

    def _get_slot_info(self, slot_name: str) -> Optional[SaveSlotInfo]:
        """Get basic info about a save slot."""
        try:
            import renpy

            # Check if slot exists
            if not renpy.loadsave.can_load(slot_name):
                return None

            # Get save json (metadata)
            json_data = renpy.loadsave.slot_json(slot_name)
            if not json_data:
                json_data = {}

            # Determine slot type
            is_auto = slot_name.startswith('auto')
            is_quick = slot_name.startswith('quick')

            # Extract slot number if present
            slot_number = None
            for prefix in ['auto-', 'quick-', '']:
                if slot_name.startswith(prefix):
                    try:
                        slot_number = int(slot_name[len(prefix):])
                    except ValueError:
                        pass
                    break

            # Get timestamp
            mtime = renpy.loadsave.slot_mtime(slot_name)
            if mtime:
                formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
            else:
                mtime = 0
                formatted_time = "Unknown"

            # Get screenshot path
            screenshot = renpy.loadsave.slot_screenshot(slot_name)
            screenshot_path = None
            if screenshot and hasattr(screenshot, 'filename'):
                screenshot_path = screenshot.filename

            # Get other metadata
            save_name = json_data.get('_save_name')
            current_label = json_data.get('_current_label')
            playtime = json_data.get('_playtime')

            return SaveSlotInfo(
                slot_name=slot_name,
                slot_number=slot_number,
                is_auto=is_auto,
                is_quick=is_quick,
                timestamp=mtime or 0,
                formatted_time=formatted_time,
                screenshot_path=screenshot_path,
                save_name=save_name,
                current_label=current_label,
                playtime=playtime,
            )

        except Exception as e:
            print(f"[DAP] Error getting slot info for {slot_name}: {e}")
            return None

    def get_save_details(self, slot_name: str, use_cache: bool = True) -> Optional[Dict[str, Any]]:
        """
        Get detailed contents of a save file.

        Args:
            slot_name: The save slot name.
            use_cache: Whether to use cached data.

        Returns:
            SaveDetails dict or None if not found.
        """
        try:
            import renpy

            # Check cache
            if use_cache and slot_name in self._cache:
                cache_age = time.time() - self._cache_time.get(slot_name, 0)
                if cache_age < 5.0:  # 5 second cache
                    return self._cache[slot_name].to_dict()

            # Load the save data without restoring game state
            save_data = self._load_save_data(slot_name)
            if not save_data:
                return None

            # Get slot info
            slot_info = self._get_slot_info(slot_name)
            if not slot_info:
                return None

            # Extract variables
            variables = self._extract_variables(save_data)

            # Extract position info
            current_node = None
            current_label = None
            return_stack = []

            if 'context' in save_data:
                ctx = save_data['context']
                current_node = ctx.get('current')
                return_stack = [str(r) for r in ctx.get('return_stack', [])]
                # Try to get label from return stack
                for entry in return_stack:
                    if isinstance(entry, str) and not entry.startswith('_'):
                        current_label = entry
                        break

            # Get rollback info
            log_entries = save_data.get('log', [])
            rollback_count = len(log_entries)
            rollback_history = self._extract_rollback_history(log_entries)

            # Get versions
            game_version = save_data.get('_version')
            renpy_version = save_data.get('_renpy_version')

            details = SaveDetails(
                slot_info=slot_info,
                variables=variables,
                current_node=current_node,
                current_label=current_label,
                return_stack=return_stack,
                rollback_count=rollback_count,
                rollback_history=rollback_history,
                game_version=game_version,
                renpy_version=renpy_version,
            )

            # Cache
            self._cache[slot_name] = details
            self._cache_time[slot_name] = time.time()

            return details.to_dict()

        except Exception as e:
            print(f"[DAP] Error getting save details: {e}")
            return None

    def _load_save_data(self, slot_name: str) -> Optional[dict]:
        """Load save data without restoring game state."""
        try:
            import renpy

            # Load the raw save data to get full information including rollback log
            log_data, signature = renpy.loadsave.location.load(slot_name)

            if not renpy.savetoken.check_load(log_data, signature):
                return None

            # Parse the save data
            roots, log = renpy.loadsave.loads(log_data)

            # Extract variables from roots (they're prefixed with "store.")
            save_vars = {k[6:]: v for k, v in roots.items() if k.startswith("store.")}

            # Build a result dict
            result = {
                "stores": {"store": save_vars},
                "log": log.log if hasattr(log, 'log') else [],
            }

            # Get context info from the log if available
            if hasattr(log, 'current') and log.current:
                ctx = log.current.context if hasattr(log.current, 'context') else None
                if ctx:
                    result["context"] = {
                        "current": getattr(ctx, 'current', None),
                        "return_stack": getattr(ctx, 'return_stack', []),
                    }

            # Also get the JSON metadata
            try:
                json_data = renpy.loadsave.slot_json(slot_name)
                if json_data:
                    result["_version"] = json_data.get("_version")
                    result["_renpy_version"] = json_data.get("_renpy_version")
            except Exception:
                pass

            return result

        except Exception:
            return None

    def _extract_rollback_history(self, log_entries: list) -> List[RollbackEntry]:
        """Extract rollback history from log entries."""
        history = []
        try:
            import renpy

            # Only show checkpoints, and limit to last 50 for performance
            checkpoint_entries = []
            for idx, rb in enumerate(log_entries):
                is_checkpoint = getattr(rb, 'checkpoint', False) or getattr(rb, 'hard_checkpoint', False)
                if is_checkpoint:
                    checkpoint_entries.append((idx, rb))

            # Take last 50 checkpoints
            for idx, rb in checkpoint_entries[-50:]:
                is_hard = getattr(rb, 'hard_checkpoint', False)

                filename = None
                line = 0
                statement_text = None

                # Extract location from context
                if hasattr(rb, 'context') and rb.context:
                    ctx = rb.context
                    if hasattr(ctx, 'current'):
                        try:
                            node = renpy.game.script.lookup(ctx.current)
                            if node:
                                filename = getattr(node, 'filename', None)
                                line = getattr(node, 'linenumber', 0)
                                statement_text = self._get_statement_text(node)
                        except Exception:
                            pass

                history.append(RollbackEntry(
                    index=idx,
                    is_hard_checkpoint=is_hard,
                    filename=filename,
                    line=line,
                    statement_text=statement_text,
                ))

        except Exception:
            pass

        return history

    def _get_statement_text(self, node) -> Optional[str]:
        """Get a human-readable representation of a statement."""
        try:
            node_type = node.__class__.__name__

            if node_type in ('Say', 'TranslateSay'):
                who = getattr(node, 'who', None) or "narrator"
                what = getattr(node, 'what', '')
                if len(what) > 50:
                    what = what[:50] + "..."
                return f'{who}: "{what}"'
            elif node_type == 'Menu':
                return "menu:"
            elif node_type == 'Label':
                name = getattr(node, 'name', '?')
                return f"label {name}:"
            elif node_type == 'Jump':
                target = getattr(node, 'target', '?')
                return f"jump {target}"
            elif node_type == 'Call':
                target = getattr(node, 'label', '?')
                return f"call {target}"
            elif node_type == 'Show':
                imspec = getattr(node, 'imspec', None)
                if imspec and imspec[0]:
                    return f"show {' '.join(imspec[0])}"
                return "show ..."
            elif node_type == 'Scene':
                imspec = getattr(node, 'imspec', None)
                if imspec and imspec[0]:
                    return f"scene {' '.join(imspec[0])}"
                return "scene ..."
            elif node_type == 'With':
                expr = getattr(node, 'expr', None)
                if expr:
                    return f"with {expr}"
                return "with ..."
            elif node_type == 'Python':
                return "python:"
            elif node_type == 'Return':
                return "return"
            else:
                return node_type.lower()
        except Exception:
            return None

    def _extract_variables(self, save_data: dict) -> List[SaveVariable]:
        """Extract variables from save data."""
        variables = []
        try:
            # Check for stores in save data
            stores = save_data.get('stores', {})

            # Internal variable names to skip
            skip_vars = {
                'args', 'kwargs',  # Function arguments
                'main_menu', 'suppress_overlay', 'mouse_visible',  # UI state
                'quick_menu', 'nvl_list',  # UI state
            }

            # Prefixes that indicate internal variables
            skip_prefixes = (
                '_',  # Private variables
                'bubble.',  # Bubble system internals
                'achievement.',  # Achievement internals
                'audio.',  # Audio internals
                'build.',  # Build system
                'config.',  # Config (shouldn't be in saves anyway)
                'gui.',  # GUI config
                'persistent.',  # Persistent (has its own section)
                'renpy.',  # Ren'Py internals
            )

            for store_name, store_data in stores.items():
                if not isinstance(store_data, dict):
                    continue

                for var_name, value in store_data.items():
                    # Skip internal variables
                    if var_name in skip_vars:
                        continue

                    # Skip variables with internal prefixes
                    if any(var_name.startswith(p) for p in skip_prefixes):
                        # But allow _game* variables
                        if not var_name.startswith('_game'):
                            continue

                    # Skip Delete sentinel objects
                    value_type = type(value).__name__
                    if value_type == 'Delete':
                        continue

                    variables.append(SaveVariable(
                        name=var_name,
                        store=store_name,
                        value=value,
                        value_repr=self._format_value(value),
                        value_type=value_type,
                    ))

            # Sort by store, then name
            variables.sort(key=lambda v: (v.store, v.name))

        except Exception as e:
            print(f"[DAP] Error extracting variables: {e}")

        return variables

    def _format_value(self, value: Any, max_length: int = 200, depth: int = 0) -> str:
        """Format a value for display, expanding collections."""
        try:
            if depth > 3:
                return "..."

            if value is None:
                return "None"
            elif isinstance(value, bool):
                return str(value)
            elif isinstance(value, (int, float)):
                return str(value)
            elif isinstance(value, str):
                if len(value) > max_length:
                    return repr(value[:max_length] + "...")
                return repr(value)
            elif isinstance(value, (list, tuple)):
                if len(value) == 0:
                    return "[]" if isinstance(value, list) else "()"
                elif len(value) <= 10:
                    # Show actual contents for small lists
                    items = [self._format_value(v, max_length // 2, depth + 1) for v in value]
                    result = "[" + ", ".join(items) + "]"
                    if len(result) > max_length:
                        return result[:max_length] + "...]"
                    return result
                else:
                    # Too large, just show count
                    return f"[...{len(value)} items...]"
            elif isinstance(value, dict):
                if len(value) == 0:
                    return "{}"
                elif len(value) <= 10:
                    # Show actual contents for small dicts
                    items = [f"{self._format_value(k, 30, depth + 1)}: {self._format_value(v, max_length // 3, depth + 1)}"
                             for k, v in list(value.items())[:10]]
                    result = "{" + ", ".join(items) + "}"
                    if len(result) > max_length:
                        return result[:max_length] + "...}"
                    return result
                else:
                    return f"{{...{len(value)} items...}}"
            elif isinstance(value, (set, frozenset)):
                if len(value) == 0:
                    return "set()"
                elif len(value) <= 10:
                    items = [self._format_value(v, max_length // 2, depth + 1) for v in list(value)[:10]]
                    result = "{" + ", ".join(items) + "}"
                    if len(result) > max_length:
                        return result[:max_length] + "...}"
                    return result
                else:
                    return f"{{...{len(value)} items...}}"
            else:
                r = repr(value)
                if len(r) > max_length:
                    return r[:max_length] + "..."
                return r
        except Exception:
            return "<unable to display>"

    def compare_saves(self, slot_a: str, slot_b: str) -> Optional[Dict[str, Any]]:
        """
        Compare two save files.

        Args:
            slot_a: First save slot name.
            slot_b: Second save slot name.

        Returns:
            SaveComparison dict or None if error.
        """
        try:
            # Load both saves
            data_a = self._load_save_data(slot_a)
            data_b = self._load_save_data(slot_b)

            if not data_a or not data_b:
                return None

            # Extract variables
            vars_a = {(v.store, v.name): v for v in self._extract_variables(data_a)}
            vars_b = {(v.store, v.name): v for v in self._extract_variables(data_b)}

            keys_a = set(vars_a.keys())
            keys_b = set(vars_b.keys())

            # Find differences
            added = [vars_b[k] for k in (keys_b - keys_a)]
            removed = [vars_a[k] for k in (keys_a - keys_b)]

            changed = []
            for key in keys_a & keys_b:
                var_a = vars_a[key]
                var_b = vars_b[key]

                try:
                    if var_a.value != var_b.value:
                        changed.append({
                            "name": var_a.name,
                            "store": var_a.store,
                            "oldValue": var_a.value_repr,
                            "newValue": var_b.value_repr,
                            "oldType": var_a.value_type,
                            "newType": var_b.value_type,
                        })
                except Exception:
                    # Values can't be compared, assume changed
                    changed.append({
                        "name": var_a.name,
                        "store": var_a.store,
                        "oldValue": var_a.value_repr,
                        "newValue": var_b.value_repr,
                        "oldType": var_a.value_type,
                        "newType": var_b.value_type,
                    })

            # Compare position
            pos_a = data_a.get('context', {}).get('current')
            pos_b = data_b.get('context', {}).get('current')
            position_changed = pos_a != pos_b

            comparison = SaveComparison(
                slot_a=slot_a,
                slot_b=slot_b,
                added_variables=added,
                removed_variables=removed,
                changed_variables=changed,
                position_changed=position_changed,
                old_position=str(pos_a) if pos_a else None,
                new_position=str(pos_b) if pos_b else None,
            )

            return comparison.to_dict()

        except Exception as e:
            print(f"[DAP] Error comparing saves: {e}")
            return None

    def get_persistent_data(self) -> Dict[str, Any]:
        """
        Get all persistent variables and preferences.

        Returns:
            Dict with 'persistent' and 'preferences' sections.
        """
        result = {
            "persistent": [],
            "preferences": [],
        }

        try:
            import renpy

            # Get persistent variables
            if hasattr(renpy, 'persistent') and renpy.persistent is not None:
                persistent = renpy.persistent

                for name in dir(persistent):
                    if name.startswith('_'):
                        continue

                    try:
                        value = getattr(persistent, name)

                        # Skip methods and functions
                        if callable(value):
                            continue

                        result["persistent"].append({
                            "name": name,
                            "value": self._format_value(value),
                            "valueType": type(value).__name__,
                            "isDefault": self._is_default_value(name, value),
                        })
                    except Exception:
                        continue

                result["persistent"].sort(key=lambda v: v["name"])

            # Get preferences (volume, text speed, etc.)
            # Preferences are stored at renpy.game.preferences
            preferences = None
            if hasattr(renpy, 'game') and hasattr(renpy.game, 'preferences'):
                preferences = renpy.game.preferences

            if preferences is not None:
                # Common preference attributes to extract
                pref_attrs = [
                    # Text settings
                    ('text_cps', 'Text Speed (CPS)'),
                    ('afm_time', 'Auto-Forward Time'),
                    ('afm_enable', 'Auto-Forward Enabled'),
                    # Skip settings
                    ('skip_unseen', 'Skip Unseen Text'),
                    ('skip_after_choices', 'Skip After Choices'),
                    # Display settings
                    ('fullscreen', 'Fullscreen'),
                    ('transitions', 'Transitions'),
                    ('video_image_fallback', 'Video Image Fallback'),
                    ('show_empty_window', 'Show Empty Window'),
                    # Audio settings
                    ('wait_voice', 'Wait for Voice'),
                    ('voice_sustain', 'Voice Sustain'),
                    ('emphasize_audio', 'Emphasize Audio'),
                    ('audio_when_minimized', 'Audio When Minimized'),
                    ('audio_when_unfocused', 'Audio When Unfocused'),
                    ('mono_audio', 'Mono Audio'),
                    # Accessibility
                    ('self_voicing', 'Self Voicing'),
                    ('high_contrast', 'High Contrast'),
                    ('font_size', 'Font Size'),
                    ('font_line_spacing', 'Font Line Spacing'),
                    ('font_transform', 'Font Transform'),
                    ('system_cursor', 'System Cursor'),
                    # Other
                    ('language', 'Language'),
                    ('mouse_move', 'Mouse Move'),
                    ('renderer', 'Renderer'),
                    ('gl_powersave', 'GL Power Save'),
                    ('gl_framerate', 'GL Framerate'),
                    ('gl_tearing', 'GL Tearing'),
                    ('maximized', 'Window Maximized'),
                    ('pad_enabled', 'Gamepad Enabled'),
                ]

                for attr_name, display_name in pref_attrs:
                    try:
                        if hasattr(preferences, attr_name):
                            value = getattr(preferences, attr_name)

                            # Skip methods and functions
                            if callable(value):
                                continue

                            result["preferences"].append({
                                "name": attr_name,
                                "displayName": display_name,
                                "value": self._format_value(value),
                                "valueType": type(value).__name__,
                            })
                    except Exception:
                        continue

                # Extract volumes from the volumes dict
                try:
                    volumes = getattr(preferences, 'volumes', None)
                    if volumes and isinstance(volumes, dict):
                        # Standard mixer names
                        mixer_names = {
                            'main': 'Master Volume',
                            'music': 'Music Volume',
                            'sfx': 'Sound Effects Volume',
                            'sound': 'Sound Volume',
                            'voice': 'Voice Volume',
                        }
                        for mixer, vol in volumes.items():
                            display_name = mixer_names.get(mixer, f'{mixer.title()} Volume')
                            result["preferences"].append({
                                "name": f"volume_{mixer}",
                                "displayName": display_name,
                                "value": self._format_value(vol),
                                "valueType": type(vol).__name__,
                            })
                except Exception:
                    pass

                # Check mute settings
                try:
                    mute = getattr(preferences, 'mute', None)
                    if mute and isinstance(mute, dict):
                        for mixer, is_muted in mute.items():
                            if is_muted:
                                result["preferences"].append({
                                    "name": f"mute_{mixer}",
                                    "displayName": f'{mixer.title()} Muted',
                                    "value": "True",
                                    "valueType": "bool",
                                })
                except Exception:
                    pass

        except Exception as e:
            print(f"[DAP] Error getting persistent data: {e}")

        return result

    def _is_default_value(self, name: str, value: Any) -> bool:
        """Check if a persistent value is at its default."""
        try:
            import renpy

            # Check if there's a default defined
            if hasattr(renpy.persistent, '_defaults'):
                defaults = renpy.persistent._defaults
                if name in defaults:
                    return value == defaults[name]

            # Common defaults
            if value is None or value is False or value == 0:
                return True

            return False

        except Exception:
            return False

    def set_persistent(self, name: str, value: Any) -> bool:
        """
        Set a persistent variable.

        Args:
            name: Variable name.
            value: New value.

        Returns:
            True if successful.
        """
        try:
            import renpy

            setattr(renpy.persistent, name, value)

            # Mark as changed
            if hasattr(renpy.persistent, '_changed'):
                renpy.persistent._changed = True

            return True

        except Exception as e:
            print(f"[DAP] Error setting persistent: {e}")
            return False

    def delete_persistent(self, name: str) -> bool:
        """
        Delete a persistent variable (reset to default).

        Args:
            name: Variable name.

        Returns:
            True if successful.
        """
        try:
            import renpy

            if hasattr(renpy.persistent, name):
                delattr(renpy.persistent, name)
                return True

            return False

        except Exception as e:
            print(f"[DAP] Error deleting persistent: {e}")
            return False

    def save_persistent(self) -> bool:
        """
        Force save persistent data to disk.

        Returns:
            True if successful.
        """
        try:
            import renpy

            renpy.persistent._save()
            return True

        except Exception as e:
            print(f"[DAP] Error saving persistent: {e}")
            return False

    def clear_cache(self) -> None:
        """Clear the save data cache."""
        self._cache.clear()
        self._cache_time.clear()


# Global instance
_inspector: Optional[SaveInspector] = None


def get_inspector() -> SaveInspector:
    """Get the global save inspector instance."""
    global _inspector
    if _inspector is None:
        _inspector = SaveInspector()
    return _inspector
