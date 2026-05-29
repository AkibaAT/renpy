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
Rollback Visualizer for Ren'Py Debugger.

This module provides APIs to inspect and navigate Ren'Py's rollback history,
enabling IDE visualization of:
- Checkpoint timeline
- Variable changes at each checkpoint
- Execution path history
- State comparison between checkpoints
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class CheckpointInfo:
    """Information about a rollback checkpoint."""
    index: int
    identifier: Tuple[int, int]
    is_checkpoint: bool
    is_hard_checkpoint: bool
    is_current: bool

    # Location info
    filename: Optional[str]
    line: int
    label: Optional[str]
    node_type: Optional[str]

    # Statement info
    statement_text: Optional[str]

    # Menu choice info (for menu statements)
    menu_choice: Optional[str]  # The text of the selected choice
    menu_choice_index: Optional[int]  # The index of the selected choice

    # Variable changes at this checkpoint
    variable_changes: Dict[str, Dict[str, Any]]  # {store_name: {var: value}}

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VariableChange:
    """Represents a variable change between checkpoints."""
    variable_name: str
    store_name: str
    old_value: Any
    new_value: Any
    checkpoint_index: int

    def to_dict(self) -> dict:
        return {
            "variable": self.variable_name,
            "store": self.store_name,
            "oldValue": self._format_value(self.old_value),
            "newValue": self._format_value(self.new_value),
            "checkpointIndex": self.checkpoint_index,
        }

    def _format_value(self, value: Any) -> str:
        try:
            if value is None:
                return "None"
            elif isinstance(value, (bool, int, float)):
                return str(value)
            elif isinstance(value, str):
                if len(value) > 100:
                    return repr(value[:100] + "...")
                return repr(value)
            else:
                r = repr(value)
                if len(r) > 100:
                    return r[:100] + "..."
                return r
        except Exception:
            return "<unable to display>"


