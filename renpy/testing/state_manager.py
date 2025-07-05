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
State Manager

This module provides functionality to save, load, export, and import game state
for testing purposes.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
import json
import time
import copy


class StateManager(object):
    """
    Manages game state saving, loading, and export/import functionality.
    """
    
    def __init__(self):
        """Initialize the state manager."""
        self._temp_slot_counter = 0
    
    def save_state(self, slot=None):
        """
        Save current game state to a slot.

        Args:
            slot (str, optional): Save slot name. If None, generates a temporary slot.

        Returns:
            str: The slot name used for saving
        """
        try:
            if slot is None:
                slot = self._generate_temp_slot()

            # Use Ren'Py's built-in save functionality
            # Import the save function from loadsave module
            from renpy.loadsave import save
            save(slot, extra_info="Testing Interface Save")
            return slot

        except Exception as e:
            raise RuntimeError("Failed to save state: {}".format(str(e)))
    
    def load_state(self, slot):
        """
        Load game state from a slot.

        Args:
            slot (str): Save slot name to load from

        Returns:
            bool: True if load was successful
        """
        try:
            # Import the functions from loadsave module
            from renpy.loadsave import can_load, load

            if not can_load(slot):
                print(f"DEBUG: Cannot load slot '{slot}' - slot does not exist")
                return False

            print(f"DEBUG: Loading slot '{slot}'...")
            load(slot)
            print(f"DEBUG: Load completed for slot '{slot}'")
            return True

        except Exception as e:
            print(f"DEBUG: Load failed for slot '{slot}': {e}")
            return False
    
    def export_state(self):
        """
        Export current state data for external analysis.

        Returns:
            dict: Serializable state data
        """
        try:
            # Create a temporary save to extract state data
            temp_slot = self._generate_temp_slot()
            self.save_state(temp_slot)

            # Get the save data
            from renpy.loadsave import get_save_data, unlink_save
            save_data = get_save_data(temp_slot)

            # Clean up temporary save
            try:
                unlink_save(temp_slot)
            except Exception:
                pass
            
            # Convert to serializable format
            exported_data = {
                'timestamp': time.time(),
                'renpy_version': renpy.version,
                'variables': {},
                'metadata': {
                    'slot': temp_slot,
                    'export_time': time.strftime('%Y-%m-%d %H:%M:%S')
                }
            }
            
            # Extract variables from save data
            if save_data:
                for key, value in save_data.items():
                    try:
                        # Try to serialize the value
                        json.dumps(value)
                        exported_data['variables'][key] = value
                    except (TypeError, ValueError):
                        # If not serializable, store string representation
                        exported_data['variables'][key] = str(value)
            
            return exported_data
            
        except Exception as e:
            raise RuntimeError("Failed to export state: {}".format(str(e)))
    
    def import_state(self, state_data):
        """
        Import state data from external source.
        
        Args:
            state_data (dict): State data to import
            
        Returns:
            bool: True if import was successful
        """
        try:
            if not isinstance(state_data, dict):
                return False
            
            variables = state_data.get('variables', {})
            
            # Set variables in the store
            if hasattr(renpy, 'store') and hasattr(renpy.store, 'store'):
                store = renpy.store.store
                for name, value in variables.items():
                    try:
                        setattr(store, name, value)
                    except Exception:
                        # Skip variables that can't be set
                        continue
            
            return True
            
        except Exception:
            return False
    
    def list_saves(self):
        """
        List available save slots.

        Returns:
            list: List of available save slot names
        """
        try:
            saves = []

            # Get list of saved games using the correct import
            from renpy.loadsave import list_saved_games
            saved_games = list_saved_games()

            for save_info in saved_games:
                # save_info is a tuple: (filename, extra_info, screenshot, time)
                if len(save_info) > 0:
                    saves.append(save_info[0])  # filename is the first element

            return saves
            
        except Exception:
            return []
    
    def delete_save(self, slot):
        """
        Delete a save slot.
        
        Args:
            slot (str): Save slot name to delete
            
        Returns:
            bool: True if deletion was successful
        """
        try:
            renpy.unlink_save(slot)
            return True
        except Exception:
            return False
    
    def get_save_info(self, slot):
        """
        Get information about a save slot.
        
        Args:
            slot (str): Save slot name
            
        Returns:
            dict or None: Save information, or None if slot doesn't exist
        """
        try:
            if not renpy.can_load(slot):
                return None
            
            # Get save metadata
            save_json = renpy.slot_json(slot)
            if save_json:
                return {
                    'slot': slot,
                    'timestamp': save_json.get('_save_time', 0),
                    'extra_info': save_json.get('_save_name', ''),
                    'screenshot': save_json.get('_screenshot', None),
                    'version': save_json.get('_renpy_version', ''),
                    'size': len(str(save_json))
                }
            
            return None
            
        except Exception:
            return None
    
    def create_checkpoint(self):
        """
        Create a checkpoint in the current game state.
        
        Returns:
            bool: True if checkpoint was created successfully
        """
        try:
            renpy.checkpoint()
            return True
        except Exception:
            return False
    
    def _generate_temp_slot(self):
        """
        Generate a unique temporary slot name.
        
        Returns:
            str: Temporary slot name
        """
        self._temp_slot_counter += 1
        return "testing_temp_{}".format(self._temp_slot_counter)
    
    def cleanup_temp_saves(self):
        """
        Clean up temporary save slots created by the testing interface.
        
        Returns:
            int: Number of temporary saves cleaned up
        """
        try:
            cleaned = 0
            saves = self.list_saves()
            
            for slot in saves:
                if slot.startswith("testing_temp_"):
                    if self.delete_save(slot):
                        cleaned += 1
            
            return cleaned
            
        except Exception:
            return 0
