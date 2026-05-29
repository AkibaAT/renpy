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
Execution Recorder for Ren'Py Debugger.

This module provides recording and playback of game sessions for:
- Automated testing and regression detection
- Bug reproduction
- Test case generation
- Coverage analysis
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum


class EventType(Enum):
    """Types of recorded events."""
    START = "start"
    CHECKPOINT = "checkpoint"
    CHOICE = "choice"
    INPUT = "input"
    CLICK = "click"
    JUMP = "jump"
    CALL = "call"
    RETURN = "return"
    SCREENSHOT = "screenshot"  # Visual regression checkpoint
    END = "end"


class PlaybackMode(Enum):
    """Playback modes for replaying recordings."""
    VERIFY = "verify"      # Replay and check assertions
    FAST = "fast"          # Skip all waits, go as fast as possible
    REALTIME = "realtime"  # Replay with original timing


@dataclass
class RecordedEvent:
    """A single recorded event."""
    type: str
    timestamp: float  # ms since recording start

    # Location info
    label: Optional[str] = None
    filename: Optional[str] = None
    line: Optional[int] = None

    # Event-specific data
    choice_index: Optional[int] = None
    choice_text: Optional[str] = None
    menu_items: Optional[List[str]] = None
    input_value: Optional[str] = None
    input_prompt: Optional[str] = None
    target_label: Optional[str] = None

    # State snapshot (for checkpoints)
    variables: Optional[Dict[str, Any]] = None

    # Visual regression data
    screenshot_name: Optional[str] = None  # Filename of reference screenshot
    screenshot_threshold: Optional[float] = None  # Allowed difference % (0-100)

    def to_dict(self) -> dict:
        """Convert to dictionary, excluding None values."""
        result = {"type": self.type, "timestamp": self.timestamp}
        for key, value in asdict(self).items():
            if key not in ("type", "timestamp") and value is not None:
                result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict) -> "RecordedEvent":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class Assertion:
    """An assertion to verify during playback."""
    event_index: int
    variable: str
    store: str
    expected: Any
    comparison: str = "eq"  # eq, ne, gt, lt, ge, le, contains

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Assertion":
        return cls(**data)

    def check(self, actual: Any) -> Tuple[bool, str]:
        """Check if assertion passes. Returns (passed, message)."""
        try:
            if self.comparison == "eq":
                passed = actual == self.expected
                msg = f"{self.variable}: expected {self.expected!r}, got {actual!r}"
            elif self.comparison == "ne":
                passed = actual != self.expected
                msg = f"{self.variable}: expected not {self.expected!r}, got {actual!r}"
            elif self.comparison == "gt":
                passed = actual > self.expected
                msg = f"{self.variable}: expected > {self.expected!r}, got {actual!r}"
            elif self.comparison == "lt":
                passed = actual < self.expected
                msg = f"{self.variable}: expected < {self.expected!r}, got {actual!r}"
            elif self.comparison == "ge":
                passed = actual >= self.expected
                msg = f"{self.variable}: expected >= {self.expected!r}, got {actual!r}"
            elif self.comparison == "le":
                passed = actual <= self.expected
                msg = f"{self.variable}: expected <= {self.expected!r}, got {actual!r}"
            elif self.comparison == "contains":
                passed = self.expected in actual
                msg = f"{self.variable}: expected {actual!r} to contain {self.expected!r}"
            else:
                passed = False
                msg = f"Unknown comparison: {self.comparison}"

            return passed, msg if not passed else ""
        except Exception as e:
            return False, f"{self.variable}: comparison error: {e}"


