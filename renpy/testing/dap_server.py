from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode  # *

import json
import os
import socket
import socketserver
import threading
import traceback
import queue
import renpy

# Lightweight native DAP server for Ren'Py debugging without debugpy.
# Speaks a minimal subset of the Debug Adapter Protocol sufficient for
# breakpoints, stepping, stack, scopes, and variables against Ren'Py state.


class DAPServer(object):
    def __init__(self, host, port, debugger):
        self.host = host
        self.port = port
        self.debugger = debugger

        # Sequence tracking and single-client socket
        self._server = None
        self._client = None
        # Legacy single-client fields kept for compatibility with notify helpers
        self._recv_thread = None
        self._accept_thread = None
        self._watchdog_thread = None
        self._running = False
        self._lock = threading.RLock()
        self._seq = 1

        # Simple variables reference registry
        self._var_ref_lock = threading.Lock()
        self._next_var_ref = 1
        self._var_refs = {}  # id -> dict/list

        # Configure Ren'Py for script editing (like interactive director)
        self._configure_for_script_editing()

        # Pause listener attachment is handled by mediator after loads

    def _configure_for_script_editing(self):
        """Configure Ren'Py for script editing like the interactive director."""
        try:
            import renpy
            # Enable script editing by disabling line clearing
            renpy.config.clear_lines = False
            # Enable line logging for better debugging
            renpy.config.line_log = True
        except Exception:
            # If configuration fails, continue anyway
            pass

    def reattach_debugger(self):
        """Reacquire the debugger object after a script reload and re-register pause listener."""
        try:
            from renpy.testing import debugger as _dbg
            self.debugger = _dbg.get_debugger()
            try:
                self.debugger.pause_listener = self._on_debugger_paused
            except Exception:
                pass
            return True
        except Exception:
            traceback.print_exc()
            return False

    # ---------- Public control ----------

    def start(self):
        # No-op in ThreadingTCPServer mode; kept for API compatibility
        self._running = True

    def stop(self):
        # No-op here; actual TCPServer shutdown is handled by stop_dap_server
        self._running = False

    # ---------- Socket handling ----------

    # accept/recv/watchdog loops are handled by ThreadingTCPServer

    # ---------- Protocol ----------

    def _handle_message(self, message, writer=None):
        mtype = message.get("type")
        if mtype == "request":
            cmd = message.get("command")
            try:
                print("[DAP] request:", cmd, message.get("arguments") or message.get("body"))
            except Exception:
                pass
            try:
                handler = getattr(self, "_handle_" + cmd)
            except Exception:
                handler = None
            if handler is None:
                self._send_response(message, success=False, body={}, message="Unsupported command: %s" % cmd, writer=writer)
                return
            try:
                body = handler(message)
                self._send_response(message, success=True, body=(body or {}), writer=writer)
            except Exception as e:
                traceback.print_exc()
                self._send_response(message, success=False, body={}, message=str(e), writer=writer)

    def _send(self, obj):
        data = json.dumps(obj).encode("utf-8")
        header = ("Content-Length: %d\r\n\r\n" % len(data)).encode("utf-8")
        with self._lock:
            if not self._client:
                return
            try:
                self._client.sendall(header + data)
            except Exception:
                pass

    def _send_writer(self, sock, obj):
        data = json.dumps(obj).encode("utf-8")
        header = ("Content-Length: %d\r\n\r\n" % len(data)).encode("utf-8")
        try:
            sock.sendall(header + data)
        except Exception:
            pass

    def _next_seq(self):
        with self._lock:
            s = self._seq
            self._seq += 1
            return s

    def _send_response(self, request, success=True, body=None, message=None, writer=None):
        resp = {
            "seq": self._next_seq(),
            "type": "response",
            "request_seq": request.get("seq", 0),
            "success": bool(success),
            "command": request.get("command"),
        }
        if message is not None:
            resp["message"] = message
        if body is not None:
            resp["body"] = body
        try:
            print("[DAP] response:", request.get("command"), body)
        except Exception:
            pass
        if writer is not None:
            self._send_writer(writer, resp)
        else:
            self._send(resp)

    def _send_event(self, event, body=None):
        ev = {
            "seq": self._next_seq(),
            "type": "event",
            "event": event,
            "body": body or {},
        }
        try:
            print("[DAP] event:", event, body)
        except Exception:
            pass
        _dap_broadcast(ev)

    # ---------- Helpers ----------

    def _register_variables(self, data):
        with self._var_ref_lock:
            ref = self._next_var_ref
            self._next_var_ref += 1
            self._var_refs[ref] = data
            return ref

    def _get_variables(self, ref):
        return self._var_refs.get(ref, {})

    def _basename(self, path):
        try:
            return os.path.basename(path)
        except Exception:
            return path

    def _resolve_full_path(self, filename):
        """Resolve a .rpy filename to an absolute path if possible."""
        if not filename:
            return filename
        try:
            # Already absolute
            if os.path.isabs(filename) and os.path.exists(filename):
                return filename
            # Try debugger helper first
            try:
                from renpy.testing import debugger as _dbg
                dbg = _dbg.get_debugger()
                full = None
                if hasattr(dbg, '_get_full_rpy_path'):
                    full = dbg._get_full_rpy_path(filename)
                if full:
                    return full
            except Exception:
                pass

            # Try gamedir
            gd = getattr(renpy.config, 'gamedir', None)
            if gd:
                cand = os.path.join(gd, filename)
                if os.path.exists(cand):
                    return os.path.abspath(cand)

            # Try basedir
            bd = getattr(renpy.config, 'basedir', None)
            if bd:
                cand = os.path.join(bd, filename)
                if os.path.exists(cand):
                    return os.path.abspath(cand)

            # Try local game folder
            cand = os.path.join('game', filename)
            if os.path.exists(cand):
                return os.path.abspath(cand)
        except Exception:
            pass
        return filename

    # ---------- Request handlers ----------

    def _handle_initialize(self, req):
        # Capabilities: minimal set
        self._send_event("initialized", {})
        return {
            "supportsConfigurationDoneRequest": True,
            "supportsRestartRequest": False,
            "supportsStepInTargetsRequest": False,
            "supportsEvaluateForHovers": False,
            "supportsSetVariable": False,
        }

    def _handle_configurationDone(self, req):
        return {}

    def _handle_threads(self, req):
        return {"threads": [{"id": 1, "name": "MainThread"}]}

    def _handle_setBreakpoints(self, req):
        args = req.get("arguments") or req.get("body") or {}
        source = args.get("source", {})
        bps = args.get("breakpoints", []) or args.get("lines", [])

        # Normalize to list of line numbers
        if bps and isinstance(bps[0], dict):
            lines = [bp.get("line") for bp in bps if bp.get("line")]
        else:
            lines = list(bps)

        filename = source.get("path") or source.get("name") or ""
        basename = self._basename(filename)
        resolved = self._resolve_full_path(basename)

        # Clear existing for this file then set new
        try:
            from renpy.testing import debugger as _dbg
            _dbg.clear_all_breakpoints(basename)
            for ln in lines:
                _dbg.set_breakpoint(basename, int(ln))
        except Exception:
            traceback.print_exc()

        return {
            "breakpoints": [
                {"verified": True, "line": ln, "source": {"path": resolved}}
                for ln in lines
            ]
        }

    def _handle_continue(self, req):
        try:
            get_mediator().submit("continue", req.get("arguments") or {})
        except Exception:
            traceback.print_exc()
        # Emit continued event
        self._send_event("continued", {"threadId": 1})
        return {"allThreadsContinued": True}

    def _handle_disconnect(self, req):
        # On disconnect request, resume if paused so the game doesn't freeze,
        # but keep the server and debugger running to allow reconnection.
        try:
            self._resume_if_paused()
        except Exception:
            traceback.print_exc()
        # Inform client but keep server alive
        self._send_event("terminated", {})
        return {}

    def _handle_terminate(self, req):
        # Same behavior as disconnect for now
        return self._handle_disconnect(req)

    def _handle_next(self, req):
        try:
            get_mediator().submit("next", req.get("arguments") or {})
        except Exception:
            traceback.print_exc()
        # Notify client that execution continued
        self._send_event("continued", {"threadId": 1})
        return {}

    def _handle_stepIn(self, req):
        try:
            get_mediator().submit("stepIn", req.get("arguments") or {})
        except Exception:
            traceback.print_exc()
        self._send_event("continued", {"threadId": 1})
        return {}

    def _handle_stepOut(self, req):
        try:
            get_mediator().submit("stepOut", req.get("arguments") or {})
        except Exception:
            traceback.print_exc()
        self._send_event("continued", {"threadId": 1})
        return {}

    def _handle_pause(self, req):
        # Not fully supported; simulate a stop at current location
        try:
            self._emit_stopped(reason="pause")
        except Exception:
            traceback.print_exc()
        return {}

    def _handle_stackTrace(self, req):
        result = get_mediator().submit("stackTrace", req.get("arguments") or {}) or {}
        frames = []
        for idx, f in enumerate(result.get("frames", [])):
            name = f.get("function") or "script"
            path = f.get("filename")
            resolved = self._resolve_full_path(path)
            line = f.get("line") or 1
            frames.append({
                "id": idx + 1,
                "name": name,
                "source": {"name": self._basename(resolved), "path": resolved},
                "line": line,
                "column": 1,
            })
        return {"stackFrames": frames, "totalFrames": len(frames)}

    def _handle_scopes(self, req):
        result = get_mediator().submit("scopes", req.get("arguments") or {}) or {}
        vars_map = result.get("variables", {})
        scene_tree = result.get("scene", {})
        scopes = []
        ref_vars = self._register_variables(vars_map)
        scopes.append({"name": "Ren'Py Variables", "variablesReference": ref_vars, "expensive": False})
        ref_scene = self._register_variables(scene_tree)
        scopes.append({"name": "Scene Objects", "variablesReference": ref_scene, "expensive": False})
        return {"scopes": scopes}

    def _handle_variables(self, req):
        args = req.get("arguments") or {}
        ref = int(args.get("variablesReference", 0))
        data = self._get_variables(ref)

        variables = []
        if isinstance(data, dict):
            for k, v in sorted(data.items(), key=lambda x: x[0]):
                child_ref = 0
                value_str = None
                if isinstance(v, (dict, list, tuple)):
                    child_ref = self._register_variables(v)
                    value_str = "{}" if isinstance(v, dict) else "[]"
                else:
                    try:
                        value_str = pystr(v)
                    except Exception:
                        value_str = str(v)
                variables.append({
                    "name": pystr(k),
                    "value": value_str,
                    "variablesReference": child_ref,
                })
        elif isinstance(data, (list, tuple)):
            for i, v in enumerate(data):
                child_ref = 0
                value_str = None
                if isinstance(v, (dict, list, tuple)):
                    child_ref = self._register_variables(v)
                    value_str = "{}" if isinstance(v, dict) else "[]"
                else:
                    try:
                        value_str = pystr(v)
                    except Exception:
                        value_str = str(v)
                variables.append({
                    "name": str(i),
                    "value": value_str,
                    "variablesReference": child_ref,
                })
        return {"variables": variables}

    # ---------- VN-specific utilities ----------

    def _handle_getSceneObjects(self, req):
        try:
            from renpy.testing.state_inspector import StateInspector
            inspector = StateInspector()
            info = inspector.get_scene_info() or {}
            # Augment with location info
            try:
                loc = {
                    'label': inspector.get_current_label(),
                }
                try:
                    dlg = inspector.get_dialogue_info() or {}
                    loc['filename'] = dlg.get('filename')
                    loc['line'] = dlg.get('linenumber')
                    loc['statement_type'] = dlg.get('statement_type')
                except Exception:
                    pass
                info['location'] = loc
            except Exception:
                pass

            # Augment audio with volume/state
            try:
                audio = info.get('audio_info') or {}
                # Query common channels
                channels = ['music', 'sound', 'voice']
                for ch in channels:
                    try:
                        vol = None
                        try:
                            # renpy.music.set_volume/get_volume typically available
                            vol = renpy.music.get_volume(channel=ch)  # type: ignore
                        except Exception:
                            pass
                        entry = audio.get(ch) if isinstance(audio.get(ch), dict) else None
                        if entry is None and ch == 'music' and audio.get('music'):
                            entry = audio['music']
                        if isinstance(entry, dict):
                            entry['volume'] = vol
                        else:
                            audio[ch] = { 'filename': None, 'channel': ch, 'volume': vol }
                    except Exception:
                        pass
                info['audio_info'] = audio
            except Exception:
                pass

            return {"scene": info}
        except Exception as e:
            traceback.print_exc()
            return {"scene": {"error": str(e)}}

    def _handle_setImagePosition(self, req):
        args = req.get("arguments") or {}
        tag = args.get("tag") or args.get("name")
        layer = args.get("layer", "master")
        xpos = args.get("xpos")
        ypos = args.get("ypos")
        xanchor = args.get("xanchor", 0.5)
        yanchor = args.get("yanchor", 1.0)
        rotate = args.get("rotate")
        zoom = args.get("zoom")
        alpha = args.get("alpha")
        xalign = args.get("xalign")
        yalign = args.get("yalign")
        # Allow partial updates: require tag, rest optional
        if tag is None:
            raise Exception("Missing required argument: tag/name")

        try:
            # Locate current image name by tag on the layer
            sl = renpy.exports.scene_lists()
            image_name = tag
            if sl and hasattr(sl, 'layers') and layer in sl.layers:
                for sle in sl.layers[layer]:
                    if getattr(sle, 'tag', None) == tag:
                        if hasattr(sle, 'name') and sle.name:
                            image_name = sle.name
                        break

            from renpy.display.transform import Transform
            kw = {}
            if xpos is not None:
                kw['xpos'] = float(xpos)
            if ypos is not None:
                kw['ypos'] = float(ypos)
            if xanchor is not None:
                kw['xanchor'] = float(xanchor)
            if yanchor is not None:
                kw['yanchor'] = float(yanchor)
            if xalign is not None:
                kw['xalign'] = float(xalign)
            if yalign is not None:
                kw['yalign'] = float(yalign)
            if rotate is not None:
                kw['rotate'] = float(rotate)
            if zoom is not None:
                kw['zoom'] = float(zoom)
            if alpha is not None:
                kw['alpha'] = float(alpha)
            t = Transform(**kw)
            # Re-show with new transform
            renpy.exports.show(image_name, at_list=[t], layer=layer, tag=tag)
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_setZOrder(self, req):
        args = req.get("arguments") or {}
        tag = args.get("tag")
        layer = args.get("layer", "master")
        z = args.get("zorder")
        if tag is None or z is None:
            raise Exception("Missing required arguments: tag, zorder")
        try:
            sl = renpy.exports.scene_lists()
            image_name = tag
            if sl and hasattr(sl, 'layers') and layer in sl.layers:
                for sle in sl.layers[layer]:
                    if getattr(sle, 'tag', None) == tag:
                        if hasattr(sle, 'name') and sle.name:
                            image_name = sle.name
                        break
            renpy.exports.show(image_name, layer=layer, tag=tag, zorder=int(z))
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_setLayer(self, req):
        args = req.get("arguments") or {}
        tag = args.get("tag")
        from_layer = args.get("fromLayer")
        to_layer = args.get("toLayer") or "master"
        if tag is None:
            raise Exception("Missing required argument: tag")
        try:
            sl = renpy.exports.scene_lists()
            image_name = tag
            if sl and hasattr(sl, 'layers'):
                # find in any layer if from not provided
                search_layers = [from_layer] if from_layer else list(sl.layers.keys())
                for layer in search_layers:
                    if layer in sl.layers:
                        for sle in sl.layers[layer]:
                            if getattr(sle, 'tag', None) == tag:
                                if hasattr(sle, 'name') and sle.name:
                                    image_name = sle.name
                                break
            # Re-show on target layer
            renpy.exports.show(image_name, layer=to_layer, tag=tag)
            # Optionally hide old one
            if from_layer and from_layer != to_layer:
                try:
                    renpy.exports.hide(tag, layer=from_layer)
                except Exception:
                    pass
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_hideImage(self, req):
        args = req.get("arguments") or {}
        tag = args.get("tag")
        layer = args.get("layer", "master")
        if tag is None:
            raise Exception("Missing required argument: tag")
        try:
            renpy.exports.hide(tag, layer=layer)
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_showImage(self, req):
        args = req.get("arguments") or {}
        tag = args.get("tag")
        name = args.get("name")
        layer = args.get("layer", "master")
        if not tag or not name:
            raise Exception("Missing required arguments: tag, name")
        try:
            renpy.exports.show(name, layer=layer, tag=tag)
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_playMusic(self, req):
        args = req.get("arguments") or {}
        filename = args.get("filename")
        channel = args.get("channel", "music")
        loop = bool(args.get("loop", True))
        if not filename:
            raise Exception("Missing required argument: filename")
        try:
            renpy.music.play(filename, channel=channel, loop=loop)  # type: ignore
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_stopMusic(self, req):
        args = req.get("arguments") or {}
        channel = args.get("channel", "music")
        try:
            renpy.music.stop(channel=channel)  # type: ignore
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_setMusicVolume(self, req):
        args = req.get("arguments") or {}
        channel = args.get("channel", "music")
        volume = args.get("volume")
        if volume is None:
            raise Exception("Missing required argument: volume")
        try:
            renpy.music.set_volume(float(volume), delay=0.0, channel=channel)  # type: ignore
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_queueAudio(self, req):
        args = req.get("arguments") or {}
        filename = args.get("filename")
        channel = args.get("channel", "music")
        loop = bool(args.get("loop", False))
        if not filename:
            raise Exception("Missing required argument: filename")
        try:
            renpy.music.queue(filename, channel=channel, loop=loop)  # type: ignore
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    # ---------- Interactive Director parity helpers ----------

    def _resolve_named(self, name):
        """Resolve a store name (transform/transition) to an object."""
        try:
            import store
            if hasattr(store, name):
                return getattr(store, name)
        except Exception:
            pass
        return None

    def _director_transforms(self):
        # Try to reuse director module if available
        try:
            import store
            if hasattr(store, 'director') and hasattr(store.director, 'transforms'):
                return list(store.director.transforms)
        except Exception:
            pass
        # Fallback: scan dump.transforms
        try:
            rv = []
            for name, file, _line in renpy.dump.transforms:
                if file.startswith("renpy/common/"):
                    continue
                if file == "game/screens.rpy":
                    continue
                rv.append(name)
            rv = sorted(set(rv))
            return rv
        except Exception:
            return []

    def _director_transitions(self):
        try:
            import store
            if hasattr(store, 'director') and hasattr(store.director, 'transitions'):
                return list(store.director.transitions)
        except Exception:
            pass
        # Fallback to some common transitions
        return ['dissolve', 'fade', 'move', 'pixellate']

    def _image_attributes(self, tag):
        try:
            import store
            # component_key from director
            ck = None
            try:
                if hasattr(store, 'director') and hasattr(store.director, 'component_key'):
                    ck = store.director.component_key
            except Exception:
                ck = None
            return renpy.get_ordered_image_attributes(tag, [], ck)
        except Exception:
            return []

    def _handle_getDirectorOptions(self, req):
        args = req.get("arguments") or {}
        tag = args.get('tag')
        try:
            showing = list(renpy.get_showing_tags())
        except Exception:
            showing = []
        transforms = self._director_transforms()
        transitions = self._director_transitions()
        attributes = self._image_attributes(tag) if tag else []
        # behind = showing excluding scene tags like 'bg'
        behind = [t for t in showing if t != tag and t != 'bg']
        return {"showing": showing, "transforms": transforms, "transitions": transitions, "attributes": attributes, "behind": behind}

    def _handle_applyShow(self, req):
        args = req.get("arguments") or {}
        tag = args.get('tag')
        attributes = args.get('attributes') or []
        layer = args.get('layer')
        behind = args.get('behind') or []
        zorder = args.get('zorder')
        at_transforms = args.get('transforms') or []
        transition = args.get('transition')

        if not tag:
            raise Exception("Missing required argument: tag")
        try:
            # Build name tuple: tag + attributes
            name = ' '.join([tag] + [a for a in attributes if a])
            # Resolve transforms by name
            at_list = []
            for t in at_transforms:
                obj = self._resolve_named(t)
                if obj is not None:
                    at_list.append(obj)
            renpy.exports.show(name, at_list=at_list, layer=layer, behind=behind, zorder=zorder, tag=tag)
            if transition:
                tr = self._resolve_named(transition)
                if tr is not None:
                    renpy.exports.with_statement(tr)
            return {"ok": True}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _build_show_statement(self, kind, tag=None, attributes=None, transforms=None, layer=None, behind=None, zorder=None, transition=None):
        attributes = attributes or []
        transforms = transforms or []
        behind = behind or []
        parts = []
        if kind in ('show', 'scene', 'hide'):
            parts.append(kind)
            if tag:
                parts.append(tag)
            for a in attributes:
                if a:
                    parts.append(a)
            if transforms:
                parts.append('at ' + ', '.join(transforms))
            if layer:
                parts.append('onlayer ' + layer)
            if behind:
                parts.append('behind ' + ', '.join(behind))
            if zorder is not None:
                parts.append('zorder ' + str(int(zorder)))
            stmt = ' '.join(parts)
            if transition:
                stmt = stmt + "\nwith " + transition
            return stmt
        elif kind == 'with' and transition:
            return 'with ' + transition
        elif kind in ('play', 'queue', 'stop', 'voice'):
            # Audio statements
            if kind == 'voice':
                fn = tag  # misuse tag to carry filename
                return 'voice ' + fn
            ch = layer or 'music'  # reuse layer for channel
            if kind == 'stop':
                return 'stop ' + ch
            fn = tag or ''
            return kind + ' ' + ch + ' ' + fn
        else:
            return None

    def _insert_before_and_remove_old(self, statement, filename, linenumber):
        # Insert new statement before the current line, then remove the old line below
        renpy.scriptedit.add_to_ast_before(statement, filename, linenumber)
        renpy.scriptedit.insert_line_before(statement, filename, linenumber)
        try:
            renpy.scriptedit.remove_from_ast(filename, linenumber + 1)
            renpy.scriptedit.remove_line(filename, linenumber + 1)
        except Exception:
            try:
                renpy.scriptedit.remove_from_ast(filename, linenumber)
                renpy.scriptedit.remove_line(filename, linenumber)
            except Exception:
                pass

    def _handle_applyShowScript(self, req):
        args = req.get("arguments") or {}
        mode = args.get('mode', 'add')  # 'add' or 'change'
        kind = args.get('kind', 'show')
        tag = args.get('tag')
        attributes = args.get('attributes') or []
        transforms = args.get('transforms') or []
        layer = args.get('layer')
        behind = args.get('behind') or []
        zorder = args.get('zorder')
        transition = args.get('transition')
        filename = args.get('filename')
        line = args.get('line')

        try:
            if not filename or not line:
                # Default to current location
                fn, ln = renpy.exports.get_filename_line()
                filename = filename or fn
                line = line or ln

            stmt = self._build_show_statement(kind, tag, attributes, transforms, layer, behind, zorder, transition)
            if not stmt:
                raise Exception('Could not build statement')

            if mode == 'add':
                renpy.scriptedit.add_to_ast_before(stmt, filename, line)
                renpy.scriptedit.insert_line_before(stmt, filename, line)
            else:
                self._insert_before_and_remove_old(stmt, filename, line)
            # Force immediate application like interactive director
            renpy.rollback(checkpoints=0, force=True, greedy=True)
            return {"ok": True, "statement": stmt, "filename": filename, "line": line}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    def _handle_hideImageImmediate(self, req):
        try:
            print(f"[DAP] hideImageImmediate called with req: {req}")
            args = req.get("arguments") or {}
            tag = args.get("tag")
            layer = args.get("layer", "master")
            filename = args.get('filename')
            line = args.get('line')

            print(f"[DAP] Parsed args: tag={tag}, layer={layer}, filename={filename}, line={line}")

            if tag is None:
                raise Exception("Missing required argument: tag")
            print(f"[DAP] hideImageImmediate: tag={tag}, layer={layer}")

            if not filename or not line:
                # Default to current location
                fn, ln = renpy.exports.get_filename_line()
                filename = filename or fn
                line = line or ln
                print(f"[DAP] Using location: {filename}:{line}")

            # Build hide statement
            print(f"[DAP] Building hide statement...")
            stmt = self._build_show_statement('hide', tag, [], [], layer, [], None, None)
            if not stmt:
                raise Exception('Could not build hide statement')
            print(f"[DAP] Built statement: {stmt}")

            # Add to AST and force immediate application
            print(f"[DAP] Adding to AST...")
            self._insert_before_and_remove_old(stmt, filename, line)

            print(f"[DAP] Calling rollback...")
            renpy.exports.rollback(checkpoints=0, force=True, greedy=True)

            print(f"[DAP] hideImageImmediate completed successfully")
            return {"ok": True, "statement": stmt, "filename": filename, "line": line}
        except Exception as e:
            error_msg = str(e) if e else "Unknown error"
            error_type = type(e).__name__ if e else "Unknown"
            print(f"[DAP] hideImageImmediate error: {error_msg}")
            print(f"[DAP] Error type: {error_type}")
            traceback.print_exc()
            return {"ok": False, "error": f"{error_type}: {error_msg}"}

    def _handle_applyTransform(self, req):
        args = req.get("arguments") or {}
        tag = args.get('tag')
        layer = args.get('layer', 'master')
        transforms = args.get('transforms') or []
        filename = args.get('filename')
        line = args.get('line')

        if not tag:
            raise Exception("Missing required argument: tag")

        try:
            if not filename or not line:
                # Default to current location
                fn, ln = renpy.exports.get_filename_line()
                filename = filename or fn
                line = line or ln

            # Build show statement with transforms (keeping existing attributes)
            # Get current attributes for the tag
            try:
                current_attrs = list(renpy.get_ordered_image_attributes(tag, [], None))
            except Exception:
                current_attrs = []

            stmt = self._build_show_statement('show', tag, current_attrs, transforms, layer, [], None, None)
            if not stmt:
                raise Exception('Could not build transform statement')

            # Add to AST and force immediate application
            self._insert_before_and_remove_old(stmt, filename, line)
            renpy.rollback(checkpoints=0, force=True, greedy=True)
            return {"ok": True, "statement": stmt, "filename": filename, "line": line}
        except Exception as e:
            traceback.print_exc()
            return {"ok": False, "error": str(e)}

    # ---------- Debugger integration ----------

    def _on_debugger_paused(self, reason, state):
        # Emit "stopped" so client can query stack/vars
        try:
            norm = (reason or "breakpoint").lower()
            self._emit_stopped(reason=norm)
        except Exception:
            traceback.print_exc()

    def _emit_stopped(self, reason="breakpoint"):
        self._send_event("stopped", {"reason": reason, "threadId": 1, "allThreadsStopped": True})

    def _resume_if_paused(self):
        try:
            from renpy.testing import debugger as _dbg
            st = _dbg.get_state()
            if isinstance(st, dict) and st.get("paused"):
                _dbg.continue_execution()
        except Exception:
            pass

    def _on_client_disconnected(self):
        # Resume game if paused; keep debugger/server alive for reconnection
        self._resume_if_paused()

    def _safe_disable_debugger(self):
        try:
            from renpy.testing import debugger as _dbg
            # Clear breakpoints so execution won't re-pause implicitly
            try:
                _dbg.clear_all_breakpoints()
            except Exception:
                pass
            # Fully disable to restore normal runtime responsiveness
            _dbg.disable()
        except Exception:
            pass


