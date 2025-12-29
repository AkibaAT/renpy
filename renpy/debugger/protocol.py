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
DAP (Debug Adapter Protocol) message types and constants.

This module defines the message format and constants used for communication
between the debugger and IDE via the Debug Adapter Protocol.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


# DAP Message Types
class MessageType:
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"


# DAP Commands (Requests)
class Command:
    # Lifecycle
    INITIALIZE = "initialize"
    CONFIGURATION_DONE = "configurationDone"
    DISCONNECT = "disconnect"
    TERMINATE = "terminate"

    # Breakpoints
    SET_BREAKPOINTS = "setBreakpoints"
    SET_FUNCTION_BREAKPOINTS = "setFunctionBreakpoints"
    SET_EXCEPTION_BREAKPOINTS = "setExceptionBreakpoints"

    # Execution Control
    CONTINUE = "continue"
    PAUSE = "pause"
    NEXT = "next"
    STEP_IN = "stepIn"
    STEP_OUT = "stepOut"

    # Stack and Variables
    THREADS = "threads"
    STACK_TRACE = "stackTrace"
    SCOPES = "scopes"
    VARIABLES = "variables"

    # Evaluation
    EVALUATE = "evaluate"


# DAP Events
class Event:
    INITIALIZED = "initialized"
    STOPPED = "stopped"
    CONTINUED = "continued"
    EXITED = "exited"
    TERMINATED = "terminated"
    THREAD = "thread"
    OUTPUT = "output"
    BREAKPOINT = "breakpoint"


# Stop Reasons
class StopReason:
    STEP = "step"
    BREAKPOINT = "breakpoint"
    EXCEPTION = "exception"
    PAUSE = "pause"
    ENTRY = "entry"
    GOTO = "goto"
    FUNCTION_BREAKPOINT = "function breakpoint"
    DATA_BREAKPOINT = "data breakpoint"


# Variable Scope Types
class ScopeType:
    LOCALS = "Locals"
    GLOBALS = "Globals"
    REGISTERS = "Registers"


# Output Categories
class OutputCategory:
    CONSOLE = "console"
    STDOUT = "stdout"
    STDERR = "stderr"
    TELEMETRY = "telemetry"


@dataclass
class DAPMessage:
    """Base class for DAP messages."""

    seq: int
    type: str

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "type": self.type}

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    def to_wire(self) -> bytes:
        """Convert to wire format with Content-Length header."""
        content = self.to_json()
        header = f"Content-Length: {len(content)}\r\n\r\n"
        return (header + content).encode("utf-8")


@dataclass
class DAPRequest(DAPMessage):
    """DAP request message from client to adapter."""

    command: str
    arguments: dict[str, Any] = field(default_factory=dict)
    type: str = field(default=MessageType.REQUEST, init=False)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["command"] = self.command
        if self.arguments:
            d["arguments"] = self.arguments
        return d


@dataclass
class DAPResponse(DAPMessage):
    """DAP response message from adapter to client."""

    request_seq: int
    success: bool
    command: str
    message: Optional[str] = None
    body: dict[str, Any] = field(default_factory=dict)
    type: str = field(default=MessageType.RESPONSE, init=False)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["request_seq"] = self.request_seq
        d["success"] = self.success
        d["command"] = self.command
        if self.message:
            d["message"] = self.message
        if self.body:
            d["body"] = self.body
        return d


@dataclass
class DAPEvent(DAPMessage):
    """DAP event message from adapter to client."""

    event: str
    body: dict[str, Any] = field(default_factory=dict)
    type: str = field(default=MessageType.EVENT, init=False)

    def to_dict(self) -> dict[str, Any]:
        d = super().to_dict()
        d["event"] = self.event
        if self.body:
            d["body"] = self.body
        return d


# DAP Capabilities - what features we support
DEBUGGER_CAPABILITIES = {
    "supportsConfigurationDoneRequest": True,
    "supportsFunctionBreakpoints": True,
    "supportsConditionalBreakpoints": True,
    "supportsHitConditionalBreakpoints": True,
    "supportsEvaluateForHovers": True,
    "supportsStepBack": True,
    "supportsSetVariable": True,
    "supportsRestartFrame": False,
    "supportsGotoTargetsRequest": True,
    "supportsStepInTargetsRequest": False,
    "supportsCompletionsRequest": True,
    "supportsModulesRequest": False,
    "supportsExceptionOptions": True,
    "supportsValueFormattingOptions": False,
    "supportsExceptionInfoRequest": True,
    "supportTerminateDebuggee": True,
    "supportsDelayedStackTraceLoading": False,
    "supportsLoadedSourcesRequest": False,
    "supportsLogPoints": True,
    "supportsTerminateThreadsRequest": False,
    "supportsSetExpression": True,
    "supportsTerminateRequest": True,
    "supportsDataBreakpoints": False,
    "supportsReadMemoryRequest": False,
    "supportsDisassembleRequest": False,
    "supportsCancelRequest": False,
    "supportsBreakpointLocationsRequest": False,
    "supportsClipboardContext": False,
    "supportsSteppingGranularity": False,
    "supportsInstructionBreakpoints": False,
    "supportsExceptionFilterOptions": True,
    # Exception breakpoint filters
    "exceptionBreakpointFilters": [
        {
            "filter": "raised",
            "label": "Raised Exceptions",
            "description": "Break when any exception is raised",
            "default": False,
        },
        {
            "filter": "uncaught",
            "label": "Uncaught Exceptions",
            "description": "Break on exceptions not caught by the game",
            "default": True,
        },
    ],
}


def parse_message(data: bytes) -> Optional[dict[str, Any]]:
    """
    Parse a DAP message from wire format.

    Returns the parsed message dict, or None if parsing fails.
    """
    try:
        text = data.decode("utf-8")

        # Find the header/body separator
        separator = "\r\n\r\n"
        sep_idx = text.find(separator)
        if sep_idx == -1:
            return None

        # Parse headers
        headers = text[:sep_idx]
        content_length = 0
        for line in headers.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":", 1)[1].strip())
                break

        if content_length == 0:
            return None

        # Parse body
        body_start = sep_idx + len(separator)
        body = text[body_start : body_start + content_length]

        return json.loads(body)
    except (ValueError, json.JSONDecodeError):
        return None


def create_response(
    request: dict[str, Any],
    seq: int,
    success: bool = True,
    body: Optional[dict[str, Any]] = None,
    message: Optional[str] = None,
) -> DAPResponse:
    """Create a response for a request."""
    return DAPResponse(
        seq=seq,
        request_seq=request.get("seq", 0),
        success=success,
        command=request.get("command", ""),
        message=message,
        body=body or {},
    )


def create_event(seq: int, event: str, body: Optional[dict[str, Any]] = None) -> DAPEvent:
    """Create an event message."""
    return DAPEvent(seq=seq, event=event, body=body or {})
