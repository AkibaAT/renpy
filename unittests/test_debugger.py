# Copyright 2004-2026 Tom Rothamel <pytom@bishoujo.us>
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

import json
import unittest

from renpy.debugger.dap_server import DAPServer
from renpy.debugger.live_edit import LiveEditManager
from renpy.debugger.protocol import create_event, create_response, parse_message


class LiveEditParsingTest(unittest.TestCase):
    def setUp(self):
        self.manager = LiveEditManager(debugger=None)

    def test_parses_narrator_line(self):
        self.assertEqual(
            self.manager._parse_say_line_full('"Hello."'),
            (None, "Hello."),
        )

    def test_parses_character_line(self):
        self.assertEqual(
            self.manager._parse_say_line_full('e "Hello."'),
            ("e", "Hello."),
        )

    def test_preserves_speaker_with_say_attributes(self):
        self.assertEqual(
            self.manager._parse_say_line_full('e happy "Hello."'),
            ("e", "Hello."),
        )
        self.assertEqual(
            self.manager._parse_say_line_full('e @ happy "Hello."'),
            ("e", "Hello."),
        )

    def test_ignores_with_clause(self):
        self.assertEqual(
            self.manager._parse_say_line_full('e "Hello." with dissolve'),
            ("e", "Hello."),
        )

    def test_unescapes_dialogue_text(self):
        self.assertEqual(
            self.manager._parse_say_line_full(r'e "Line\n\"quoted\""'),
            ("e", 'Line\n"quoted"'),
        )


class ProtocolTest(unittest.TestCase):
    def test_response_round_trips_through_wire_format(self):
        response = create_response(
            {"seq": 7, "command": "threads"},
            seq=3,
            body={"threads": [{"id": 1, "name": "Main Thread"}]},
        )

        parsed = parse_message(response.to_wire())

        self.assertEqual(parsed["type"], "response")
        self.assertEqual(parsed["request_seq"], 7)
        self.assertEqual(parsed["command"], "threads")
        self.assertTrue(parsed["success"])
        self.assertEqual(parsed["body"]["threads"][0]["name"], "Main Thread")

    def test_event_omits_empty_body(self):
        event = create_event(1, "initialized")
        payload = json.loads(event.to_wire().split(b"\r\n\r\n", 1)[1])

        self.assertEqual(payload, {"seq": 1, "type": "event", "event": "initialized"})


class DAPRequestRoutingTest(unittest.TestCase):
    def test_engine_implements_extension_custom_requests(self):
        server = DAPServer(debugger=object())
        extension_requests = [
            "getRollbackHistory",
            "gotoCheckpoint",
            "findVariableChanges",
            "getRecordingStatus",
            "getPlaybackStatus",
            "listRecordings",
            "startRecording",
            "stopRecording",
            "captureScreenshot",
            "addAssertion",
            "playRecording",
            "stopPlayback",
            "deleteRecording",
            "exportRecording",
            "listSaves",
            "getPersistentData",
            "getSaveDetails",
            "compareSaves",
            "setPersistent",
            "deletePersistent",
            "getLayeredImages",
            "getShownLayeredImages",
            "getLayeredImageDetails",
            "setLayeredImageAttribute",
            "previewLayeredImage",
            "getSceneState",
            "runToLine",
            "jumpToLabel",
            "gotoTargets",
            "goto",
        ]

        for command in extension_requests:
            with self.subTest(command=command):
                self.assertTrue(hasattr(server, f"_handle_{command}"))

    def test_unknown_command_returns_error_response(self):
        server = DAPServer(debugger=object())
        responses = []
        server._send_response = responses.append

        server._handle_request({"seq": 1, "type": "request", "command": "missingCommand"})

        self.assertEqual(len(responses), 1)
        response = responses[0].to_dict()
        self.assertFalse(response["success"])
        self.assertEqual(response["command"], "missingCommand")
        self.assertIn("Unknown command", response["message"])

    def test_custom_handler_response_shape(self):
        class Debugger:
            pass

        server = DAPServer(debugger=Debugger())

        response = server._success_response(
            {"seq": 2, "command": "listSaves"},
            {"saves": [], "count": 0},
        ).to_dict()

        self.assertTrue(response["success"])
        self.assertEqual(response["body"], {"saves": [], "count": 0})


if __name__ == "__main__":
    unittest.main()