_server_instance = None
_tcp_server = None
_tcp_thread = None
_dap_clients = set()
_dap_clients_lock = threading.RLock()

class _DAPHandler(socketserver.BaseRequestHandler):
    def handle(self):
        # Register client
        with _dap_clients_lock:
            _dap_clients.add(self.request)
        buffer = b""
        try:
            while True:
                chunk = self.request.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while True:
                    header_end = buffer.find(b"\r\n\r\n")
                    if header_end == -1:
                        break
                    header = buffer[:header_end].decode("utf-8", errors="ignore")
                    cl = 0
                    for line in header.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            try:
                                cl = int(line.split(":", 1)[1].strip())
                            except Exception:
                                cl = 0
                    total_len = header_end + 4 + cl
                    if len(buffer) < total_len:
                        break
                    content = buffer[header_end + 4: total_len]
                    buffer = buffer[total_len:]
                    try:
                        message = json.loads(content.decode("utf-8"))
                        core = getattr(renpy, '_dap_server', None)
                        if isinstance(core, DAPServer):
                            core._handle_message(message, writer=self.request)
                    except Exception:
                        traceback.print_exc()
        finally:
            with _dap_clients_lock:
                try:
                    _dap_clients.remove(self.request)
                except Exception:
                    pass

class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True

def _dap_broadcast(obj):
    data = json.dumps(obj).encode("utf-8")
    header = ("Content-Length: %d\r\n\r\n" % len(data)).encode("utf-8")
    with _dap_clients_lock:
        dead = []
        for s in list(_dap_clients):
            try:
                s.sendall(header + data)
            except Exception:
                dead.append(s)
        for s in dead:
            try:
                _dap_clients.remove(s)
            except Exception:
                pass


