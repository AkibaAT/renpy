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
DAP (Debug Adapter Protocol) server implementation.

This module provides a TCP server that speaks the Debug Adapter Protocol,
allowing IDEs like VSCode to debug Ren'Py games.
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Optional, TYPE_CHECKING

from .protocol import (
    Command,
    Event,
    StopReason,
    DEBUGGER_CAPABILITIES,
    DAPResponse,
    DAPEvent,
    create_response,
    create_event,
)
from .core import DebuggerCore, StepMode

if TYPE_CHECKING:
    pass


class DAPServer:
    """
    Debug Adapter Protocol server.

    Runs a TCP server that accepts connections from debug clients
    and translates DAP requests into debugger operations.
    """

    def __init__(self, debugger: DebuggerCore, port: int = 5678):
        self.debugger = debugger
        self.port = port

        self._socket: Optional[socket.socket] = None
        self._client: Optional[socket.socket] = None
        self._client_addr: Optional[tuple] = None

        self._running = False
        self._server_thread: Optional[threading.Thread] = None
        self._client_thread: Optional[threading.Thread] = None

        self._lock = threading.Lock()
        self._seq = 1

        # Buffer for incomplete messages
        self._recv_buffer = b""

        # Event to signal when a client connects
        self._client_connected = threading.Event()

        # Event to signal shutdown - all blocking operations should check this
        self._shutdown_event = threading.Event()

    def start(self) -> bool:
        """
        Start the DAP server.

        Returns True if server started successfully.
        """
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.bind(("127.0.0.1", self.port))
            self._socket.listen(5)  # Allow pending connections to queue
            self._socket.settimeout(1.0)

            self._running = True
            self._server_thread = threading.Thread(target=self._server_loop, daemon=True)
            self._server_thread.start()

            self._log(f"DAP server listening on port {self.port}")
            return True

        except Exception as e:
            self._log(f"Failed to start DAP server: {e}")
            return False

    def stop(self) -> None:
        """Stop the DAP server.

        This method prioritizes IMMEDIATE shutdown. No waiting for threads -
        just signal them to stop and close all sockets to unblock them.
        """
        # Signal shutdown FIRST - this unblocks all waiting operations
        self._shutdown_event.set()
        self._running = False

        self._client_connected.set()

        if self._client:
            try:
                # Shutdown to unblock any recv() calls
                self._client.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        # Don't wait for threads - immediate shutdown means immediate
        self._client_thread = None
        self._server_thread = None

        self._log("DAP server stopped")

    def wait_for_client(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for a debug client to connect.

        Args:
            timeout: Maximum time to wait in seconds, or None to wait indefinitely.

        Returns:
            True if a client connected, False if timeout expired or shutdown requested.
        """
        self._log("Waiting for debug client connection...")

        if timeout is None:
            while not self._shutdown_event.is_set():
                if self._client_connected.wait(timeout=0.5):
                    self._log("Debug client connected, resuming execution")
                    return True
            self._log("Shutdown requested while waiting for client")
            return False
        else:
            start = __import__('time').time()
            remaining = timeout
            while remaining > 0 and not self._shutdown_event.is_set():
                wait_time = min(0.5, remaining)
                if self._client_connected.wait(timeout=wait_time):
                    self._log("Debug client connected, resuming execution")
                    return True
                remaining = timeout - (__import__('time').time() - start)

            if self._shutdown_event.is_set():
                self._log("Shutdown requested while waiting for client")
            else:
                self._log("Timeout waiting for debug client")
            return False

    def _server_loop(self) -> None:
        """Main server loop - accepts connections."""
        while self._running and self._socket and not self._shutdown_event.is_set():
            try:
                client, addr = self._socket.accept()

                # Check shutdown again after accept (may have been signaled during wait)
                if self._shutdown_event.is_set():
                    try:
                        client.close()
                    except Exception:
                        pass
                    break

                self._log(f"Client connected from {addr}")

                if self._client:
                    try:
                        self._client.close()
                    except Exception:
                        pass

                self._client = client
                self._client_addr = addr
                self._recv_buffer = b""
                self._client_connected.set()
                client.settimeout(0.5)
                self._client_thread = threading.Thread(target=self._client_loop, daemon=True)
                self._client_thread.start()

            except socket.timeout:
                continue
            except Exception as e:
                if self._running and not self._shutdown_event.is_set():
                    self._log(f"Server error: {e}")
                break

    def _client_loop(self) -> None:
        """Handle communication with a connected client."""
        client = self._client
        if not client:
            return

        try:
            while self._running and self._client == client and not self._shutdown_event.is_set():
                try:
                    data = client.recv(4096)
                    if not data:
                        break
                    self._recv_buffer += data
                except socket.timeout:
                    if self._shutdown_event.is_set():
                        break
                    continue
                except Exception:
                    break

                while not self._shutdown_event.is_set():
                    message = self._parse_message()
                    if message is None:
                        break
                    self._handle_message(message)

        except Exception as e:
            if not self._shutdown_event.is_set():
                self._log(f"Client error: {e}")
        finally:
            if not self._shutdown_event.is_set():
                self._log("Client disconnected")
            if self._client == client:
                self._client = None
                self.debugger.detach()

    def _parse_message(self) -> Optional[dict[str, Any]]:
        """Parse a complete DAP message from the receive buffer."""
        header_end = self._recv_buffer.find(b"\r\n\r\n")
        if header_end == -1:
            return None

        header = self._recv_buffer[:header_end].decode("utf-8")
        content_length = 0

        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break

        if content_length == 0:
            self._recv_buffer = self._recv_buffer[header_end + 4 :]
            return None

        body_start = header_end + 4
        body_end = body_start + content_length

        if len(self._recv_buffer) < body_end:
            return None

        body = self._recv_buffer[body_start:body_end]
        self._recv_buffer = self._recv_buffer[body_end:]

        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as e:
            self._log(f"JSON parse error: {e}")
            return None

    def _handle_message(self, message: dict[str, Any]) -> None:
        """Handle a DAP message."""
        msg_type = message.get("type")
        command = message.get("command")

        if msg_type == "request":
            self._handle_request(message)
        else:
            self._log(f"Unknown message type: {msg_type}")

    def _handle_request(self, request: dict[str, Any]) -> None:
        """Handle a DAP request."""
        command = request.get("command", "")
        args = request.get("arguments", {})

        self._log(f"Handling request: {command}")

        handler = getattr(self, f"_handle_{command}", None)
        if handler:
            try:
                response = handler(request, args)
                if response is not None:
                    self._send_response(response)
            except Exception as e:
                self._log(f"Error handling {command}: {e}")
                self._send_response(self._error_response(request, str(e)))
        else:
            self._log(f"Unknown command: {command}")
            self._send_response(self._error_response(request, f"Unknown command: {command}"))

    def _send_response(self, response: DAPResponse) -> None:
        """Send a response to the client."""
        self._send_message(response)

    def _send_message(self, message: Any) -> None:
        """Send a DAP message to the client."""
        if not self._client:
            return

        try:
            data = message.to_wire()
            self._client.sendall(data)
        except Exception as e:
            self._log(f"Send error: {e}")

    def send_event(self, event: str, body: Optional[dict[str, Any]] = None) -> None:
        """Send an event to the client."""
        with self._lock:
            seq = self._seq
            self._seq += 1

        evt = create_event(seq, event, body)
        self._send_message(evt)

    def _next_seq(self) -> int:
        """Get the next sequence number."""
        with self._lock:
            seq = self._seq
            self._seq += 1
            return seq

    def _success_response(self, request: dict[str, Any], body: Optional[dict[str, Any]] = None) -> DAPResponse:
        """Create a success response."""
        return create_response(request, self._next_seq(), success=True, body=body)

    def _error_response(self, request: dict[str, Any], message: str) -> DAPResponse:
        """Create an error response."""
        return create_response(request, self._next_seq(), success=False, message=message)

    def _log(self, message: str, force: bool = False) -> None:
        """Log a debug message. Only prints to console for errors or if force=True."""
        try:
            import renpy

            if hasattr(renpy, "display") and hasattr(renpy.display, "log"):
                renpy.display.log.write(f"[DAP] {message}")
        except Exception:
            pass

        # Only print to console for errors or forced messages
        if force or message.startswith("Error") or "error" in message.lower():
            print(f"[DAP] {message}")

    # DAP Request Handlers

    def _handle_initialize(self, request: dict, args: dict) -> DAPResponse:
        """Handle initialize request."""
        self.debugger.attach(self)

        response = self._success_response(request, DEBUGGER_CAPABILITIES)
        self._send_response(response)
        self.send_event(Event.INITIALIZED)

        return None

    def _handle_launch(self, request: dict, args: dict) -> DAPResponse:
        """Handle launch request.

        Since Ren'Py is already running when the DAP server starts,
        this just acknowledges the request.
        """
        return self._success_response(request)

    def _handle_attach(self, request: dict, args: dict) -> DAPResponse:
        """Handle attach request.

        Used when the debugger connects to an already-running game.
        """
        return self._success_response(request)

    def _handle_configurationDone(self, request: dict, args: dict) -> DAPResponse:
        """Handle configurationDone request."""
        return self._success_response(request)

    def _handle_setBreakpoints(self, request: dict, args: dict) -> DAPResponse:
        """Handle setBreakpoints request."""
        source = args.get("source", {})
        path = source.get("path", "")
        breakpoints = args.get("breakpoints", [])

        bps = self.debugger.set_breakpoints(path, breakpoints)
        return self._success_response(request, {"breakpoints": [bp.to_dap() for bp in bps]})

    def _handle_setFunctionBreakpoints(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle setFunctionBreakpoints request.

        Sets breakpoints that trigger when entering specific labels.
        """
        breakpoints_data = args.get("breakpoints", [])
        verified = self.debugger.set_function_breakpoints(breakpoints_data)
        return self._success_response(request, {"breakpoints": verified})

    def _handle_setExceptionBreakpoints(self, request: dict, args: dict) -> DAPResponse:
        """Handle setExceptionBreakpoints request."""
        filters = args.get("filters", [])
        break_on_raised = "raised" in filters
        break_on_uncaught = "uncaught" in filters
        self.debugger.set_exception_breakpoints(break_on_raised, break_on_uncaught)
        return self._success_response(request)

    def _handle_exceptionInfo(self, request: dict, args: dict) -> DAPResponse:
        """Handle exceptionInfo request - return details about current exception."""
        exc_info = self.debugger.get_exception_info()
        if exc_info:
            return self._success_response(request, exc_info)
        else:
            return self._success_response(request, {
                "exceptionId": "unknown",
                "description": "No exception information available",
                "breakMode": "never",
            })

    def _handle_threads(self, request: dict, args: dict) -> DAPResponse:
        """Handle threads request."""
        # Ren'Py runs on a single thread from the script perspective
        return self._success_response(
            request,
            {
                "threads": [
                    {"id": 1, "name": "Main Thread"},
                ]
            },
        )

    def _handle_stackTrace(self, request: dict, args: dict) -> DAPResponse:
        """Handle stackTrace request."""
        frames = self.debugger.get_stack_trace()
        return self._success_response(
            request,
            {
                "stackFrames": frames,
                "totalFrames": len(frames),
            },
        )

    def _handle_scopes(self, request: dict, args: dict) -> DAPResponse:
        """Handle scopes request."""
        frame_id = args.get("frameId", 0)
        scopes = self.debugger.get_scopes(frame_id)
        return self._success_response(request, {"scopes": scopes})

    def _handle_variables(self, request: dict, args: dict) -> DAPResponse:
        """Handle variables request."""
        ref = args.get("variablesReference", 0)
        variables = self.debugger.get_variables(ref)
        return self._success_response(request, {"variables": variables})

    def _handle_setVariable(self, request: dict, args: dict) -> DAPResponse:
        """Handle setVariable request - modify a variable's value."""
        reference = args.get("variablesReference", 0)
        name = args.get("name", "")
        value = args.get("value", "")

        result = self.debugger.set_variable(reference, name, value)

        if result.get("success"):
            return self._success_response(
                request,
                {
                    "value": result.get("value", ""),
                    "type": result.get("type", ""),
                    "variablesReference": result.get("variablesReference", 0),
                },
            )
        else:
            return self._error_response(request, result.get("message", "Failed to set variable"))

    def _handle_dataBreakpointInfo(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle dataBreakpointInfo request - get info about watching a variable.

        This is called when the user wants to set a watchpoint on a variable.
        """
        name = args.get("name", "")
        variables_reference = args.get("variablesReference", 0)

        info = self.debugger.get_data_breakpoint_info(name, variables_reference)

        return self._success_response(request, info)

    def _handle_setDataBreakpoints(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle setDataBreakpoints request - set watchpoints.

        Watchpoints break when a variable's value changes.
        """
        breakpoints = args.get("breakpoints", [])

        verified = self.debugger.set_data_breakpoints(breakpoints)

        return self._success_response(request, {"breakpoints": verified})

    def _handle_continue(self, request: dict, args: dict) -> DAPResponse:
        """Handle continue request."""
        self.debugger.resume()
        return self._success_response(request, {"allThreadsContinued": True})

    def _handle_pause(self, request: dict, args: dict) -> DAPResponse:
        """Handle pause request."""
        self.debugger.pause()
        return self._success_response(request)

    def _handle_next(self, request: dict, args: dict) -> DAPResponse:
        """Handle next (step over) request."""
        self.debugger.step(StepMode.OVER)
        return self._success_response(request)

    def _handle_stepIn(self, request: dict, args: dict) -> DAPResponse:
        """Handle stepIn request."""
        self.debugger.step(StepMode.INTO)
        return self._success_response(request)

    def _handle_stepOut(self, request: dict, args: dict) -> DAPResponse:
        """Handle stepOut request."""
        self.debugger.step(StepMode.OUT)
        return self._success_response(request)

    def _handle_stepBack(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle stepBack request - step backwards using Ren'Py's rollback.

        This leverages Ren'Py's built-in rollback system to go back one interaction.
        """
        result = self.debugger.step_back()
        if result.get("success"):
            return self._success_response(request)
        else:
            return self._error_response(request, result.get("message", "Step back failed"))

    def _handle_reverseContinue(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle reverseContinue request - roll back to previous state.

        For Ren'Py, this is the same as stepBack since rollback goes
        back by interactions, not individual statements.
        """
        result = self.debugger.step_back()
        if result.get("success"):
            return self._success_response(request)
        else:
            return self._error_response(request, result.get("message", "Reverse continue failed"))

    def _handle_gotoTargets(self, request: dict, args: dict) -> DAPResponse:
        """Handle gotoTargets request - return available jump targets (labels)."""
        source = args.get("source", {})
        path = source.get("path", "")
        line = args.get("line", 0)

        targets = self.debugger.get_goto_targets(path, line)
        return self._success_response(request, {"targets": targets})

    def _handle_goto(self, request: dict, args: dict) -> DAPResponse:
        """Handle goto request - jump to a label."""
        target_id = args.get("targetId", 0)

        try:
            import renpy

            if hasattr(renpy.game, "script") and renpy.game.script:
                for node in renpy.game.script.namemap.values():
                    label_name = getattr(node, "name", None)
                    if not isinstance(label_name, str):
                        continue
                    if (hash(label_name) & 0x7FFFFFFF) == target_id:
                        if self.debugger.jump_to_label(label_name):
                            return self._success_response(request)
                        else:
                            return self._error_response(request, f"Failed to jump to '{label_name}'")

            return self._error_response(request, f"Target {target_id} not found")

        except Exception as e:
            return self._error_response(request, str(e))

    def _handle_runToLine(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom runToLine request.

        This jumps to the containing label (if needed), sets a temp breakpoint,
        enables skip mode, and resumes execution.
        """
        source = args.get("source", {})
        path = source.get("path", "")
        line = args.get("line", 0)

        result = self.debugger.run_to_line(path, line)

        if result.get("success"):
            return self._success_response(request)
        else:
            return self._error_response(request, result.get("message", "Failed to run to line"))

    def _handle_jumpToLabel(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom jumpToLabel request.

        This is a simpler alternative to goto that takes the label name directly.
        """
        label = args.get("label", "")

        if not label:
            return self._error_response(request, "No label specified")

        if self.debugger.jump_to_label(label):
            return self._success_response(request)
        else:
            return self._error_response(request, f"Failed to jump to '{label}'")

    def _handle_disconnect(self, request: dict, args: dict) -> DAPResponse:
        """Handle disconnect request."""
        self.debugger.detach()
        return self._success_response(request)

    def _handle_terminate(self, request: dict, args: dict) -> DAPResponse:
        """Handle terminate request."""
        self.debugger.detach()

        try:
            import renpy

            renpy.exports.quit()
        except Exception:
            pass

        return self._success_response(request)

    def _handle_evaluate(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle evaluate request.

        Supports contexts:
        - "watch": Watch panel expressions
        - "hover": Hover evaluation in editor
        - "repl": Debug console input (supports both expressions and statements)

        Note: Output from print() and other stdout-writing functions will appear
        in the terminal where the game was launched, not in the Debug Console.
        This is intentional to support interactive functions like help().
        """
        expression = args.get("expression", "")
        context = args.get("context", "watch")

        try:
            import renpy

            # Get evaluation context: frame locals + store globals
            inspector = self.debugger.variable_inspector
            frame = inspector._current_frame

            # Use store as globals, frame locals (if available) as locals
            globals_dict = renpy.python.store_dicts["store"]
            if frame is not None:
                # Merge store globals with frame locals, locals take precedence
                locals_dict = dict(globals_dict)
                locals_dict.update(frame.f_locals)
            else:
                locals_dict = globals_dict

            try:
                result = renpy.python.py_eval(expression, globals_dict, locals_dict)
                var_info = inspector._format_variable(expression, result)

                return self._success_response(
                    request,
                    {
                        "result": var_info["value"],
                        "type": var_info["type"],
                        "variablesReference": var_info["variablesReference"],
                        "namedVariables": var_info.get("namedVariables", 0),
                        "indexedVariables": var_info.get("indexedVariables", 0),
                    },
                )
            except SyntaxError:
                if context == "repl":
                    bytecode = renpy.python.py_compile(expression, "exec")
                    renpy.python.py_exec_bytecode(bytecode, globals=globals_dict, locals=locals_dict)
                    return self._success_response(
                        request,
                        {
                            "result": "OK",
                            "type": "statement",
                            "variablesReference": 0,
                        },
                    )
                else:
                    raise

        except Exception as e:
            if context == "hover":
                return self._success_response(
                    request,
                    {
                        "result": "",
                        "variablesReference": 0,
                    },
                )
            return self._success_response(
                request,
                {
                    "result": f"Error: {e}",
                    "type": "error",
                    "variablesReference": 0,
                },
            )

    def _handle_setExpression(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle setExpression request - modify a watched expression's value.

        This allows editing values directly in the Watch panel.
        """
        expression = args.get("expression", "")
        value = args.get("value", "")

        if not expression:
            return self._error_response(request, "No expression provided")

        try:
            import renpy

            # Get evaluation context: frame locals + store globals
            inspector = self.debugger.variable_inspector
            frame = inspector._current_frame

            globals_dict = renpy.python.store_dicts["store"]
            if frame is not None:
                locals_dict = dict(globals_dict)
                locals_dict.update(frame.f_locals)
            else:
                locals_dict = globals_dict

            assignment = f"{expression} = {value}"
            bytecode = renpy.python.py_compile(assignment, "exec")
            renpy.python.py_exec_bytecode(bytecode, globals=globals_dict, locals=locals_dict)
            new_value = renpy.python.py_eval(expression, globals_dict, locals_dict)
            var_info = inspector._format_variable(expression, new_value)

            return self._success_response(
                request,
                {
                    "value": var_info["value"],
                    "type": var_info["type"],
                    "variablesReference": var_info["variablesReference"],
                    "namedVariables": var_info.get("namedVariables", 0),
                    "indexedVariables": var_info.get("indexedVariables", 0),
                },
            )

        except Exception as e:
            return self._error_response(request, f"Failed to set expression: {e}")

    def _handle_completions(self, request: dict, args: dict) -> DAPResponse:
        """Handle completions request for Debug Console autocomplete."""
        text = args.get("text", "")
        column = args.get("column", len(text))
        text_to_cursor = text[:column]

        targets = []

        try:
            import renpy

            # Get frame locals for completions
            inspector = self.debugger.variable_inspector
            frame = inspector._current_frame
            frame_locals = frame.f_locals if frame is not None else {}

            if "." in text_to_cursor:
                targets = self._get_attribute_completions(text_to_cursor)
            else:
                prefix = ""
                for i in range(len(text_to_cursor) - 1, -1, -1):
                    c = text_to_cursor[i]
                    if c.isalnum() or c == "_":
                        prefix = c + prefix
                    else:
                        break

                prefix_lower = prefix.lower()

                # Add frame locals to completions
                for name, value in frame_locals.items():
                    if name.startswith("_"):
                        continue
                    if not prefix or name.lower().startswith(prefix_lower):
                        if not callable(value) and not isinstance(value, type):
                            targets.append({
                                "label": name,
                                "type": "variable",
                            })

                if hasattr(renpy, "store"):
                    for name in dir(renpy.store):
                        if name.startswith("_"):
                            continue
                        if not prefix or name.lower().startswith(prefix_lower):
                            try:
                                value = getattr(renpy.store, name)
                                if not callable(value) and not isinstance(value, type):
                                    targets.append({
                                        "label": name,
                                        "type": "variable",
                                    })
                            except Exception:
                                pass

                renpy_completions = [
                    "renpy", "persistent", "config", "store",
                ]
                for name in renpy_completions:
                    if not prefix or name.lower().startswith(prefix_lower):
                        targets.append({
                            "label": name,
                            "type": "module",
                        })

                builtins = [
                    "len", "str", "int", "float", "bool", "list", "dict", "set",
                    "tuple", "range", "enumerate", "zip", "map", "filter",
                    "sum", "min", "max", "abs", "round", "sorted", "reversed",
                    "any", "all", "print", "type", "isinstance", "hasattr",
                    "getattr", "setattr", "True", "False", "None",
                ]
                for name in builtins:
                    if not prefix or name.lower().startswith(prefix_lower):
                        targets.append({
                            "label": name,
                            "type": "function" if name[0].islower() else "value",
                        })

        except Exception as e:
            print(f"[DAP] Completions error: {e}")

        targets = sorted(targets, key=lambda x: x["label"])[:50]

        return self._success_response(request, {"targets": targets})

    def _get_attribute_completions(self, text: str) -> list:
        """Get completions for attribute access (e.g., 'obj.attr')."""
        targets = []

        try:
            import renpy

            last_dot = text.rfind(".")
            if last_dot == -1:
                return targets

            obj_expr = text[:last_dot]
            attr_prefix = text[last_dot + 1:].lower()

            # Get evaluation context with frame locals
            inspector = self.debugger.variable_inspector
            frame = inspector._current_frame

            globals_dict = renpy.python.store_dicts["store"]
            if frame is not None:
                locals_dict = dict(globals_dict)
                locals_dict.update(frame.f_locals)
            else:
                locals_dict = globals_dict

            try:
                obj = renpy.python.py_eval(obj_expr, globals_dict, locals_dict)
            except Exception:
                return targets

            for name in dir(obj):
                if name.startswith("_"):
                    continue
                if not attr_prefix or name.lower().startswith(attr_prefix):
                    try:
                        value = getattr(obj, name)
                        if callable(value):
                            comp_type = "method"
                        elif isinstance(value, type):
                            comp_type = "class"
                        else:
                            comp_type = "property"

                        targets.append({
                            "label": name,
                            "type": comp_type,
                        })
                    except Exception:
                        pass

        except Exception as e:
            print(f"[DAP] Attribute completions error: {e}")

        return targets

    def _handle_getSceneState(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getSceneState request.

        Returns the current scene state including:
        - Showing images (by layer)
        - Playing audio (by channel)
        - Current label and line
        """
        state = self.debugger.get_scene_state()
        return self._success_response(request, state)

    def _handle_getImageDefinition(self, request: dict, args: dict) -> DAPResponse:
        """Handle custom getImageDefinition request."""
        tag = args.get("tag", "")
        if not tag:
            return self._error_response(request, "No image tag provided")

        definition = self.debugger._find_image_definition(tag)
        if definition:
            return self._success_response(request, definition)
        else:
            return self._success_response(request, {"found": False})

    def _handle_source(self, request: dict, args: dict) -> DAPResponse:
        """Handle source request - return source file contents."""
        source = args.get("source", {})
        path = source.get("path", "")

        if not path:
            return self._error_response(request, "No source path provided")

        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            return self._success_response(request, {"content": content})
        except FileNotFoundError:
            return self._error_response(request, f"Source file not found: {path}")
        except Exception as e:
            return self._error_response(request, f"Error reading source: {e}")

    # Rollback Visualizer Handlers

    def _handle_getRollbackHistory(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getRollbackHistory request.

        Returns the rollback history as a list of checkpoint info objects.

        Args (in request arguments):
            includeNonCheckpoints: If True, include all rollback entries,
                                   not just user-visible checkpoints.

        Returns:
            List of checkpoint info objects with location, variable changes, etc.
        """
        self._log(f"getRollbackHistory called with args: {args}")
        try:
            from .rollback_visualizer import get_visualizer

            visualizer = get_visualizer()
            include_non_checkpoints = args.get("includeNonCheckpoints", False)

            history = visualizer.get_history(include_non_checkpoints)
            self._log(f"getRollbackHistory returning {len(history)} checkpoints")

            return self._success_response(request, {
                "checkpoints": [cp.to_dict() for cp in history],
                "count": len(history),
            })

        except Exception as e:
            import traceback
            self._log(f"Error getting rollback history: {e}")
            traceback.print_exc()
            return self._error_response(request, f"Failed to get rollback history: {e}")

    def _handle_getCheckpointDetails(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getCheckpointDetails request.

        Returns detailed information about a specific checkpoint.

        Args (in request arguments):
            index: The index of the checkpoint in the log.

        Returns:
            Detailed checkpoint info including full variable state.
        """
        try:
            from .rollback_visualizer import get_visualizer

            visualizer = get_visualizer()
            index = args.get("index", -1)

            if index < 0:
                return self._error_response(request, "Invalid checkpoint index")

            details = visualizer.get_checkpoint_details(index)

            if details:
                return self._success_response(request, details)
            else:
                return self._error_response(request, f"Checkpoint {index} not found")

        except Exception as e:
            self._log(f"Error getting checkpoint details: {e}")
            return self._error_response(request, f"Failed to get checkpoint details: {e}")

    def _handle_gotoCheckpoint(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom gotoCheckpoint request.

        Rolls back to a specific checkpoint in the history.

        Args (in request arguments):
            index: The index of the checkpoint to go to.

        Returns:
            Success/failure status.
        """
        try:
            import renpy
            from .rollback_visualizer import get_visualizer

            index = args.get("index", -1)
            self._log(f"gotoCheckpoint called with index={index}")

            if index < 0:
                return self._error_response(request, "Invalid checkpoint index (negative)")

            # Calculate how many hard checkpoints back we need to go
            log = renpy.game.log
            if not log:
                return self._error_response(request, "No rollback log available")

            log_len = len(log.log)
            self._log(f"gotoCheckpoint: log has {log_len} entries")

            if index >= log_len:
                return self._error_response(request, f"Invalid checkpoint index ({index} >= {log_len})")

            current_idx = log_len - 1

            # Count hard checkpoints between current position and target (exclusive)
            checkpoints_back = 0
            for i in range(current_idx, index, -1):
                rb = log.log[i]
                if getattr(rb, 'hard_checkpoint', False):
                    checkpoints_back += 1

            # To land AT the target, we must include it if it's a hard checkpoint
            # renpy.rollback(checkpoints=N) rolls back N hard checkpoints
            target_rb = log.log[index]
            target_is_hard = getattr(target_rb, 'hard_checkpoint', False)
            if target_is_hard:
                checkpoints_back += 1

            self._log(f"gotoCheckpoint: index={index}, current_idx={current_idx}, target_is_hard={target_is_hard}, checkpoints_back={checkpoints_back}")

            if checkpoints_back <= 0:
                return self._error_response(request, "Target checkpoint is not a valid rollback target (no hard checkpoints)")

            # Use the debugger core to perform the rollback on the main thread
            self._log(f"gotoCheckpoint: calling rollback_to_checkpoint({checkpoints_back})")
            result = self.debugger.rollback_to_checkpoint(checkpoints_back)
            self._log(f"gotoCheckpoint: result={result}")

            if result.get("success"):
                # Invalidate visualizer cache since rollback occurred
                visualizer = get_visualizer()
                visualizer.invalidate_cache()
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, result.get("message", "Failed to rollback to checkpoint"))

        except Exception as e:
            self._log(f"Error going to checkpoint: {e}")
            return self._error_response(request, f"Failed to go to checkpoint: {e}")

    def _handle_findVariableChanges(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom findVariableChanges request.

        Finds all checkpoints where a specific variable changed.

        Args (in request arguments):
            variableName: Name of the variable to search for.
            storeName: Which store to search in (default: "store").

        Returns:
            List of variable change objects.
        """
        try:
            from .rollback_visualizer import get_visualizer

            visualizer = get_visualizer()
            variable_name = args.get("variableName", "")
            store_name = args.get("storeName", "store")

            if not variable_name:
                return self._error_response(request, "No variable name provided")

            changes = visualizer.find_variable_changes(variable_name, store_name)

            return self._success_response(request, {
                "changes": [c.to_dict() for c in changes],
                "count": len(changes),
            })

        except Exception as e:
            self._log(f"Error finding variable changes: {e}")
            return self._error_response(request, f"Failed to find variable changes: {e}")

    def _handle_compareCheckpoints(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom compareCheckpoints request.

        Compares variable state between two checkpoints.

        Args (in request arguments):
            indexA: First checkpoint index.
            indexB: Second checkpoint index.

        Returns:
            Dict with added, removed, and changed variables.
        """
        try:
            from .rollback_visualizer import get_visualizer

            visualizer = get_visualizer()
            index_a = args.get("indexA", -1)
            index_b = args.get("indexB", -1)

            if index_a < 0 or index_b < 0:
                return self._error_response(request, "Invalid checkpoint indices")

            comparison = visualizer.compare_checkpoints(index_a, index_b)

            return self._success_response(request, comparison)

        except Exception as e:
            self._log(f"Error comparing checkpoints: {e}")
            return self._error_response(request, f"Failed to compare checkpoints: {e}")

    def _handle_getExecutionPath(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getExecutionPath request.

        Returns the sequence of labels visited during execution.

        Returns:
            List of dicts with label and checkpoint index info.
        """
        try:
            from .rollback_visualizer import get_visualizer

            visualizer = get_visualizer()
            path = visualizer.get_execution_path()

            return self._success_response(request, {
                "path": path,
                "count": len(path),
            })

        except Exception as e:
            self._log(f"Error getting execution path: {e}")
            return self._error_response(request, f"Failed to get execution path: {e}")

    # Execution Recording Handlers

    def _handle_startRecording(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom startRecording request.

        Starts recording user interactions for automated testing.

        Args (in request arguments):
            name: Name for the recording.
            description: Optional description.
            trackVariables: Optional list of variables to track at checkpoints.

        Returns:
            Success status.
        """
        try:
            from .recorder import get_recorder

            recorder = get_recorder()
            name = args.get("name", f"recording_{int(__import__('time').time())}")
            description = args.get("description", "")
            track_vars = args.get("trackVariables", [])

            # Set tracked variables
            for var in track_vars:
                store = var.get("store", "store")
                var_name = var.get("name", "")
                if var_name:
                    recorder.add_tracked_variable(store, var_name)

            success = recorder.start_recording(name, description)

            if success:
                return self._success_response(request, {
                    "success": True,
                    "name": name,
                })
            else:
                return self._error_response(request, "Failed to start recording (already recording?)")

        except Exception as e:
            self._log(f"Error starting recording: {e}")
            return self._error_response(request, f"Failed to start recording: {e}")

    def _handle_stopRecording(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom stopRecording request.

        Stops the current recording and optionally saves it.

        Args (in request arguments):
            save: Whether to save the recording (default: True).

        Returns:
            Recording summary.
        """
        try:
            from .recorder import get_recorder, get_storage

            recorder = get_recorder()
            save = args.get("save", True)

            recording = recorder.stop_recording()

            if not recording:
                return self._error_response(request, "No active recording")

            result = {
                "success": True,
                "name": recording.name,
                "eventCount": len(recording.events),
                "assertionCount": len(recording.assertions),
                "durationMs": recording.duration_ms,
                "labelsVisited": recording.labels_visited,
                "statementsExecuted": recording.statements_executed,
            }

            if save:
                storage = get_storage()
                saved = storage.save(recording)
                result["saved"] = saved

            return self._success_response(request, result)

        except Exception as e:
            self._log(f"Error stopping recording: {e}")
            return self._error_response(request, f"Failed to stop recording: {e}")

    def _handle_captureScreenshot(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom captureScreenshot request.

        Captures a screenshot as a visual regression checkpoint.

        Args (in request arguments):
            name: Optional name for the screenshot.
            threshold: Maximum allowed difference % (default: 1.0).

        Returns:
            Success status and screenshot info.
        """
        try:
            from .recorder import get_recorder

            recorder = get_recorder()
            name = args.get("name")
            threshold = args.get("threshold", 1.0)

            if not recorder.is_recording:
                return self._error_response(request, "Not currently recording")

            success = recorder.capture_screenshot(name, threshold)

            if success:
                return self._success_response(request, {
                    "success": True,
                    "name": name or "auto-generated",
                    "threshold": threshold,
                })
            else:
                return self._error_response(request, "Failed to capture screenshot")

        except Exception as e:
            self._log(f"Error capturing screenshot: {e}")
            return self._error_response(request, f"Failed to capture screenshot: {e}")

    def _handle_addAssertion(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom addAssertion request.

        Adds an assertion at the current point in the recording.

        Args (in request arguments):
            variable: Variable name to assert.
            store: Store name (default: "store").
            expected: Expected value (if not provided, captures current value).
            comparison: Comparison type (eq, ne, gt, lt, ge, le, contains).

        Returns:
            Success status.
        """
        try:
            from .recorder import get_recorder

            recorder = get_recorder()

            if not recorder.is_recording:
                return self._error_response(request, "Not currently recording")

            variable = args.get("variable", "")
            store = args.get("store", "store")
            expected = args.get("expected")
            comparison = args.get("comparison", "eq")

            if not variable:
                return self._error_response(request, "No variable specified")

            success = recorder.add_assertion_current(variable, store, expected, comparison)

            if success:
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, "Failed to add assertion")

        except Exception as e:
            self._log(f"Error adding assertion: {e}")
            return self._error_response(request, f"Failed to add assertion: {e}")

    def _handle_listRecordings(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom listRecordings request.

        Returns list of saved recordings.
        """
        try:
            from .recorder import get_storage

            storage = get_storage()
            recordings = storage.list_recordings()

            return self._success_response(request, {
                "recordings": recordings,
                "count": len(recordings),
            })

        except Exception as e:
            self._log(f"Error listing recordings: {e}")
            return self._error_response(request, f"Failed to list recordings: {e}")

    def _handle_playRecording(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom playRecording request.

        Starts playback of a saved recording.

        Args (in request arguments):
            name: Name of the recording to play.
            mode: Playback mode (verify, fast, realtime). Default: verify.

        Returns:
            Success status.
        """
        try:
            from .recorder import get_recorder, get_storage, PlaybackMode

            recorder = get_recorder()
            storage = get_storage()

            name = args.get("name", "")
            mode_str = args.get("mode", "verify")

            if not name:
                return self._error_response(request, "No recording name specified")

            recording = storage.load(name)
            if not recording:
                return self._error_response(request, f"Recording not found: {name}")

            mode_map = {
                "verify": PlaybackMode.VERIFY,
                "fast": PlaybackMode.FAST,
                "realtime": PlaybackMode.REALTIME,
            }
            mode = mode_map.get(mode_str, PlaybackMode.VERIFY)

            success = recorder.start_playback(recording, mode)

            if success:
                return self._success_response(request, {
                    "success": True,
                    "name": recording.name,
                    "eventCount": len(recording.events),
                    "mode": mode_str,
                })
            else:
                return self._error_response(request, "Failed to start playback")

        except Exception as e:
            self._log(f"Error starting playback: {e}")
            return self._error_response(request, f"Failed to start playback: {e}")

    def _handle_stopPlayback(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom stopPlayback request.

        Stops the current playback and returns results.
        """
        try:
            from .recorder import get_recorder

            recorder = get_recorder()
            result = recorder.stop_playback()

            if result:
                return self._success_response(request, result.to_dict())
            else:
                return self._error_response(request, "No active playback")

        except Exception as e:
            self._log(f"Error stopping playback: {e}")
            return self._error_response(request, f"Failed to stop playback: {e}")

    def _handle_getPlaybackStatus(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getPlaybackStatus request.

        Returns the current playback status.
        """
        try:
            from .recorder import get_recorder

            recorder = get_recorder()

            if recorder.is_playing:
                result = recorder.playback_result
                return self._success_response(request, {
                    "isPlaying": True,
                    "eventsPlayed": result.events_played if result else 0,
                    "eventsTotal": result.events_total if result else 0,
                    "assertionsPassed": result.assertions_passed if result else 0,
                    "assertionsFailed": result.assertions_failed if result else 0,
                    "screenshotsPassed": result.screenshots_passed if result else 0,
                    "screenshotsFailed": result.screenshots_failed if result else 0,
                })
            else:
                return self._success_response(request, {"isPlaying": False})

        except Exception as e:
            self._log(f"Error getting playback status: {e}")
            return self._error_response(request, f"Failed to get playback status: {e}")

    def _handle_getRecordingStatus(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getRecordingStatus request.

        Returns the current recording status.
        """
        try:
            from .recorder import get_recorder

            recorder = get_recorder()

            if recorder.is_recording:
                recording = recorder.current_recording
                return self._success_response(request, {
                    "isRecording": True,
                    "name": recording.name if recording else "",
                    "eventCount": len(recording.events) if recording else 0,
                    "assertionCount": len(recording.assertions) if recording else 0,
                })
            else:
                return self._success_response(request, {"isRecording": False})

        except Exception as e:
            self._log(f"Error getting recording status: {e}")
            return self._error_response(request, f"Failed to get recording status: {e}")

    def _handle_deleteRecording(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom deleteRecording request.

        Deletes a saved recording.

        Args (in request arguments):
            name: Name of the recording to delete.
        """
        try:
            from .recorder import get_storage

            storage = get_storage()
            name = args.get("name", "")

            if not name:
                return self._error_response(request, "No recording name specified")

            success = storage.delete(name)

            if success:
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, f"Failed to delete recording: {name}")

        except Exception as e:
            self._log(f"Error deleting recording: {e}")
            return self._error_response(request, f"Failed to delete recording: {e}")

    def _handle_exportRecording(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom exportRecording request.

        Exports a recording to a specific format.

        Args (in request arguments):
            name: Name of the recording to export.
            format: Export format (renpy_test, json). Default: renpy_test.

        Returns:
            Exported content as string.
        """
        try:
            from .recorder import get_recorder, get_storage

            storage = get_storage()
            recorder = get_recorder()

            name = args.get("name", "")
            export_format = args.get("format", "renpy_test")

            if not name:
                return self._error_response(request, "No recording name specified")

            recording = storage.load(name)
            if not recording:
                return self._error_response(request, f"Recording not found: {name}")

            if export_format == "renpy_test":
                content = recorder.export_to_renpy_test(recording)
            elif export_format == "json":
                content = recorder.export_to_json(recording)
            else:
                return self._error_response(request, f"Unknown export format: {export_format}")

            return self._success_response(request, {
                "format": export_format,
                "content": content,
            })

        except Exception as e:
            self._log(f"Error exporting recording: {e}")
            return self._error_response(request, f"Failed to export recording: {e}")

    # Layered Image Inspector Handlers

    def _handle_getLayeredImages(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getLayeredImages request.

        Returns list of all layered images defined in the game.
        """
        try:
            from .layered_image_inspector import get_inspector

            inspector = get_inspector()
            images = inspector.get_layered_images()

            return self._success_response(request, {
                "images": images,
                "count": len(images),
            })

        except Exception as e:
            self._log(f"Error getting layered images: {e}")
            return self._error_response(request, f"Failed to get layered images: {e}")

    def _handle_getLayeredImageDetails(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getLayeredImageDetails request.

        Args (in request arguments):
            imageName: The name of the layered image.

        Returns:
            Detailed layered image info with attributes, groups, and layers.
        """
        try:
            from .layered_image_inspector import get_inspector

            inspector = get_inspector()
            image_name = args.get("imageName", "")

            if not image_name:
                return self._error_response(request, "No image name specified")

            details = inspector.get_layered_image_details(image_name)

            if details:
                return self._success_response(request, details)
            else:
                return self._error_response(request, f"Layered image not found: {image_name}")

        except Exception as e:
            self._log(f"Error getting layered image details: {e}")
            return self._error_response(request, f"Failed to get layered image details: {e}")

    def _handle_getShownLayeredImages(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getShownLayeredImages request.

        Returns layered images currently displayed on screen.
        """
        try:
            from .layered_image_inspector import get_inspector

            inspector = get_inspector()
            shown = inspector.get_shown_layered_images()

            return self._success_response(request, {
                "images": shown,
                "count": len(shown),
            })

        except Exception as e:
            self._log(f"Error getting shown layered images: {e}")
            return self._error_response(request, f"Failed to get shown layered images: {e}")

    def _handle_setLayeredImageAttribute(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom setLayeredImageAttribute request.

        Toggle an attribute on a shown layered image.

        Args (in request arguments):
            imageTag: The tag of the shown image.
            attribute: The attribute to toggle.
            enabled: Whether to enable or disable.

        Returns:
            Success status.
        """
        try:
            from .layered_image_inspector import get_inspector

            inspector = get_inspector()
            image_tag = args.get("imageTag", "")
            attribute = args.get("attribute", "")
            enabled = args.get("enabled", True)

            if not image_tag or not attribute:
                return self._error_response(request, "Image tag and attribute required")

            success = inspector.set_attribute(image_tag, attribute, enabled)

            if success:
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, "Failed to set attribute")

        except Exception as e:
            self._log(f"Error setting layered image attribute: {e}")
            return self._error_response(request, f"Failed to set attribute: {e}")

    def _handle_previewLayeredImage(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom previewLayeredImage request.

        Show a layered image with specific attributes for preview.

        Args (in request arguments):
            imageName: Base name of the layered image.
            attributes: List of attributes to show.

        Returns:
            Success status.
        """
        try:
            from .layered_image_inspector import get_inspector

            inspector = get_inspector()
            image_name = args.get("imageName", "")
            attributes = args.get("attributes", [])

            if not image_name:
                return self._error_response(request, "Image name required")

            success = inspector.preview_attributes(image_name, attributes)

            if success:
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, "Failed to preview image")

        except Exception as e:
            self._log(f"Error previewing layered image: {e}")
            return self._error_response(request, f"Failed to preview image: {e}")

    # Save Inspector Handlers

    def _handle_listSaves(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom listSaves request.

        Returns list of all save files.
        """
        try:
            from .save_inspector import get_inspector

            inspector = get_inspector()
            saves = inspector.list_saves()

            return self._success_response(request, {
                "saves": saves,
                "count": len(saves),
            })

        except Exception as e:
            self._log(f"Error listing saves: {e}")
            return self._error_response(request, f"Failed to list saves: {e}")

    def _handle_getSaveDetails(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getSaveDetails request.

        Args (in request arguments):
            slotName: The save slot name.

        Returns:
            Detailed save contents.
        """
        try:
            from .save_inspector import get_inspector

            inspector = get_inspector()
            slot_name = args.get("slotName", "")

            if not slot_name:
                return self._error_response(request, "No slot name specified")

            details = inspector.get_save_details(slot_name)

            if details:
                return self._success_response(request, details)
            else:
                return self._error_response(request, f"Save not found: {slot_name}")

        except Exception as e:
            self._log(f"Error getting save details: {e}")
            return self._error_response(request, f"Failed to get save details: {e}")

    def _handle_compareSaves(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom compareSaves request.

        Compare two save files.

        Args (in request arguments):
            slotA: First save slot name.
            slotB: Second save slot name.

        Returns:
            Comparison results with added, removed, and changed variables.
        """
        try:
            from .save_inspector import get_inspector

            inspector = get_inspector()
            slot_a = args.get("slotA", "")
            slot_b = args.get("slotB", "")

            if not slot_a or not slot_b:
                return self._error_response(request, "Both slot names required")

            comparison = inspector.compare_saves(slot_a, slot_b)

            if comparison:
                return self._success_response(request, comparison)
            else:
                return self._error_response(request, "Failed to compare saves")

        except Exception as e:
            self._log(f"Error comparing saves: {e}")
            return self._error_response(request, f"Failed to compare saves: {e}")

    # Persistent Data Handlers

    def _handle_getPersistentData(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom getPersistentData request.

        Returns all persistent variables and preferences.
        """
        try:
            from .save_inspector import get_inspector

            inspector = get_inspector()
            data = inspector.get_persistent_data()

            return self._success_response(request, {
                "persistent": data.get("persistent", []),
                "preferences": data.get("preferences", []),
                "persistentCount": len(data.get("persistent", [])),
                "preferencesCount": len(data.get("preferences", [])),
            })

        except Exception as e:
            self._log(f"Error getting persistent data: {e}")
            return self._error_response(request, f"Failed to get persistent data: {e}")

    def _handle_setPersistent(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom setPersistent request.

        Set a persistent variable.

        Args (in request arguments):
            name: Variable name.
            value: New value (as string, will be evaluated).
            valueType: Type hint (string, int, float, bool, none).

        Returns:
            Success status.
        """
        try:
            from .save_inspector import get_inspector

            inspector = get_inspector()
            name = args.get("name", "")
            value_str = args.get("value", "")
            value_type = args.get("valueType", "string")

            if not name:
                return self._error_response(request, "Variable name required")

            # Parse value based on type
            if value_type == "none" or value_str.lower() == "none":
                value = None
            elif value_type == "bool":
                value = value_str.lower() in ("true", "1", "yes")
            elif value_type == "int":
                value = int(value_str)
            elif value_type == "float":
                value = float(value_str)
            elif value_type == "eval":
                # Evaluate as Python expression (careful!)
                value = eval(value_str)
            else:
                value = value_str

            success = inspector.set_persistent(name, value)

            if success:
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, "Failed to set persistent")

        except Exception as e:
            self._log(f"Error setting persistent: {e}")
            return self._error_response(request, f"Failed to set persistent: {e}")

    def _handle_deletePersistent(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom deletePersistent request.

        Delete (reset) a persistent variable.

        Args (in request arguments):
            name: Variable name.

        Returns:
            Success status.
        """
        try:
            from .save_inspector import get_inspector

            inspector = get_inspector()
            name = args.get("name", "")

            if not name:
                return self._error_response(request, "Variable name required")

            success = inspector.delete_persistent(name)

            if success:
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, f"Failed to delete persistent: {name}")

        except Exception as e:
            self._log(f"Error deleting persistent: {e}")
            return self._error_response(request, f"Failed to delete persistent: {e}")

    def _handle_savePersistent(self, request: dict, args: dict) -> DAPResponse:
        """
        Handle custom savePersistent request.

        Force save persistent data to disk.

        Returns:
            Success status.
        """
        try:
            from .save_inspector import get_inspector

            inspector = get_inspector()
            success = inspector.save_persistent()

            if success:
                return self._success_response(request, {"success": True})
            else:
                return self._error_response(request, "Failed to save persistent")

        except Exception as e:
            self._log(f"Error saving persistent: {e}")
            return self._error_response(request, f"Failed to save persistent: {e}")
