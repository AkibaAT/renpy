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
Breakpoint management for the Ren'Py debugger.

This module handles storage, lookup, and verification of breakpoints
for both Ren'Py script statements and Python code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class Breakpoint:
    """Represents a single breakpoint."""

    id: int
    file: str  # Normalized file path
    line: int  # 1-based line number
    verified: bool = True  # Whether the breakpoint is at a valid location
    condition: Optional[str] = None  # Optional condition expression
    hit_condition: Optional[str] = None  # Optional hit count condition (e.g., ">5", "==10")
    log_message: Optional[str] = None  # Optional log message (for logpoints)
    hit_count: int = field(default=0, compare=False)  # Number of times hit

    def to_dap(self) -> dict:
        """Convert to DAP Breakpoint format."""
        return {
            "id": self.id,
            "verified": self.verified,
            "line": self.line,
            "source": {"path": self.file},
        }

    def should_break(self) -> bool:
        """
        Check if this breakpoint should trigger a break.

        Evaluates condition and hit condition if set.
        Returns True if execution should pause, False otherwise.
        """
        # Check condition expression
        if self.condition:
            try:
                import renpy
                result = renpy.python.py_eval(self.condition)
                if not result:
                    return False
            except Exception:
                # If condition evaluation fails, don't break
                return False

        # Check hit condition
        if self.hit_condition:
            try:
                # Parse hit condition like ">5", "==10", ">=3", "%2" (every 2nd hit)
                condition = self.hit_condition.strip()
                count = self.hit_count

                if condition.startswith(">="):
                    return count >= int(condition[2:])
                elif condition.startswith("<="):
                    return count <= int(condition[2:])
                elif condition.startswith("=="):
                    return count == int(condition[2:])
                elif condition.startswith("!="):
                    return count != int(condition[2:])
                elif condition.startswith(">"):
                    return count > int(condition[1:])
                elif condition.startswith("<"):
                    return count < int(condition[1:])
                elif condition.startswith("%"):
                    # Every Nth hit
                    n = int(condition[1:])
                    return n > 0 and count % n == 0
                else:
                    # Treat as plain number - break when hit count equals it
                    return count == int(condition)
            except (ValueError, TypeError):
                # If hit condition parsing fails, break anyway
                pass

        return True