def start_dap_server(port=8765):
    """Start the native Ren'Py DAP server in a background thread (idempotent)."""
    global _server_instance
    # If a server instance is already set, keep it.
    try:
        existing = getattr(renpy, '_dap_server', None)
        if isinstance(existing, DAPServer) and existing._running:
            _server_instance = existing
            return True
    except Exception:
        pass

    # Create a brand-new server and start it once.
    try:
        from renpy.testing import debugger as _dbg
        dbg = _dbg.get_debugger()
        core = DAPServer("127.0.0.1", int(port), dbg)
        core.start()
        global _tcp_server, _tcp_thread
        _tcp_server = _ThreadingTCPServer(("127.0.0.1", int(port)), _DAPHandler)
        _tcp_thread = threading.Thread(target=_tcp_server.serve_forever, name="RenpyDAP-Serve", daemon=True)
        _tcp_thread.start()
        _server_instance = core
        setattr(renpy, '_dap_server', core)
        # Persist TCP server and thread on renpy module to survive module reloads
        try:
            setattr(renpy, '_dap_tcp_server', _tcp_server)
            setattr(renpy, '_dap_tcp_thread', _tcp_thread)
        except Exception:
            pass
        return True
    except Exception:
        return False


def init_dap_once(port=8765):
    """Initialize the DAP listener exactly once for the process lifetime."""
    try:
        existing = getattr(renpy, '_dap_server', None)
        if isinstance(existing, DAPServer) and existing._running:
            return True
    except Exception:
        pass
    return start_dap_server(port=port)


