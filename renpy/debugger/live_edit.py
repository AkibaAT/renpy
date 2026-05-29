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
Live editing support for Ren'Py debugger.

This module provides hot-reload capabilities for Ren'Py scripts without
requiring a full script reload. When enabled:

1. Text changes to Say statements are applied immediately
2. Show/scene/hide statement changes update the display in real-time
3. Python blocks are recompiled and re-executed
4. Shaders are recompiled when changed
5. **New statements can be added to the AST dynamically**

The key insight from the Interactive Director:
1. Don't try to patch the display directly
2. Use renpy.exports.rollback(checkpoints=0, force=True, greedy=True) to re-execute
3. This preserves game state while applying the new code

For adding new statements:
1. Detect when new lines appear in the file that aren't in the AST
2. Use renpy.scriptedit.add_to_ast_before() to insert them
3. Trigger rollback to execute the new statements

Supported live editing features:
- Say/dialogue text changes
- Show/scene/hide statements
- Python blocks and $ expressions
- Menu items
- Play/stop/queue audio
- Screen definitions
- Transform definitions
- Style definitions
- Define/default statements
- Shaders (GLSL files)
- **Adding new statements** (any supported statement type)
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Optional, Set, Dict, List, Tuple

if TYPE_CHECKING:
    from .core import DebuggerCore


class LiveEditSyntaxError:
    """Represents a syntax error in a file for live editing diagnostics."""
    def __init__(self, file: str, line: int, column: int, message: str, severity: str = "error"):
        self.file = file
        self.line = line
        self.column = column
        self.message = message
        self.severity = severity  # "error", "warning", "info"

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "column": self.column,
            "message": self.message,
            "severity": self.severity,
        }


