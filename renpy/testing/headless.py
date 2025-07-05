# Copyright 2004-2024 Tom Rothamel <pytom@bishoujo.us>
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
Headless Mode Support

This module provides functionality to run Ren'Py in headless mode for
automated testing environments where no display is available.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import os
import renpy


# Global headless state
_headless_enabled = False
_original_config = {}


def is_headless():
    """
    Check if headless mode is currently enabled.
    
    Returns:
        bool: True if headless mode is enabled
    """
    return _headless_enabled


def enable_headless():
    """
    Enable headless mode for automated testing.
    
    This configures Ren'Py to run without requiring a display,
    using dummy video and audio drivers.
    
    Returns:
        bool: True if headless mode was enabled successfully
    """
    global _headless_enabled, _original_config
    
    try:
        if _headless_enabled:
            return True
        
        # Store original configuration
        _original_config = {
            'SDL_VIDEODRIVER': os.environ.get('SDL_VIDEODRIVER'),
            'SDL_AUDIODRIVER': os.environ.get('SDL_AUDIODRIVER'),
            'config_developer': getattr(renpy.config, 'developer', None),
            'config_debug': getattr(renpy.config, 'debug', None),
            'config_log_to_stdout': getattr(renpy.config, 'log_to_stdout', None),
        }
        
        # Set environment variables for dummy drivers
        os.environ['SDL_VIDEODRIVER'] = 'dummy'
        os.environ['SDL_AUDIODRIVER'] = 'dummy'
        
        # Configure Ren'Py for headless operation
        renpy.config.developer = False
        renpy.config.debug = False
        renpy.config.log_to_stdout = True
        
        # Disable various display-related features
        if hasattr(renpy.config, 'window_show_function'):
            renpy.config.window_show_function = None
        
        if hasattr(renpy.config, 'window_hide_function'):
            renpy.config.window_hide_function = None
        
        # Set fast skipping for automated testing
        renpy.config.skipping = "fast"
        renpy.config.fast_skipping = True
        renpy.config.allow_skipping = True
        
        # Disable transitions for faster execution
        renpy.config.intra_transition = None
        renpy.config.after_load_transition = None
        renpy.config.end_splash_transition = None
        renpy.config.end_game_transition = None
        renpy.config.game_main_transition = None
        renpy.config.main_game_transition = None
        
        # Disable sound and music
        renpy.config.has_sound = False
        renpy.config.has_music = False
        renpy.config.has_voice = False
        
        # Set minimal window size
        renpy.config.screen_width = 800
        renpy.config.screen_height = 600
        
        _headless_enabled = True
        return True
        
    except Exception:
        return False


def disable_headless():
    """
    Disable headless mode and restore original configuration.
    
    Returns:
        bool: True if headless mode was disabled successfully
    """
    global _headless_enabled, _original_config
    
    try:
        if not _headless_enabled:
            return True
        
        # Restore environment variables
        for key, value in _original_config.items():
            if key.startswith('SDL_'):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        
        # Restore Ren'Py configuration
        if 'config_developer' in _original_config and _original_config['config_developer'] is not None:
            renpy.config.developer = _original_config['config_developer']
        
        if 'config_debug' in _original_config and _original_config['config_debug'] is not None:
            renpy.config.debug = _original_config['config_debug']
        
        if 'config_log_to_stdout' in _original_config and _original_config['config_log_to_stdout'] is not None:
            renpy.config.log_to_stdout = _original_config['config_log_to_stdout']
        
        # Reset skipping configuration
        renpy.config.skipping = None
        renpy.config.fast_skipping = False
        
        # Re-enable sound and music
        renpy.config.has_sound = True
        renpy.config.has_music = True
        renpy.config.has_voice = True
        
        _headless_enabled = False
        _original_config = {}
        return True
        
    except Exception:
        return False


def configure_for_testing(enable_auto_advance=False):
    """
    Configure Ren'Py settings optimized for automated testing.

    This can be used even when not in headless mode to speed up testing.

    Args:
        enable_auto_advance (bool): Whether to enable auto-advance mode (default: False)
    """
    try:
        # Enable fast skipping
        renpy.config.allow_skipping = True
        renpy.config.fast_skipping = True

        # Reduce delays
        renpy.config.auto_choice_delay = 0.1
        renpy.config.auto_voice_delay = 0.0

        # Disable unnecessary features for testing
        renpy.config.save_on_mobile_background = False
        renpy.config.autosave_on_choice = False
        renpy.config.autosave_on_quit = False

        # Set preferences for automated testing
        if hasattr(renpy.store, '_preferences'):
            # Only enable auto-advance if explicitly requested
            if enable_auto_advance:
                renpy.store._preferences.afm_enable = True
                renpy.store._preferences.afm_time = 0.1
            else:
                # Explicitly disable auto-advance for HTTP server mode
                renpy.store._preferences.afm_enable = False

            renpy.store._preferences.skip_unseen = True
            renpy.store._preferences.skip_after_choices = True

        return True

    except Exception:
        return False


def is_display_available():
    """
    Check if a display is available for rendering.
    
    Returns:
        bool: True if display is available
    """
    try:
        # Check environment variables
        if os.environ.get('SDL_VIDEODRIVER') == 'dummy':
            return False
        
        # Check if we're in a headless environment
        if os.environ.get('DISPLAY') is None and os.name != 'nt':
            return False
        
        return True
        
    except Exception:
        return False


def get_headless_config():
    """
    Get current headless configuration.
    
    Returns:
        dict: Dictionary containing headless configuration information
    """
    return {
        'enabled': _headless_enabled,
        'display_available': is_display_available(),
        'video_driver': os.environ.get('SDL_VIDEODRIVER'),
        'audio_driver': os.environ.get('SDL_AUDIODRIVER'),
        'config_developer': getattr(renpy.config, 'developer', None),
        'config_debug': getattr(renpy.config, 'debug', None),
        'fast_skipping': getattr(renpy.config, 'fast_skipping', None),
    }


class HeadlessContext(object):
    """
    Context manager for temporarily enabling headless mode.
    """
    
    def __init__(self):
        self.was_headless = False
    
    def __enter__(self):
        self.was_headless = is_headless()
        if not self.was_headless:
            enable_headless()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.was_headless:
            disable_headless()


def headless_context():
    """
    Create a context manager for headless mode.
    
    Returns:
        HeadlessContext: Context manager for headless mode
        
    Example:
        with headless_context():
            # Code runs in headless mode
            pass
    """
    return HeadlessContext()