def notify_breakpoint_hit(file_path, line, reason="breakpoint"):
    """External helper to notify the connected DAP client of a breakpoint hit."""
    if _server_instance is not None:
        try:
            _server_instance._emit_stopped(reason=reason)
        except Exception:
            traceback.print_exc()


class _DapMediator(object):
    def __init__(self):
        self.request_queue = queue.Queue()
        self.lock = threading.RLock()

    def submit(self, method, arguments=None, timeout=5.0):
        # Control-flow methods should execute immediately so the VM can resume
        if method in ("continue", "next", "stepIn", "stepOut"):
            try:
                return _execute_dap_method(method, arguments or {})
            except Exception:
                pass

        # If VM is paused and the method is read-only, serve synchronously
        try:
            if method in ("stackTrace", "scopes"):
                from renpy.testing import debugger as _dbg
                st = _dbg.get_state()
                if isinstance(st, dict) and st.get("paused"):
                    return _execute_dap_method(method, arguments or {})
        except Exception:
            pass

        job = {"method": method, "arguments": arguments or {}, "event": threading.Event(), "result": None, "error": None}
        self.request_queue.put(job)
        if not job["event"].wait(timeout):
            # Provide dummy responses to keep DAP happy while VM is busy
            if method == "stackTrace":
                return {"frames": []}
            if method == "scopes":
                return {"variables": {}, "scene": {}}
            return {}
        if job["error"]:
            raise job["error"]
        return job["result"]

    def on_pause(self, reason, state):
        try:
            srv = getattr(renpy, '_dap_server', None)
            if isinstance(srv, DAPServer):
                srv._emit_stopped(reason=reason)
        except Exception:
            traceback.print_exc()