class RollbackVisualizer:
    """
    Provides access to Ren'Py's rollback history for debugging visualization.
    """

    def __init__(self):
        self._cached_history: Optional[List[CheckpointInfo]] = None
        self._cache_valid = False

    def invalidate_cache(self) -> None:
        """Invalidate the cached history (call when rollback occurs)."""
        self._cache_valid = False
        self._cached_history = None

    def get_history(self, include_non_checkpoints: bool = False) -> List[CheckpointInfo]:
        """
        Get the rollback history as a list of checkpoint info objects.

        Args:
            include_non_checkpoints: If True, include all rollback entries,
                                    not just user-visible checkpoints.

        Returns:
            List of CheckpointInfo objects, oldest first.
        """
        try:
            import renpy

            if not hasattr(renpy, 'game') or not hasattr(renpy.game, 'log'):
                return []

            log = renpy.game.log
            if log is None:
                return []

            if not hasattr(log, 'log'):
                return []

            total_entries = len(log.log)

            # Early return if no entries
            if total_entries == 0:
                return []

            history = []
            current_identifier = self._get_current_identifier()

            for idx, rb in enumerate(log.log):
                is_cp = getattr(rb, 'checkpoint', False)

                # Skip non-checkpoints unless requested
                if not include_non_checkpoints and not is_cp:
                    continue

                info = self._extract_checkpoint_info(idx, rb, current_identifier)
                history.append(info)

            return history

        except Exception:
            return []

    def _get_current_identifier(self) -> Optional[Tuple[int, int]]:
        """Get the identifier of the current rollback entry."""
        try:
            import renpy
            if renpy.game.log and renpy.game.log.current:
                return renpy.game.log.current.identifier
            return None
        except Exception:
            return None

    def _resolve_path(self, filename: Optional[str]) -> Optional[str]:
        """Convert a Ren'Py relative path to an absolute path."""
        if not filename:
            return None

        try:
            import renpy
            import os

            # If already absolute, return as-is
            if os.path.isabs(filename):
                return filename

            # Try to resolve using basedir
            if hasattr(renpy, 'config') and hasattr(renpy.config, 'basedir'):
                basedir = renpy.config.basedir
                if basedir:
                    full_path = os.path.join(basedir, filename)
                    if os.path.exists(full_path):
                        return full_path

            # Try gamedir
            if hasattr(renpy, 'config') and hasattr(renpy.config, 'gamedir'):
                gamedir = renpy.config.gamedir
                if gamedir:
                    # filename often starts with "game/", so try both with and without
                    full_path = os.path.join(gamedir, filename)
                    if os.path.exists(full_path):
                        return full_path

                    # If filename starts with "game/", strip it and try gamedir directly
                    if filename.startswith("game/"):
                        stripped = filename[5:]  # Remove "game/"
                        full_path = os.path.join(gamedir, stripped)
                        if os.path.exists(full_path):
                            return full_path

            # Fallback: return original filename
            return filename

        except Exception:
            return filename

    def _extract_checkpoint_info(self, index: int, rb, current_id: Optional[Tuple]) -> CheckpointInfo:
        """Extract information from a Rollback object."""
        try:
            import renpy

            # Get location from context
            filename = None
            line = 0
            label = None
            node_type = None
            statement_text = None
            node = None
            menu_choice = None
            menu_choice_index = None

            if hasattr(rb, 'context') and rb.context:
                ctx = rb.context

                # Get current node from context
                if hasattr(ctx, 'current'):
                    try:
                        node = renpy.game.script.lookup(ctx.current)
                        if node:
                            raw_filename = getattr(node, 'filename', None)
                            filename = self._resolve_path(raw_filename)
                            line = getattr(node, 'linenumber', 0)
                            node_type = node.__class__.__name__
                            statement_text = self._get_statement_text(node)
                    except Exception:
                        pass

                # Get label from return stack
                if hasattr(ctx, 'return_stack') and ctx.return_stack:
                    # The first entry is usually the current label
                    for entry in reversed(ctx.return_stack):
                        if isinstance(entry, tuple) and len(entry) >= 1:
                            name = entry[0]
                            if isinstance(name, str) and not name.startswith('_'):
                                label = name
                                break

            # Get variable changes
            variable_changes = {}
            if hasattr(rb, 'stores') and rb.stores:
                for store_name, changes in rb.stores.items():
                    if changes:
                        variable_changes[store_name] = {
                            k: self._format_value_for_display(v)
                            for k, v in changes.items()
                        }

            # Extract menu choice info from rb.forward
            # rb.forward contains the data passed to checkpoint() - for menus, this is the choice index
            forward_data = getattr(rb, 'forward', None)
            if forward_data is not None and node is not None and node_type == 'Menu':
                try:
                    # forward_data is the choice index
                    if isinstance(forward_data, int):
                        menu_choice_index = forward_data
                        # Get the choice text from the menu items
                        items = getattr(node, 'items', None)
                        if items and 0 <= forward_data < len(items):
                            choice_label = items[forward_data][0]  # (label, condition, block)
                            if choice_label:
                                menu_choice = choice_label
                                # Update statement_text to include the choice
                                statement_text = f"menu: chose \"{choice_label}\""
                except Exception:
                    pass

            return CheckpointInfo(
                index=index,
                identifier=getattr(rb, 'identifier', (0, index)),
                is_checkpoint=getattr(rb, 'checkpoint', False),
                is_hard_checkpoint=getattr(rb, 'hard_checkpoint', False),
                is_current=(rb.identifier == current_id) if current_id else False,
                filename=filename,
                line=line,
                label=label,
                node_type=node_type,
                statement_text=statement_text,
                menu_choice=menu_choice,
                menu_choice_index=menu_choice_index,
                variable_changes=variable_changes,
            )

        except Exception as e:
            # Return minimal info on error
            return CheckpointInfo(
                index=index,
                identifier=(0, index),
                is_checkpoint=False,
                is_hard_checkpoint=False,
                is_current=False,
                filename=None,
                line=0,
                label=None,
                node_type=None,
                statement_text=None,
                menu_choice=None,
                menu_choice_index=None,
                variable_changes={},
            )

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

            elif node_type == 'Hide':
                imspec = getattr(node, 'imspec', None)
                if imspec and imspec[0]:
                    return f"hide {' '.join(imspec[0])}"
                return "hide ..."

            elif node_type == 'With':
                # With statement - show the transition expression
                expr = getattr(node, 'expr', None)
                if expr:
                    return f"with {expr}"
                return "with ..."

            elif node_type == 'Python':
                # Try to get the code if available
                code = getattr(node, 'code', None)
                if code and hasattr(code, 'source'):
                    src = code.source.strip()
                    if len(src) > 40:
                        src = src[:40] + "..."
                    return f"$ {src}"
                return "python:"

            elif node_type == 'EarlyPython':
                return "python early:"

            elif node_type == 'Return':
                return "return"

            elif node_type == 'If':
                return "if:"

            elif node_type == 'While':
                return "while:"

            elif node_type == 'Pass':
                return "pass"

            elif node_type == 'Init':
                return "init:"

            elif node_type == 'Define':
                varname = getattr(node, 'varname', '?')
                return f"define {varname}"

            elif node_type == 'Default':
                varname = getattr(node, 'varname', '?')
                return f"default {varname}"

            elif node_type == 'UserStatement':
                # Custom user statement - get the line text if possible
                line = getattr(node, 'line', None)
                if line:
                    if len(line) > 50:
                        line = line[:50] + "..."
                    return line
                return "user statement"

            elif node_type == 'Play':
                channel = getattr(node, 'channel', 'music')
                file = getattr(node, 'file', '?')
                if isinstance(file, str) and len(file) > 30:
                    file = "..." + file[-27:]
                return f"play {channel} {file}"

            elif node_type == 'Stop':
                channel = getattr(node, 'channel', 'music')
                return f"stop {channel}"

            elif node_type == 'Queue':
                channel = getattr(node, 'channel', 'music')
                return f"queue {channel}"

            elif node_type == 'Pause':
                return "pause"

            elif node_type == 'Screen':
                name = getattr(node, 'name', '?')
                return f"screen {name}:"

            elif node_type == 'ShowScreen':
                name = getattr(node, 'screen_name', '?')
                return f"show screen {name}"

            elif node_type == 'HideScreen':
                name = getattr(node, 'screen_name', '?')
                return f"hide screen {name}"

            elif node_type == 'CallScreen':
                name = getattr(node, 'screen_name', '?')
                return f"call screen {name}"

            else:
                return node_type.lower()

        except Exception:
            return None

    def _format_value_for_display(self, value: Any) -> str:
        """Format a value for display in the visualizer."""
        try:
            if value is None:
                return "None"
            elif isinstance(value, bool):
                return str(value)
            elif isinstance(value, (int, float)):
                return str(value)
            elif isinstance(value, str):
                if len(value) > 50:
                    return repr(value[:50] + "...")
                return repr(value)
            elif isinstance(value, (list, tuple)):
                return f"{type(value).__name__}[{len(value)}]"
            elif isinstance(value, dict):
                return f"dict[{len(value)}]"
            else:
                return f"<{type(value).__name__}>"
        except Exception:
            return "<error>"

    def get_checkpoint_details(self, index: int) -> Optional[Dict]:
        """
        Get detailed information about a specific checkpoint.

        Args:
            index: The index of the checkpoint in the log.

        Returns:
            Detailed checkpoint info including full variable state.
        """
        try:
            import renpy

            log = renpy.game.log
            if not log or index < 0 or index >= len(log.log):
                return None

            rb = log.log[index]
            current_id = self._get_current_identifier()

            info = self._extract_checkpoint_info(index, rb, current_id)
            result = info.to_dict()

            # Add more detailed variable info
            result['fullVariables'] = {}

            if hasattr(rb, 'stores') and rb.stores:
                for store_name, changes in rb.stores.items():
                    if changes:
                        result['fullVariables'][store_name] = {
                            k: {
                                'value': self._format_value_for_display(v),
                                'type': type(v).__name__,
                            }
                            for k, v in changes.items()
                        }

            return result

        except Exception as e:
            print(f"[DAP] Error getting checkpoint details: {e}")
            return None

    def find_variable_changes(self, variable_name: str, store_name: str = "store") -> List[VariableChange]:
        """
        Find all checkpoints where a variable changed.

        Args:
            variable_name: Name of the variable to search for.
            store_name: Which store to search in (default: "store").

        Returns:
            List of VariableChange objects describing each change.
        """
        try:
            import renpy

            log = renpy.game.log
            if not log:
                return []

            changes = []
            prev_value = None

            for idx, rb in enumerate(log.log):
                if not hasattr(rb, 'stores') or not rb.stores:
                    continue

                store_changes = rb.stores.get(store_name, {})
                if variable_name in store_changes:
                    new_value = store_changes[variable_name]

                    changes.append(VariableChange(
                        variable_name=variable_name,
                        store_name=store_name,
                        old_value=prev_value,
                        new_value=new_value,
                        checkpoint_index=idx,
                    ))

                    prev_value = new_value

            return changes

        except Exception as e:
            print(f"[DAP] Error finding variable changes: {e}")
            return []

    def get_execution_path(self) -> List[Dict]:
        """
        Get the execution path (sequence of labels visited).

        Returns:
            List of dicts with label info.
        """
        try:
            import renpy

            log = renpy.game.log
            if not log:
                return []

            path = []
            last_label = None

            for idx, rb in enumerate(log.log):
                if not rb.checkpoint:
                    continue

                if hasattr(rb, 'context') and rb.context:
                    ctx = rb.context

                    # Try to get label from context
                    label = None
                    if hasattr(ctx, 'return_stack') and ctx.return_stack:
                        for entry in reversed(ctx.return_stack):
                            if isinstance(entry, tuple) and len(entry) >= 1:
                                name = entry[0]
                                if isinstance(name, str) and not name.startswith('_'):
                                    label = name
                                    break

                    if label and label != last_label:
                        path.append({
                            'label': label,
                            'checkpointIndex': idx,
                        })
                        last_label = label

            return path

        except Exception as e:
            print(f"[DAP] Error getting execution path: {e}")
            return []

    def goto_checkpoint(self, index: int) -> bool:
        """
        Roll back to a specific checkpoint.

        Args:
            index: The index of the checkpoint to go to.

        Returns:
            True if rollback was initiated, False otherwise.
        """
        try:
            import renpy

            log = renpy.game.log
            if not log or index < 0 or index >= len(log.log):
                return False

            # Calculate how many checkpoints back we need to go
            current_idx = len(log.log) - 1

            # Count hard checkpoints between current and target
            checkpoints_back = 0
            for i in range(current_idx, index, -1):
                if log.log[i].hard_checkpoint:
                    checkpoints_back += 1

            if checkpoints_back > 0:
                # Trigger rollback
                renpy.rollback(checkpoints=checkpoints_back, force=True, greedy=True)
                return True

            return False

        except Exception as e:
            print(f"[DAP] Error going to checkpoint: {e}")
            return False

    def compare_checkpoints(self, index_a: int, index_b: int) -> Dict:
        """
        Compare variable state between two checkpoints.

        Args:
            index_a: First checkpoint index.
            index_b: Second checkpoint index.

        Returns:
            Dict with added, removed, and changed variables.
        """
        try:
            import renpy

            log = renpy.game.log
            if not log:
                return {'added': {}, 'removed': {}, 'changed': {}}

            # Get cumulative state at each checkpoint
            state_a = self._get_cumulative_state(index_a)
            state_b = self._get_cumulative_state(index_b)

            added = {}
            removed = {}
            changed = {}

            all_keys = set(state_a.keys()) | set(state_b.keys())

            for key in all_keys:
                in_a = key in state_a
                in_b = key in state_b

                if in_b and not in_a:
                    added[key] = self._format_value_for_display(state_b[key])
                elif in_a and not in_b:
                    removed[key] = self._format_value_for_display(state_a[key])
                elif in_a and in_b:
                    try:
                        if state_a[key] != state_b[key]:
                            changed[key] = {
                                'from': self._format_value_for_display(state_a[key]),
                                'to': self._format_value_for_display(state_b[key]),
                            }
                    except Exception:
                        # Can't compare, assume changed
                        changed[key] = {
                            'from': self._format_value_for_display(state_a[key]),
                            'to': self._format_value_for_display(state_b[key]),
                        }

            return {
                'added': added,
                'removed': removed,
                'changed': changed,
            }

        except Exception as e:
            print(f"[DAP] Error comparing checkpoints: {e}")
            return {'added': {}, 'removed': {}, 'changed': {}}

    def _get_cumulative_state(self, up_to_index: int) -> Dict[str, Any]:
        """Get cumulative variable state up to a checkpoint index."""
        try:
            import renpy

            log = renpy.game.log
            if not log:
                return {}

            state = {}

            for idx in range(min(up_to_index + 1, len(log.log))):
                rb = log.log[idx]
                if hasattr(rb, 'stores') and rb.stores:
                    for store_name, changes in rb.stores.items():
                        if store_name == 'store' and changes:
                            state.update(changes)

            return state

        except Exception:
            return {}


# Global instance
_visualizer: Optional[RollbackVisualizer] = None


def get_visualizer() -> RollbackVisualizer:
    """Get the global rollback visualizer instance."""
    global _visualizer
    if _visualizer is None:
        _visualizer = RollbackVisualizer()
    return _visualizer
