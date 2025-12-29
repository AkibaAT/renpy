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
Variable inspection for the Ren'Py debugger.

This module provides facilities for inspecting game variables,
Python local/global variables, and formatting them for DAP display.
"""

from __future__ import annotations

from typing import Any, Optional
from types import FrameType


# Maximum depth for recursive object inspection
MAX_DEPTH = 3

# Maximum number of items to show in collections
MAX_ITEMS = 100

# Maximum string length before truncation
MAX_STRING_LENGTH = 1000


class VariableInspector:
    """
    Inspects and formats variables for debugger display.

    Manages variable references for lazy expansion of complex objects.
    """

    # Special scope reference IDs
    SCOPE_LOCALS = 1
    SCOPE_STORE = 2
    SCOPE_GLOBALS = 3

    def __init__(self):
        # Map from reference ID to object for lazy expansion
        self._references: dict[int, Any] = {}
        self._next_ref = 1000  # Start after reserved scope IDs

        # Store frame for locals access
        self._current_frame: Optional[FrameType] = None

    def set_frame(self, frame: Optional[FrameType]) -> None:
        """Set the current Python frame for locals access."""
        self._current_frame = frame

    def clear_references(self) -> None:
        """
        Clear all variable references.

        Call this when resuming execution to free memory.
        """
        self._references.clear()
        self._next_ref = 1000
        self._current_frame = None

    def get_scopes(self, frame_id: int) -> list[dict]:
        """
        Get available variable scopes for a stack frame.

        Args:
            frame_id: The stack frame ID (currently unused, we show global scopes)

        Returns:
            List of DAP Scope objects
        """
        scopes = []

        # Always show Ren'Py store variables
        scopes.append(
            {
                "name": "Store Variables",
                "variablesReference": self.SCOPE_STORE,
                "expensive": False,
            }
        )

        # Show locals if we have a Python frame
        if self._current_frame is not None:
            scopes.insert(
                0,
                {
                    "name": "Locals",
                    "variablesReference": self.SCOPE_LOCALS,
                    "expensive": False,
                },
            )

        # Show Python globals
        scopes.append(
            {
                "name": "Globals",
                "variablesReference": self.SCOPE_GLOBALS,
                "expensive": True,  # Can be large
            }
        )

        return scopes

    def get_variables(self, reference: int) -> list[dict]:
        """
        Get variables for a given reference.

        Args:
            reference: The variable reference ID (scope ID or object ref)

        Returns:
            List of DAP Variable objects
        """
        if reference == self.SCOPE_LOCALS:
            return self._get_locals()
        elif reference == self.SCOPE_STORE:
            return self._get_store_variables()
        elif reference == self.SCOPE_GLOBALS:
            return self._get_globals()
        elif reference in self._references:
            return self._expand_reference(reference)
        else:
            return []

    def _get_locals(self) -> list[dict]:
        """Get local variables from current Python frame."""
        if self._current_frame is None:
            return []

        variables = []
        for name, value in self._current_frame.f_locals.items():
            if not name.startswith("_"):  # Skip private vars
                variables.append(self._format_variable(name, value))

        return sorted(variables, key=lambda v: v["name"])

    def _get_store_variables(self) -> list[dict]:
        """Get variables from Ren'Py's store."""
        variables = []

        try:
            import renpy

            if hasattr(renpy, "store"):
                store = renpy.store
                for name in dir(store):
                    # Skip private and special attributes
                    if name.startswith("_"):
                        continue
                    # Skip modules and functions (usually imports)
                    try:
                        value = getattr(store, name)
                        if not callable(value) and not isinstance(value, type):
                            variables.append(self._format_variable(name, value))
                    except Exception:
                        pass
        except ImportError:
            pass

        return sorted(variables, key=lambda v: v["name"])

    def _get_globals(self) -> list[dict]:
        """Get Python global variables."""
        variables = []

        try:
            import renpy

            if hasattr(renpy, "python") and hasattr(renpy.python, "store_dicts"):
                # Get variables from store namespace
                store_dicts = renpy.python.store_dicts
                if "store" in store_dicts:
                    store_dict = store_dicts["store"]
                    for name, value in store_dict.items():
                        if not name.startswith("_"):
                            variables.append(self._format_variable(name, value))
        except (ImportError, AttributeError):
            pass

        return sorted(variables, key=lambda v: v["name"])[:MAX_ITEMS]

    def _expand_reference(self, reference: int) -> list[dict]:
        """Expand a complex object into its components."""
        obj = self._references.get(reference)
        if obj is None:
            return []

        variables = []

        if isinstance(obj, dict):
            for i, (key, value) in enumerate(obj.items()):
                if i >= MAX_ITEMS:
                    variables.append(
                        {
                            "name": "...",
                            "value": f"({len(obj) - MAX_ITEMS} more items)",
                            "variablesReference": 0,
                        }
                    )
                    break
                variables.append(self._format_variable(repr(key), value))

        elif isinstance(obj, (list, tuple)):
            for i, value in enumerate(obj):
                if i >= MAX_ITEMS:
                    variables.append(
                        {
                            "name": "...",
                            "value": f"({len(obj) - MAX_ITEMS} more items)",
                            "variablesReference": 0,
                        }
                    )
                    break
                variables.append(self._format_variable(f"[{i}]", value))

        elif isinstance(obj, set):
            for i, value in enumerate(obj):
                if i >= MAX_ITEMS:
                    variables.append(
                        {
                            "name": "...",
                            "value": f"({len(obj) - MAX_ITEMS} more items)",
                            "variablesReference": 0,
                        }
                    )
                    break
                variables.append(self._format_variable(f"{{{i}}}", value))

        else:
            # Generic object - show attributes
            try:
                attrs = []
                for name in dir(obj):
                    if not name.startswith("_"):
                        try:
                            value = getattr(obj, name)
                            if not callable(value):
                                attrs.append((name, value))
                        except Exception:
                            pass

                for i, (name, value) in enumerate(attrs):
                    if i >= MAX_ITEMS:
                        variables.append(
                            {
                                "name": "...",
                                "value": f"({len(attrs) - MAX_ITEMS} more attributes)",
                                "variablesReference": 0,
                            }
                        )
                        break
                    variables.append(self._format_variable(name, value))
            except Exception:
                pass

        return variables

    def _format_variable(self, name: str, value: Any, depth: int = 0) -> dict:
        """
        Format a variable for DAP display.

        Args:
            name: Variable name
            value: Variable value
            depth: Current recursion depth

        Returns:
            DAP Variable object
        """
        var = {
            "name": str(name),
            "value": self._format_value(value),
            "type": type(value).__name__,
            "variablesReference": 0,
        }

        # Create reference for expandable objects
        if depth < MAX_DEPTH and self._is_expandable(value):
            ref = self._next_ref
            self._next_ref += 1
            self._references[ref] = value
            var["variablesReference"] = ref

            # Add indexed/named children count hint
            if isinstance(value, dict):
                var["namedVariables"] = len(value)
            elif isinstance(value, (list, tuple, set)):
                var["indexedVariables"] = len(value)

        return var

    def _format_value(self, value: Any) -> str:
        """Format a value as a string for display."""
        try:
            if value is None:
                return "None"
            elif isinstance(value, bool):
                return str(value)
            elif isinstance(value, (int, float)):
                return str(value)
            elif isinstance(value, str):
                if len(value) > MAX_STRING_LENGTH:
                    return repr(value[:MAX_STRING_LENGTH] + "...")
                return repr(value)
            elif isinstance(value, bytes):
                if len(value) > MAX_STRING_LENGTH:
                    return repr(value[:MAX_STRING_LENGTH] + b"...")
                return repr(value)
            elif isinstance(value, dict):
                return f"dict ({len(value)} items)"
            elif isinstance(value, list):
                return f"list ({len(value)} items)"
            elif isinstance(value, tuple):
                return f"tuple ({len(value)} items)"
            elif isinstance(value, set):
                return f"set ({len(value)} items)"
            elif isinstance(value, frozenset):
                return f"frozenset ({len(value)} items)"
            else:
                # For other objects, try repr but limit length
                r = repr(value)
                if len(r) > MAX_STRING_LENGTH:
                    return r[:MAX_STRING_LENGTH] + "..."
                return r
        except Exception as e:
            return f"<error: {e}>"

    def _is_expandable(self, value: Any) -> bool:
        """Check if a value can be expanded to show children."""
        if value is None:
            return False
        if isinstance(value, (bool, int, float, str, bytes)):
            return False
        if isinstance(value, (dict, list, tuple, set, frozenset)):
            return len(value) > 0
        # Check if object has non-private attributes
        try:
            for name in dir(value):
                if not name.startswith("_"):
                    attr = getattr(value, name)
                    if not callable(attr):
                        return True
        except Exception:
            pass
        return False

    def set_variable(self, reference: int, name: str, value_expr: str) -> dict:
        """
        Set a variable's value.

        Args:
            reference: The scope or object reference
            name: The variable name
            value_expr: The new value as a Python expression string

        Returns:
            DAP Variable object with the new value, or error info
        """
        try:
            import renpy

            # Evaluate the new value expression
            new_value = renpy.python.py_eval(value_expr)

            if reference == self.SCOPE_LOCALS:
                return self._set_local(name, new_value)
            elif reference == self.SCOPE_STORE:
                return self._set_store_variable(name, new_value)
            elif reference == self.SCOPE_GLOBALS:
                return self._set_global(name, new_value)
            elif reference in self._references:
                return self._set_reference_member(reference, name, new_value)
            else:
                return {"success": False, "message": "Unknown reference"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _set_local(self, name: str, value: Any) -> dict:
        """Set a local variable in the current frame."""
        if self._current_frame is None:
            return {"success": False, "message": "No frame available"}

        try:
            self._current_frame.f_locals[name] = value
            # Force locals update (needed for some Python versions)
            import ctypes
            ctypes.pythonapi.PyFrame_LocalsToFast(
                ctypes.py_object(self._current_frame), ctypes.c_int(0)
            )
            return {
                "success": True,
                "value": self._format_value(value),
                "type": type(value).__name__,
                "variablesReference": 0,
            }
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _set_store_variable(self, name: str, value: Any) -> dict:
        """Set a variable in Ren'Py's store."""
        try:
            import renpy

            if hasattr(renpy, "store"):
                setattr(renpy.store, name, value)
                return {
                    "success": True,
                    "value": self._format_value(value),
                    "type": type(value).__name__,
                    "variablesReference": 0,
                }
            return {"success": False, "message": "Store not available"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _set_global(self, name: str, value: Any) -> dict:
        """Set a Python global variable."""
        try:
            import renpy

            if hasattr(renpy, "python") and hasattr(renpy.python, "store_dicts"):
                store_dicts = renpy.python.store_dicts
                if "store" in store_dicts:
                    store_dicts["store"][name] = value
                    return {
                        "success": True,
                        "value": self._format_value(value),
                        "type": type(value).__name__,
                        "variablesReference": 0,
                    }
            return {"success": False, "message": "Globals not available"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    def _set_reference_member(self, reference: int, name: str, value: Any) -> dict:
        """Set a member of a referenced object."""
        obj = self._references.get(reference)
        if obj is None:
            return {"success": False, "message": "Reference not found"}

        try:
            if isinstance(obj, dict):
                # For dicts, the name might be a repr of the key
                # Try to evaluate it as a Python expression
                try:
                    import renpy
                    key = renpy.python.py_eval(name)
                except Exception:
                    key = name
                obj[key] = value
            elif isinstance(obj, list):
                # Name is like "[0]" or just "0"
                index = int(name.strip("[]"))
                obj[index] = value
            else:
                # Generic object attribute
                setattr(obj, name, value)

            return {
                "success": True,
                "value": self._format_value(value),
                "type": type(value).__name__,
                "variablesReference": 0,
            }
        except Exception as e:
            return {"success": False, "message": str(e)}