class BreakpointManager:
    """
    Manages breakpoints and provides fast lookup for breakpoint checking.

    Breakpoints are stored by normalized file path for efficient lookup
    during execution.
    """

    def __init__(self):
        # Map from normalized file path to dict of line -> Breakpoint
        self._breakpoints: dict[str, dict[int, Breakpoint]] = {}
        self._next_id = 1

        # Cache for path normalization
        self._path_cache: dict[str, str] = {}

        # Fast lookup: set of basenames that have breakpoints
        # This allows quick rejection without path normalization
        self._basenames_with_breakpoints: set[str] = set()

    def set_breakpoints(self, file: str, breakpoint_data: list[dict]) -> list[Breakpoint]:
        """
        Set breakpoints for a file, replacing any existing breakpoints.

        Args:
            file: The file path (will be normalized)
            breakpoint_data: List of breakpoint dicts with keys:
                - line: Line number (required)
                - condition: Optional condition expression
                - hitCondition: Optional hit count condition
                - logMessage: Optional log message (for logpoints)

        Returns:
            List of Breakpoint objects (verified or unverified)
        """
        normalized = self._normalize_path(file)
        basename = os.path.basename(normalized)

        # Clear existing breakpoints for this file
        self._breakpoints[normalized] = {}

        # Create new breakpoints
        breakpoints = []
        for bp_data in breakpoint_data:
            line = bp_data.get("line", 0)
            if not line:
                continue

            bp = Breakpoint(
                id=self._next_id,
                file=normalized,
                line=line,
                verified=self._verify_breakpoint(normalized, line),
                condition=bp_data.get("condition"),
                hit_condition=bp_data.get("hitCondition"),
                log_message=bp_data.get("logMessage"),
            )
            self._next_id += 1
            self._breakpoints[normalized][line] = bp
            breakpoints.append(bp)

        # Update basename index
        self._rebuild_basename_index()

        return breakpoints

    def clear_file(self, file: str) -> None:
        """Clear all breakpoints for a file."""
        normalized = self._normalize_path(file)
        if normalized in self._breakpoints:
            del self._breakpoints[normalized]
            self._rebuild_basename_index()

    def clear_all(self) -> None:
        """Clear all breakpoints."""
        self._breakpoints.clear()
        self._basenames_with_breakpoints.clear()

    def _rebuild_basename_index(self) -> None:
        """Rebuild the basename index for fast rejection."""
        self._basenames_with_breakpoints = {
            os.path.basename(path)
            for path, bps in self._breakpoints.items()
            if bps  # Only include files with actual breakpoints
        }

    def check_breakpoint(self, filename: str, line: int) -> Optional[Breakpoint]:
        """
        Check if there's a breakpoint at the given location.

        PERFORMANCE CRITICAL: Called on every statement execution.

        Args:
            filename: The file path (will be normalized)
            line: The line number

        Returns:
            The Breakpoint if one exists and is verified, None otherwise
        """
        # Fast path: check basename first to avoid expensive normalization
        basename = os.path.basename(filename)
        if basename not in self._basenames_with_breakpoints:
            return None

        # Slower path: normalize and check exact match
        normalized = self._normalize_path(filename)
        file_bps = self._breakpoints.get(normalized)
        if file_bps:
            bp = file_bps.get(line)
            if bp and bp.verified:
                return bp
        return None

    def check_breakpoint_range(self, filename: str, start_line: int, end_line: int) -> Optional[Breakpoint]:
        """
        Check if there's a breakpoint in a line range.

        Useful for matching breakpoints to statements that span multiple lines.

        Args:
            filename: The file path
            start_line: First line of the range
            end_line: Last line of the range (inclusive)

        Returns:
            The first matching Breakpoint, or None
        """
        # Fast path: check basename first
        basename = os.path.basename(filename)
        if basename not in self._basenames_with_breakpoints:
            return None

        normalized = self._normalize_path(filename)
        file_bps = self._breakpoints.get(normalized)
        if file_bps:
            for line in range(start_line, end_line + 1):
                bp = file_bps.get(line)
                if bp and bp.verified:
                    return bp
        return None

    def get_all_breakpoints(self) -> list[Breakpoint]:
        """Get all breakpoints across all files."""
        all_bps = []
        for file_bps in self._breakpoints.values():
            all_bps.extend(file_bps.values())
        return all_bps

    def get_file_breakpoints(self, file: str) -> list[Breakpoint]:
        """Get all breakpoints for a specific file."""
        normalized = self._normalize_path(file)
        file_bps = self._breakpoints.get(normalized, {})
        return list(file_bps.values())

    def has_breakpoints(self) -> bool:
        """Check if any breakpoints are set. O(1) operation."""
        return bool(self._basenames_with_breakpoints)

    def has_file_breakpoints(self, file: str) -> bool:
        """Check if any breakpoints are set for a file."""
        # Fast path: check basename first
        basename = os.path.basename(file)
        if basename not in self._basenames_with_breakpoints:
            return False
        # Slower path for exact match
        normalized = self._normalize_path(file)
        return bool(self._breakpoints.get(normalized))

    def _normalize_path(self, path: str) -> str:
        """
        Normalize a file path for consistent comparison.

        Handles:
        - Relative vs absolute paths
        - Different path separators
        - Case sensitivity (on case-insensitive systems)
        """
        if path in self._path_cache:
            return self._path_cache[path]

        # Handle Ren'Py's game-relative paths
        normalized = path

        # Convert to absolute path if possible
        if not os.path.isabs(normalized):
            # Try to resolve relative to game directory
            try:
                import renpy

                if hasattr(renpy, "config") and hasattr(renpy.config, "basedir"):
                    candidate = os.path.join(renpy.config.basedir, normalized)
                    if os.path.exists(candidate):
                        normalized = candidate
            except (ImportError, AttributeError):
                pass

        # Normalize path separators and resolve .. etc
        normalized = os.path.normpath(normalized)

        # Use realpath to resolve symlinks
        if os.path.exists(normalized):
            normalized = os.path.realpath(normalized)

        # Cache the result
        self._path_cache[path] = normalized

        return normalized

    def _verify_breakpoint(self, file: str, line: int) -> bool:
        """
        Verify that a breakpoint is at a valid location.

        A breakpoint is valid if:
        - The file exists
        - The line contains a Ren'Py statement or Python code

        For now, we assume all breakpoints are valid and let the
        debugger handle verification during execution.
        """
        # Check if file exists
        if not os.path.exists(file):
            return False

        # For now, accept all breakpoints in existing files
        # More sophisticated verification could check:
        # - Is this line a statement?
        # - Is this line inside a Python block?
        # - Is this line a comment or blank?
        return True

    def invalidate_path_cache(self) -> None:
        """
        Invalidate the path cache.

        Call this when game files may have been reloaded.
        """
        self._path_cache.clear()