def get_mediator():
    med = getattr(renpy, '_dap_mediator', None)
    if med is None:
        med = _DapMediator()
        setattr(renpy, '_dap_mediator', med)
    return med


def _process_dap_jobs():
    med = get_mediator()
    # Drain up to a reasonable number per frame to avoid starvation
    for _ in range(100):
        try:
            job = med.request_queue.get_nowait()
        except queue.Empty:
            break
        try:
            method = job["method"]
            args = job["arguments"] or {}
            job["result"] = _execute_dap_method(method, args)
        except Exception as e:
            job["error"] = e
        finally:
            job["event"].set()


def _execute_dap_method(method, args):
    # Map methods to current debugger/state inspector
    from renpy.testing import debugger as _dbg
    if method == "setBreakpoints":
        source = args.get("source", {})
        bps = args.get("breakpoints", []) or args.get("lines", [])
        lines = [bp.get("line") for bp in bps] if (bps and isinstance(bps[0], dict)) else list(bps)
        filename = source.get("path") or source.get("name") or ""
        basename = os.path.basename(filename)
        _dbg.clear_all_breakpoints(basename)
        for ln in lines:
            _dbg.set_breakpoint(basename, int(ln))
        return {"breakpoints": [{"verified": True, "line": ln, "source": {"path": filename}} for ln in lines]}

    if method == "continue":
        _dbg.continue_execution()
        return {}
    if method == "next":
        _dbg.step_over()
        return {}
    if method == "stepIn":
        _dbg.step_in()
        return {}
    if method == "stepOut":
        _dbg.step_out()
        return {}

    if method == "stackTrace":
        stack = _dbg.get_call_stack() or []
        return {"frames": stack}

    if method == "scopes":
        vars_map = _dbg.get_variables() or {}
        try:
            from renpy.testing.state_inspector import StateInspector
            scene_info = StateInspector().get_scene_info() or {}
        except Exception:
            scene_info = {}
        scene_tree = {
            "shown_images": scene_info.get("shown_images", []),
            "active_screens": scene_info.get("active_screens", []),
            "layers": scene_info.get("scene_lists", {}),
            "audio": scene_info.get("audio_info", {}),
        }
        return {"variables": vars_map, "scene": scene_tree}

    return {}