class LiveEditManager:
    """
    Manages live editing of Ren'Py scripts.

    When enabled, intercepts autoreload for .rpy files and applies
    targeted updates using rollback instead of full script reloads.
    """

    # Set to True to enable verbose debug logging
    VERBOSE_LOGGING = False

    def _log(self, message: str, force: bool = False) -> None:
        """Log a message. Only prints if VERBOSE_LOGGING is True or force=True."""
        if self.VERBOSE_LOGGING or force:
            print(f"[DAP] Live edit: {message}")

    def _is_control_exception(self, exc: BaseException) -> bool:
        """Check if an exception is a Ren'Py control exception that should be re-raised."""
        # Always re-raise keyboard interrupt and system exit
        if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            return True
        # Check for Ren'Py control exceptions
        try:
            import renpy
            if hasattr(renpy, 'game') and hasattr(renpy.game, 'CONTROL_EXCEPTIONS'):
                return isinstance(exc, renpy.game.CONTROL_EXCEPTIONS)
        except Exception:
            pass
        return False

    def __init__(self, debugger: DebuggerCore):
        self._debugger = debugger
        self._enabled = False
        self._registered = False
        self._pending_files: Set[str] = set()
        # Track file line counts to detect added/removed lines
        self._file_line_counts: Dict[str, int] = {}
        # Track AST statement positions per file
        self._file_ast_lines: Dict[str, Set[int]] = {}
        # Track syntax errors per file (for error recovery)
        self._syntax_errors: Dict[str, List[LiveEditSyntaxError]] = {}
        # Callbacks for error notification
        self._error_callbacks: List[callable] = []

    def enable(self) -> None:
        """Enable live editing mode."""
        if self._enabled:
            return

        self._enabled = True
        self._register_autoreload_handler()

        # Enable Ren'Py's autoreload system if not already enabled
        # This is required for file change detection
        try:
            import renpy

            was_off = not renpy.autoreload
            if was_off:
                renpy.autoreload = True

            # Populate file tracking if it wasn't done during startup
            self._populate_file_tracking()

            if was_off:
                # Start the autoreload thread if it wasn't running
                renpy.loader.auto_init()
                print("[DAP] Live editing enabled (autoreload was off, now enabled)")
            else:
                print("[DAP] Live editing enabled (autoreload already active)")
        except Exception as e:
            print(f"[DAP] Live editing enabled (could not check autoreload: {e})")
            import traceback
            traceback.print_exc()

    def disable(self) -> None:
        """Disable live editing mode."""
        if not self._enabled:
            return

        self._enabled = False
        self._unregister_autoreload_handler()
        print("[DAP] Live editing disabled")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def register_error_callback(self, callback: callable) -> None:
        """
        Register a callback to be notified of syntax errors.

        The callback receives (file_path, errors_list) where errors_list
        is a list of SyntaxError objects (empty list means errors cleared).
        """
        if callback not in self._error_callbacks:
            self._error_callbacks.append(callback)

    def unregister_error_callback(self, callback: callable) -> None:
        """Remove an error callback."""
        if callback in self._error_callbacks:
            self._error_callbacks.remove(callback)

    def get_errors(self, file_path: Optional[str] = None) -> Dict[str, List[SyntaxError]]:
        """
        Get current syntax errors.

        Args:
            file_path: If provided, get errors only for this file.
                      If None, get all errors.

        Returns:
            Dict mapping file paths to lists of SyntaxError objects.
        """
        if file_path:
            normalized = os.path.normpath(file_path)
            return {normalized: self._syntax_errors.get(normalized, [])}
        return dict(self._syntax_errors)

    def _report_error(self, file_path: str, line: int, column: int, message: str, severity: str = "error") -> None:
        """
        Report a syntax error for a file.

        This stores the error and notifies all registered callbacks.
        """
        normalized = os.path.normpath(file_path)
        error = LiveEditSyntaxError(normalized, line, column, message, severity)

        if normalized not in self._syntax_errors:
            self._syntax_errors[normalized] = []

        self._syntax_errors[normalized].append(error)

        print(f"[DAP] Live edit: {severity.upper()} at {file_path}:{line}:{column}: {message}")

        # Notify callbacks
        for callback in self._error_callbacks:
            try:
                callback(normalized, self._syntax_errors[normalized])
            except Exception as e:
                print(f"[DAP] Live edit: Error in error callback: {e}")

    def _clear_errors(self, file_path: str) -> None:
        """
        Clear all errors for a file (called when file parses successfully).
        """
        normalized = os.path.normpath(file_path)

        had_errors = normalized in self._syntax_errors and self._syntax_errors[normalized]

        if normalized in self._syntax_errors:
            del self._syntax_errors[normalized]

        # Notify callbacks that errors are cleared
        if had_errors:
            for callback in self._error_callbacks:
                try:
                    callback(normalized, [])
                except Exception as e:
                    print(f"[DAP] Live edit: Error in error callback: {e}")

    def _parse_with_error_recovery(self, code: str, filename: str, start_line: int = 1) -> Tuple[Optional[object], Optional[SyntaxError]]:
        """
        Attempt to parse Ren'Py code with error recovery.

        Returns:
            Tuple of (parsed_result, error) where:
            - On success: (parsed_result, None)
            - On failure: (None, SyntaxError)
        """
        try:
            import renpy

            # Use Ren'Py's lexer to parse
            lexer = renpy.lexer.Lexer([(filename, start_line, code, ())])
            lexer.advance()

            # Try to parse as ATL (for transforms)
            try:
                result = renpy.atl.parse_atl(lexer)
                return (result, None)
            except Exception:
                pass

            # Try to parse as general statement
            try:
                # Reset lexer
                lexer = renpy.lexer.Lexer([(filename, start_line, code, ())])
                lexer.advance()

                # Try script parsing
                block, _init = renpy.game.script.load_string(filename, code, linenumber=start_line)
                return (block, None)
            except Exception:
                pass

            return (None, None)  # Couldn't parse but no clear error

        except renpy.parser.ParseError as e:
            # Extract line number and message from parse error
            error_line = getattr(e, 'line', start_line)
            error_msg = str(e)
            return (None, LiveEditSyntaxError(filename, error_line, 0, error_msg))

        except SyntaxError as e:
            # Python syntax error (in $ blocks, etc.)
            error_line = getattr(e, 'lineno', start_line) or start_line
            error_col = getattr(e, 'offset', 0) or 0
            error_msg = getattr(e, 'msg', str(e)) or str(e)
            return (None, LiveEditSyntaxError(filename, error_line, error_col, f"Python syntax error: {error_msg}"))

        except Exception as e:
            # Generic error
            return (None, LiveEditSyntaxError(filename, start_line, 0, f"Parse error: {str(e)}"))

    def _validate_file_syntax(self, filepath: str, content: str) -> Tuple[bool, List[LiveEditSyntaxError]]:
        """
        Validate Ren'Py script syntax without modifying the AST.

        This is called before applying any changes to ensure the file is valid.
        If there are syntax errors, the changes are not applied and the errors
        are reported to the IDE.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors: List[SyntaxError] = []

        try:
            import renpy

            # Get the relative filename for Ren'Py
            if hasattr(renpy.config, 'gamedir') and renpy.config.gamedir:
                rel_path = os.path.relpath(filepath, renpy.config.gamedir)
            else:
                rel_path = filepath
            rel_path = rel_path.replace("\\", "/")

            # Try to parse the file using Ren'Py's parser
            try:
                # Use load_string which will throw ParseError on syntax issues
                renpy.game.script.load_string(rel_path, content)
                return (True, [])

            except renpy.parser.ParseError as e:
                # Extract error details
                error_msg = str(e)

                # Try to extract line number from error message
                # ParseError format is usually "filename:line: message"
                line_num = 1
                col_num = 0

                if hasattr(e, 'filename') and hasattr(e, 'number'):
                    line_num = e.number or 1
                else:
                    # Try to parse from message
                    import re as re_module
                    match = re_module.search(r':(\d+):', error_msg)
                    if match:
                        line_num = int(match.group(1))

                errors.append(LiveEditSyntaxError(filepath, line_num, col_num, error_msg))
                return (False, errors)

            except SyntaxError as e:
                # Python syntax error (in python blocks)
                line_num = getattr(e, 'lineno', 1) or 1
                col_num = getattr(e, 'offset', 0) or 0
                msg = getattr(e, 'msg', str(e)) or str(e)

                errors.append(LiveEditSyntaxError(filepath, line_num, col_num, f"Python: {msg}"))
                return (False, errors)

        except Exception as e:
            # If validation itself fails, we can't be sure about the file
            # Log it but allow the update to proceed (fail safely)
            print(f"[DAP] Live edit: Validation error (allowing update): {e}")
            return (True, [])

    def _populate_file_tracking(self) -> None:
        """
        Populate the autoreload file tracking with game script files.

        This is needed when autoreload was off during startup, as the
        file list wouldn't have been populated.
        """
        try:
            import renpy
            import glob

            gamedir = renpy.config.gamedir
            if not gamedir:
                print("[DAP] Live edit: No gamedir configured")
                return

            # Find all .rpy files in the game directory
            rpy_pattern = os.path.join(gamedir, "**", "*.rpy")
            rpy_files = glob.glob(rpy_pattern, recursive=True)

            added = 0
            for filepath in rpy_files:
                filepath = filepath.replace("\\", "/")
                # add_auto checks renpy.autoreload, which we've set to True
                renpy.loader.add_auto(filepath, force=True)
                added += 1
                # Track initial line counts for detecting added lines
                self._track_file_state(filepath)

            # Also track shader files
            for ext in ["*.glsl", "*.vert", "*.frag", "*.shader"]:
                shader_pattern = os.path.join(gamedir, "**", ext)
                for filepath in glob.glob(shader_pattern, recursive=True):
                    filepath = filepath.replace("\\", "/")
                    renpy.loader.add_auto(filepath, force=True)
                    added += 1

            # Track image files for hot-swap
            image_count = 0
            for ext in ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.gif", "*.bmp"]:
                image_pattern = os.path.join(gamedir, "**", ext)
                for filepath in glob.glob(image_pattern, recursive=True):
                    filepath = filepath.replace("\\", "/")
                    renpy.loader.add_auto(filepath, force=True)
                    image_count += 1

            # Track font files for hot-swap
            font_count = 0
            for ext in ["*.ttf", "*.otf", "*.ttc"]:
                font_pattern = os.path.join(gamedir, "**", ext)
                for filepath in glob.glob(font_pattern, recursive=True):
                    filepath = filepath.replace("\\", "/")
                    renpy.loader.add_auto(filepath, force=True)
                    font_count += 1

            # Track audio files for hot-swap
            audio_count = 0
            for ext in ["*.mp3", "*.ogg", "*.wav", "*.opus", "*.flac"]:
                audio_pattern = os.path.join(gamedir, "**", ext)
                for filepath in glob.glob(audio_pattern, recursive=True):
                    filepath = filepath.replace("\\", "/")
                    renpy.loader.add_auto(filepath, force=True)
                    audio_count += 1


        except Exception as e:
            print(f"[DAP] Live edit: Error populating file tracking: {e}")
            import traceback
            traceback.print_exc()

    def _track_file_state(self, filepath: str) -> None:
        """
        Track the current state of a file (line count and AST positions).
        Used for detecting added/removed lines later.
        """
        try:
            import renpy

            filepath_normalized = os.path.normpath(filepath)

            # Count lines in file
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()
            self._file_line_counts[filepath_normalized] = len(lines)

            # Track which lines have AST nodes
            ast_lines: Set[int] = set()
            for node in renpy.game.script.all_stmts:
                node_file = getattr(node, 'filename', None)
                if not node_file:
                    continue
                node_file_normalized = os.path.normpath(node_file)
                if node_file_normalized == filepath_normalized or node_file_normalized.endswith(os.path.basename(filepath)):
                    ast_lines.add(getattr(node, 'linenumber', 0))

            self._file_ast_lines[filepath_normalized] = ast_lines

        except Exception as e:
            print(f"[DAP] Live edit: Error tracking file state: {e}")

    def _reload_scriptedit_file(self, filepath: str) -> None:
        """
        Reload scriptedit's line tracking for a file.

        This is necessary when lines are added or removed, as scriptedit's
        internal line offsets need to be recalculated.
        """
        try:
            import renpy

            # Get the elided filename for scriptedit
            if hasattr(renpy.config, 'gamedir') and renpy.config.gamedir:
                rel_path = os.path.relpath(filepath, renpy.config.gamedir)
            else:
                rel_path = filepath
            rel_path = rel_path.replace("\\", "/")

            # Remove the file from scriptedit's tracking so it reloads fresh
            if rel_path in renpy.scriptedit.files:
                renpy.scriptedit.files.remove(rel_path)

            # Remove all line entries for this file
            keys_to_remove = [k for k in renpy.scriptedit.lines if k[0] == rel_path]
            for key in keys_to_remove:
                del renpy.scriptedit.lines[key]

            # Reload the file
            renpy.scriptedit.ensure_loaded(rel_path)

        except Exception:
            pass

    def _register_autoreload_handler(self) -> None:
        """Register our handler to intercept file changes."""
        if self._registered:
            return

        try:
            import renpy

            # Insert at the beginning so we're checked first
            # Pattern matches .rpy files but not .rpyc
            rpy_handler = (r"\.rpy$", self._handle_rpy_change)

            # Handler for shader files
            shader_handler = (r"\.(glsl|vert|frag|shader)$", self._handle_shader_file_change)

            # Handler for image files
            image_handler = (r"\.(png|jpg|jpeg|webp|gif|bmp)$", self._handle_image_file_change)

            # Handler for font files
            font_handler = (r"\.(ttf|otf|ttc)$", self._handle_font_file_change)

            # Handler for audio files
            audio_handler = (r"\.(mp3|ogg|wav|opus|flac)$", self._handle_audio_file_change)

            handlers = [rpy_handler, shader_handler, image_handler, font_handler, audio_handler]

            for handler in handlers:
                if handler not in renpy.config.autoreload_functions:
                    renpy.config.autoreload_functions.insert(0, handler)

            self._registered = True
            print(f"[DAP] Registered autoreload handlers. Current handlers: {len(renpy.config.autoreload_functions)}")

        except ImportError:
            pass

    def _unregister_autoreload_handler(self) -> None:
        """Remove our autoreload handler."""
        if not self._registered:
            return

        try:
            import renpy

            # Find and remove our handler
            for i, (regex, func) in enumerate(renpy.config.autoreload_functions):
                if func == self._handle_rpy_change:
                    renpy.config.autoreload_functions.pop(i)
                    break

            self._registered = False

        except ImportError:
            pass

    def _handle_shader_file_change(self, filename: str) -> None:
        """
        Handle a changed shader file (.glsl, .vert, .frag, .shader).

        Clears shader cache and forces recompilation on next draw.
        """

        if not self._enabled:
            return

        try:
            import renpy

            # Get full path
            full_path = os.path.join(renpy.config.gamedir, filename)

            # Read the shader source
            with open(full_path, "r", encoding="utf-8") as f:
                shader_source = f.read()

            # Clear the entire shader cache
            if hasattr(renpy, 'gl2') and hasattr(renpy.gl2, 'gl2shadercache'):
                cache_module = renpy.gl2.gl2shadercache

                # Clear compiled program cache
                if hasattr(cache_module, 'cache') and cache_module.cache:
                    cache_module.cache.clear()

                # If this is a named shader file, try to update the shader_part registry
                shader_name = os.path.splitext(os.path.basename(filename))[0]
                if hasattr(cache_module, 'shader_part'):
                    if shader_name in cache_module.shader_part:
                        # Update existing shader part
                        part = cache_module.shader_part[shader_name]
                        # Determine if vertex or fragment based on extension or content
                        ext = os.path.splitext(filename)[1].lower()
                        if ext == '.vert' or 'gl_Position' in shader_source:
                            part.vertex_parts = {100: shader_source}
                        elif ext == '.frag' or 'gl_FragColor' in shader_source:
                            part.fragment_parts = {100: shader_source}
                        print(f"[DAP] Live edit: Updated shader part '{shader_name}'")

            # Force redraw to use new shaders
            renpy.exports.restart_interaction()
            print(f"[DAP] Live edit: Shader reload complete")

        except Exception as e:
            print(f"[DAP] Live edit: Error reloading shader: {e}")
            import traceback
            traceback.print_exc()

    def _handle_image_file_change(self, filename: str) -> None:
        """
        Handle a changed image file (.png, .jpg, .webp, etc.).

        Invalidates image caches and forces redraw.
        """
        print(f"[DAP] Live edit: Image file changed: {filename}")

        if not self._enabled:
            return

        try:
            import renpy

            # Get full path
            full_path = os.path.join(renpy.config.gamedir, filename)

            # Get the image name (relative path without extension)
            rel_path = filename.replace("\\", "/")

            # Clear various image caches
            self._invalidate_image_caches(rel_path, full_path)

            # Force redraw
            renpy.exports.restart_interaction()
            print(f"[DAP] Live edit: Image reload complete for {filename}")

        except Exception as e:
            print(f"[DAP] Live edit: Error reloading image: {e}")
            import traceback
            traceback.print_exc()

    def _invalidate_image_caches(self, rel_path: str, full_path: str) -> None:
        """
        Invalidate all image caches that might contain the given image.
        """
        try:
            import renpy

            # Get the base name without extension for matching
            base_name = os.path.splitext(os.path.basename(rel_path))[0]

            # 1. Clear the main image cache (renpy.display.im)
            if hasattr(renpy.display, 'im'):
                im = renpy.display.im

                # Clear the image cache
                if hasattr(im, 'cache') and im.cache:
                    # Find and remove entries containing this image
                    keys_to_remove = []
                    for key in list(im.cache.keys()):
                        key_str = str(key)
                        if rel_path in key_str or base_name in key_str:
                            keys_to_remove.append(key)

                    for key in keys_to_remove:
                        del im.cache[key]

                    if keys_to_remove:
                        print(f"[DAP] Live edit: Cleared {len(keys_to_remove)} entries from im.cache")

                # Clear the image predict cache
                if hasattr(im, 'predict_cache'):
                    im.predict_cache.clear()

            # 2. Clear render cache
            if hasattr(renpy.display, 'render'):
                render = renpy.display.render

                # Clear the render cache
                if hasattr(render, 'render_cache'):
                    render.render_cache.clear()
                    print(f"[DAP] Live edit: Cleared render cache")

                # Mark all renders as needing update
                if hasattr(render, 'invalidate_all'):
                    render.invalidate_all()

            # 3. Clear texture cache if available
            if hasattr(renpy, 'gl2') and hasattr(renpy.gl2, 'gl2texture'):
                tex = renpy.gl2.gl2texture
                if hasattr(tex, 'texture_cache'):
                    # Remove textures that match this image
                    keys_to_remove = []
                    for key in list(tex.texture_cache.keys()):
                        if rel_path in str(key) or base_name in str(key):
                            keys_to_remove.append(key)
                    for key in keys_to_remove:
                        del tex.texture_cache[key]
                    if keys_to_remove:
                        print(f"[DAP] Live edit: Cleared {len(keys_to_remove)} textures")

            # 4. Clear the loader cache for this file
            if hasattr(renpy.loader, 'auto_mtimes'):
                # Force the file to be seen as modified
                renpy.loader.add_auto(full_path, force=True)

            # 5. Clear displayable cache
            if hasattr(renpy.display, 'image'):
                image_module = renpy.display.image
                # Clear the images dictionary cache if needed
                if hasattr(image_module, 'images'):
                    # Don't clear the whole dict, just mark for refresh
                    pass

            # 6. Invalidate any ATL transforms using this image
            if hasattr(renpy.display, 'transform'):
                # Transforms will pick up new image on next render
                pass

            print(f"[DAP] Live edit: Image caches invalidated for {rel_path}")

        except Exception as e:
            print(f"[DAP] Live edit: Error invalidating image caches: {e}")
            import traceback
            traceback.print_exc()

    def _handle_font_file_change(self, filename: str) -> None:
        """
        Handle a changed font file (.ttf, .otf, .ttc).

        Reloads font and forces text re-rendering.
        """
        print(f"[DAP] Live edit: Font file changed: {filename}")

        if not self._enabled:
            return

        try:
            import renpy

            # Get full path
            full_path = os.path.join(renpy.config.gamedir, filename)

            # Clear font caches
            if hasattr(renpy.text, 'font'):
                font_module = renpy.text.font

                # Clear the font cache
                if hasattr(font_module, 'font_cache'):
                    font_module.font_cache.clear()
                    print(f"[DAP] Live edit: Cleared font cache")

                # Clear the glyph cache
                if hasattr(font_module, 'glyph_cache'):
                    font_module.glyph_cache.clear()

            # Clear text layout cache
            if hasattr(renpy.text, 'text'):
                text_module = renpy.text.text

                if hasattr(text_module, 'layout_cache'):
                    text_module.layout_cache.clear()
                    print(f"[DAP] Live edit: Cleared text layout cache")

            # Rebuild styles to pick up font changes
            if hasattr(renpy, 'style') and hasattr(renpy.style, 'rebuild'):
                renpy.style.rebuild()
                print(f"[DAP] Live edit: Rebuilt styles")

            # Force redraw
            renpy.exports.restart_interaction()
            print(f"[DAP] Live edit: Font reload complete for {filename}")

        except Exception as e:
            print(f"[DAP] Live edit: Error reloading font: {e}")
            import traceback
            traceback.print_exc()

    def _handle_audio_file_change(self, filename: str) -> None:
        """
        Handle a changed audio file (.mp3, .ogg, .wav, etc.).

        Notes the change - audio will use new file on next play.
        """
        print(f"[DAP] Live edit: Audio file changed: {filename}")

        if not self._enabled:
            return

        try:
            import renpy

            # Get full path
            full_path = os.path.join(renpy.config.gamedir, filename)

            # Clear audio-related caches
            if hasattr(renpy, 'audio') and hasattr(renpy.audio, 'audio'):
                audio_module = renpy.audio.audio

                # Clear any cached audio data
                if hasattr(audio_module, 'audio_cache'):
                    audio_module.audio_cache.clear()

            # Update loader tracking
            renpy.loader.add_auto(full_path, force=True)

            # Note: Currently playing audio won't be affected until it's replayed
            # For a more aggressive approach, we could stop and restart current audio
            # but that might be disruptive

            print(f"[DAP] Live edit: Audio file noted for reload: {filename}")
            print(f"[DAP] Live edit: Audio will use new file on next play")

        except Exception as e:
            print(f"[DAP] Live edit: Error handling audio change: {e}")
            import traceback
            traceback.print_exc()

    def _handle_rpy_change(self, filename: str) -> None:
        """
        Handle a changed .rpy file.

        Uses the same approach as the Interactive Director:
        1. Reload scriptedit lines data for the changed file
        2. Detect structural changes (added/removed lines)
        3. Add/remove statements from AST as needed
        4. Use rollback to re-execute current statement with new code

        With error recovery:
        - Parse errors are reported but don't crash the game
        - The old working AST is kept when parse fails
        - Errors are cleared when the file is fixed
        """
        print(f"[DAP] Live edit: _handle_rpy_change called for {filename}")
        if not self._enabled:
            print(f"[DAP] Live edit: DISABLED, returning")
            return

        import renpy

        # Get full path
        full_path = os.path.join(renpy.config.gamedir, filename)

        # Read the new file content first
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                file_content = ''.join(lines)
        except Exception as e:
            print(f"[DAP] Live edit: Could not read file: {e}")
            self._report_error(full_path, 1, 0, f"Could not read file: {e}")
            return

        # Validate the file syntax before proceeding
        # This prevents crashes from malformed Ren'Py code
        syntax_valid, syntax_errors = self._validate_file_syntax(full_path, file_content)

        if not syntax_valid:
            print(f"[DAP] Live edit: Syntax errors in {filename}, skipping update")
            # Report all errors but keep the old working AST
            for err in syntax_errors:
                self._report_error(full_path, err.line, err.column, err.message, err.severity)
            return

        # File is valid - clear any previous errors
        self._clear_errors(full_path)

        # FIRST: Process define statements directly from file content
        # This is the simple, reliable approach for Character definitions
        # that doesn't require AST lookups or line number alignment
        self._process_define_statements_directly(lines)

        # Reload scriptedit's line data for this file
        self._reload_scriptedit_file(full_path)

        # Structural change detection is disabled for now as it causes issues
        # with AST line tracking getting out of sync
        structural_change = False

        # Get current execution state - use Ren'Py's context, not the debugger's cached node
        # The debugger's node is only set during statement hook, but during dialogue
        # we're in an interaction and need to look up the current statement differently
        try:
            current_node = renpy.game.script.lookup(renpy.game.context().current)
        except Exception:
            current_node = self._debugger._current_node

        if current_node is None:
            print(f"[DAP] Live edit: current_node is None, returning early")
            # If we had structural changes, trigger rollback to apply them
            if structural_change:
                try:
                    renpy.exports.rollback(checkpoints=0, force=True, greedy=True)
                except BaseException as e:
                    if self._is_control_exception(e):
                        raise
                except Exception:
                    pass
            return

        current_file = getattr(current_node, 'filename', None)
        current_line = getattr(current_node, 'linenumber', 0)
        print(f"[DAP] Live edit: current_file={current_file}, current_line={current_line}")

        if not current_file:
            print(f"[DAP] Live edit: no current_file, returning early")
            return

        # Normalize and compare paths
        current_file_normalized = os.path.normpath(current_file)
        full_path_normalized = os.path.normpath(full_path)

        # Check if this change is in the current file
        is_current_file = (
            current_file_normalized == full_path_normalized or
            current_file_normalized.endswith(filename.replace("/", os.sep))
        )
        print(f"[DAP] Live edit: is_current_file={is_current_file} (current_file_normalized={current_file_normalized}, full_path_normalized={full_path_normalized})")

        if not is_current_file:
            print(f"[DAP] Live edit: Not in current file, updating AST and returning")
            # Still update the AST so changes take effect when we reach those lines
            updated_lines = self._update_ast_from_file(full_path)
            # Check for shader changes (these apply globally)
            self._check_and_reload_shaders(full_path)

            # Check if any changes are in labels we've already passed through
            # If so, we may need to rollback to re-execute them
            if updated_lines:
                self._check_cross_label_rollback(full_path, updated_lines)

            self._pending_files.add(full_path_normalized)

            # If we had structural changes, trigger rollback
            if structural_change:
                try:
                    renpy.exports.rollback(checkpoints=0, force=True, greedy=True)
                except BaseException as e:
                    if self._is_control_exception(e):
                        raise
                except Exception:
                    renpy.exports.restart_interaction()
            return

        # Update ALL changed nodes in the file's AST, not just current line
        # This allows editing lines we're not currently on
        updated_lines = self._update_ast_from_file(full_path)

        # Check for shader changes in this file too
        self._check_and_reload_shaders(full_path)

        # If we had structural changes, trigger rollback to apply them
        if structural_change:
            try:
                renpy.exports.rollback(checkpoints=0, force=True, greedy=True)
            except BaseException as e:
                if self._is_control_exception(e):
                    raise
                renpy.exports.restart_interaction()
            return

        # Check if any updated lines are BEFORE the current line
        # If so, we need to rollback to re-execute them
        # EXCEPT: if the current line itself changed, prioritize applying the live edit
        earliest_changed = self._find_earliest_changed_line(full_path, current_line)
        current_line_changed = current_line in updated_lines
        print(f"[DAP] Live edit: earliest_changed={earliest_changed}, current_line={current_line}, current_line_changed={current_line_changed}, updated_lines={updated_lines}")

        # Only roll back if:
        # 1. There are changes before current line, AND
        # 2. The current line itself didn't change (otherwise we want to apply live edit first)
        if earliest_changed is not None and earliest_changed < current_line and not current_line_changed:
            print(f"[DAP] Live edit: Rolling back to line {earliest_changed}")
            self._rollback_to_line(full_path, earliest_changed, current_line)
            return

        # Check what type of statement we're on
        node_class = current_node.__class__.__name__
        print(f"[DAP] Live edit: current node class: {node_class}, line: {current_line}, file: {full_path}")

        # For Say statements, update the displayed text AND check for show changes before it
        if node_class in ("Say", "TranslateSay"):
            print(f"[DAP] Live edit: Handling Say statement, node.who={getattr(current_node, 'who', None)}, node.what={getattr(current_node, 'what', 'N/A')[:50] if getattr(current_node, 'what', None) else 'None'}...")
            # Only apply show statement changes if we have updated show/scene/hide lines
            # Don't re-execute all show statements on every text edit
            show_lines_changed = any(
                ln in updated_lines
                for ln in self._get_show_statement_lines(full_path, current_line)
            )
            if show_lines_changed:
                print(f"[DAP] Live edit: Show statement lines changed, applying...")
                self._apply_show_statement_changes(full_path, current_line)
            # Then update the text display
            # Pass whether current line was updated so we can force refresh even if texts appear equal
            print(f"[DAP] Live edit: About to call _apply_live_text_edit, current_line_changed={current_line_changed}")
            self._apply_live_text_edit(current_node, full_path, current_line, force_refresh=current_line_changed)
        else:
            # For other statements, check if any show/scene/hide statements changed
            self._apply_show_statement_changes(full_path, current_line)

    def _update_ast_from_file(self, filepath: str) -> list:
        """
        Update all AST nodes from the given file with new content.

        This allows editing lines we're not currently on - the changes
        will take effect when the game reaches those lines.

        Returns a list of line numbers that were updated.
        """
        try:
            import renpy

            # Read the new file content
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Normalize the filepath for comparison
            filepath_normalized = os.path.normpath(filepath)

            # Compute what Ren'Py's node.filename would look like for this file
            # Ren'Py stores filenames relative to basedir with "game/" prefix
            # e.g., "game/script.rpy" not just "script.rpy"
            try:
                # Get path relative to basedir (parent of gamedir)
                basedir = os.path.dirname(renpy.config.gamedir)
                filepath_renpy_style = os.path.relpath(filepath_normalized, basedir)
            except ValueError:
                filepath_renpy_style = os.path.basename(filepath_normalized)

            print(f"[DAP] AST update: Looking for nodes matching '{filepath_renpy_style}'")
            updated_lines = []

            # Find all statements from this file
            for node in renpy.game.script.all_stmts:
                node_file = getattr(node, 'filename', None)
                if not node_file:
                    continue

                # Ren'Py stores filenames like "game/script.rpy" or "game/tl/czech/script.rpy"
                # We need EXACT match to avoid updating translation files
                node_file_normalized = os.path.normpath(node_file)

                # Skip if not an exact match
                # This prevents matching game/tl/*/script.rpy when editing game/script.rpy
                if node_file_normalized != filepath_renpy_style and node_file_normalized != filepath_normalized:
                    continue

                node_line = getattr(node, 'linenumber', 0)
                if node_line < 1 or node_line > len(lines):
                    continue

                line_content = lines[node_line - 1]
                node_class = node.__class__.__name__

                # Update Say/TranslateSay nodes
                if node_class in ("Say", "TranslateSay"):
                    new_who, new_text = self._parse_say_line_full(line_content)
                    if new_text is not None:
                        old_text = getattr(node, 'what', None)
                        old_who = getattr(node, 'who', None)
                        text_changed = old_text != new_text
                        who_changed = old_who != new_who
                        if text_changed or who_changed:
                            print(f"[DAP] AST update: Say at line {node_line}, who={old_who}->{new_who}, text_changed={text_changed}, who_changed={who_changed}")
                            if text_changed:
                                node.what = new_text
                            if who_changed:
                                node.who = new_who
                            updated_lines.append(node_line)

                # Update Show nodes
                elif node_class == "Show":
                    # Parse the show statement and update attributes
                    if line_content.strip().startswith("show "):
                        parts = line_content.strip()[5:].split()
                        if parts:
                            # Update the image name tuple
                            tag = parts[0]
                            attrs = []
                            for p in parts[1:]:
                                if p in ("at", "with", "behind", "onlayer", "zorder", "as"):
                                    break
                                attrs.append(p)
                            new_imspec = [tag] + attrs
                            # Show nodes have imspec attribute
                            if hasattr(node, 'imspec') and node.imspec:
                                old_imspec = list(node.imspec[0]) if node.imspec[0] else []
                                if old_imspec != new_imspec:
                                    # Update the first element of imspec (the image name tuple)
                                    node.imspec = (tuple(new_imspec),) + node.imspec[1:]
                                    updated_lines.append(node_line)

                # Update Python nodes - recompile bytecode
                elif node_class in ("Python", "EarlyPython"):
                    if self._update_python_node(node, lines, node_line):
                        updated_lines.append(node_line)

                # Update single-line Python ($) statements
                elif node_class == "UserStatement" and hasattr(node, 'line'):
                    if self._update_user_statement(node, line_content):
                        updated_lines.append(node_line)

                # Update Menu items
                elif node_class == "Menu":
                    if self._update_menu_node(node, lines, node_line):
                        updated_lines.append(node_line)

                # Update Scene node (background changes)
                elif node_class == "Scene":
                    if line_content.strip().startswith("scene "):
                        parts = line_content.strip()[6:].split()
                        if parts and hasattr(node, 'imspec') and node.imspec:
                            tag = parts[0]
                            attrs = []
                            for p in parts[1:]:
                                if p in ("at", "with", "behind", "onlayer", "zorder", "as"):
                                    break
                                attrs.append(p)
                            new_imspec = [tag] + attrs
                            old_imspec = list(node.imspec[0]) if node.imspec[0] else []
                            if old_imspec != new_imspec:
                                node.imspec = (tuple(new_imspec),) + node.imspec[1:]
                                updated_lines.append(node_line)

                # Update Play (music/sound) statements
                elif node_class == "Play":
                    if self._update_play_node(node, line_content):
                        updated_lines.append(node_line)

                # Update Screen definitions
                elif node_class == "Screen":
                    if self._update_screen_node(node, lines, node_line):
                        updated_lines.append(node_line)

                # Update Transform definitions
                elif node_class == "Transform":
                    if self._update_transform_node(node, lines, node_line):
                        updated_lines.append(node_line)

                # Update Style definitions
                elif node_class == "Style":
                    if self._update_style_node(node, line_content):
                        updated_lines.append(node_line)

                # Update Define statements (characters, variables)
                elif node_class == "Define":
                    if self._update_define_node(node, line_content):
                        updated_lines.append(node_line)

                # Update Default statements
                elif node_class == "Default":
                    if self._update_default_node(node, line_content):
                        updated_lines.append(node_line)

            # Store for later reference
            self._last_updated_lines = updated_lines
            return updated_lines

        except Exception as e:
            print(f"[DAP] Live edit: Error updating AST: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _update_python_node(self, node, lines: list, start_line: int) -> bool:
        """
        Update a Python/EarlyPython node by recompiling its bytecode.

        Returns True if the node was updated.
        """
        try:
            import renpy

            # Python blocks can span multiple lines - find the block end
            # Look for the indented block following 'python:' or 'init python:'
            if start_line < 1 or start_line > len(lines):
                return False

            # Get the code object
            code = getattr(node, 'code', None)
            if code is None:
                return False

            # Extract the Python block source from file
            # Start from the line after the 'python:' declaration
            block_lines = []
            base_indent = None

            for i in range(start_line, len(lines)):
                line = lines[i]
                stripped = line.lstrip()

                # Skip empty lines
                if not stripped or stripped.startswith('#'):
                    block_lines.append(line)
                    continue

                # Determine indentation
                indent = len(line) - len(stripped)

                if base_indent is None:
                    base_indent = indent
                elif indent < base_indent and stripped:
                    # Block ended - less indented non-empty line
                    break

                block_lines.append(line)

            if not block_lines:
                return False

            # Join and normalize the source
            new_source = ''.join(block_lines)

            # Compare with existing source
            old_source = getattr(code, 'source', None)
            if old_source == new_source:
                return False

            # Recompile the bytecode
            try:
                mode = getattr(code, 'mode', 'exec')
                if mode == 'hide':
                    mode = 'exec'

                # Compile the new source
                filename = getattr(node, 'filename', '<live_edit>')
                new_bytecode = compile(new_source, filename, mode)

                # Update the code object
                code.source = new_source
                code.bytecode = new_bytecode

                # Invalidate any cached bytecode
                if hasattr(renpy.game, 'script') and hasattr(renpy.game.script, 'bytecode_newcache'):
                    # Clear relevant cache entries
                    cache = renpy.game.script.bytecode_newcache
                    keys_to_remove = [k for k in cache if filename in str(k)]
                    for k in keys_to_remove:
                        del cache[k]

                return True

            except Exception as e:
                # Catch all compilation errors (SyntaxError, TypeError for invalid exception handlers, etc.)
                # Don't log - these are often expected for Ren'Py-specific code
                return False

        except Exception:
            # Silently fail - this is expected for many Python blocks
            return False

    def _update_user_statement(self, node, line_content: str) -> bool:
        """
        Update a UserStatement (like $ python expression).
        """
        try:
            line = line_content.strip()
            if not line.startswith("$"):
                return False

            # Extract the Python code after $
            new_code = line[1:].strip()
            old_code = getattr(node, 'line', '')

            if old_code == new_code:
                return False

            node.line = new_code

            # Also update the parsed code if present
            if hasattr(node, 'code') and node.code:
                try:
                    node.code.source = new_code
                    node.code.bytecode = compile(new_code, '<live_edit>', 'exec')
                except SyntaxError:
                    pass

            return True

        except Exception as e:
            print(f"[DAP] Live edit: Error updating $ statement: {e}")
            return False

    def _update_menu_node(self, node, lines: list, start_line: int) -> bool:
        """
        Update a Menu node's choice text.
        """
        try:
            if not hasattr(node, 'items') or not node.items:
                return False

            updated = False

            # Menu items are tuples: (caption, condition, block)
            # We need to find and update the caption text for each choice
            new_items = []

            for i, item in enumerate(node.items):
                if len(item) >= 1:
                    caption = item[0]
                    rest = item[1:]

                    # Try to find the new caption from the file
                    # Menu choices are on lines after the 'menu:' line
                    choice_line_idx = start_line + i
                    if choice_line_idx < len(lines):
                        choice_line = lines[choice_line_idx].strip()
                        # Extract quoted text from choice line
                        new_caption = self._parse_say_line(choice_line)
                        if new_caption and new_caption != caption:
                            new_items.append((new_caption,) + rest)
                            updated = True
                            continue

                new_items.append(item)

            if updated:
                node.items = new_items

            return updated

        except Exception as e:
            print(f"[DAP] Live edit: Error updating Menu: {e}")
            return False

    def _update_play_node(self, node, line_content: str) -> bool:
        """
        Update a Play (music/sound) statement.
        """
        try:
            line = line_content.strip()

            # Parse: play channel "filename" [options]
            # or: play channel <filename> [options]
            match = re.match(r'play\s+(\w+)\s+["\']?([^"\'>\s]+)["\']?', line)
            if not match:
                return False

            new_channel = match.group(1)
            new_file = match.group(2)

            # Update node attributes
            old_channel = getattr(node, 'channel', None)
            old_file = getattr(node, 'file', None)

            changed = False
            if old_channel != new_channel:
                node.channel = new_channel
                changed = True
            if old_file != new_file:
                node.file = new_file
                changed = True

            return changed

        except Exception as e:
            print(f"[DAP] Live edit: Error updating Play: {e}")
            return False

    def _update_screen_node(self, node, lines: list, start_line: int) -> bool:
        """
        Update a Screen definition and refresh it.
        """
        try:
            import renpy

            screen_name = getattr(node, 'name', None)
            if not screen_name:
                return False

            # Extract the screen code block
            block_source = self._extract_indented_block(lines, start_line)
            if not block_source:
                return False

            # The screen needs to be re-parsed and the screen object updated
            # This is complex - for now, we'll invalidate the screen cache
            # and force a re-show

            # Invalidate screen prediction cache
            if hasattr(renpy.display, 'screen'):
                screens = renpy.display.screen

                # Clear cached screen instances
                if hasattr(screens, 'screens_by_name'):
                    if screen_name in screens.screens_by_name:
                        del screens.screens_by_name[screen_name]

                # Force refresh of shown screens
                if hasattr(screens, 'prepared'):
                    screens.prepared = False

            # Mark that screen definitions changed
            self._screens_changed = True

            # Restart interaction to rebuild screens
            renpy.exports.restart_interaction()

            return True

        except Exception as e:
            print(f"[DAP] Live edit: Error updating Screen: {e}")
            return False

    def _update_transform_node(self, node, lines: list, start_line: int) -> bool:
        """
        Update a Transform definition with live ATL recompilation.
        """
        try:
            import renpy

            transform_name = getattr(node, 'varname', None)
            if not transform_name:
                return False

            # Extract the transform ATL block source
            block_source = self._extract_atl_block(lines, start_line)
            if not block_source:
                return False

            # Get the store name
            store_name = getattr(node, 'store', 'store')

            # Try to reparse the ATL block
            try:
                # Create a lexer for the ATL block
                filename = getattr(node, 'filename', '<live_edit>')

                # Use Ren'Py's lexer to parse the ATL
                lexer = renpy.lexer.Lexer([(filename, start_line + 1, block_source, ())])
                lexer.advance()

                # Parse the ATL block
                new_atl = renpy.atl.parse_atl(lexer)

                if new_atl is None:
                    print(f"[DAP] Live edit: Failed to parse ATL for transform {transform_name}")
                    return False

                # Update the node's ATL block
                old_atl = node.atl
                node.atl = new_atl

                # Get the parameters
                parameters = getattr(node, 'parameters', None)
                if parameters is None:
                    parameters = renpy.ast.EMPTY_PARAMETERS

                # Analyze the new ATL
                new_atl.analyze(parameters)

                # Create a new ATLTransform with the updated ATL
                new_transform = renpy.display.motion.ATLTransform(new_atl, parameters=parameters)

                # Update the store with the new transform
                if store_name == 'store':
                    setattr(renpy.store, transform_name, new_transform)
                else:
                    ns = getattr(renpy.store, store_name, None)
                    if ns:
                        setattr(ns, transform_name, new_transform)

                # Clear any cached compiled ATL blocks
                if hasattr(old_atl, 'compiled_block'):
                    old_atl.compiled_block = None
                if hasattr(new_atl, 'compiled_block'):
                    new_atl.compiled_block = None

                # Invalidate transform instances that might be using the old transform
                self._invalidate_active_transforms(transform_name)

                print(f"[DAP] Live edit: Recompiled transform '{transform_name}'")

                # Force a restart to apply
                renpy.exports.restart_interaction()

                return True

            except Exception as e:
                print(f"[DAP] Live edit: Error parsing ATL for transform {transform_name}: {e}")
                import traceback
                traceback.print_exc()
                return False

        except Exception as e:
            print(f"[DAP] Live edit: Error updating Transform: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _extract_atl_block(self, lines: list, start_line: int) -> Optional[str]:
        """
        Extract ATL block source starting from the line after the transform declaration.
        """
        if start_line < 1 or start_line > len(lines):
            return None

        # Get the declaration line
        decl_line = lines[start_line - 1]

        # Find the start of the ATL block (indented lines after the declaration)
        block_lines = []
        base_indent = None

        # Start from the line after the declaration
        for i in range(start_line, len(lines)):
            line = lines[i]
            stripped = line.lstrip()

            # Skip empty lines but keep them in the block
            if not stripped:
                if block_lines:  # Only add empty lines if we've started the block
                    block_lines.append("")
                continue

            # Calculate indentation
            indent = len(line) - len(stripped)

            if base_indent is None:
                # First non-empty line sets the base indentation
                base_indent = indent
                block_lines.append(stripped)
            elif indent >= base_indent:
                # Remove base indentation to normalize
                block_lines.append(line[base_indent:].rstrip())
            else:
                # Less indented - block ended
                break

        if not block_lines:
            return None

        return '\n'.join(block_lines)

    def _invalidate_active_transforms(self, transform_name: str) -> None:
        """
        Invalidate any active transform instances that use the given transform.
        """
        try:
            import renpy

            # Clear render cache to force re-rendering with new transform
            if hasattr(renpy.display, 'render'):
                render = renpy.display.render
                if hasattr(render, 'render_cache'):
                    render.render_cache.clear()
                if hasattr(render, 'invalidate_all'):
                    render.invalidate_all()

            # Clear the scene list cache if it exists
            if hasattr(renpy.game, 'interface') and renpy.game.interface:
                interface = renpy.game.interface
                if hasattr(interface, 'display_reset'):
                    interface.display_reset = True

            # Mark transforms for refresh
            if hasattr(renpy.display, 'transform'):
                transform_module = renpy.display.transform
                # Clear any transform-specific caches
                if hasattr(transform_module, 'null'):
                    # Reset null transforms if needed
                    pass

            print(f"[DAP] Live edit: Invalidated caches for transform '{transform_name}'")

        except Exception as e:
            print(f"[DAP] Live edit: Error invalidating transform: {e}")

    def _update_style_node(self, node, line_content: str) -> bool:
        """
        Update a Style definition.
        """
        try:
            import renpy

            style_name = getattr(node, 'style_name', None)
            if not style_name:
                return False

            # Rebuild styles
            if hasattr(renpy, 'style'):
                # Invalidate style cache to force rebuild
                if hasattr(renpy.style, 'rebuild'):
                    renpy.style.rebuild()

            renpy.exports.restart_interaction()
            return True

        except Exception as e:
            print(f"[DAP] Live edit: Error updating Style: {e}")
            return False

    def _update_define_node(self, node, line_content: str) -> bool:
        """
        Update a Define statement (like define e = Character(...)).

        Handles:
        - Character definitions with all properties (name, color, who_color, etc.)
        - ADVCharacter and NVLCharacter
        - Other variable definitions

        Returns True only if the value actually changed.
        """
        try:
            import renpy

            var_name = getattr(node, 'varname', None)
            if not var_name:
                return False

            # Parse the define statement
            # define varname = expression
            match = re.match(r'define\s+(\w+)\s*=\s*(.+)', line_content.strip())
            if not match:
                return False

            expr = match.group(2)

            # Get the old value to check if it's a Character
            old_value = getattr(renpy.store, var_name, None)
            is_character = isinstance(old_value, renpy.character.ADVCharacter)

            # Build a comprehensive evaluation context
            eval_context = self._build_define_eval_context()

            # Try to evaluate and update the store
            try:
                # Evaluate in the store context
                value = eval(expr, eval_context, vars(renpy.store))

                # Check if value actually changed before updating
                value_changed = False

                if is_character and isinstance(value, renpy.character.ADVCharacter):
                    # For characters, compare key properties
                    old_props = self._get_character_props(old_value) if old_value else {}
                    new_props = self._get_character_props(value)
                    value_changed = old_props != new_props
                elif old_value != value:
                    value_changed = True

                if value_changed:
                    setattr(renpy.store, var_name, value)
                    # If it's a Character, do additional updates
                    if is_character or isinstance(value, renpy.character.ADVCharacter):
                        self._handle_character_update(var_name, value, old_value)
                    return True

                return False

            except Exception as e:
                print(f"[DAP] Live edit: Could not evaluate define expression: {e}")
                import traceback
                traceback.print_exc()
                return False

        except Exception as e:
            print(f"[DAP] Live edit: Error updating Define: {e}")
            return False

    def _get_character_props(self, char) -> dict:
        """
        Get comparable properties from a Character object.
        Used to detect if a Character definition actually changed.
        """
        if char is None:
            return {}

        props = {}
        # Key properties that affect display
        for prop in ['name', 'who_color', 'what_color', 'who_bold', 'what_bold',
                     'who_italic', 'what_italic', 'who_size', 'what_size',
                     'who_font', 'what_font', 'who_outlines', 'what_outlines',
                     'image', 'voice_tag', 'kind']:
            if hasattr(char, prop):
                val = getattr(char, prop)
                # Make sure value is hashable for comparison
                if isinstance(val, (list, dict)):
                    props[prop] = str(val)
                else:
                    props[prop] = val

        return props

    def _process_define_statements_directly(self, lines: list) -> bool:
        """
        Process define statements directly from file content without AST lookup.

        This is the simple, reliable approach for updating Character definitions
        and other define statements. It:
        1. Scans lines for 'define' statements
        2. Parses variable name and expression directly from text
        3. Evaluates and stores in renpy.store
        4. Updates displayed characters if needed

        Returns True if any defines were processed.
        """
        import renpy

        processed_any = False
        eval_context = self._build_define_eval_context()

        for line in lines:
            stripped = line.strip()

            # Skip empty lines and comments
            if not stripped or stripped.startswith('#'):
                continue

            # Match define statements (including 'define foo = ...')
            # Handle both 'define x = ...' and 'define x = Character(...)'
            match = re.match(r'^define\s+(\w+)\s*=\s*(.+)$', stripped)
            if not match:
                continue

            var_name = match.group(1)
            expr = match.group(2)

            try:
                # Get the old value to detect character changes
                old_value = getattr(renpy.store, var_name, None)
                was_character = isinstance(old_value, renpy.character.ADVCharacter)

                # Evaluate the expression in the store context
                new_value = eval(expr, eval_context, vars(renpy.store))

                # Store it - update both renpy.store AND the store_dicts directly
                # eval_who() in ast.py looks up characters via store_dicts, not renpy.store
                setattr(renpy.store, var_name, new_value)
                renpy.python.store_dicts["store"][var_name] = new_value
                processed_any = True

                is_character = isinstance(new_value, renpy.character.ADVCharacter)

                if was_character or is_character:
                    self._handle_character_update(var_name, new_value, old_value)

            except BaseException as e:
                # Re-raise control exceptions (rollback, etc.)
                if self._is_control_exception(e):
                    raise
                # Only log errors for define statements that look like they should work
                if self.VERBOSE_LOGGING and 'Character' in expr:
                    print(f"[DAP] Character define error for '{var_name}': {e}")
                continue

        return processed_any

    def _build_define_eval_context(self) -> dict:
        """
        Build a comprehensive evaluation context for define statements.
        """
        import renpy

        context = {
            'renpy': renpy,
            # Character types
            'Character': renpy.character.Character,
            'ADVCharacter': renpy.character.ADVCharacter,
            # Common functions and values
            'Color': renpy.color.Color if hasattr(renpy, 'color') else str,
            'Dissolve': renpy.curry.curry(renpy.display.transition.Dissolve) if hasattr(renpy.display, 'transition') else None,
            'Fade': renpy.curry.curry(renpy.display.transition.Fade) if hasattr(renpy.display, 'transition') else None,
            'True': True,
            'False': False,
            'None': None,
            # Style access
            'style': renpy.style if hasattr(renpy, 'style') else None,
            # Common text tags helper
            'im': renpy.display.im if hasattr(renpy.display, 'im') else None,
            'Image': renpy.display.image.Image if hasattr(renpy.display, 'image') else None,
            'Text': renpy.text.text.Text if hasattr(renpy.text, 'text') else None,
            'Transform': renpy.display.transform.Transform if hasattr(renpy.display, 'transform') else None,
            # Audio
            'AudioData': getattr(renpy.audio.audio, 'AudioData', None) if hasattr(renpy.audio, 'audio') else None,
        }

        # Add NVLCharacter if available
        if hasattr(renpy.character, 'NVLCharacter'):
            context['NVLCharacter'] = renpy.character.NVLCharacter

        # Add gui values if available
        if hasattr(renpy.store, 'gui'):
            context['gui'] = renpy.store.gui

        # Filter out None values
        return {k: v for k, v in context.items() if v is not None}

    def _handle_character_update(self, var_name: str, new_char, old_char) -> None:
        """
        Handle additional updates needed when a Character definition changes.
        This includes updating the currently displayed say screen if needed.

        The character object in the store has already been updated by our caller.
        We need to:
        1. Update the rollback history so the change persists through rollbacks
        2. Refresh the display to show the new name/color
        """
        try:
            import renpy
            from renpy.pydict import DictItems

            # Update the store's 'old' tracking so the character change persists
            # through the current checkpoint
            store_dict = renpy.python.store_dicts.get("store")
            if store_dict is not None and hasattr(store_dict, 'old'):
                # Update 'old' to include our new character value
                store_dict.old = DictItems(store_dict)

            # Update the character in ALL rollback checkpoints
            # This ensures the change persists even if the user rolls back
            if hasattr(renpy, 'game') and hasattr(renpy.game, 'log') and renpy.game.log is not None:
                rollback_log = renpy.game.log

                # Update each Rollback object in the log
                for rollback in getattr(rollback_log, 'log', []):
                    if hasattr(rollback, 'stores') and 'store' in rollback.stores:
                        # The stores dict maps variable names to their old values
                        # We need to update it to use our new character
                        store_changes = rollback.stores['store']
                        if var_name in store_changes:
                            # Replace the old character with the new one
                            store_changes[var_name] = new_char

                # Also update the current rollback if it exists
                current = getattr(rollback_log, 'current', None)
                if current is not None and hasattr(current, 'stores'):
                    if 'store' in current.stores and var_name in current.stores['store']:
                        current.stores['store'][var_name] = new_char

            # The say screen was created with the old character properties.
            # We need to force it to be recreated with the new properties.
            # Hide and re-show the say screen to pick up the new character.
            try:
                # Get the current say screen info
                say_screen = renpy.display.screen.get_screen("say")
                if say_screen is not None:
                    # Get the scope (who, what, etc.) from the current screen
                    scope = getattr(say_screen, 'scope', {})
                    who = scope.get('who')
                    what = scope.get('what')

                    if who is not None or what is not None:
                        # Re-evaluate who to get the updated character
                        if var_name and hasattr(renpy.store, var_name):
                            char = getattr(renpy.store, var_name)
                            if hasattr(char, 'do_show') and what:
                                # Hide current say screen
                                renpy.display.screen.hide_screen("say")
                                # Re-show with the new character
                                char.do_show(getattr(char, 'name', who), what)
            except Exception:
                pass

            # Also force a redraw
            if hasattr(renpy, 'game') and hasattr(renpy.game, 'interface'):
                renpy.game.interface.force_redraw = True
                renpy.game.interface.restart_interaction = True

        except BaseException as e:
            # Re-raise control exceptions, silently fail on others
            if self._is_control_exception(e):
                raise
            pass

    def _update_default_node(self, node, line_content: str) -> bool:
        """
        Update a Default statement.
        """
        try:
            import renpy

            var_name = getattr(node, 'varname', None)
            if not var_name:
                return False

            # Parse: default varname = expression
            match = re.match(r'default\s+(\w+)\s*=\s*(.+)', line_content.strip())
            if not match:
                return False

            expr = match.group(2)

            # Evaluate and update
            try:
                value = eval(expr, {'renpy': renpy}, vars(renpy.store))
                setattr(renpy.store, var_name, value)
                return True
            except Exception as e:
                print(f"[DAP] Live edit: Could not evaluate default expression: {e}")
                return False

        except Exception as e:
            print(f"[DAP] Live edit: Error updating Default: {e}")
            return False

    def _extract_indented_block(self, lines: list, start_line: int) -> Optional[str]:
        """
        Extract an indented code block starting from start_line.
        """
        if start_line < 1 or start_line > len(lines):
            return None

        block_lines = []
        base_indent = None

        for i in range(start_line - 1, len(lines)):
            line = lines[i]
            stripped = line.lstrip()

            if not stripped:
                block_lines.append(line)
                continue

            indent = len(line) - len(stripped)

            if base_indent is None:
                base_indent = indent
                block_lines.append(line)
            elif indent >= base_indent:
                block_lines.append(line)
            else:
                break

        return ''.join(block_lines) if block_lines else None

    def _detect_structural_changes(self, filepath: str, lines: List[str]) -> Tuple[List[int], List[int]]:
        """
        Detect added and removed lines by comparing file content with AST state.

        Returns:
            Tuple of (added_line_numbers, removed_line_numbers)
        """
        try:
            import renpy

            filepath_normalized = os.path.normpath(filepath)
            old_line_count = self._file_line_counts.get(filepath_normalized, 0)
            new_line_count = len(lines)

            # Get previously tracked AST lines
            previous_ast_lines = self._file_ast_lines.get(filepath_normalized, set())

            # Get current AST lines for this file
            current_ast_lines: Set[int] = set()
            ast_nodes_by_line: Dict[int, object] = {}
            for node in renpy.game.script.all_stmts:
                node_file = getattr(node, 'filename', None)
                if not node_file:
                    continue
                node_file_normalized = os.path.normpath(node_file)
                if node_file_normalized == filepath_normalized or node_file_normalized.endswith(os.path.basename(filepath)):
                    line_num = getattr(node, 'linenumber', 0)
                    current_ast_lines.add(line_num)
                    ast_nodes_by_line[line_num] = node

            added_lines: List[int] = []
            removed_lines: List[int] = []

            # Detect REMOVED statements:
            # AST has a node at line X, but the file line X is now empty/comment/different
            for ast_line in current_ast_lines:
                if ast_line < 1 or ast_line > new_line_count:
                    # Line number is beyond file - statement was removed
                    removed_lines.append(ast_line)
                    print(f"[DAP] Live edit: Line {ast_line} no longer exists (file has {new_line_count} lines)")
                    continue

                file_line = lines[ast_line - 1].strip()

                # If line is now empty or a comment, the statement was removed
                if not file_line or file_line.startswith("#"):
                    removed_lines.append(ast_line)
                    print(f"[DAP] Live edit: Line {ast_line} is now empty/comment, statement removed")
                    continue

                # Check if the line content still matches the statement type
                node = ast_nodes_by_line.get(ast_line)
                if node and not self._line_matches_node_type(file_line, node):
                    removed_lines.append(ast_line)
                    print(f"[DAP] Live edit: Line {ast_line} content changed type, old statement removed")

            # Detect ADDED statements:
            # File has a statement-like line that's not in the AST
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                # Skip empty lines and comments
                if not stripped or stripped.startswith("#"):
                    continue
                # Check if this looks like a statement that should be in AST
                if self._is_statement_line(stripped):
                    if i not in current_ast_lines:
                        added_lines.append(i)
                        print(f"[DAP] Live edit: Detected new statement at line {i}: {stripped[:50]}...")

            # Log summary
            if new_line_count != old_line_count:
                print(f"[DAP] Live edit: Line count changed from {old_line_count} to {new_line_count}")

            # Update tracked state
            self._file_line_counts[filepath_normalized] = new_line_count
            self._file_ast_lines[filepath_normalized] = current_ast_lines

            return added_lines, removed_lines

        except Exception as e:
            print(f"[DAP] Live edit: Error detecting structural changes: {e}")
            import traceback
            traceback.print_exc()
            return [], []

    def _line_matches_node_type(self, line: str, node) -> bool:
        """
        Check if a file line content matches the expected node type.
        Used to detect when a line's statement type has changed.
        """
        node_class = node.__class__.__name__

        # Map node types to expected line patterns
        if node_class in ("Say", "TranslateSay"):
            # Should be dialogue: "text" or character "text"
            return bool(re.search(r'["\']', line))

        elif node_class == "Show":
            return line.startswith("show ")

        elif node_class == "Scene":
            return line.startswith("scene ")

        elif node_class == "Hide":
            return line.startswith("hide ")

        elif node_class == "Play":
            return line.startswith("play ")

        elif node_class == "Stop":
            return line.startswith("stop ")

        elif node_class == "Label":
            return line.startswith("label ") and line.rstrip().endswith(":")

        elif node_class == "Jump":
            return line.startswith("jump ")

        elif node_class == "Call":
            return line.startswith("call ")

        elif node_class == "Return":
            return line.startswith("return")

        elif node_class == "Menu":
            return line.startswith("menu") and ":" in line

        elif node_class in ("Python", "EarlyPython"):
            return "python" in line.lower() and ":" in line

        elif node_class == "Define":
            return line.startswith("define ")

        elif node_class == "Default":
            return line.startswith("default ")

        elif node_class == "Screen":
            return line.startswith("screen ")

        elif node_class == "Transform":
            return line.startswith("transform ")

        elif node_class == "Image":
            return line.startswith("image ")

        # For unknown types, assume it matches
        return True

    def _is_statement_line(self, line: str) -> bool:
        """
        Check if a line looks like a Ren'Py statement that should be in the AST.
        """
        # Statement keywords that create AST nodes
        statement_prefixes = (
            '"',  # Narrator dialogue
            "'",  # Single-quote dialogue (narrator)
            "show ", "scene ", "hide ",  # Image statements
            "play ", "stop ", "queue ",  # Audio statements
            "with ",  # Transitions
            "jump ", "call ", "return",  # Control flow
            "menu:",  # Menus
            "label ",  # Labels
            "if ", "elif ", "else:",  # Conditionals
            "while ", "for ",  # Loops
            "python:", "init ", "define ", "default ",  # Python and definitions
            "$",  # One-line Python
            "screen ",  # Screens
            "transform ",  # Transforms
            "style ",  # Styles
            "image ",  # Image definitions
            "layeredimage ",  # Layered images
            "nvl ", "window ",  # NVL mode
            "pause",  # Pause
            "pass",  # Pass statement
        )

        # Check for character dialogue (identifier followed by string)
        # e.g., "e 'Hello'" or "eileen 'Hi there'"
        if re.match(r'^[a-zA-Z_]\w*\s+["\']', line):
            return True

        return line.startswith(statement_prefixes)

    def _add_new_statements(self, filepath: str, lines: List[str], added_line_numbers: List[int]) -> bool:
        """
        Add new statements to the AST.

        Uses renpy.scriptedit to properly insert new statements into the AST chain.

        Returns True if any statements were added.
        """
        if not added_line_numbers:
            return False

        try:
            import renpy

            # Get the elided filename for scriptedit
            if hasattr(renpy.config, 'gamedir') and renpy.config.gamedir:
                rel_path = os.path.relpath(filepath, renpy.config.gamedir)
            else:
                rel_path = filepath
            rel_path = rel_path.replace("\\", "/")

            added_any = False

            # Sort by line number and process from bottom to top
            # This prevents line number shifts from affecting subsequent insertions
            for line_num in sorted(added_line_numbers, reverse=True):
                if line_num < 1 or line_num > len(lines):
                    continue

                line_content = lines[line_num - 1].strip()

                # Skip empty lines and comments
                if not line_content or line_content.startswith("#"):
                    continue

                # Find the next existing statement to insert before
                insertion_point = self._find_insertion_point(filepath, line_num)
                if insertion_point is None:
                    print(f"[DAP] Live edit: Could not find insertion point for line {line_num}")
                    continue

                print(f"[DAP] Live edit: Adding new statement at line {line_num}: {line_content[:50]}...")

                try:
                    # Use scriptedit to add to AST
                    # First, ensure scriptedit has loaded the file
                    renpy.scriptedit.ensure_loaded(rel_path)

                    # Add to AST before the insertion point
                    renpy.scriptedit.add_to_ast_before(line_content, rel_path, insertion_point)

                    # Also insert the line in scriptedit's line tracking
                    # This is usually done by insert_line_before, but we're not modifying the file
                    # (the user already did that) - we just need the AST update

                    added_any = True
                    print(f"[DAP] Live edit: Successfully added statement to AST")

                except Exception as e:
                    print(f"[DAP] Live edit: Error adding statement at line {line_num}: {e}")
                    import traceback
                    traceback.print_exc()

            return added_any

        except Exception as e:
            print(f"[DAP] Live edit: Error adding new statements: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _find_insertion_point(self, filepath: str, new_line_num: int) -> Optional[int]:
        """
        Find the line number of the next existing AST statement after new_line_num.

        This is where we'll insert the new statement "before".
        """
        try:
            import renpy

            filepath_normalized = os.path.normpath(filepath)

            # Find all statement line numbers from this file that are >= new_line_num
            candidates = []
            for node in renpy.game.script.all_stmts:
                node_file = getattr(node, 'filename', None)
                if not node_file:
                    continue
                node_file_normalized = os.path.normpath(node_file)
                if not (node_file_normalized == filepath_normalized or
                        node_file_normalized.endswith(os.path.basename(filepath))):
                    continue

                node_line = getattr(node, 'linenumber', 0)
                if node_line >= new_line_num:
                    candidates.append(node_line)

            if candidates:
                return min(candidates)

            # If no statements after, try to find the last statement and use it
            # The new statement will be added to the end of the label
            all_lines = []
            for node in renpy.game.script.all_stmts:
                node_file = getattr(node, 'filename', None)
                if not node_file:
                    continue
                node_file_normalized = os.path.normpath(node_file)
                if node_file_normalized == filepath_normalized or node_file_normalized.endswith(os.path.basename(filepath)):
                    all_lines.append(getattr(node, 'linenumber', 0))

            if all_lines:
                # Return the last statement - we'll add after it
                return max(all_lines)

            return None

        except Exception as e:
            print(f"[DAP] Live edit: Error finding insertion point: {e}")
            return None

    def _remove_deleted_statements(self, filepath: str, removed_line_numbers: List[int]) -> bool:
        """
        Remove statements from the AST that were deleted from the file.

        Returns True if any statements were removed.
        """
        if not removed_line_numbers:
            return False

        try:
            import renpy

            # Get the elided filename for scriptedit
            if hasattr(renpy.config, 'gamedir') and renpy.config.gamedir:
                rel_path = os.path.relpath(filepath, renpy.config.gamedir)
            else:
                rel_path = filepath
            rel_path = rel_path.replace("\\", "/")

            removed_any = False

            # Sort by line number and process from bottom to top
            for line_num in sorted(removed_line_numbers, reverse=True):
                try:
                    # Check if there's a node at this line
                    nodes = renpy.scriptedit.nodes_on_line(rel_path, line_num)
                    if not nodes:
                        continue

                    print(f"[DAP] Live edit: Removing statement at line {line_num}")

                    # Remove from AST
                    renpy.scriptedit.remove_from_ast(rel_path, line_num)

                    removed_any = True
                    print(f"[DAP] Live edit: Successfully removed statement from AST")

                except Exception as e:
                    print(f"[DAP] Live edit: Error removing statement at line {line_num}: {e}")

            return removed_any

        except Exception as e:
            print(f"[DAP] Live edit: Error removing deleted statements: {e}")
            return False

    def _check_and_reload_shaders(self, filepath: str) -> bool:
        """
        Check if any shader definitions changed and reload them.

        Looks for renpy.register_shader() calls and updates the shader cache.
        Returns True if any shaders were reloaded.
        """
        try:
            import renpy

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # Look for shader registration patterns
            shader_pattern = re.compile(
                r'renpy\.register_shader\s*\(\s*["\']([^"\']+)["\']',
                re.MULTILINE
            )

            shader_names = shader_pattern.findall(content)
            if not shader_names:
                return False

            print(f"[DAP] Live edit: Found shader definitions: {shader_names}")

            # Clear the shader cache to force recompilation
            if hasattr(renpy, 'gl2') and hasattr(renpy.gl2, 'gl2shadercache'):
                cache = renpy.gl2.gl2shadercache
                if hasattr(cache, 'cache'):
                    # Clear cached compiled programs
                    cache.cache.clear()
                    print(f"[DAP] Live edit: Cleared shader cache")

            # Re-execute the file to update shader_part registry
            # This is a simplified approach - execute shader registration code
            try:
                # Extract and execute just the shader registration blocks
                exec_globals = {'renpy': renpy}
                exec(content, exec_globals)
                print(f"[DAP] Live edit: Re-executed shader definitions")
            except Exception as e:
                print(f"[DAP] Live edit: Error re-executing shader code: {e}")

            # Force a redraw to use new shaders
            renpy.exports.restart_interaction()

            return True

        except Exception as e:
            print(f"[DAP] Live edit: Error checking shaders: {e}")
            return False

    def _check_cross_label_rollback(self, filepath: str, updated_lines: list) -> None:
        """
        Check if changes in another file affect our execution history.

        Uses Ren'Py's rollback log to find if we've passed through any
        of the changed lines, and rolls back if needed.
        """
        try:
            import renpy

            if not updated_lines:
                return

            # Get the rollback log - this contains our execution history
            if not hasattr(renpy.game, 'log') or not renpy.game.log:
                return

            log = renpy.game.log

            # Normalize filepath for comparison
            filepath_normalized = os.path.normpath(filepath)
            basename = os.path.basename(filepath)

            # Check the rollback log for any entries from the changed file/lines
            # The log contains RollbackLog entries with context information
            checkpoints_back = 0
            found_change = False

            # Access the log's internal list
            if hasattr(log, 'log'):
                for i, entry in enumerate(reversed(log.log)):
                    checkpoints_back += 1

                    # Check if this entry is from the changed file
                    if hasattr(entry, 'context') and entry.context:
                        ctx = entry.context
                        # The context has 'current' which is a label/node reference
                        if hasattr(ctx, 'current'):
                            current_ref = ctx.current
                            # Look up the actual node
                            try:
                                node = renpy.game.script.lookup(current_ref)
                                if node:
                                    node_file = getattr(node, 'filename', '')
                                    node_line = getattr(node, 'linenumber', 0)

                                    # Check if this node's file matches
                                    if node_file:
                                        node_file_normalized = os.path.normpath(node_file)
                                        if (node_file_normalized == filepath_normalized or
                                                node_file_normalized.endswith(basename)):
                                            # Check if this line was updated
                                            if node_line in updated_lines:
                                                found_change = True
                                                print(f"[DAP] Live edit: Found changed line {node_line} in rollback history ({checkpoints_back} checkpoints back)")
                                                break
                            except Exception:
                                pass

                    # Limit how far back we search
                    if checkpoints_back > 100:
                        break

            if found_change and checkpoints_back > 0:
                print(f"[DAP] Live edit: Rolling back {checkpoints_back} checkpoints to re-execute changed code")
                try:
                    renpy.exports.rollback(checkpoints=checkpoints_back, force=True, greedy=True)
                except BaseException as e:
                    if self._is_control_exception(e):
                        raise
                except Exception as e:
                    print(f"[DAP] Live edit: Cross-label rollback failed: {e}")

        except BaseException as e:
            if self._is_control_exception(e):
                raise
            print(f"[DAP] Live edit: Error checking cross-label rollback: {e}")

    def _find_earliest_changed_line(self, filepath: str, current_line: int) -> Optional[int]:
        """
        Find the earliest line that changed before the current line.

        Returns the line number, or None if no changes before current line.
        """
        updated_lines = getattr(self, '_last_updated_lines', [])
        before_current = [ln for ln in updated_lines if ln < current_line]
        if before_current:
            return min(before_current)
        return None

    def _rollback_to_line(self, filepath: str, target_line: int, current_line: int) -> None:
        """
        Rollback to re-execute from a changed line.

        Uses Ren'Py's rollback system to go back and re-execute with the new code.
        """
        try:
            import renpy

            # Calculate how many statements we need to roll back
            # This is approximate - we count statements between target and current
            statements_back = 0
            filepath_normalized = os.path.normpath(filepath)

            for node in renpy.game.script.all_stmts:
                node_file = getattr(node, 'filename', None)
                if not node_file:
                    continue

                node_file_normalized = os.path.normpath(node_file)
                if not (node_file_normalized == filepath_normalized or
                        node_file_normalized.endswith(os.path.basename(filepath))):
                    continue

                node_line = getattr(node, 'linenumber', 0)
                if target_line <= node_line < current_line:
                    statements_back += 1

            if statements_back == 0:
                statements_back = 1  # At least roll back one


            # Use greedy rollback to re-execute forward after rolling back
            # checkpoints parameter is how many "hard" checkpoints to go back
            # For dialogue, each say statement is typically a checkpoint
            try:
                renpy.exports.rollback(checkpoints=statements_back, force=True, greedy=True)
            except BaseException as e:
                # Rollback raises control exceptions to unwind the stack - re-raise them
                if self._is_control_exception(e):
                    raise
                # Fallback: just restart interaction
                renpy.exports.restart_interaction()

        except BaseException as e:
            if self._is_control_exception(e):
                raise
            print(f"[DAP] Live edit: Error in rollback: {e}")
            import traceback
            traceback.print_exc()

    def _apply_live_text_edit(self, node, filepath: str, linenumber: int, force_refresh: bool = False) -> bool:
        """
        Apply a live text edit to the current Say statement.

        Uses the Interactive Director's approach:
        1. Reload the scriptedit data for the file
        2. Update the AST node's text
        3. Use rollback to re-execute

        Args:
            force_refresh: If True, refresh the display even if texts appear equal
                          (useful when AST was just updated and display may be stale)
        """
        try:
            import renpy

            # Re-read the file to get the new line content
            print(f"[DAP] Live edit: Reading from file: {filepath}")
            new_text = self._extract_say_text_from_file(filepath, linenumber)
            if new_text is None:
                print(f"[DAP] Live edit: Could not extract text from line {linenumber}")
                return False

            # Get the DISPLAYED text for comparison (not node.what, which may already be updated)
            # The say screen's scope contains what's actually shown on screen
            displayed_text = None
            try:
                say_screen = renpy.display.screen.get_screen("say")
                if say_screen is not None:
                    scope = getattr(say_screen, 'scope', {})
                    displayed_text = scope.get('what')
            except Exception:
                pass

            # Fall back to node.what if we couldn't get displayed text
            old_text = displayed_text if displayed_text is not None else getattr(node, 'what', None)
            print(f"[DAP] Live edit: Displayed text: {repr(old_text)[:80] if old_text else None}...")
            print(f"[DAP] Live edit: New text: {repr(new_text)[:80]}...")

            if old_text == new_text and not force_refresh:
                print("[DAP] Live edit: Text unchanged, no update needed")
                return True  # Nothing to do

            if old_text == new_text and force_refresh:
                print("[DAP] Live edit: Text appears unchanged but force_refresh=True, refreshing display")

            old_preview = old_text[:50] if old_text else "None"
            new_preview = new_text[:50] if new_text else "None"
            print(f"[DAP] Live edit: Updating text from '{old_preview}' to '{new_preview}'")

            # Update the node's text directly so it persists
            node.what = new_text

            # Reload the scriptedit line data so future edits work
            self._reload_scriptedit_line(filepath, linenumber)

            # Hide and re-show the say screen to pick up the new text/speaker
            try:
                say_screen = renpy.display.screen.get_screen("say")
                if say_screen is not None:
                    scope = getattr(say_screen, 'scope', {})
                    displayed_who = scope.get('who')  # The currently displayed character name
                    displayed_what = scope.get('what')  # The currently displayed text

                    # Get the character variable name from the node (may have been updated)
                    node_who = getattr(node, 'who', None)

                    print(f"[DAP] Live edit: node.who={node_who}, displayed_who={displayed_who}, displayed_what={displayed_what[:30] if displayed_what else None}...")

                    # Hide the current say screen first
                    renpy.display.screen.hide_screen("say")

                    if node_who is None:
                        # Narrator line - use renpy.say with None as the character
                        print(f"[DAP] Live edit: Narrator line, re-showing with who=None, new_text={new_text[:30]}...")
                        renpy.exports.say(None, new_text, interact=False)
                    else:
                        # Character line - look up the character and use its do_show
                        char = renpy.python.store_dicts["store"].get(node_who)
                        if char is not None and hasattr(char, 'do_show'):
                            # Use the character's actual name for display
                            char_name = getattr(char, 'name', None)
                            print(f"[DAP] Live edit: Re-showing with char={node_who}, char_name={char_name}, new_text={new_text[:30]}...")
                            char.do_show(char_name, new_text)
                        else:
                            print(f"[DAP] Live edit: No char found for '{node_who}', using fallback say")
                            # Fallback: try to use renpy.say with the variable name
                            renpy.exports.say(node_who, new_text, interact=False)
                else:
                    print(f"[DAP] Live edit: No say screen found")
                    self._update_displayed_text_widget(new_text)
            except Exception as ex:
                print(f"[DAP] Live edit: Exception in re-show: {ex}")
                import traceback
                traceback.print_exc()
                self._update_displayed_text_widget(new_text)

            # Force display refresh
            if hasattr(renpy, 'game') and hasattr(renpy.game, 'interface'):
                renpy.game.interface.force_redraw = True
                renpy.game.interface.restart_interaction = True

            return True

        except BaseException as e:
            # Re-raise control exceptions (like rollback)
            if self._is_control_exception(e):
                raise
            print(f"[DAP] Live edit: Error applying edit: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_show_statement_lines(self, filepath: str, current_line: int) -> list:
        """
        Get line numbers of show/scene/hide statements before the current line.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            show_lines = []
            # Find the label we're in by searching backwards
            label_line = 0
            for i in range(current_line - 1, -1, -1):
                line = lines[i].strip() if i < len(lines) else ""
                if line.startswith("label ") and line.endswith(":"):
                    label_line = i + 1
                    break

            # Find show/scene/hide lines
            for i in range(label_line, min(current_line, len(lines))):
                line = lines[i].strip()
                if line.startswith(("show ", "scene ", "hide ")):
                    show_lines.append(i + 1)  # 1-based line number

            return show_lines
        except Exception:
            return []

    def _apply_show_statement_changes(self, filepath: str, current_line: int) -> bool:
        """
        Re-execute show/scene/hide statements from the file that are before the current line.

        This allows live editing of image statements to take effect immediately.
        """
        try:
            import renpy

            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            executed_any = False

            # Find the label we're in by searching backwards
            label_line = 0
            for i in range(current_line - 1, -1, -1):
                line = lines[i].strip() if i < len(lines) else ""
                if line.startswith("label ") and line.endswith(":"):
                    label_line = i + 1
                    break

            # Process lines from label start to current line
            for i in range(label_line, min(current_line, len(lines))):
                line = lines[i].strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Check for show/scene/hide/with statements
                result = self._parse_and_execute_image_statement(line)
                if result:
                    executed_any = True
                    print(f"[DAP] Live edit: Executed '{line[:50]}...' from line {i + 1}")

            if executed_any:
                # Restart interaction to refresh the display
                renpy.exports.restart_interaction()

            return executed_any

        except Exception as e:
            print(f"[DAP] Live edit: Error applying show changes: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _parse_and_execute_image_statement(self, line: str) -> bool:
        """
        Parse and execute a show/scene/hide/with statement.

        Returns True if a statement was executed.
        """
        try:
            import renpy

            line = line.strip()

            # scene statement - clears images and optionally shows new one
            if line.startswith("scene "):
                parts = line[6:].split()
                if not parts or parts[0] in ("black", "white"):
                    # scene black/white or just scene
                    renpy.exports.scene()
                    if parts:
                        # Show a solid color
                        renpy.exports.show(parts[0])
                else:
                    # scene with image
                    self._execute_show_from_parts(parts, is_scene=True)
                return True

            # show statement
            elif line.startswith("show "):
                parts = line[5:].split()
                if parts:
                    self._execute_show_from_parts(parts, is_scene=False)
                    return True

            # hide statement
            elif line.startswith("hide "):
                parts = line[5:].split()
                if parts:
                    tag = parts[0]
                    renpy.exports.hide(tag)
                    return True

            # with statement (transition) - skip for live edit, transitions are jarring
            elif line.startswith("with "):
                # Skip transitions during live edit
                return False

            return False

        except Exception as e:
            print(f"[DAP] Live edit: Error executing '{line}': {e}")
            return False

    def _execute_show_from_parts(self, parts: list, is_scene: bool = False) -> None:
        """
        Execute a show statement from parsed parts.

        Handles: show tag attributes at transform
        """
        import renpy

        if not parts:
            return

        # Parse the parts
        tag = parts[0]
        attributes = []
        at_list = []

        i = 1
        while i < len(parts):
            if parts[i] == "at" and i + 1 < len(parts):
                # Collect transforms after "at"
                i += 1
                while i < len(parts) and parts[i] not in ("with", "behind", "onlayer", "zorder", "as"):
                    at_list.append(parts[i].rstrip(","))
                    i += 1
            elif parts[i] in ("with", "behind", "onlayer", "zorder", "as"):
                # Skip these clauses for now
                break
            else:
                attributes.append(parts[i])
                i += 1

        # Build the image name
        if attributes:
            image_name = (tag,) + tuple(attributes)
        else:
            image_name = (tag,)

        # Get transforms
        transforms = []
        for t in at_list:
            transform = getattr(renpy.store, t, None)
            if transform:
                transforms.append(transform)

        # Execute
        if is_scene:
            renpy.exports.scene()

        if transforms:
            renpy.exports.show(image_name, at_list=transforms)
        else:
            renpy.exports.show(image_name)

    def _update_displayed_text_widget(self, new_text: str) -> bool:
        """
        Directly update the currently displayed dialogue text widget.

        This provides immediate visual feedback without waiting for rollback.
        """
        try:
            import renpy

            # Get the "what" text widget from the say screen
            what_widget = None
            for screen_name in ["say", "nvl", "dialogue", "screen"]:
                try:
                    what_widget = renpy.display.screen.get_widget(screen_name, "what")
                    if what_widget is not None:
                        break
                except Exception:
                    continue

            if what_widget is None:
                print("[DAP] Live edit: Could not find 'what' text widget")
                return False

            # Update the text content
            if hasattr(what_widget, 'set_text'):
                what_widget.set_text(new_text)
                print(f"[DAP] Live edit: Updated widget text directly")

                # Force a redraw
                renpy.display.render.redraw(what_widget, 0)
                return True
            else:
                print(f"[DAP] Live edit: Widget {type(what_widget)} has no set_text")
                return False

        except Exception as e:
            print(f"[DAP] Live edit: Error updating widget: {e}")
            return False

    def _extract_say_text_from_file(self, filepath: str, linenumber: int) -> Optional[str]:
        """
        Extract the dialogue text from a Say statement at the given line.
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            if linenumber < 1 or linenumber > len(lines):
                return None

            line = lines[linenumber - 1]
            return self._parse_say_line(line)

        except Exception as e:
            print(f"[DAP] Live edit: Error reading file: {e}")
            return None

    def _parse_say_line(self, line: str) -> Optional[str]:
        """
        Parse a Say statement line to extract the dialogue text.

        Handles various Say formats:
        - "Text here"
        - character "Text here"
        - e "Text here"
        - "Text here" with dissolve

        In Ren'Py, dialogue text is always in double quotes. Single quotes
        in the content are literal characters, not delimiters.
        """
        _, text = self._parse_say_line_full(line)
        return text

    def _parse_say_line_full(self, line: str) -> tuple:
        """
        Parse a Say statement line to extract both the speaker and dialogue text.

        Returns:
            (speaker, text) tuple where:
            - speaker is the character variable name (str) or None for narrator
            - text is the dialogue text (str) or None if not a valid say line

        Handles various Say formats:
        - "Text here"                    -> (None, "Text here")
        - character "Text here"          -> ("character", "Text here")
        - e "Text here"                  -> ("e", "Text here")
        - "Text here" with dissolve      -> (None, "Text here")
        """
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            return (None, None)

        # Remove 'with' clause if present
        with_match = re.search(r'\s+with\s+\w+\s*$', stripped)
        if with_match:
            stripped = stripped[:with_match.start()]

        # Try triple-quoted strings first
        triple_match = re.search(r'"""(.*?)"""', stripped, re.DOTALL)
        if triple_match:
            # Check for speaker before the triple quotes
            before_quotes = stripped[:triple_match.start()].strip()
            speaker = before_quotes if before_quotes and before_quotes.isidentifier() else None
            return (speaker, triple_match.group(1))

        # In Ren'Py, dialogue is in DOUBLE quotes only
        # Find the first double-quoted string position to determine speaker
        first_quote_pos = stripped.find('"')
        if first_quote_pos == -1:
            return (None, None)

        # Everything before the first quote is potentially the speaker plus
        # say attributes, for example: e happy "Text" or e @ happy "Text".
        before_quotes = stripped[:first_quote_pos].strip()

        speaker = self._parse_say_speaker(before_quotes)

        # Find all quoted strings and take the last one as the text
        double_quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', stripped)

        if double_quoted:
            # Take the last one - that's usually the dialogue text
            text = double_quoted[-1]
            # Unescape common escape sequences
            text = text.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t")
            return (speaker, text)

        return (None, None)

    def _parse_say_speaker(self, prefix: str) -> Optional[str]:
        """
        Extract the character variable from the text before a say string.

        Ren'Py say statements can include attributes after the character name:
        ``e happy "Text"``, ``e @ happy "Text"``, and similar forms. Live edit
        only needs the character variable so it can update ``node.who`` without
        turning attributed dialogue into narrator text.
        """
        if not prefix:
            return None

        parts = prefix.split()
        if not parts:
            return None

        candidate = parts[0]
        return candidate if candidate.isidentifier() else None

    def _reload_scriptedit_line(self, filepath: str, linenumber: int) -> None:
        """
        Reload the scriptedit data for a specific line.

        This ensures the Line object has the correct text for future edits.
        """
        try:
            import renpy

            # Get the elided filename (relative to game dir)
            if hasattr(renpy.config, 'gamedir') and renpy.config.gamedir:
                rel_path = os.path.relpath(filepath, renpy.config.gamedir)
            else:
                rel_path = filepath

            rel_path = rel_path.replace("\\", "/")

            # Read the new line content
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            lines_list = content.split('\n')
            if linenumber >= 1 and linenumber <= len(lines_list):
                new_text = lines_list[linenumber - 1]

                # Update scriptedit.lines if it exists
                if hasattr(renpy, 'scriptedit') and hasattr(renpy.scriptedit, 'lines'):
                    key = (rel_path, linenumber)
                    if key in renpy.scriptedit.lines:
                        renpy.scriptedit.lines[key].text = new_text.strip()

        except Exception as e:
            print(f"[DAP] Live edit: Error reloading scriptedit: {e}")


# Global instance, initialized when debugger starts
_live_edit_manager: Optional[LiveEditManager] = None


def get_live_edit_manager() -> Optional[LiveEditManager]:
    """Get the global live edit manager instance."""
    return _live_edit_manager


def init_live_edit(debugger: DebuggerCore) -> LiveEditManager:
    """Initialize the live edit manager for a debugger instance."""
    global _live_edit_manager
    _live_edit_manager = LiveEditManager(debugger)
    return _live_edit_manager
