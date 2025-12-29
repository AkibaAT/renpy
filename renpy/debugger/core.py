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
Core debugger implementation for Ren'Py.

This module contains the DebuggerCore class which coordinates all
debugging functionality including breakpoints, stepping, and variable
inspection.
"""

from __future__ import annotations

import sys
import threading
from enum import Enum
from types import FrameType
from typing import Any, Callable, Dict, Optional, Tuple, TYPE_CHECKING

from .breakpoints import BreakpointManager, Breakpoint
from .variables import VariableInspector

if TYPE_CHECKING:
    from .dap_server import DAPServer


class DebuggerState(Enum):
    """Debugger execution states."""

    DISCONNECTED = "disconnected"  # No debugger attached
    RUNNING = "running"  # Executing normally
    PAUSED = "paused"  # Paused at breakpoint or by user
    STEPPING = "stepping"  # Single-stepping


class StepMode(Enum):
    """Stepping modes."""

    NONE = "none"  # Not stepping
    INTO = "into"  # Step into (single statement/line)
    OVER = "over"  # Step over (skip calls)
    OUT = "out"  # Step out (run until return)


class DebuggerCore:
    """
    Central debugger coordinator.

    Manages debugger state, breakpoints, and coordinates between
    the DAP server and Ren'Py/Python execution.
    """

    def __init__(self):
        self.state = DebuggerState.DISCONNECTED
        self.step_mode = StepMode.NONE
        self.step_depth = 0  # Call depth for step over/out

        # Threading synchronization
        self._pause_event = threading.Event()
        self._pause_event.set()  # Start unpaused
        self._lock = threading.Lock()

        self.breakpoint_manager = BreakpointManager()
        self.variable_inspector = VariableInspector()

        self._dap_server: Optional[DAPServer] = None

        self._current_node: Optional[Any] = None
        self._current_frame: Optional[FrameType] = None
        self._current_filename: Optional[str] = None
        self._current_line: int = 0

        self._original_trace: Optional[Callable] = None
        self._trace_enabled = False
        self._trace_requested = False
        self._python_call_depth = 0
        self._python_step_start_depth = 0

        self._hook_registered = False
        self._pending_jump: Optional[str] = None
        self._pause_after_jump = False

        self._break_on_raised = False
        self._break_on_uncaught = True

        self._show_statement_locations: Dict[Tuple[str, str], dict] = {}
        self._function_breakpoints: dict[str, dict] = {}
        self._last_label: Optional[str] = None

        self._pending_rollback = False
        self._current_exception: Optional[tuple] = None
        self._original_excepthook: Optional[Callable] = None

        self._shutdown_requested = False

    def attach(self, dap_server: DAPServer) -> None:
        """
        Attach the debugger and start listening for events.

        Called when a debug client connects.
        """
        with self._lock:
            self._dap_server = dap_server
            self.state = DebuggerState.RUNNING
            self._pause_event.set()

            if not self._hook_registered:
                self._register_hooks()
                self._hook_registered = True

    def detach(self) -> None:
        """
        Detach the debugger.

        Called when a debug client disconnects.
        """
        with self._lock:
            self._dap_server = None
            self.state = DebuggerState.DISCONNECTED
            self.step_mode = StepMode.NONE
            self._pause_event.set()
            self._disable_trace()

    def shutdown(self) -> None:
        """
        Fully shut down the debugger.

        Called when the game is quitting. This ensures all threads
        are stopped and resources are released. Shutdown is prioritized
        over all other operations.
        """
        print("[DAP] Debugger shutting down")

        self._shutdown_requested = True
        self._pause_event.set()
        self.detach()
        self._unregister_hooks()
        self._hook_registered = False
        self._function_breakpoints.clear()
        self.breakpoint_manager.clear_all()

    def _on_reload(self) -> None:
        """
        Handle script reload (Shift+R).

        Re-registers hooks that were cleared during reload and invalidates
        caches that may contain stale data. If we were paused at a breakpoint,
        continues execution since the old context is no longer valid.
        """
        print("[DAP] Recovering from script reload")

        # If we were paused, we need to continue - the old context is gone
        was_paused = self.state == DebuggerState.PAUSED
        if was_paused:
            with self._lock:
                self.state = DebuggerState.RUNNING
                self.step_mode = StepMode.NONE
                self._pause_event.set()

            # Notify the IDE that we continued
            if self._dap_server:
                self._dap_server.send_event("continued", {
                    "threadId": 1,
                    "allThreadsContinued": True
                })

        # Clear stale execution context
        self._current_node = None
        self._current_frame = None
        self._current_filename = None
        self._current_line = 0

        # Hooks were cleared when renpy.config was restored
        self._hook_registered = False
        self._register_hooks()
        self._hook_registered = True

        # File paths may have changed
        self.breakpoint_manager.invalidate_path_cache()

        # Clear tracked show/scene statements as they may be stale
        self._show_statement_locations.clear()

    def _register_hooks(self) -> None:
        """Register debugger hooks with Ren'Py."""
        try:
            import renpy

            if hasattr(renpy, "config") and hasattr(renpy.config, "pre_statement_callbacks"):
                if self._on_statement_hook not in renpy.config.pre_statement_callbacks:
                    renpy.config.pre_statement_callbacks.append(self._on_statement_hook)

            self._install_exception_hook()
        except ImportError:
            pass

    def _unregister_hooks(self) -> None:
        """Remove debugger hooks from Ren'Py."""
        try:
            import renpy

            if hasattr(renpy, "config") and hasattr(renpy.config, "pre_statement_callbacks"):
                if self._on_statement_hook in renpy.config.pre_statement_callbacks:
                    renpy.config.pre_statement_callbacks.remove(self._on_statement_hook)

            self._uninstall_exception_hook()
        except ImportError:
            pass

    def _install_exception_hook(self) -> None:
        """Install custom exception hook to catch uncaught exceptions."""
        import sys

        if self._original_excepthook is None:
            self._original_excepthook = sys.excepthook

        def debugger_excepthook(exc_type, exc_value, exc_tb):
            self._current_exception = (exc_type, exc_value, exc_tb)

            if self._break_on_uncaught and self.state != DebuggerState.DISCONNECTED:
                self._pause_on_exception(exc_type, exc_value, exc_tb)

            if self._original_excepthook:
                self._original_excepthook(exc_type, exc_value, exc_tb)

        sys.excepthook = debugger_excepthook

    def _uninstall_exception_hook(self) -> None:
        """Restore original exception hook."""
        import sys

        if self._original_excepthook is not None:
            sys.excepthook = self._original_excepthook
            self._original_excepthook = None

    def _pause_on_exception(self, exc_type, exc_value, exc_tb) -> None:
        """Pause execution when an exception is caught."""
        if self._shutdown_requested:
            return

        import traceback

        self._current_exception = (exc_type, exc_value, exc_tb)

        if exc_tb:
            tb = exc_tb
            while tb.tb_next:
                tb = tb.tb_next
            self._current_filename = tb.tb_frame.f_code.co_filename
            self._current_line = tb.tb_lineno
            self._current_frame = tb.tb_frame

        with self._lock:
            self.state = DebuggerState.PAUSED
            self._pause_event.clear()

        if self._dap_server:
            self._dap_server.send_event("stopped", {
                "reason": "exception",
                "threadId": 1,
                "allThreadsStopped": True,
                "description": str(exc_value),
                "text": f"{exc_type.__name__}: {exc_value}",
            })

        self._wait_for_resume()

    def set_exception_breakpoints(self, break_on_raised: bool, break_on_uncaught: bool) -> None:
        """Configure exception breakpoints."""
        self._break_on_raised = break_on_raised
        self._break_on_uncaught = break_on_uncaught

        if break_on_raised:
            self._enable_exception_trace()
        else:
            self._disable_exception_trace()

        print(f"[DAP] Exception breakpoints: raised={break_on_raised}, uncaught={break_on_uncaught}")

    def _enable_exception_trace(self) -> None:
        """Enable tracing to catch raised exceptions."""
        import sys

        def trace_exceptions(frame, event, arg):
            if event == "exception" and self._break_on_raised:
                exc_type, exc_value, exc_tb = arg
                # Skip internal exceptions
                if self._should_break_on_exception(exc_type, frame):
                    self._pause_on_exception(exc_type, exc_value, exc_tb)
            return trace_exceptions

        sys.settrace(trace_exceptions)

    def _disable_exception_trace(self) -> None:
        """Disable exception tracing."""
        import sys
        sys.settrace(None)

    def _should_break_on_exception(self, exc_type, frame) -> bool:
        """Check if we should break on this exception."""
        if exc_type in (StopIteration, GeneratorExit, KeyboardInterrupt, SystemExit):
            return False

        filename = frame.f_code.co_filename
        if "debugger" in filename:
            return False

        return True

    def get_exception_info(self) -> Optional[dict]:
        """Get information about the current exception."""
        if not self._current_exception:
            return None

        exc_type, exc_value, exc_tb = self._current_exception
        import traceback

        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        full_traceback = "".join(tb_lines)

        return {
            "exceptionId": exc_type.__name__,
            "description": str(exc_value),
            "breakMode": "always",
            "details": {
                "message": str(exc_value),
                "typeName": exc_type.__name__,
                "fullTypeName": f"{exc_type.__module__}.{exc_type.__name__}",
                "stackTrace": full_traceback,
            },
        }

    def _on_statement_hook(self, node: Any) -> None:
        """
        Hook called before each Ren'Py statement executes.

        This is registered as a pre_statement_callback.
        """
        # Exit immediately if shutdown is in progress
        if self._shutdown_requested:
            return

        if self.state == DebuggerState.DISCONNECTED:
            return

        if self._trace_requested and not self._trace_enabled:
            self._enable_trace_in_main_thread()

        self._check_pending_jump()
        self._check_pending_rollback()

        self._current_node = node
        self._current_filename = getattr(node, "filename", None)
        self._current_line = getattr(node, "linenumber", 0)

        self._track_show_statement(node)

        if self._pause_after_jump:
            self._pause_after_jump = False
            self._disable_skip_mode()
            self._pause("goto")
            return

        if self._function_breakpoints:
            current_label = self._get_current_label()
            if current_label and current_label != self._last_label:
                self._last_label = current_label
                if current_label in self._function_breakpoints:
                    fb = self._function_breakpoints[current_label]
                    fb["hit_count"] = fb.get("hit_count", 0) + 1
                    self._pause("function breakpoint")
                    return

        if self._current_filename and self._current_line:
            bp = self.breakpoint_manager.check_breakpoint(self._current_filename, self._current_line)
            if bp:
                self._pause_at_breakpoint(bp)
                return

        if self.step_mode == StepMode.INTO:
            self._pause_for_step()
        elif self.step_mode == StepMode.OVER:
            current_depth = self._get_call_depth()
            if current_depth <= self.step_depth:
                self._pause_for_step()

    def _get_call_depth(self) -> int:
        """Get the current Ren'Py call stack depth."""
        try:
            import renpy

            ctx = renpy.game.context()
            return len(ctx.return_stack) if ctx else 0
        except Exception:
            return 0

    def _pause_at_breakpoint(self, bp: Breakpoint) -> None:
        """Pause execution at a breakpoint."""
        bp.hit_count += 1

        if not bp.should_break():
            return

        if bp.log_message:
            self._log_breakpoint_message(bp)
            return

        self._cleanup_temp_breakpoint()
        self._pause("breakpoint", bp.id)

    def _log_breakpoint_message(self, bp: Breakpoint) -> None:
        """Log a message for a logpoint without pausing."""
        message = bp.log_message
        if not message:
            return

        import re
        def replace_expr(match):
            expr = match.group(1)
            try:
                import renpy
                result = renpy.python.py_eval(expr)
                return str(result)
            except Exception as e:
                return f"<{expr}: {e}>"

        message = re.sub(r'\{([^}]+)\}', replace_expr, message)

        if self._dap_server:
            self._dap_server.send_event("output", {
                "category": "console",
                "output": f"[Logpoint] {message}\n",
                "source": {"path": bp.file},
                "line": bp.line,
            })

    def _pause_for_step(self) -> None:
        """Pause execution for single-step."""
        self.step_mode = StepMode.NONE
        self._pause("step")

    def _pause(self, reason: str, breakpoint_id: Optional[int] = None) -> None:
        """Pause execution and wait for resume."""
        if self._shutdown_requested:
            return

        with self._lock:
            self.state = DebuggerState.PAUSED
            self._pause_event.clear()

        self.variable_inspector.set_frame(self._current_frame)

        if self._dap_server:
            body = {"reason": reason, "threadId": 1, "allThreadsStopped": True}
            if breakpoint_id is not None:
                body["hitBreakpointIds"] = [breakpoint_id]
            self._dap_server.send_event("stopped", body)

        self._wait_for_resume()
        self._check_pending_jump()

    def _check_pending_jump(self) -> None:
        """Check for and execute any pending jump."""
        if self._pending_jump is not None:
            import renpy
            target = self._pending_jump
            self._pending_jump = None
            raise renpy.game.JumpException(target)

    def _check_pending_rollback(self) -> None:
        """Check for and execute any pending rollback (step back)."""
        if self._pending_rollback:
            self._pending_rollback = False
            try:
                import renpy
                renpy.exports.rollback(force=True, checkpoints=1)
            except Exception as e:
                print(f"[DAP] Rollback failed: {e}")

    def _wait_for_resume(self) -> None:
        """Wait until execution is resumed."""
        while not self._pause_event.is_set():
            if self._shutdown_requested:
                break

            self._pause_event.wait(timeout=0.1)

            if self._shutdown_requested:
                break

            if self.state == DebuggerState.DISCONNECTED:
                break

            if self._dap_server is None:
                with self._lock:
                    self.state = DebuggerState.DISCONNECTED
                    self._pause_event.set()
                break

            if self._dap_server and self._dap_server._client is None:
                with self._lock:
                    self.state = DebuggerState.DISCONNECTED
                    self._dap_server = None
                    self._pause_event.set()
                break

    def pause(self) -> None:
        """Pause execution at the next opportunity."""
        with self._lock:
            if self.state == DebuggerState.RUNNING:
                self.step_mode = StepMode.INTO
                self.state = DebuggerState.STEPPING

    def resume(self) -> None:
        """Resume execution."""
        with self._lock:
            self.state = DebuggerState.RUNNING
            self.step_mode = StepMode.NONE
            self.variable_inspector.clear_references()
            self._pause_event.set()

        if self._dap_server:
            self._dap_server.send_event("continued", {"threadId": 1, "allThreadsContinued": True})

    def step_back(self) -> dict:
        """Step backwards using Ren'Py's rollback system."""
        try:
            import renpy

            if not renpy.can_rollback():
                return {"success": False, "message": "Cannot rollback - no rollback data available"}

            self._pending_rollback = True

            with self._lock:
                self.state = DebuggerState.RUNNING
                self.step_mode = StepMode.INTO
                self.variable_inspector.clear_references()
                self._pause_event.set()

            if self._dap_server:
                self._dap_server.send_event("continued", {"threadId": 1, "allThreadsContinued": True})

            return {"success": True}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def step(self, mode: StepMode) -> None:
        """Start stepping with the given mode."""
        with self._lock:
            self.step_mode = mode
            self.step_depth = self._get_call_depth()
            self._python_step_start_depth = self._python_call_depth
            self.state = DebuggerState.STEPPING
            self.variable_inspector.clear_references()
            self._pause_event.set()

    def _enable_trace(self) -> None:
        """Request Python tracing to be enabled."""
        self._trace_requested = True

    def _enable_trace_in_main_thread(self) -> None:
        """Actually enable tracing - must be called from main thread."""
        if self._trace_enabled:
            return

        self._original_trace = sys.gettrace()
        sys.settrace(self._trace_function)
        self._trace_enabled = True
        print("[DAP] Python tracing enabled")

    def _disable_trace(self) -> None:
        """Disable Python tracing."""
        self._trace_requested = False

        if not self._trace_enabled:
            return

        sys.settrace(self._original_trace)
        self._original_trace = None
        self._trace_enabled = False
        print("[DAP] Python tracing disabled")

    def _trace_function(self, frame: FrameType, event: str, arg: Any) -> Optional[Callable]:
        """Python trace callback for debugging Python code."""
        if self._shutdown_requested:
            return None

        if self.state == DebuggerState.DISCONNECTED:
            return None

        filename = frame.f_code.co_filename

        if not self._is_game_file(filename):
            return self._trace_function

        if event == "line":
            self._current_frame = frame
            line = frame.f_lineno

            bp = self.breakpoint_manager.check_breakpoint(filename, line)
            if bp:
                self._current_filename = filename
                self._current_line = line
                self._pause_at_breakpoint(bp)
            elif self.step_mode == StepMode.INTO:
                self._current_filename = filename
                self._current_line = line
                self._pause_for_step()
            elif self.step_mode == StepMode.OVER:
                if self._python_call_depth <= self._python_step_start_depth:
                    self._current_filename = filename
                    self._current_line = line
                    self._pause_for_step()

        elif event == "call":
            self._python_call_depth += 1

        elif event == "return":
            self._python_call_depth -= 1
            if self.step_mode == StepMode.OUT and self._python_call_depth < self._python_step_start_depth:
                self._current_frame = frame
                self._pause_for_step()

        return self._trace_function

    def _is_game_file(self, filename: str) -> bool:
        """Check if a file is a game file (not Ren'Py internals)."""
        if not filename:
            return False

        if "renpy" in filename.lower() and "game" not in filename.lower():
            return False

        if filename.endswith(".rpy") or filename.endswith(".rpym"):
            return True

        try:
            import renpy

            if hasattr(renpy, "config") and hasattr(renpy.config, "gamedir"):
                gamedir = renpy.config.gamedir
                if gamedir and filename.startswith(gamedir):
                    return True
        except ImportError:
            pass

        return False

    def get_stack_trace(self) -> list[dict]:
        """Build a unified stack trace combining Ren'Py and Python frames."""
        frames = []
        frame_id = 1

        if self._current_filename and self._current_line:
            name = self._get_current_name()
            abs_path = self._get_absolute_path(self._current_filename)
            frames.append(
                {
                    "id": frame_id,
                    "name": name,
                    "source": {"path": abs_path, "name": self._get_source_name(self._current_filename)},
                    "line": self._current_line,
                    "column": 0,
                }
            )
            frame_id += 1

        if self._current_frame:
            frame = self._current_frame.f_back
            while frame:
                filename = frame.f_code.co_filename
                if self._is_game_file(filename):
                    abs_path = self._get_absolute_path(filename)
                    frames.append(
                        {
                            "id": frame_id,
                            "name": frame.f_code.co_name,
                            "source": {"path": abs_path, "name": self._get_source_name(filename)},
                            "line": frame.f_lineno,
                            "column": 0,
                        }
                    )
                    frame_id += 1
                frame = frame.f_back

        try:
            import renpy

            ctx = renpy.game.context()
            if ctx and ctx.return_stack:
                for name in reversed(ctx.return_stack):
                    try:
                        node = renpy.game.script.lookup(name)
                        if node:
                            abs_path = self._get_absolute_path(node.filename)
                            frames.append(
                                {
                                    "id": frame_id,
                                    "name": f"return to {name}" if isinstance(name, str) else f"return to {name[0]}",
                                    "source": {
                                        "path": abs_path,
                                        "name": self._get_source_name(node.filename),
                                    },
                                    "line": node.linenumber,
                                    "column": 0,
                                }
                            )
                            frame_id += 1
                    except Exception:
                        pass
        except Exception:
            pass

        return frames

    def _get_current_name(self) -> str:
        """Get a display name for the current execution point."""
        if self._current_node:
            node_type = type(self._current_node).__name__

            if hasattr(self._current_node, "what"):
                what = self._current_node.what
                if what and len(what) > 30:
                    what = what[:30] + "..."
                return f'say "{what}"'
            elif hasattr(self._current_node, "target"):
                return f"{node_type.lower()} {self._current_node.target}"
            elif hasattr(self._current_node, "label"):
                return f"label {self._current_node.label}"
            else:
                return node_type.lower()

        if self._current_frame:
            return self._current_frame.f_code.co_name

        return "<unknown>"

    def _get_source_name(self, path: str) -> str:
        """Get a short display name for a source file."""
        if not path:
            return "<unknown>"
        import os

        return os.path.basename(path)

    def _get_absolute_path(self, path: str) -> str:
        """Convert a potentially relative path to an absolute path."""
        if not path:
            return path

        import os

        if "://" in path:
            if path.startswith("file://"):
                path = path[7:]
            else:
                path = path.split(":", 1)[1]
                if path.startswith("//"):
                    path = path[2:]
        elif path.startswith("vscode-local:"):
            path = path[13:]

        if os.path.isabs(path):
            return os.path.normpath(path)

        try:
            import renpy

            if hasattr(renpy, "config") and hasattr(renpy.config, "basedir"):
                basedir = renpy.config.basedir
                if basedir:
                    full_path = os.path.join(basedir, path)
                    if os.path.exists(full_path):
                        return os.path.normpath(full_path)
        except ImportError:
            pass

        return os.path.abspath(path)

    def set_breakpoints(self, file: str, breakpoint_data: list[dict]) -> list[Breakpoint]:
        """Set breakpoints for a file."""
        bps = self.breakpoint_manager.set_breakpoints(file, breakpoint_data)

        if breakpoint_data:
            self._enable_trace()

        return bps

    def clear_breakpoints(self, file: str) -> None:
        """Clear breakpoints for a file."""
        self.breakpoint_manager.clear_file(file)

    def set_function_breakpoints(self, breakpoints: list[dict]) -> list[dict]:
        """
        Set function breakpoints (break on label entry).

        Args:
            breakpoints: List of dicts with 'name' (label name) and optional 'condition'

        Returns:
            List of verified breakpoint dicts for DAP response
        """
        import renpy

        self._function_breakpoints.clear()

        verified = []
        bp_id = 1000

        for bp_data in breakpoints:
            label_name = bp_data.get("name", "")
            condition = bp_data.get("condition")

            if not label_name:
                verified.append({
                    "verified": False,
                    "message": "No label name provided",
                })
                continue

            label_exists = False
            label_file = None
            label_line = 0

            try:
                if hasattr(renpy.game, "script") and renpy.game.script:
                    namemap = renpy.game.script.namemap
                    if label_name in namemap:
                        node = namemap[label_name]
                        label_exists = True
                        label_file = getattr(node, "filename", None)
                        label_line = getattr(node, "linenumber", 0)
            except Exception:
                pass

            if label_exists:
                self._function_breakpoints[label_name] = {
                    "id": bp_id,
                    "name": label_name,
                    "condition": condition,
                    "hit_count": 0,
                }
                verified.append({
                    "id": bp_id,
                    "verified": True,
                    "source": {"path": label_file} if label_file else None,
                    "line": label_line,
                })
            else:
                verified.append({
                    "verified": False,
                    "message": f"Label '{label_name}' not found",
                })

            bp_id += 1

        return verified

    # Variable inspection passthrough

    def get_scopes(self, frame_id: int) -> list[dict]:
        """Get variable scopes for a frame."""
        return self.variable_inspector.get_scopes(frame_id)

    def get_variables(self, reference: int) -> list[dict]:
        """Get variables for a reference."""
        return self.variable_inspector.get_variables(reference)

    def set_variable(self, reference: int, name: str, value: str) -> dict:
        """Set a variable's value."""
        return self.variable_inspector.set_variable(reference, name, value)

    # Navigation and goto functionality

    def get_goto_targets(self, filename: str, line: int) -> list[dict]:
        """
        Get valid goto targets (labels) for a source location.

        Args:
            filename: Source file path
            line: Line number (used to find nearby/relevant labels)

        Returns:
            List of DAP GotoTarget objects
        """
        targets = []

        try:
            import renpy

            # Get all labels from the script
            if hasattr(renpy.game, "script") and renpy.game.script:
                script = renpy.game.script
                abs_filename = self._get_absolute_path(filename)

                # Iterate through all labels (nodes)
                # The keys are AST nodes, but each node has a .name attribute that is the label name
                for node in script.namemap.values():
                    # Get the label name from the node
                    label_name = getattr(node, "name", None)

                    # Skip non-string labels (internal nodes with integer IDs, etc.)
                    if not isinstance(label_name, str):
                        continue

                    # Skip internal labels (starting with _)
                    if label_name.startswith("_"):
                        continue

                    # Get label location
                    label_file = getattr(node, "filename", "")
                    label_line = getattr(node, "linenumber", 0)

                    # Convert to absolute path for comparison
                    abs_label_file = self._get_absolute_path(label_file)

                    target = {
                        "id": hash(label_name) & 0x7FFFFFFF,  # Positive int ID
                        "label": label_name,
                        "line": label_line,
                        "column": 0,
                    }

                    # Include source if it's a different file
                    if abs_label_file != abs_filename:
                        target["instructionPointerReference"] = abs_label_file

                    targets.append(target)

        except Exception as e:
            print(f"[DAP] Error getting goto targets: {e}")
            import traceback
            traceback.print_exc()

        # Sort by line number, with labels in the same file first
        abs_filename = self._get_absolute_path(filename)
        targets.sort(key=lambda t: (
            0 if t.get("instructionPointerReference", abs_filename) == abs_filename else 1,
            t["line"]
        ))

        return targets

    def get_label_for_line(self, filename: str, line: int) -> Optional[str]:
        """
        Find the label that contains a given line.

        Args:
            filename: Source file path
            line: Line number

        Returns:
            Label name, or None if not found
        """
        try:
            import renpy
            import os

            if not hasattr(renpy.game, "script") or not renpy.game.script:
                return None

            script = renpy.game.script
            abs_filename = self._get_absolute_path(filename)

            # Find all labels in this file, sorted by line number
            # Iterate values (nodes) and check node.name for the label string
            file_labels = []
            for node in script.namemap.values():
                # Get the label name from the node
                label_name = getattr(node, "name", None)

                # Skip non-string labels (internal nodes with integer IDs, etc.)
                if not isinstance(label_name, str):
                    continue

                # Skip internal labels
                if label_name.startswith("_"):
                    continue

                label_file = getattr(node, "filename", "")
                abs_label_file = self._get_absolute_path(label_file)

                # Check both absolute and basename matching
                if abs_label_file == abs_filename or os.path.basename(label_file) == os.path.basename(filename):
                    label_line = getattr(node, "linenumber", 0)
                    file_labels.append((label_line, label_name))

            # Sort by line number descending to find the nearest label before the target line
            file_labels.sort(key=lambda x: x[0], reverse=True)

            for label_line, label_name in file_labels:
                if label_line <= line:
                    return label_name

        except Exception as e:
            print(f"[DAP] Error finding label for line: {e}")
            import traceback
            traceback.print_exc()

        return None

    def jump_to_label(self, label_name: str, pause_after: bool = True) -> bool:
        """
        Jump execution to a label.

        This queues the jump to be executed in the main Ren'Py thread.
        The actual jump happens when the next statement hook fires.

        Args:
            label_name: The label to jump to
            pause_after: Whether to pause after arriving at the label

        Returns:
            True if the jump was queued, False if the label doesn't exist
        """
        try:
            import renpy

            # Verify label exists
            if not hasattr(renpy.game, "script") or not renpy.game.script:
                return False

            if label_name not in renpy.game.script.namemap:
                return False

            # Queue the jump to be executed in the main thread
            print(f"[DAP] jump_to_label: Queuing jump to '{label_name}', pause_after={pause_after}")
            self._pending_jump = label_name
            self._pause_after_jump = pause_after

            # Resume execution so the hook can process the jump
            print(f"[DAP] jump_to_label: Calling resume()")
            self.resume()

            # Force the game to advance past any current interaction
            # This ensures the jump happens immediately without waiting for user click
            try:
                import pygame

                # Enable skip mode - this makes the SayBehavior return True immediately
                # on TIMEEVENT when skipping == "fast"
                self._enable_skip_mode()

                # Set a timeout of 0 to force the interaction to end immediately
                if renpy.game.interface:
                    renpy.game.interface.timeout(0)
                    # Post a TIMEEVENT to wake up the event loop and trigger skip processing
                    time_event = pygame.event.Event(renpy.display.core.TIMEEVENT, {"modal": False})
                    pygame.event.post(time_event)
                    print(f"[DAP] jump_to_label: Enabled skip mode, set timeout(0), posted TIMEEVENT")
            except Exception as e:
                print(f"[DAP] jump_to_label: Could not force interaction end: {e}")

            return True

        except Exception as e:
            print(f"[DAP] Error queuing jump to label: {e}")

        return False

    def run_to_line(self, filename: str, line: int) -> dict:
        """
        Run execution to a specific line, using skip mode for speed.

        This will:
        1. Set a temporary breakpoint on the target line
        2. Find the label containing the target line (if any)
        3. Enable skip mode for fast execution
        4. Jump to that label (which resumes execution) or just resume

        If the line is not inside a label (e.g., init block), we just
        set a breakpoint and continue without jumping.

        Args:
            filename: Target file path
            line: Target line number

        Returns:
            Dict with success status and message
        """
        try:
            import renpy

            abs_filename = self._get_absolute_path(filename)

            # Set a temporary breakpoint on the target line FIRST
            # (before resuming execution)
            temp_bp_data = [{"line": line, "_temporary": True}]
            self.breakpoint_manager.set_breakpoints(abs_filename, temp_bp_data)

            # Store info about the temporary breakpoint for cleanup
            self._temp_breakpoint = (abs_filename, line)

            # Enable skip mode for faster execution
            self._enable_skip_mode()

            # Find the label containing this line (may be None for init blocks, etc.)
            target_label = self.get_label_for_line(filename, line)

            if target_label:
                # Check if we're already in this label's scope
                current_label = self._get_current_label()
                if current_label != target_label:
                    # Jump to the label (this will resume execution)
                    # pause_after=False so we keep running until the breakpoint
                    if not self.jump_to_label(target_label, pause_after=False):
                        return {"success": False, "message": f"Failed to jump to label '{target_label}'"}
                    return {"success": True, "message": f"Running to line {line} in '{target_label}'"}

            # No jump needed, just resume execution
            self.resume()

            if target_label:
                return {"success": True, "message": f"Running to line {line} in '{target_label}'"}
            else:
                return {"success": True, "message": f"Running to line {line} (breakpoint set, continuing)"}

        except Exception as e:
            return {"success": False, "message": str(e)}

    def _track_show_statement(self, node: Any) -> None:
        """
        Track show/scene/screen statements for Scene Inspector.

        When a Show, Scene, or ShowScreen node executes, record its location
        so we can jump to the actual statement that displayed an image or screen.
        """
        try:
            import os
            import renpy

            node_type = type(node).__name__
            filename = getattr(node, 'filename', None)
            linenumber = getattr(node, 'linenumber', 0)

            if not filename or not linenumber:
                return

            # Convert relative filename to absolute path
            abs_filename = filename
            if not os.path.isabs(filename):
                # Try basedir first, then gamedir
                if renpy.config.basedir:
                    candidate = os.path.join(renpy.config.basedir, filename)
                    if os.path.isfile(candidate):
                        abs_filename = candidate
                if abs_filename == filename and renpy.config.gamedir:
                    candidate = os.path.join(renpy.config.gamedir, filename)
                    if os.path.isfile(candidate):
                        abs_filename = candidate

            # Track Show and Scene statements (images)
            if node_type in ('Show', 'Scene'):
                imspec = getattr(node, 'imspec', None)
                if not imspec:
                    return

                # imspec is typically a tuple: (name_parts, expression, tag, at_list, layer, zorder, behind)
                if isinstance(imspec, (list, tuple)) and len(imspec) >= 1:
                    name_parts = imspec[0]
                    if isinstance(name_parts, (list, tuple)) and len(name_parts) > 0:
                        # Get tag (explicit or first name part)
                        tag = imspec[2] if len(imspec) > 2 and imspec[2] else name_parts[0]
                        # Get layer (explicit or 'master')
                        layer = imspec[4] if len(imspec) > 4 and imspec[4] else 'master'

                        # For Scene statements, clear existing tracked shows for this layer
                        if node_type == 'Scene':
                            keys_to_remove = [k for k in self._show_statement_locations if k[0] == layer]
                            for k in keys_to_remove:
                                del self._show_statement_locations[k]

                        self._show_statement_locations[(layer, tag)] = {
                            'file': abs_filename,
                            'line': linenumber,
                            'statement_type': node_type.lower(),  # 'show' or 'scene'
                        }

            # Track ShowScreen statements
            elif node_type == 'ShowScreen':
                screen_name = getattr(node, 'screen_name', None)
                if screen_name:
                    # Use a special key format for screens
                    self._show_statement_locations[('screens', f'screen:{screen_name}')] = {
                        'file': abs_filename,
                        'line': linenumber,
                    }

            # Track HideScreen statements - remove from tracking
            elif node_type == 'HideScreen':
                screen_name = getattr(node, 'screen_name', None)
                if screen_name:
                    key = ('screens', f'screen:{screen_name}')
                    if key in self._show_statement_locations:
                        del self._show_statement_locations[key]

        except Exception as e:
            # Don't let tracking errors affect execution
            print(f"[DAP] Error tracking show statement: {e}")

    def _get_current_label(self) -> Optional[str]:
        """Get the current execution label."""
        try:
            import renpy

            ctx = renpy.game.context()
            if ctx and hasattr(ctx, "current"):
                current = ctx.current
                if isinstance(current, str):
                    return current
                elif isinstance(current, tuple):
                    return current[0]
        except Exception:
            pass
        return None

    def _enable_skip_mode(self) -> None:
        """Enable Ren'Py's skip mode for fast-forward."""
        try:
            import renpy

            # Save original skip_delay for restoration
            self._original_skip_delay = renpy.config.skip_delay

            # Set skipping mode
            renpy.config.skipping = "fast"
            # Set skip_delay to 0 for instant skipping
            renpy.config.skip_delay = 0

            # Also set the store variable
            if hasattr(renpy, "store"):
                renpy.store._skipping = True

            print(f"[DAP] Skip mode enabled (fast, delay=0)")

        except Exception as e:
            print(f"[DAP] Error enabling skip mode: {e}")

    def _disable_skip_mode(self) -> None:
        """Disable Ren'Py's skip mode."""
        try:
            import renpy

            renpy.config.skipping = None

            # Restore original skip_delay
            if hasattr(self, "_original_skip_delay"):
                renpy.config.skip_delay = self._original_skip_delay
                del self._original_skip_delay

            if hasattr(renpy, "store"):
                renpy.store._skipping = False

            print(f"[DAP] Skip mode disabled")

        except Exception as e:
            print(f"[DAP] Error disabling skip mode: {e}")

    def _cleanup_temp_breakpoint(self) -> None:
        """Clean up temporary breakpoint and disable skip mode."""
        if hasattr(self, "_temp_breakpoint") and self._temp_breakpoint:
            filename, line = self._temp_breakpoint
            # Remove the temporary breakpoint
            self.breakpoint_manager.clear_file(filename)
            self._temp_breakpoint = None

        # Disable skip mode
        self._disable_skip_mode()

    def get_scene_state(self) -> dict:
        """
        Get the current scene state for the Scene Inspector.

        Returns:
            Dict containing:
            - images: List of showing images per layer
            - audio: Dict of audio channels and what's playing
            - current_label: Current execution label
            - current_line: Current line number
        """
        state = {
            "images": [],
            "screens": [],
            "audio": {},
            "current_label": None,
            "current_line": 0,
        }

        try:
            import renpy

            # Get current location
            state["current_label"] = self._get_current_label()
            state["current_line"] = self._current_line

            # Get showing images by layer
            try:
                scene_lists = renpy.game.context().scene_lists

                # Get images from each layer
                for layer in renpy.config.layers:
                    layer_images = []

                    # Get tags showing on this layer
                    showing_tags = scene_lists.get_showing_tags(layer)

                    for tag in showing_tags:
                        # Try to get the full image name with attributes
                        try:
                            # Skip screens - they're handled separately
                            displayable = scene_lists.get_displayable_by_tag(layer, tag)
                            if displayable and type(displayable).__name__ == 'ScreenDisplayable':
                                continue

                            # Get attributes from renpy.game.context().images
                            images = renpy.game.context().images
                            attrs = images.get_attributes(layer, tag)
                            attrs = list(attrs) if attrs else []

                            # Get the registered image to check if it's a LayeredImage
                            full_name = (tag,) + tuple(attrs) if attrs else (tag,)
                            registered = renpy.display.image.get_registered_image((tag,))

                            # Check if this is a LayeredImage
                            if registered is not None and type(registered).__name__ == 'LayeredImage':
                                # Get the layered image components
                                components = self._get_layered_image_components(
                                    registered, tag, attrs, layer
                                )
                                layer_images.extend(components)
                            else:
                                # Regular image - create single entry
                                image_info = {
                                    "tag": tag,
                                    "layer": layer,
                                    "attributes": attrs,
                                    "file": self._get_image_file(full_name),
                                }

                                # Find the image definition (if any)
                                definition = self._find_image_definition(tag)
                                if definition:
                                    image_info["definition"] = definition

                                # Get the tracked show statement location and type
                                show_statement = self._show_statement_locations.get((layer, tag))
                                if show_statement:
                                    image_info["show_statement"] = {
                                        'file': show_statement.get('file'),
                                        'line': show_statement.get('line'),
                                    }
                                    # Add statement type (show, scene)
                                    if 'statement_type' in show_statement:
                                        image_info["statement_type"] = show_statement['statement_type']

                                # Try to get position/transform info
                                try:
                                    transforms = scene_lists.at_list.get((layer, tag), [])
                                    if transforms:
                                        positions = []
                                        for t in transforms:
                                            if hasattr(t, 'name'):
                                                positions.append(t.name)
                                            elif hasattr(t, '__name__'):
                                                positions.append(t.__name__)
                                        if positions:
                                            image_info["position"] = ", ".join(positions)
                                except Exception:
                                    pass

                                layer_images.append(image_info)

                        except Exception as e:
                            print(f"[DAP] Error getting image attributes for {tag}: {e}")
                            # Fallback: add basic info
                            layer_images.append({
                                "tag": tag,
                                "layer": layer,
                                "attributes": [],
                            })

                    if layer_images:
                        state["images"].extend(layer_images)

            except Exception as e:
                print(f"[DAP] Error getting scene images: {e}")

            # Get showing screens
            try:
                # Screens are displayables on the 'screens' layer (or other layers)
                # We iterate through layers and find ScreenDisplayable objects
                screen_layers = ['screens'] + list(renpy.config.overlay_layers)
                seen_screens = set()

                for screen_layer in screen_layers:
                    if screen_layer not in scene_lists.layers:
                        continue

                    for entry in scene_lists.layers[screen_layer]:
                        try:
                            displayable = entry.displayable
                            # Check if this is a ScreenDisplayable
                            if type(displayable).__name__ != 'ScreenDisplayable':
                                continue

                            screen_name = getattr(displayable, 'screen_name', None)
                            if not screen_name:
                                continue

                            # Get the base screen name (first part of tuple if tuple)
                            if isinstance(screen_name, tuple):
                                screen_name = screen_name[0]

                            # Skip duplicates
                            if screen_name in seen_screens:
                                continue
                            seen_screens.add(screen_name)

                            screen_info = {
                                "name": screen_name,
                                "type": "screen",
                                "layer": screen_layer,
                            }

                            # Find the screen definition
                            definition = self._find_screen_definition(screen_name)
                            if definition:
                                screen_info["definition"] = definition

                            # Get the tracked show screen statement
                            show_statement = self._show_statement_locations.get(('screens', f'screen:{screen_name}'))
                            if show_statement:
                                screen_info["show_statement"] = show_statement

                            state["screens"].append(screen_info)

                        except Exception as e:
                            print(f"[DAP] Error getting screen info: {e}")

            except Exception as e:
                print(f"[DAP] Error getting screens: {e}")

            # Get audio state
            try:
                # Check common audio channels
                channels = ["music", "sound", "voice", "audio"]

                for channel in channels:
                    try:
                        playing = renpy.audio.music.get_playing(channel=channel)
                        if playing:
                            # Try to get just the filename
                            if isinstance(playing, str):
                                # Extract filename from path
                                import os
                                playing = os.path.basename(playing)
                            state["audio"][channel] = playing
                    except Exception:
                        pass

            except Exception as e:
                print(f"[DAP] Error getting audio state: {e}")

            # Get additional context info
            try:
                ctx = renpy.game.context()

                # Current say info (who's speaking)
                if hasattr(ctx, 'who') and ctx.who:
                    state["current_speaker"] = str(ctx.who)

            except Exception:
                pass

        except Exception as e:
            print(f"[DAP] Error getting scene state: {e}")

        return state

    def _get_image_file(self, image_name: tuple) -> Optional[str]:
        """
        Get the file path for an image name.

        Args:
            image_name: Tuple of image name parts (e.g., ("bg", "uni"))

        Returns:
            Absolute file path if found, None otherwise
        """
        try:
            import renpy.display.image
            import renpy.loader

            # Get the registered image displayable
            displayable = renpy.display.image.get_registered_image(image_name)
            if displayable is None:
                return None

            # Try to get the filename from the displayable
            filename = None

            # Direct Image with filename attribute
            if hasattr(displayable, 'filename'):
                filename = displayable.filename

            # ImageReference or other wrappers - try to resolve
            elif hasattr(displayable, 'target') and hasattr(displayable.target, 'filename'):
                filename = displayable.target.filename

            # Check for child displayable
            elif hasattr(displayable, 'child') and hasattr(displayable.child, 'filename'):
                filename = displayable.child.filename

            # Composite images (like ConditionSwitch, LayeredImage) are complex
            # For now just try to find any filename attribute recursively
            elif hasattr(displayable, '__dict__'):
                for attr_name in ['image', 'displayable', 'base']:
                    if hasattr(displayable, attr_name):
                        attr = getattr(displayable, attr_name)
                        if hasattr(attr, 'filename'):
                            filename = attr.filename
                            break

            if filename is None:
                return None

            # Try to get the absolute path using renpy.loader.transpath
            try:
                abs_path = renpy.loader.transpath(filename)
                if abs_path:
                    return abs_path
            except Exception:
                pass

            # Fallback: construct path from gamedir
            import os
            gamedir_path = os.path.join(renpy.config.gamedir, filename)
            if os.path.isfile(gamedir_path):
                return gamedir_path

            # Try images directory
            images_path = os.path.join(renpy.config.gamedir, "images", filename)
            if os.path.isfile(images_path):
                return images_path

            return None

        except Exception as e:
            print(f"[DAP] Error getting image file for {image_name}: {e}")
            return None

    def _extract_file_from_displayable(self, displayable: Any) -> Optional[str]:
        """
        Extract the file path from any displayable object.

        Handles various displayable types including Image, ImageReference,
        wrapped displayables, and string filenames.

        Args:
            displayable: Any Ren'Py displayable object

        Returns:
            Absolute file path if found, None otherwise
        """
        try:
            import renpy.loader
            import os

            filename = None

            # If it's a string, treat it as a filename directly
            if isinstance(displayable, str):
                filename = displayable

            # Direct Image with filename attribute
            elif hasattr(displayable, 'filename'):
                filename = displayable.filename

            # ImageReference or other wrappers - try to resolve
            elif hasattr(displayable, 'target'):
                target = displayable.target
                if hasattr(target, 'filename'):
                    filename = target.filename
                elif isinstance(target, str):
                    filename = target

            # Check for child displayable
            elif hasattr(displayable, 'child'):
                child = displayable.child
                if hasattr(child, 'filename'):
                    filename = child.filename
                elif isinstance(child, str):
                    filename = child

            # Check for image attribute (common in layered image layers)
            elif hasattr(displayable, 'image'):
                img = displayable.image
                if hasattr(img, 'filename'):
                    filename = img.filename
                elif isinstance(img, str):
                    filename = img

            # Try other common attributes
            if filename is None and hasattr(displayable, '__dict__'):
                for attr_name in ['displayable', 'base', '_image']:
                    if hasattr(displayable, attr_name):
                        attr = getattr(displayable, attr_name)
                        if hasattr(attr, 'filename'):
                            filename = attr.filename
                            break
                        elif isinstance(attr, str):
                            filename = attr
                            break

            if filename is None:
                return None

            # Try to get the absolute path using renpy.loader.transpath
            try:
                abs_path = renpy.loader.transpath(filename)
                if abs_path and os.path.isfile(abs_path):
                    return abs_path
            except Exception:
                pass

            # Fallback: construct path from gamedir
            gamedir_path = os.path.join(renpy.config.gamedir, filename)
            if os.path.isfile(gamedir_path):
                return gamedir_path

            # Try images directory
            images_path = os.path.join(renpy.config.gamedir, "images", filename)
            if os.path.isfile(images_path):
                return images_path

            return None

        except Exception as e:
            print(f"[DAP] Error extracting file from displayable: {e}")
            return None

    def _get_layered_image_components(
        self, layered_image: Any, tag: str, attrs: list, layer: str
    ) -> list:
        """
        Get the individual components of a LayeredImage.

        Args:
            layered_image: The LayeredImage object
            tag: The image tag (e.g., "debug_char")
            attrs: List of current attributes
            layer: The display layer name

        Returns:
            List of image_info dicts for each active component
        """
        components = []
        attrs_set = set(attrs)

        # Add default attributes from groups
        if hasattr(layered_image, 'attributes'):
            banned = layered_image.get_banned(attrs_set) if hasattr(layered_image, 'get_banned') else set()
            for attr_obj in layered_image.attributes:
                if hasattr(attr_obj, 'default') and attr_obj.default:
                    if hasattr(attr_obj, 'attribute') and attr_obj.attribute not in banned:
                        attrs_set.add(attr_obj.attribute)

        # First, add a parent entry for the layered image itself
        parent_info = {
            "tag": tag,
            "layer": layer,
            "attributes": list(attrs),
            "is_layered": True,
            "components": [],
        }

        # Find the layeredimage definition location
        definition = self._find_image_definition(tag)
        if definition:
            parent_info["definition"] = definition

        # Get the tracked show statement location
        show_statement = self._show_statement_locations.get((layer, tag))
        if show_statement:
            parent_info["show_statement"] = show_statement

        # Iterate through layers to find active components
        if hasattr(layered_image, 'layers'):
            for layer_obj in layered_image.layers:
                try:
                    # Get the displayable for this layer
                    displayable = None
                    component_name = None
                    group_name = None
                    attr_name = None

                    # Check what type of layer this is
                    layer_type = type(layer_obj).__name__

                    if layer_type == 'Attribute':
                        # Attribute layer - only active if attribute is in set
                        if hasattr(layer_obj, 'attribute'):
                            attr_name = layer_obj.attribute
                            if attr_name in attrs_set:
                                displayable = getattr(layer_obj, 'image', None)
                                group_name = getattr(layer_obj, 'group', None)
                                component_name = f"{group_name}:{attr_name}" if group_name else attr_name

                    elif layer_type == 'Always':
                        # Always layer - always active
                        displayable = getattr(layer_obj, 'image', None)
                        component_name = "always"

                    elif layer_type == 'Condition':
                        # Condition layer - would need to evaluate condition
                        # For now, just note it exists
                        component_name = "condition"

                    elif layer_type == 'ConditionGroup':
                        # Condition group - would need to evaluate conditions
                        component_name = "condition_group"

                    if displayable is not None or component_name:
                        # Try to get file path from the displayable
                        file_path = None
                        displayable_type = None

                        if displayable is not None:
                            displayable_type = type(displayable).__name__
                            file_path = self._extract_file_from_displayable(displayable)

                        # Create component info
                        comp_info = {
                            "name": component_name or "unknown",
                            "type": displayable_type,
                            "file": file_path,
                        }

                        if group_name:
                            comp_info["group"] = group_name
                        if attr_name:
                            comp_info["attribute"] = attr_name

                        # Find the definition location for this attribute
                        if attr_name:
                            attr_definition = self._find_layeredimage_attribute(
                                tag, group_name, attr_name
                            )
                            if attr_definition:
                                comp_info["definition"] = attr_definition

                        parent_info["components"].append(comp_info)

                except Exception as e:
                    print(f"[DAP] Error processing layer component: {e}")

        components.append(parent_info)
        return components

    def _find_image_definition(self, tag: str) -> Optional[dict]:
        """
        Find where an image (including layeredimage) is defined in the .rpy files.

        Args:
            tag: The image tag to search for (e.g., "debug_char")

        Returns:
            Dict with 'file' and 'line' if found, None otherwise
        """
        import os
        import re
        import renpy

        # Search patterns for different image definition types
        patterns = [
            # layeredimage tag:
            rf'^layeredimage\s+{re.escape(tag)}\s*:',
            # image tag = ...
            rf'^image\s+{re.escape(tag)}\s*=',
            # image tag attribute = ...
            rf'^image\s+{re.escape(tag)}\s+\w',
        ]

        try:
            # Get the game directory
            gamedir = renpy.config.gamedir
            if not gamedir:
                return None

            # Search all .rpy files in the game directory
            for root, dirs, files in os.walk(gamedir):
                # Skip some common directories
                dirs[:] = [d for d in dirs if d not in ['cache', '.git', '__pycache__']]

                for filename in files:
                    if not filename.endswith('.rpy'):
                        continue

                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for line_num, line in enumerate(f, 1):
                                for pattern in patterns:
                                    if re.match(pattern, line.strip()):
                                        return {
                                            'file': filepath,
                                            'line': line_num,
                                            'type': 'definition',
                                        }
                    except (IOError, UnicodeDecodeError):
                        continue

            return None

        except Exception as e:
            print(f"[DAP] Error finding image definition for {tag}: {e}")
            return None

    def _find_screen_definition(self, screen_name: str) -> Optional[dict]:
        """
        Find where a screen is defined in the .rpy files.

        Args:
            screen_name: The screen name to search for (e.g., "quick_menu")

        Returns:
            Dict with 'file' and 'line' if found, None otherwise
        """
        import os
        import re
        import renpy

        # Pattern for screen definition: screen screenname(...):
        pattern = rf'^screen\s+{re.escape(screen_name)}(\s*\(|\s*:)'

        try:
            gamedir = renpy.config.gamedir
            if not gamedir:
                return None

            # Search all .rpy files in the game directory
            for root, dirs, files in os.walk(gamedir):
                dirs[:] = [d for d in dirs if d not in ['cache', '.git', '__pycache__']]

                for filename in files:
                    if not filename.endswith('.rpy'):
                        continue

                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for line_num, line in enumerate(f, 1):
                                if re.match(pattern, line.strip()):
                                    return {
                                        'file': filepath,
                                        'line': line_num,
                                        'type': 'screen',
                                    }
                    except (IOError, UnicodeDecodeError):
                        continue

            # Also check renpy common files
            try:
                commondir = renpy.config.commondir
                if commondir:
                    for root, dirs, files in os.walk(commondir):
                        dirs[:] = [d for d in dirs if d not in ['cache', '.git', '__pycache__']]

                        for filename in files:
                            if not filename.endswith('.rpy'):
                                continue

                            filepath = os.path.join(root, filename)
                            try:
                                with open(filepath, 'r', encoding='utf-8') as f:
                                    for line_num, line in enumerate(f, 1):
                                        if re.match(pattern, line.strip()):
                                            return {
                                                'file': filepath,
                                                'line': line_num,
                                                'type': 'screen',
                                            }
                            except (IOError, UnicodeDecodeError):
                                continue
            except Exception:
                pass

            return None

        except Exception as e:
            print(f"[DAP] Error finding screen definition for {screen_name}: {e}")
            return None

    def _find_layeredimage_attribute(self, tag: str, group: Optional[str], attribute: str) -> Optional[dict]:
        """
        Find where a specific attribute is defined within a layeredimage block.

        Args:
            tag: The layeredimage tag (e.g., "debug_char")
            group: The group name (e.g., "base") or None for ungrouped attributes
            attribute: The attribute name (e.g., "green")

        Returns:
            Dict with 'file' and 'line' if found, None otherwise
        """
        import os
        import re
        import renpy

        try:
            gamedir = renpy.config.gamedir
            if not gamedir:
                return None

            # First find the layeredimage definition
            layeredimage_pattern = rf'^layeredimage\s+{re.escape(tag)}\s*:'

            for root, dirs, files in os.walk(gamedir):
                dirs[:] = [d for d in dirs if d not in ['cache', '.git', '__pycache__']]

                for filename in files:
                    if not filename.endswith('.rpy'):
                        continue

                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            lines = f.readlines()

                        in_layeredimage = False
                        layeredimage_indent = 0
                        in_target_group = False
                        current_group = None
                        group_indent = 0

                        for line_num, line in enumerate(lines, 1):
                            stripped = line.strip()
                            if not stripped or stripped.startswith('#'):
                                continue

                            # Calculate current indentation
                            current_indent = len(line) - len(line.lstrip())

                            # Check if we're entering the layeredimage block
                            if re.match(layeredimage_pattern, stripped):
                                in_layeredimage = True
                                layeredimage_indent = current_indent
                                continue

                            if not in_layeredimage:
                                continue

                            # Check if we've left the layeredimage block
                            if current_indent <= layeredimage_indent and stripped and not stripped.startswith('#'):
                                if not re.match(layeredimage_pattern, stripped):
                                    in_layeredimage = False
                                    continue

                            # Check for group definition
                            group_match = re.match(r'^group\s+(\w+)\s*:', stripped)
                            if group_match:
                                current_group = group_match.group(1)
                                group_indent = current_indent
                                in_target_group = (group == current_group)
                                continue

                            # Check for "always:" block
                            if re.match(r'^always\s*:', stripped):
                                current_group = None
                                in_target_group = (group is None)
                                continue

                            # Check if we've left the current group
                            if current_group and current_indent <= group_indent:
                                current_group = None
                                in_target_group = False

                            # Check for attribute definition
                            # Patterns: "attribute name:" or "attribute name default:" etc.
                            attr_match = re.match(rf'^attribute\s+{re.escape(attribute)}(\s|:|$)', stripped)
                            if attr_match:
                                # Check if we're in the right context
                                if group is None and current_group is None:
                                    # Ungrouped attribute at layeredimage level
                                    return {
                                        'file': filepath,
                                        'line': line_num,
                                        'type': 'attribute',
                                    }
                                elif group and current_group == group:
                                    # Attribute in the correct group
                                    return {
                                        'file': filepath,
                                        'line': line_num,
                                        'type': 'attribute',
                                    }

                    except (IOError, UnicodeDecodeError):
                        continue

            return None

        except Exception as e:
            print(f"[DAP] Error finding attribute {attribute} in {tag}: {e}")
            return None

    def _find_show_statement(self, tag: str, attrs: list) -> Optional[dict]:
        """
        Find where a show statement for this image might be.
        This searches for 'show tag attrs' patterns.

        Args:
            tag: The image tag
            attrs: List of attributes

        Returns:
            Dict with 'file' and 'line' if found, None otherwise
        """
        import os
        import re
        import renpy

        # Build search pattern for show statement
        # Match: show tag [attrs]
        if attrs:
            # Create pattern that matches the tag followed by any of the attributes
            attr_pattern = r'\s+'.join([re.escape(tag)] + [re.escape(a) for a in attrs[:3]])  # Limit to first 3 attrs
            patterns = [
                rf'^\s*(show|scene)\s+{attr_pattern}',
            ]
        else:
            patterns = [
                rf'^\s*(show|scene)\s+{re.escape(tag)}\s*($|at\s|with\s|:)',
            ]

        try:
            gamedir = renpy.config.gamedir
            if not gamedir:
                return None

            # We could track the actual show location, but for now search the files
            # A more sophisticated approach would hook into show_imspec

            for root, dirs, files in os.walk(gamedir):
                dirs[:] = [d for d in dirs if d not in ['cache', '.git', '__pycache__']]

                for filename in files:
                    if not filename.endswith('.rpy'):
                        continue

                    filepath = os.path.join(root, filename)
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            for line_num, line in enumerate(f, 1):
                                for pattern in patterns:
                                    if re.match(pattern, line):
                                        return {
                                            'file': filepath,
                                            'line': line_num,
                                            'type': 'show',
                                        }
                    except (IOError, UnicodeDecodeError):
                        continue

            return None

        except Exception as e:
            print(f"[DAP] Error finding show statement for {tag}: {e}")
            return None