def _attach_mediator_to_debugger():
    try:
        from renpy.testing import debugger as _dbg
        dbg = _dbg.get_debugger()
        med = get_mediator()
        dbg.pause_listener = med.on_pause
    except Exception:
        pass


# Register mediator processing on each interaction and after loads
try:
    if _process_dap_jobs not in renpy.config.start_interact_callbacks:
        renpy.config.start_interact_callbacks.append(_process_dap_jobs)
    if _attach_mediator_to_debugger not in renpy.config.after_load_callbacks:
        renpy.config.after_load_callbacks.append(_attach_mediator_to_debugger)
    # Attach immediately on first import so pause events fire before any reload
    try:
        _attach_mediator_to_debugger()
    except Exception:
        pass
except Exception:
    pass
def stop_dap_server():
    """Stop the native DAP server and clean up debugger state."""
    global _server_instance
    try:
        global _tcp_server, _tcp_thread, _server_instance
        # Prefer renpy module references to ensure we stop the right instance
        try:
            srv = getattr(renpy, '_dap_tcp_server', None)
            thr = getattr(renpy, '_dap_tcp_thread', None)
            if srv is not None:
                _tcp_server = srv
            if thr is not None:
                _tcp_thread = thr
        except Exception:
            pass

        if _tcp_server is not None:
            try:
                _tcp_server.shutdown()
            except Exception:
                pass
            try:
                _tcp_server.server_close()
            except Exception:
                pass
        _tcp_server = None
        _tcp_thread = None
        _server_instance = None
        try:
            if hasattr(renpy, '_dap_server'):
                delattr(renpy, '_dap_server')
        except Exception:
            pass
        try:
            if hasattr(renpy, '_dap_tcp_server'):
                delattr(renpy, '_dap_tcp_server')
            if hasattr(renpy, '_dap_tcp_thread'):
                delattr(renpy, '_dap_tcp_thread')
        except Exception:
            pass
    except Exception:
        traceback.print_exc()


def _port_listening(host: str, port: int) -> bool:
    # Avoid active connects from this process to prevent hijacking the sole client slot.
    # Since we're in-process, prefer instance checks over probing.
    srv = getattr(renpy, '_dap_server', None)
    if isinstance(srv, DAPServer) and srv._running:
        return True
    return False


def ensure_dap_server(port=8765):
    """Ensure a DAP server is listening; start if needed. Safe across reloads."""
    try:
        # If our instance exists and is running, we're fine.
        existing = getattr(renpy, '_dap_server', None)
        if existing not in (None,):
            if _port_listening("127.0.0.1", int(port)):
                # Refresh debugger binding in case it changed during reloads
                try:
                    if isinstance(existing, DAPServer):
                        existing.reattach_debugger()
                except Exception:
                    pass
                return True
            # Instance attr exists but port is down; clear and restart
            try:
                delattr(renpy, '_dap_server')
            except Exception:
                pass
        # Start fresh
        return start_dap_server(port=port)
    except Exception:
        traceback.print_exc()
        return False
