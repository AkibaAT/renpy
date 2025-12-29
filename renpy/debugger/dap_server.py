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
            self._socket.listen(1)
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

        This method prioritizes fast shutdown. All blocking operations
        check the shutdown event and exit quickly.
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

        if self._client_thread:
            self._client_thread.join(timeout=0.2)
            self._client_thread = None

        if self._server_thread:
            self._server_thread.join(timeout=0.2)
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

    def _log(self, message: str) -> None:
        """Log a debug message."""
        try:
            import renpy

            if hasattr(renpy, "display") and hasattr(renpy.display, "log"):
                renpy.display.log.write(f"[DAP] {message}")
        except Exception:
            pass
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

            try:
                result = renpy.python.py_eval(expression)
                inspector = self.debugger.variable_inspector
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
                    renpy.python.py_exec(expression)
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

            assignment = f"{expression} = {value}"
            renpy.python.py_exec(assignment)
            new_value = renpy.python.py_eval(expression)
            inspector = self.debugger.variable_inspector
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

            try:
                obj = renpy.python.py_eval(obj_expr)
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