@dataclass
class Recording:
    """A complete recording of a game session."""
    name: str
    version: int = 1
    created: str = ""
    description: str = ""

    events: List[RecordedEvent] = field(default_factory=list)
    assertions: List[Assertion] = field(default_factory=list)

    # Coverage data
    labels_visited: List[str] = field(default_factory=list)
    statements_executed: int = 0
    menu_branches: Dict[str, int] = field(default_factory=dict)  # "file:line" -> choice_index

    # Metadata
    duration_ms: float = 0
    game_name: Optional[str] = None
    game_version: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "created": self.created,
            "description": self.description,
            "events": [e.to_dict() for e in self.events],
            "assertions": [a.to_dict() for a in self.assertions],
            "labels_visited": self.labels_visited,
            "statements_executed": self.statements_executed,
            "menu_branches": self.menu_branches,
            "duration_ms": self.duration_ms,
            "game_name": self.game_name,
            "game_version": self.game_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Recording":
        events = [RecordedEvent.from_dict(e) for e in data.get("events", [])]
        assertions = [Assertion.from_dict(a) for a in data.get("assertions", [])]

        return cls(
            name=data.get("name", "unnamed"),
            version=data.get("version", 1),
            created=data.get("created", ""),
            description=data.get("description", ""),
            events=events,
            assertions=assertions,
            labels_visited=data.get("labels_visited", []),
            statements_executed=data.get("statements_executed", 0),
            menu_branches=data.get("menu_branches", {}),
            duration_ms=data.get("duration_ms", 0),
            game_name=data.get("game_name"),
            game_version=data.get("game_version"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "Recording":
        return cls.from_dict(json.loads(json_str))


@dataclass
class VisualDiff:
    """Result of a visual comparison."""
    screenshot_name: str
    reference_path: str
    actual_path: str
    diff_path: Optional[str]
    difference_percent: float
    threshold: float
    passed: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlaybackResult:
    """Result of playing back a recording."""
    success: bool
    events_played: int
    events_total: int
    assertions_passed: int
    assertions_failed: int
    screenshots_passed: int = 0
    screenshots_failed: int = 0
    failures: List[Dict[str, Any]] = field(default_factory=list)
    visual_diffs: List[VisualDiff] = field(default_factory=list)
    duration_ms: float = 0

    def to_dict(self) -> dict:
        result = asdict(self)
        result["visual_diffs"] = [d.to_dict() for d in self.visual_diffs]
        return result


class ExecutionRecorder:
    """
    Records and plays back game execution for testing.
    """

    def __init__(self):
        self._recording: Optional[Recording] = None
        self._is_recording = False
        self._start_time: float = 0

        self._playback: Optional[Recording] = None
        self._is_playing = False
        self._playback_index = 0
        self._playback_mode = PlaybackMode.VERIFY
        self._playback_result: Optional[PlaybackResult] = None

        # Callbacks for IDE notification
        self._on_event_recorded: Optional[Callable[[RecordedEvent], None]] = None
        self._on_playback_event: Optional[Callable[[int, RecordedEvent], None]] = None
        self._on_assertion_result: Optional[Callable[[Assertion, bool, str], None]] = None

        # Variables to track for snapshots
        self._tracked_variables: List[Tuple[str, str]] = []  # (store_name, var_name)

        # Labels visited during recording
        self._visited_labels: set = set()
        self._statement_count = 0

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    @property
    def current_recording(self) -> Optional[Recording]:
        return self._recording

    @property
    def playback_result(self) -> Optional[PlaybackResult]:
        return self._playback_result

    def set_tracked_variables(self, variables: List[Tuple[str, str]]) -> None:
        """Set which variables to snapshot at checkpoints."""
        self._tracked_variables = variables

    def add_tracked_variable(self, store: str, name: str) -> None:
        """Add a variable to track."""
        if (store, name) not in self._tracked_variables:
            self._tracked_variables.append((store, name))

    # Recording methods

    def start_recording(self, name: str, description: str = "") -> bool:
        """Start a new recording session."""
        if self._is_recording or self._is_playing:
            return False

        try:
            import renpy

            self._recording = Recording(
                name=name,
                description=description,
                created=time.strftime("%Y-%m-%dT%H:%M:%S"),
                game_name=getattr(renpy.config, 'name', None),
                game_version=getattr(renpy.config, 'version', None),
            )

            self._is_recording = True
            self._start_time = time.time() * 1000
            self._visited_labels = set()
            self._statement_count = 0

            # Record start event
            self._record_event(RecordedEvent(
                type=EventType.START.value,
                timestamp=0,
                label=self._get_current_label(),
            ))

            print(f"[DAP] Started recording: {name}")
            return True

        except Exception as e:
            print(f"[DAP] Failed to start recording: {e}")
            return False

    def stop_recording(self) -> Optional[Recording]:
        """Stop recording and return the recording."""
        if not self._is_recording or not self._recording:
            return None

        try:
            # Record end event
            self._record_event(RecordedEvent(
                type=EventType.END.value,
                timestamp=self._elapsed_ms(),
            ))

            # Finalize recording
            self._recording.duration_ms = self._elapsed_ms()
            self._recording.labels_visited = list(self._visited_labels)
            self._recording.statements_executed = self._statement_count

            recording = self._recording
            self._recording = None
            self._is_recording = False

            print(f"[DAP] Stopped recording: {recording.name} ({len(recording.events)} events)")
            return recording

        except Exception as e:
            print(f"[DAP] Error stopping recording: {e}")
            self._is_recording = False
            return None

    def _elapsed_ms(self) -> float:
        """Get elapsed time since recording start in milliseconds."""
        return (time.time() * 1000) - self._start_time

    def _record_event(self, event: RecordedEvent) -> None:
        """Add an event to the current recording."""
        if not self._is_recording or not self._recording:
            return

        self._recording.events.append(event)

        if self._on_event_recorded:
            self._on_event_recorded(event)

    def _get_current_label(self) -> Optional[str]:
        """Get the current label from Ren'Py context."""
        try:
            import renpy
            ctx = renpy.game.context()
            if ctx and hasattr(ctx, 'current'):
                node = renpy.game.script.lookup(ctx.current)
                if node:
                    # Try to find the label
                    if hasattr(node, 'name') and isinstance(node.name, str):
                        return node.name
                    # Walk up to find enclosing label
                    # This is simplified - real implementation would trace back
            return None
        except Exception:
            return None

    def _get_current_location(self) -> Tuple[Optional[str], Optional[int]]:
        """Get current filename and line number."""
        try:
            import renpy
            ctx = renpy.game.context()
            if ctx and hasattr(ctx, 'current'):
                node = renpy.game.script.lookup(ctx.current)
                if node:
                    return getattr(node, 'filename', None), getattr(node, 'linenumber', None)
            return None, None
        except Exception:
            return None, None

    def _snapshot_variables(self) -> Dict[str, Any]:
        """Take a snapshot of tracked variables."""
        try:
            import renpy

            snapshot = {}
            for store_name, var_name in self._tracked_variables:
                try:
                    if store_name == "store":
                        store = renpy.python.store_dicts.get("store", {})
                    else:
                        store = renpy.python.store_dicts.get(store_name, {})

                    if var_name in store:
                        value = store[var_name]
                        # Only include JSON-serializable values
                        snapshot[f"{store_name}.{var_name}"] = self._serialize_value(value)
                except Exception:
                    pass

            return snapshot
        except Exception:
            return {}

    def _serialize_value(self, value: Any) -> Any:
        """Serialize a value for JSON storage."""
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        elif isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]
        elif isinstance(value, dict):
            return {str(k): self._serialize_value(v) for k, v in value.items()}
        else:
            return repr(value)

    # Event recording hooks (called by debugger core)

    def on_checkpoint(self) -> None:
        """Called when a hard checkpoint is reached."""
        if not self._is_recording:
            return

        filename, line = self._get_current_location()
        label = self._get_current_label()

        if label:
            self._visited_labels.add(label)

        self._record_event(RecordedEvent(
            type=EventType.CHECKPOINT.value,
            timestamp=self._elapsed_ms(),
            label=label,
            filename=filename,
            line=line,
            variables=self._snapshot_variables() if self._tracked_variables else None,
        ))

    def on_menu_choice(self, items: List[Tuple[str, Any]], chosen_index: int) -> None:
        """Called when the player makes a menu choice."""
        if not self._is_recording:
            return

        filename, line = self._get_current_location()
        menu_texts = [item[0] for item in items if item[1] is not None]  # Exclude None (disabled) items
        chosen_text = menu_texts[chosen_index] if chosen_index < len(menu_texts) else ""

        # Track branch coverage
        branch_key = f"{filename}:{line}"
        if self._recording:
            self._recording.menu_branches[branch_key] = chosen_index

        self._record_event(RecordedEvent(
            type=EventType.CHOICE.value,
            timestamp=self._elapsed_ms(),
            label=self._get_current_label(),
            filename=filename,
            line=line,
            choice_index=chosen_index,
            choice_text=chosen_text,
            menu_items=menu_texts,
        ))

    def on_input(self, prompt: str, value: str) -> None:
        """Called when the player provides text input."""
        if not self._is_recording:
            return

        filename, line = self._get_current_location()

        self._record_event(RecordedEvent(
            type=EventType.INPUT.value,
            timestamp=self._elapsed_ms(),
            label=self._get_current_label(),
            filename=filename,
            line=line,
            input_prompt=prompt,
            input_value=value,
        ))

    def on_click(self) -> None:
        """Called when the player clicks to continue."""
        if not self._is_recording:
            return

        self._record_event(RecordedEvent(
            type=EventType.CLICK.value,
            timestamp=self._elapsed_ms(),
        ))

    def on_jump(self, target: str) -> None:
        """Called when a jump occurs."""
        if not self._is_recording:
            return

        self._visited_labels.add(target)

        self._record_event(RecordedEvent(
            type=EventType.JUMP.value,
            timestamp=self._elapsed_ms(),
            target_label=target,
        ))

    def on_call(self, target: str) -> None:
        """Called when a call occurs."""
        if not self._is_recording:
            return

        self._visited_labels.add(target)

        self._record_event(RecordedEvent(
            type=EventType.CALL.value,
            timestamp=self._elapsed_ms(),
            target_label=target,
        ))

    def on_return(self) -> None:
        """Called when a return occurs."""
        if not self._is_recording:
            return

        self._record_event(RecordedEvent(
            type=EventType.RETURN.value,
            timestamp=self._elapsed_ms(),
        ))

    def on_statement(self) -> None:
        """Called for each statement executed (for counting)."""
        if self._is_recording:
            self._statement_count += 1

    # Screenshot methods

    def capture_screenshot(self, name: Optional[str] = None, threshold: float = 1.0) -> bool:
        """
        Capture a screenshot as a visual regression checkpoint.

        Args:
            name: Optional name for the screenshot. Auto-generated if not provided.
            threshold: Maximum allowed difference percentage (0-100). Default 1%.

        Returns:
            True if screenshot was captured successfully.
        """
        if not self._is_recording or not self._recording:
            return False

        try:
            import renpy

            # Generate screenshot name if not provided
            if not name:
                name = f"screenshot_{len(self._recording.events):04d}"

            # Get screenshot storage path
            screenshot_dir = self._get_screenshot_dir()
            os.makedirs(screenshot_dir, exist_ok=True)

            # Capture screenshot using Ren'Py's screenshot function
            screenshot_path = os.path.join(screenshot_dir, f"{name}.png")

            # Use Ren'Py's screenshot capability
            if hasattr(renpy, 'screenshot') and hasattr(renpy.screenshot, 'screenshot'):
                # Take screenshot to a specific file
                surface = renpy.screenshot.screenshot()
                if surface:
                    import pygame
                    pygame.image.save(surface, screenshot_path)
            elif hasattr(renpy.exports, 'screenshot'):
                # Alternative method
                renpy.exports.screenshot(screenshot_path)
            else:
                print(f"[DAP] Screenshot capture not available")
                return False

            filename, line = self._get_current_location()

            self._record_event(RecordedEvent(
                type=EventType.SCREENSHOT.value,
                timestamp=self._elapsed_ms(),
                label=self._get_current_label(),
                filename=filename,
                line=line,
                screenshot_name=name,
                screenshot_threshold=threshold,
            ))

            print(f"[DAP] Captured screenshot: {name}")
            return True

        except Exception as e:
            print(f"[DAP] Failed to capture screenshot: {e}")
            return False

    def _get_screenshot_dir(self) -> str:
        """Get the directory for storing screenshots."""
        if not self._recording:
            return os.path.join(os.getcwd(), "recordings", "screenshots")

        try:
            import renpy
            base = os.path.join(renpy.config.basedir, "recordings", "screenshots")
        except Exception:
            base = os.path.join(os.getcwd(), "recordings", "screenshots")

        # Create subdirectory for this recording
        return os.path.join(base, self._recording.name.replace(" ", "_"))

    def compare_screenshot(self, reference_path: str, actual_path: str,
                          diff_path: Optional[str] = None) -> Tuple[float, Optional[str]]:
        """
        Compare two screenshots and return difference percentage.

        Args:
            reference_path: Path to reference screenshot
            actual_path: Path to actual screenshot
            diff_path: Optional path to save diff image

        Returns:
            Tuple of (difference_percent, diff_image_path or None)
        """
        try:
            # Try to use PIL for comparison
            from PIL import Image, ImageChops
            import math

            ref_img = Image.open(reference_path).convert('RGB')
            act_img = Image.open(actual_path).convert('RGB')

            # Resize if dimensions don't match
            if ref_img.size != act_img.size:
                act_img = act_img.resize(ref_img.size, Image.LANCZOS)

            # Calculate difference
            diff = ImageChops.difference(ref_img, act_img)

            # Calculate RMS difference
            h = diff.histogram()
            sq = (value * ((idx % 256) ** 2) for idx, value in enumerate(h))
            sum_of_squares = sum(sq)
            rms = math.sqrt(sum_of_squares / float(ref_img.size[0] * ref_img.size[1] * 3))

            # Convert to percentage (0-100)
            # Max RMS is 255, so normalize
            diff_percent = (rms / 255.0) * 100

            # Save diff image if requested
            saved_diff_path = None
            if diff_path and diff_percent > 0:
                # Enhance difference for visibility
                diff_enhanced = ImageChops.multiply(diff, diff)
                diff_enhanced.save(diff_path)
                saved_diff_path = diff_path

            return diff_percent, saved_diff_path

        except ImportError:
            # Fallback: simple byte comparison
            try:
                with open(reference_path, 'rb') as f1, open(actual_path, 'rb') as f2:
                    ref_bytes = f1.read()
                    act_bytes = f2.read()

                if ref_bytes == act_bytes:
                    return 0.0, None

                # Rough estimate based on byte differences
                min_len = min(len(ref_bytes), len(act_bytes))
                diff_count = sum(1 for a, b in zip(ref_bytes[:min_len], act_bytes[:min_len]) if a != b)
                diff_count += abs(len(ref_bytes) - len(act_bytes))

                diff_percent = (diff_count / max(len(ref_bytes), len(act_bytes))) * 100
                return diff_percent, None

            except Exception as e:
                print(f"[DAP] Screenshot comparison error: {e}")
                return 100.0, None

        except Exception as e:
            print(f"[DAP] Screenshot comparison error: {e}")
            return 100.0, None

    def verify_screenshot(self, event: RecordedEvent) -> Optional[VisualDiff]:
        """
        Verify a screenshot during playback.

        Returns VisualDiff with comparison results.
        """
        if not self._is_playing or not self._playback or not event.screenshot_name:
            return None

        try:
            import renpy

            name = event.screenshot_name
            threshold = event.screenshot_threshold or 1.0

            # Paths
            ref_dir = os.path.join(
                renpy.config.basedir, "recordings", "screenshots",
                self._playback.name.replace(" ", "_")
            )
            actual_dir = os.path.join(
                renpy.config.basedir, "recordings", "screenshots",
                self._playback.name.replace(" ", "_"), "actual"
            )
            diff_dir = os.path.join(
                renpy.config.basedir, "recordings", "screenshots",
                self._playback.name.replace(" ", "_"), "diff"
            )

            os.makedirs(actual_dir, exist_ok=True)
            os.makedirs(diff_dir, exist_ok=True)

            ref_path = os.path.join(ref_dir, f"{name}.png")
            actual_path = os.path.join(actual_dir, f"{name}.png")
            diff_path = os.path.join(diff_dir, f"{name}_diff.png")

            # Capture current screenshot
            if hasattr(renpy, 'screenshot') and hasattr(renpy.screenshot, 'screenshot'):
                surface = renpy.screenshot.screenshot()
                if surface:
                    import pygame
                    pygame.image.save(surface, actual_path)
            elif hasattr(renpy.exports, 'screenshot'):
                renpy.exports.screenshot(actual_path)
            else:
                return None

            # Compare
            diff_percent, saved_diff = self.compare_screenshot(ref_path, actual_path, diff_path)
            passed = diff_percent <= threshold

            result = VisualDiff(
                screenshot_name=name,
                reference_path=ref_path,
                actual_path=actual_path,
                diff_path=saved_diff,
                difference_percent=diff_percent,
                threshold=threshold,
                passed=passed,
            )

            # Update playback result
            if self._playback_result:
                if passed:
                    self._playback_result.screenshots_passed += 1
                else:
                    self._playback_result.screenshots_failed += 1
                    self._playback_result.success = False
                    self._playback_result.failures.append({
                        "type": "visual",
                        "screenshot": name,
                        "difference": diff_percent,
                        "threshold": threshold,
                        "reference": ref_path,
                        "actual": actual_path,
                        "diff": saved_diff,
                    })
                self._playback_result.visual_diffs.append(result)

            print(f"[DAP] Screenshot '{name}': {diff_percent:.2f}% diff (threshold: {threshold}%) - {'PASS' if passed else 'FAIL'}")
            return result

        except Exception as e:
            print(f"[DAP] Screenshot verification error: {e}")
            return None

    # Playback methods

    def start_playback(self, recording: Recording, mode: PlaybackMode = PlaybackMode.VERIFY) -> bool:
        """Start playing back a recording."""
        if self._is_recording or self._is_playing:
            return False

        self._playback = recording
        self._is_playing = True
        self._playback_index = 0
        self._playback_mode = mode
        self._playback_result = PlaybackResult(
            success=True,
            events_played=0,
            events_total=len(recording.events),
            assertions_passed=0,
            assertions_failed=0,
        )
        self._start_time = time.time() * 1000

        print(f"[DAP] Started playback: {recording.name} ({len(recording.events)} events)")
        return True

    def stop_playback(self) -> Optional[PlaybackResult]:
        """Stop playback and return results."""
        if not self._is_playing:
            return None

        result = self._playback_result
        if result:
            result.duration_ms = self._elapsed_ms()

        self._playback = None
        self._is_playing = False
        self._playback_index = 0

        print(f"[DAP] Stopped playback")
        return result

    def get_next_action(self) -> Optional[RecordedEvent]:
        """
        Get the next action to perform during playback.

        Returns None if playback is complete or not active.
        """
        if not self._is_playing or not self._playback:
            return None

        while self._playback_index < len(self._playback.events):
            event = self._playback.events[self._playback_index]

            # Handle screenshot verification automatically
            if event.type == EventType.SCREENSHOT.value:
                self.verify_screenshot(event)
                self._playback_index += 1
                if self._playback_result:
                    self._playback_result.events_played += 1
                continue

            # Skip non-actionable events
            if event.type in (EventType.START.value, EventType.END.value,
                             EventType.CHECKPOINT.value, EventType.JUMP.value,
                             EventType.CALL.value, EventType.RETURN.value):
                self._playback_index += 1
                if self._playback_result:
                    self._playback_result.events_played += 1
                continue

            return event

        # Playback complete
        self._finish_playback()
        return None

    def confirm_action(self, event_type: str) -> None:
        """Confirm that an action was performed during playback."""
        if not self._is_playing or not self._playback_result:
            return

        self._playback_index += 1
        self._playback_result.events_played += 1

        if self._on_playback_event and self._playback:
            idx = self._playback_index - 1
            if idx < len(self._playback.events):
                self._on_playback_event(idx, self._playback.events[idx])

        # Check assertions at this point
        self._check_assertions_at_index(self._playback_index - 1)

    def _check_assertions_at_index(self, event_index: int) -> None:
        """Check any assertions associated with this event index."""
        if not self._playback or not self._playback_result:
            return

        try:
            import renpy

            for assertion in self._playback.assertions:
                if assertion.event_index != event_index:
                    continue

                # Get actual value
                store = renpy.python.store_dicts.get(assertion.store, {})
                actual = store.get(assertion.variable)

                passed, message = assertion.check(actual)

                if passed:
                    self._playback_result.assertions_passed += 1
                else:
                    self._playback_result.assertions_failed += 1
                    self._playback_result.success = False
                    self._playback_result.failures.append({
                        "type": "assertion",
                        "event_index": event_index,
                        "variable": assertion.variable,
                        "expected": assertion.expected,
                        "actual": actual,
                        "message": message,
                    })

                if self._on_assertion_result:
                    self._on_assertion_result(assertion, passed, message)

        except Exception as e:
            print(f"[DAP] Error checking assertions: {e}")

    def _finish_playback(self) -> None:
        """Finish playback and finalize results."""
        if self._playback_result:
            self._playback_result.duration_ms = self._elapsed_ms()
        self._is_playing = False

    # Assertion management

    def add_assertion(self, event_index: int, variable: str, store: str,
                     expected: Any, comparison: str = "eq") -> bool:
        """Add an assertion to the current recording."""
        if not self._is_recording or not self._recording:
            return False

        self._recording.assertions.append(Assertion(
            event_index=event_index,
            variable=variable,
            store=store,
            expected=expected,
            comparison=comparison,
        ))
        return True

    def add_assertion_current(self, variable: str, store: str = "store",
                             expected: Any = None, comparison: str = "eq") -> bool:
        """Add an assertion at the current event."""
        if not self._is_recording or not self._recording:
            return False

        # If expected is None, capture current value
        if expected is None:
            try:
                import renpy
                store_dict = renpy.python.store_dicts.get(store, {})
                expected = self._serialize_value(store_dict.get(variable))
            except Exception:
                return False

        event_index = len(self._recording.events) - 1
        return self.add_assertion(event_index, variable, store, expected, comparison)

    # Export methods

    def export_to_renpy_test(self, recording: Recording) -> str:
        """Export a recording to Ren'Py test script format."""
        lines = [
            f"# Auto-generated test from recording: {recording.name}",
            f"# Created: {recording.created}",
            f"# Description: {recording.description}",
            "",
            "testcase test_" + recording.name.replace(" ", "_").replace("-", "_") + ":",
            "",
        ]

        indent = "    "

        for event in recording.events:
            if event.type == EventType.START.value:
                if event.label:
                    lines.append(f"{indent}# Starting from label: {event.label}")
                    lines.append(f'{indent}jump "{event.label}"')
                    lines.append("")

            elif event.type == EventType.CHOICE.value:
                lines.append(f"{indent}# Menu choice at {event.filename}:{event.line}")
                if event.choice_text:
                    lines.append(f'{indent}"{event.choice_text}"')
                else:
                    lines.append(f"{indent}choice {event.choice_index}")
                lines.append("")

            elif event.type == EventType.INPUT.value:
                lines.append(f'{indent}# Input: {event.input_prompt}')
                lines.append(f'{indent}type "{event.input_value}"')
                lines.append("")

            elif event.type == EventType.CLICK.value:
                lines.append(f"{indent}click")

            elif event.type == EventType.CHECKPOINT.value:
                if event.label:
                    lines.append(f"{indent}# Checkpoint: {event.label}")

        # Add assertions
        if recording.assertions:
            lines.append("")
            lines.append(f"{indent}# Assertions")
            for assertion in recording.assertions:
                var_ref = f"{assertion.store}.{assertion.variable}" if assertion.store != "store" else assertion.variable
                if assertion.comparison == "eq":
                    lines.append(f'{indent}assert {var_ref} == {assertion.expected!r}')
                elif assertion.comparison == "ne":
                    lines.append(f'{indent}assert {var_ref} != {assertion.expected!r}')
                elif assertion.comparison == "gt":
                    lines.append(f'{indent}assert {var_ref} > {assertion.expected!r}')
                elif assertion.comparison == "lt":
                    lines.append(f'{indent}assert {var_ref} < {assertion.expected!r}')

        return "\n".join(lines)

    def export_to_json(self, recording: Recording) -> str:
        """Export a recording to JSON format."""
        return recording.to_json()


# Storage for recordings
class RecordingStorage:
    """Manages saving and loading recordings."""

    def __init__(self, base_path: Optional[str] = None):
        self._base_path = base_path

    def _get_storage_path(self) -> str:
        """Get the path to store recordings."""
        if self._base_path:
            return self._base_path

        try:
            import renpy
            # Store in game's base directory
            return os.path.join(renpy.config.basedir, "recordings")
        except Exception:
            return os.path.join(os.getcwd(), "recordings")

    def _ensure_storage_exists(self) -> None:
        """Ensure the storage directory exists."""
        path = self._get_storage_path()
        os.makedirs(path, exist_ok=True)

    def save(self, recording: Recording) -> bool:
        """Save a recording to disk."""
        try:
            self._ensure_storage_exists()

            filename = recording.name.replace(" ", "_") + ".json"
            filepath = os.path.join(self._get_storage_path(), filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(recording.to_json())

            print(f"[DAP] Saved recording to: {filepath}")
            return True

        except Exception as e:
            print(f"[DAP] Failed to save recording: {e}")
            return False

    def load(self, name: str) -> Optional[Recording]:
        """Load a recording from disk."""
        try:
            filename = name.replace(" ", "_") + ".json"
            filepath = os.path.join(self._get_storage_path(), filename)

            with open(filepath, "r", encoding="utf-8") as f:
                return Recording.from_json(f.read())

        except Exception as e:
            print(f"[DAP] Failed to load recording: {e}")
            return None

    def list_recordings(self) -> List[Dict[str, Any]]:
        """List all available recordings."""
        try:
            self._ensure_storage_exists()
            path = self._get_storage_path()

            recordings = []
            for filename in os.listdir(path):
                if filename.endswith(".json"):
                    filepath = os.path.join(path, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            recordings.append({
                                "name": data.get("name", filename[:-5]),
                                "created": data.get("created", ""),
                                "description": data.get("description", ""),
                                "duration_ms": data.get("duration_ms", 0),
                                "event_count": len(data.get("events", [])),
                                "assertion_count": len(data.get("assertions", [])),
                            })
                    except Exception:
                        pass

            return sorted(recordings, key=lambda r: r.get("created", ""), reverse=True)

        except Exception as e:
            print(f"[DAP] Failed to list recordings: {e}")
            return []

    def delete(self, name: str) -> bool:
        """Delete a recording."""
        try:
            filename = name.replace(" ", "_") + ".json"
            filepath = os.path.join(self._get_storage_path(), filename)

            if os.path.exists(filepath):
                os.remove(filepath)
                print(f"[DAP] Deleted recording: {name}")
                return True
            return False

        except Exception as e:
            print(f"[DAP] Failed to delete recording: {e}")
            return False


# Global instances
_recorder: Optional[ExecutionRecorder] = None
_storage: Optional[RecordingStorage] = None


def get_recorder() -> ExecutionRecorder:
    """Get the global execution recorder instance."""
    global _recorder
    if _recorder is None:
        _recorder = ExecutionRecorder()
    return _recorder


def get_storage() -> RecordingStorage:
    """Get the global recording storage instance."""
    global _storage
    if _storage is None:
        _storage = RecordingStorage()
    return _storage
