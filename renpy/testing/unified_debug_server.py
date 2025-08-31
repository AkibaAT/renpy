"""
Unified Debug Server for Ren'Py

This module provides a unified debug server that combines:
- Debug Adapter Protocol (DAP) server
- HTTP API server for testing and inspection
- WebSocket server for real-time updates
- Automatic port detection and discovery

All servers are started together with a single --debug flag.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode  # *

import json
import os
import socket
import socketserver
import threading
import time
import traceback
import tempfile

try:
    from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs
except ImportError:
    # Python 2 compatibility
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler
    from urlparse import urlparse, parse_qs
    import SocketServer
    class ThreadingHTTPServer(SocketServer.ThreadingMixIn, HTTPServer):
        pass

import renpy

class ChangeTracker:
    """Track runtime changes for later AST application."""

    def __init__(self):
        self.changes = []
        self.change_id_counter = 0

    def add_change(self, change_type, data):
        """Add a change to the tracking list."""
        self.change_id_counter += 1
        change = {
            'id': self.change_id_counter,
            'type': change_type,
            'data': data,
            'timestamp': time.time()
        }
        self.changes.append(change)
        return change

    def get_changes(self):
        """Get all tracked changes."""
        return self.changes.copy()

    def clear_changes(self):
        """Clear all tracked changes."""
        self.changes.clear()
        self.change_id_counter = 0

    def remove_change(self, change_id):
        """Remove a specific change by ID."""
        self.changes = [c for c in self.changes if c['id'] != change_id]

    def get_change_summary(self):
        """Get a summary of changes by type."""
        summary = {}
        for change in self.changes:
            change_type = change['type']
            summary[change_type] = summary.get(change_type, 0) + 1
        return summary

# Import existing server components
from .dap_server import DAPServer, _DAPHandler, _ThreadingTCPServer, _dap_broadcast
from .http_server import TestingAPIHandler, get_openapi_spec


class UnifiedDebugServer(object):
    """
    Unified debug server that manages DAP, HTTP API, and WebSocket servers.
    """
    
    def __init__(self, preferred_ports=None):
        """
        Initialize the unified debug server.
        
        Args:
            preferred_ports: Dict with preferred ports for each service
                           {'dap': 8765, 'http': 8080, 'websocket': 8081}
        """
        self.preferred_ports = preferred_ports or {
            'dap': 8765,
            'http': 8080, 
            'websocket': 8081
        }
        
        # Actual ports assigned after auto-detection
        self.ports = {}
        
        # Server instances
        self.dap_server = None
        self.http_server = None
        self.websocket_server = None
        
        # Threading
        self.dap_thread = None
        self.http_thread = None
        self.websocket_thread = None
        
        # State
        self.running = False
        self.lock = threading.RLock()
        
        # WebSocket clients
        self.websocket_clients = set()
        self.websocket_lock = threading.RLock()

        # Change tracking for AST application
        self.change_tracker = ChangeTracker()
        
        # Debug info file for extension discovery
        self.debug_info_file = None
        
    def find_available_ports(self, preferred_ports):
        """
        Find available ports, starting with preferred ones.
        
        Returns:
            Dict mapping service names to available ports
        """
        available_ports = {}
        
        for service, preferred_port in preferred_ports.items():
            port = self._find_available_port(preferred_port)
            available_ports[service] = port
            
        return available_ports
    
    def _find_available_port(self, start_port, max_attempts=100):
        """Find an available port starting from start_port."""
        for port in range(start_port, start_port + max_attempts):
            if self._is_port_available(port):
                return port
        
        # Fallback to any available port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('localhost', 0))
        port = sock.getsockname()[1]
        sock.close()
        return port
    
    def _is_port_available(self, port):
        """Check if a port is available."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            sock.close()
            return result != 0
        except Exception:
            return False
    
    def start(self):
        """Start all debug servers."""
        with self.lock:
            if self.running:
                return True
                
            try:
                # Find available ports
                self.ports = self.find_available_ports(self.preferred_ports)
                
                # Start DAP server
                self._start_dap_server()
                
                # Start HTTP API server  
                self._start_http_server()
                
                # Start WebSocket server
                self._start_websocket_server()
                
                # Write debug info file for extension discovery
                self._write_debug_info_file()
                
                # Print startup information
                self._print_startup_info()
                
                self.running = True
                return True
                
            except Exception as e:
                print(f"Failed to start unified debug server: {e}")
                traceback.print_exc()
                self.stop()
                return False
    
    def _start_dap_server(self):
        """Start the DAP server."""
        try:
            from renpy.testing import debugger as _dbg
            dbg = _dbg.get_debugger()
            
            # Create DAP server instance
            self.dap_server = DAPServer("127.0.0.1", self.ports['dap'], dbg)
            self.dap_server.start()
            
            # Start TCP server
            tcp_server = _ThreadingTCPServer(("127.0.0.1", self.ports['dap']), _DAPHandler)
            self.dap_thread = threading.Thread(
                target=tcp_server.serve_forever, 
                name="UnifiedDAP-Server", 
                daemon=True
            )
            self.dap_thread.start()
            
            # Store references for cleanup
            setattr(renpy, '_unified_dap_server', self.dap_server)
            setattr(renpy, '_unified_dap_tcp_server', tcp_server)
            
        except Exception as e:
            print(f"Failed to start DAP server: {e}")
            raise
    
    def _start_http_server(self):
        """Start the HTTP API server."""
        try:
            from renpy.testing.interface import TestingInterface
            testing_interface = TestingInterface()
            
            # Create custom handler class with testing interface
            class UnifiedHTTPHandler(TestingAPIHandler):
                def __init__(self, *args, **kwargs):
                    super(UnifiedHTTPHandler, self).__init__(testing_interface, *args, **kwargs)
                    
                def do_GET(self):
                    # Add WebSocket endpoint handling
                    parsed_url = urlparse(self.path)
                    if parsed_url.path in ['/ws', '/websocket']:
                        if self.headers.get('Upgrade', '').lower() == 'websocket':
                            self._handle_websocket_upgrade()
                            return

                    # Add debug server info endpoint
                    if parsed_url.path == '/api/debug/info':
                        self._handle_debug_info()
                        return

                    # Add webview endpoints
                    if parsed_url.path.startswith('/webview/'):
                        self._handle_webview_request()
                        return

                    # Add static file endpoints
                    if parsed_url.path.startswith('/static/'):
                        self._handle_static_request()
                        return

                    # Add image serving endpoints
                    if parsed_url.path.startswith('/api/debug/image/'):
                        self._handle_image_request()
                        return

                    # Delegate to parent
                    super(UnifiedHTTPHandler, self).do_GET()

                def do_POST(self):
                    # Handle POST requests for debug actions
                    parsed_url = urlparse(self.path)

                    if parsed_url.path.startswith('/api/debug/'):
                        self._handle_debug_action()
                        return

                    # Delegate to parent
                    super(UnifiedHTTPHandler, self).do_POST()

                def _handle_debug_action(self):
                    """Handle debug action POST requests."""
                    try:
                        content_length = int(self.headers.get('Content-Length', 0))
                        post_data = self.rfile.read(content_length)
                        data = json.loads(post_data.decode('utf-8'))

                        parsed_url = urlparse(self.path)
                        action_path = parsed_url.path

                        result = None

                        if action_path == '/api/debug/move-object':
                            result = self._handle_move_object(data)
                        elif action_path == '/api/debug/toggle-object':
                            result = self._handle_toggle_object(data)
                        elif action_path == '/api/debug/action':
                            result = self._handle_generic_action(data)
                        elif action_path.startswith('/api/debug/scene/'):
                            result = self._handle_scene_action(action_path, data)
                        elif action_path.startswith('/api/debug/audio/'):
                            result = self._handle_audio_action(action_path, data)
                        elif action_path.startswith('/api/debug/script/'):
                            result = self._handle_script_action(action_path, data)
                        elif action_path == '/api/debug/get-attributes':
                            result = self._handle_get_attributes(data)
                        elif action_path.startswith('/api/debug/transform/'):
                            result = self._handle_transform_action(action_path, data)
                        elif action_path == '/api/debug/set-position':
                            result = self._handle_set_position(data)
                        elif action_path == '/api/debug/set-properties':
                            result = self._handle_set_properties(data)
                        elif action_path == '/api/debug/get-scene-render-data':
                            result = self._handle_get_scene_render_data(data)
                        elif action_path == '/api/debug/get-assets':
                            result = self._handle_get_assets(data)
                        else:
                            self._send_error(404, "Action not found")
                            return

                        # Send success response
                        self._send_json_response({'success': True, 'result': result})

                        # Broadcast update to WebSocket clients with fresh scene data
                        unified_server = self.server.unified_server
                        if unified_server:
                            # Get fresh scene data for broadcast
                            try:
                                from renpy.testing.state_inspector import StateInspector
                                inspector = StateInspector()
                                fresh_scene_data = inspector.get_scene_info()
                            except Exception:
                                fresh_scene_data = {}

                            unified_server.broadcast_websocket_message({
                                'type': 'scene_update',
                                'action': action_path,
                                'data': data,
                                'scene_data': fresh_scene_data,
                                'timestamp': time.time()
                            })

                    except Exception as e:
                        # Always send JSON error response for API endpoints
                        import traceback
                        error_details = traceback.format_exc()
                        print(f"Debug action error: {e}")
                        print(error_details)
                        self._send_json_response({
                            'success': False,
                            'error': str(e),
                            'details': error_details
                        })

                def _handle_move_object(self, data):
                    """Handle move object action."""
                    try:
                        # Use DAP server functionality if available
                        from renpy.testing import debugger as _dbg
                        dbg = _dbg.get_debugger()

                        if dbg and hasattr(dbg, 'set_image_position'):
                            dbg.set_image_position(
                                tag=data.get('tag'),
                                layer=data.get('layer', 'master'),
                                xpos=data.get('x', 0),
                                ypos=data.get('y', 0)
                            )
                            return {'moved': True}
                        else:
                            # Fallback to direct Ren'Py calls
                            import renpy
                            tag = data.get('tag')
                            layer = data.get('layer', 'master')
                            x = data.get('x', 0)
                            y = data.get('y', 0)

                            # Try to move the object
                            renpy.show_layer_at([renpy.Transform(xpos=x, ypos=y)], layer=layer, tag=tag)
                            return {'moved': True, 'fallback': True}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_toggle_object(self, data):
                    """Handle show/hide object action."""
                    try:
                        action = data.get('action', 'show')
                        tag = data.get('tag')
                        layer = data.get('layer', 'master')

                        import renpy

                        if action == 'hide':
                            renpy.hide(tag, layer=layer)
                        else:
                            # For show, we need an image name
                            name = data.get('name', tag)
                            renpy.show(name, tag=tag, layer=layer)

                        return {'action': action, 'tag': tag, 'layer': layer}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_generic_action(self, data):
                    """Handle generic debug actions."""
                    try:
                        action = data.get('action')

                        if action == 'refresh_scene':
                            # Trigger scene refresh
                            return {'refreshed': True}
                        elif action == 'get_scene_info':
                            from renpy.testing.state_inspector import StateInspector
                            inspector = StateInspector()
                            return inspector.get_scene_info()
                        elif action == 'hide_screen':
                            screen_name = data.get('screen')
                            if screen_name:
                                renpy.hide_screen(screen_name)
                                return {'action': 'hide_screen', 'screen': screen_name}
                            else:
                                return {'error': 'Screen name is required'}
                        elif action == 'clear_changes':
                            unified_server = self.server.unified_server
                            if unified_server:
                                unified_server.change_tracker.clear_changes()
                                return {'action': 'clear_changes', 'success': True}
                            else:
                                return {'error': 'Server not available'}
                        elif action == 'get_scene_render_data':
                            return self._handle_get_scene_render_data(data)
                        elif action == 'get_assets':
                            return self._handle_get_assets(data)
                        else:
                            return {'error': f'Unknown action: {action}'}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_scene_action(self, action_path, data):
                    """Handle scene manipulation actions (show, hide, scene)."""
                    try:
                        action = action_path.split('/')[-1]  # Extract action from path
                        tag = data.get('tag')
                        attributes = data.get('attributes', [])
                        transforms = data.get('transforms', [])
                        behind = data.get('behind', [])
                        layer = data.get('layer', 'master')

                        if not tag and action != 'scene':
                            return {'error': 'Tag is required for this action'}

                        if action == 'show':
                            # Build image name with attributes
                            image_name = [tag] + attributes

                            # Apply transforms
                            at_list = []
                            for transform in transforms:
                                try:
                                    # Get transform object
                                    transform_obj = getattr(renpy.store, transform, None)
                                    if transform_obj:
                                        at_list.append(transform_obj)
                                except Exception:
                                    pass

                            # Show the image
                            if behind:
                                renpy.show(' '.join(image_name), at_list=at_list, behind=behind, layer=layer)
                            else:
                                renpy.show(' '.join(image_name), at_list=at_list, layer=layer)

                            # Track the change
                            unified_server = self.server.unified_server
                            if unified_server:
                                unified_server.change_tracker.add_change('show', {
                                    'tag': tag,
                                    'attributes': attributes,
                                    'transforms': transforms,
                                    'behind': behind,
                                    'layer': layer
                                })

                            return {
                                'action': 'show',
                                'tag': tag,
                                'attributes': attributes,
                                'transforms': transforms,
                                'behind': behind,
                                'layer': layer
                            }

                        elif action == 'hide':
                            renpy.hide(tag, layer=layer)

                            # Track the change
                            unified_server = self.server.unified_server
                            if unified_server:
                                unified_server.change_tracker.add_change('hide', {
                                    'tag': tag,
                                    'layer': layer
                                })

                            return {'action': 'hide', 'tag': tag, 'layer': layer}

                        elif action == 'scene':
                            if tag:
                                # Scene with image
                                image_name = [tag] + attributes
                                at_list = []
                                for transform in transforms:
                                    try:
                                        transform_obj = getattr(renpy.store, transform, None)
                                        if transform_obj:
                                            at_list.append(transform_obj)
                                    except Exception:
                                        pass
                                renpy.scene(layer=layer)
                                renpy.show(' '.join(image_name), at_list=at_list, layer=layer)
                            else:
                                # Clear scene
                                renpy.scene(layer=layer)

                            # Track the change
                            unified_server = self.server.unified_server
                            if unified_server:
                                unified_server.change_tracker.add_change('scene', {
                                    'tag': tag,
                                    'attributes': attributes,
                                    'transforms': transforms,
                                    'layer': layer
                                })

                            return {
                                'action': 'scene',
                                'tag': tag,
                                'attributes': attributes,
                                'transforms': transforms,
                                'layer': layer
                            }
                        else:
                            return {'error': f'Unknown scene action: {action}'}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_audio_action(self, action_path, data):
                    """Handle audio control actions (play, stop, queue)."""
                    try:
                        action = action_path.split('/')[-1]  # Extract action from path
                        channel = data.get('channel', 'music')
                        filename = data.get('filename')

                        if action in ['play', 'queue'] and not filename:
                            return {'error': 'Filename is required for play/queue actions'}

                        if action == 'play':
                            renpy.music.play(filename, channel=channel)
                            return {'action': 'play', 'channel': channel, 'filename': filename}

                        elif action == 'stop':
                            renpy.music.stop(channel=channel)
                            return {'action': 'stop', 'channel': channel}

                        elif action == 'queue':
                            renpy.music.queue(filename, channel=channel)
                            return {'action': 'queue', 'channel': channel, 'filename': filename}

                        else:
                            return {'error': f'Unknown audio action: {action}'}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_get_attributes(self, data):
                    """Get available attributes for a specific tag."""
                    try:
                        tag = data.get('tag')
                        if not tag:
                            return {'error': 'Tag is required'}

                        from renpy.testing.state_inspector import StateInspector
                        inspector = StateInspector()
                        attributes = inspector.get_image_attributes(tag)
                        behind_tags = inspector.get_behind_tags(tag)

                        return {
                            'tag': tag,
                            'attributes': attributes,
                            'behind_tags': behind_tags
                        }

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_transform_action(self, action_path, data):
                    """Handle transform-related actions."""
                    try:
                        action = action_path.split('/')[-1]  # Extract action from path
                        tag = data.get('tag')

                        if not tag:
                            return {'error': 'Tag is required for transform actions'}

                        if action == 'apply':
                            transform_name = data.get('transform')
                            if not transform_name:
                                return {'error': 'Transform name is required'}

                            # Apply transform to existing image
                            try:
                                transform_obj = getattr(renpy.store, transform_name, None)
                                if transform_obj:
                                    renpy.show(tag, at_list=[transform_obj])
                                    return {'action': 'apply_transform', 'tag': tag, 'transform': transform_name}
                                else:
                                    return {'error': f'Transform "{transform_name}" not found'}
                            except Exception as e:
                                return {'error': f'Failed to apply transform: {str(e)}'}

                        elif action == 'reset':
                            # Reset to default position
                            renpy.show(tag)
                            return {'action': 'reset_transform', 'tag': tag}

                        else:
                            return {'error': f'Unknown transform action: {action}'}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_set_position(self, data):
                    """Handle setting object position."""
                    try:
                        tag = data.get('tag')
                        x = data.get('x')
                        y = data.get('y')

                        if not tag:
                            return {'error': 'Tag is required'}

                        if x is None or y is None:
                            return {'error': 'Both x and y coordinates are required'}

                        # Create a position transform
                        position_transform = renpy.store.Transform(xpos=x, ypos=y)
                        renpy.show(tag, at_list=[position_transform])

                        return {'action': 'set_position', 'tag': tag, 'x': x, 'y': y}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_set_properties(self, data):
                    """Handle setting object properties (alpha, zoom, etc.)."""
                    try:
                        tag = data.get('tag')
                        properties = data.get('properties', {})

                        if not tag:
                            return {'error': 'Tag is required'}

                        if not properties:
                            return {'error': 'Properties are required'}

                        # Create transform with specified properties
                        transform_kwargs = {}

                        # Map common properties
                        if 'alpha' in properties:
                            transform_kwargs['alpha'] = float(properties['alpha'])
                        if 'zoom' in properties:
                            transform_kwargs['zoom'] = float(properties['zoom'])
                        if 'xpos' in properties:
                            transform_kwargs['xpos'] = int(properties['xpos'])
                        if 'ypos' in properties:
                            transform_kwargs['ypos'] = int(properties['ypos'])
                        if 'xalign' in properties:
                            transform_kwargs['xalign'] = float(properties['xalign'])
                        if 'yalign' in properties:
                            transform_kwargs['yalign'] = float(properties['yalign'])
                        if 'rotate' in properties:
                            transform_kwargs['rotate'] = float(properties['rotate'])

                        if transform_kwargs:
                            property_transform = renpy.store.Transform(**transform_kwargs)
                            renpy.show(tag, at_list=[property_transform])

                            return {
                                'action': 'set_properties',
                                'tag': tag,
                                'properties': transform_kwargs
                            }
                        else:
                            return {'error': 'No valid properties provided'}

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_script_action(self, action_path, data):
                    """Handle AST script editing actions."""
                    try:
                        action = action_path.split('/')[-1]  # Extract action from path

                        if action == 'add-statement':
                            return self._add_statement_to_ast(data)
                        elif action == 'commit-changes':
                            return self._commit_changes_to_ast(data)
                        elif action == 'rollback':
                            return self._rollback_changes(data)
                        elif action == 'get-changes':
                            return self._get_pending_changes(data)
                        elif action == 'preview-changes':
                            return self._preview_changes(data)
                        else:
                            return {'error': f'Unknown script action: {action}'}

                    except Exception as e:
                        return {'error': str(e)}

                def _add_statement_to_ast(self, data):
                    """Add a statement to the AST."""
                    try:
                        statement = data.get('statement')
                        filename = data.get('filename')
                        line_number = data.get('line_number')

                        if not statement:
                            return {'error': 'Statement is required'}
                        if not filename:
                            return {'error': 'Filename is required'}
                        if line_number is None:
                            return {'error': 'Line number is required'}

                        # Use renpy.scriptedit to add statement
                        renpy.scriptedit.add_to_ast_before(statement, filename, line_number)

                        return {
                            'action': 'add_statement',
                            'statement': statement,
                            'filename': filename,
                            'line_number': line_number,
                            'success': True
                        }

                    except Exception as e:
                        return {'error': f'Failed to add statement: {str(e)}'}

                def _commit_changes_to_ast(self, data):
                    """Commit current runtime changes to AST."""
                    try:
                        changes = data.get('changes', [])
                        filename = data.get('filename', 'game/script.rpy')
                        line_number = data.get('line_number')

                        if not changes:
                            return {'error': 'No changes to commit'}

                        committed_changes = []

                        for change in changes:
                            change_type = change.get('type')

                            if change_type == 'show':
                                statement = self._build_show_statement(change)
                            elif change_type == 'hide':
                                statement = self._build_hide_statement(change)
                            elif change_type == 'scene':
                                statement = self._build_scene_statement(change)
                            elif change_type == 'audio':
                                statement = self._build_audio_statement(change)
                            else:
                                continue

                            if statement:
                                # Add statement to AST
                                target_line = line_number if line_number is not None else self._find_insertion_point(filename)
                                renpy.scriptedit.add_to_ast_before(statement, filename, target_line)

                                committed_changes.append({
                                    'type': change_type,
                                    'statement': statement,
                                    'line': target_line
                                })

                        # Force rollback to apply changes
                        if committed_changes:
                            renpy.rollback(checkpoints=0, force=True, greedy=True)

                        return {
                            'action': 'commit_changes',
                            'committed': committed_changes,
                            'filename': filename,
                            'success': True
                        }

                    except Exception as e:
                        return {'error': f'Failed to commit changes: {str(e)}'}

                def _rollback_changes(self, data):
                    """Rollback AST changes."""
                    try:
                        # Force rollback to previous state
                        renpy.rollback(checkpoints=0, force=True, greedy=True)

                        return {
                            'action': 'rollback',
                            'success': True
                        }

                    except Exception as e:
                        return {'error': f'Failed to rollback: {str(e)}'}

                def _get_pending_changes(self, data):
                    """Get list of pending changes that can be committed."""
                    try:
                        unified_server = self.server.unified_server
                        if unified_server:
                            changes = unified_server.change_tracker.get_changes()
                            summary = unified_server.change_tracker.get_change_summary()

                            return {
                                'action': 'get_changes',
                                'changes': changes,
                                'count': len(changes),
                                'summary': summary
                            }
                        else:
                            return {
                                'action': 'get_changes',
                                'changes': [],
                                'count': 0,
                                'summary': {}
                            }

                    except Exception as e:
                        return {'error': str(e)}

                def _preview_changes(self, data):
                    """Preview what changes would be made to the script."""
                    try:
                        changes = data.get('changes', [])

                        preview = []
                        for change in changes:
                            change_type = change.get('type')

                            if change_type == 'show':
                                statement = self._build_show_statement(change)
                            elif change_type == 'hide':
                                statement = self._build_hide_statement(change)
                            elif change_type == 'scene':
                                statement = self._build_scene_statement(change)
                            elif change_type == 'audio':
                                statement = self._build_audio_statement(change)
                            else:
                                continue

                            if statement:
                                preview.append({
                                    'type': change_type,
                                    'statement': statement,
                                    'description': self._describe_change(change)
                                })

                        return {
                            'action': 'preview_changes',
                            'preview': preview,
                            'count': len(preview)
                        }

                    except Exception as e:
                        return {'error': str(e)}

                def _build_show_statement(self, change):
                    """Build a show statement from change data."""
                    try:
                        tag = change.get('tag')
                        attributes = change.get('attributes', [])
                        transforms = change.get('transforms', [])
                        behind = change.get('behind', [])

                        if not tag:
                            return None

                        # Build show statement
                        parts = ['show', tag]

                        # Add attributes
                        if attributes:
                            parts.extend(attributes)

                        # Add transforms
                        if transforms:
                            parts.append('at')
                            parts.extend(transforms)

                        # Add behind
                        if behind:
                            parts.append('behind')
                            parts.extend(behind)

                        return ' '.join(parts)

                    except Exception:
                        return None

                def _build_hide_statement(self, change):
                    """Build a hide statement from change data."""
                    try:
                        tag = change.get('tag')

                        if not tag:
                            return None

                        return f'hide {tag}'

                    except Exception:
                        return None

                def _build_scene_statement(self, change):
                    """Build a scene statement from change data."""
                    try:
                        tag = change.get('tag')
                        attributes = change.get('attributes', [])
                        transforms = change.get('transforms', [])

                        if not tag:
                            return 'scene'

                        # Build scene statement
                        parts = ['scene', tag]

                        # Add attributes
                        if attributes:
                            parts.extend(attributes)

                        # Add transforms
                        if transforms:
                            parts.append('at')
                            parts.extend(transforms)

                        return ' '.join(parts)

                    except Exception:
                        return None

                def _build_audio_statement(self, change):
                    """Build an audio statement from change data."""
                    try:
                        action = change.get('action')
                        channel = change.get('channel', 'music')
                        filename = change.get('filename')

                        if action == 'play' and filename:
                            return f'play {channel} "{filename}"'
                        elif action == 'stop':
                            return f'stop {channel}'
                        elif action == 'queue' and filename:
                            return f'queue {channel} "{filename}"'

                        return None

                    except Exception:
                        return None

                def _find_insertion_point(self, filename):
                    """Find a good insertion point in the script file."""
                    try:
                        # Get current line from renpy context
                        current_line = renpy.get_filename_line()
                        if current_line and current_line[0] == filename:
                            return current_line[1]

                        # Default to end of file
                        return 1000  # Large number to append at end

                    except Exception:
                        return 1000

                def _describe_change(self, change):
                    """Create a human-readable description of a change."""
                    try:
                        change_type = change.get('type')

                        if change_type == 'show':
                            tag = change.get('tag')
                            attributes = change.get('attributes', [])
                            if attributes:
                                return f'Show {tag} with attributes: {", ".join(attributes)}'
                            else:
                                return f'Show {tag}'

                        elif change_type == 'hide':
                            tag = change.get('tag')
                            return f'Hide {tag}'

                        elif change_type == 'scene':
                            tag = change.get('tag')
                            if tag:
                                return f'Scene with {tag}'
                            else:
                                return 'Clear scene'

                        elif change_type == 'audio':
                            action = change.get('action')
                            channel = change.get('channel')
                            filename = change.get('filename')
                            if action == 'play':
                                return f'Play {filename} on {channel}'
                            elif action == 'stop':
                                return f'Stop {channel}'
                            elif action == 'queue':
                                return f'Queue {filename} on {channel}'

                        return f'Unknown change: {change_type}'

                    except Exception:
                        return 'Unknown change'

                def _handle_get_scene_render_data(self, data):
                    """Get scene rendering data for visual scene builder."""
                    try:
                        # Try to get real scene data
                        try:
                            from renpy.testing.state_inspector import StateInspector
                            inspector = StateInspector()
                            scene_data = inspector.get_scene_info()
                        except Exception as e:
                            print(f"Warning: Could not get scene data from StateInspector: {e}")
                            scene_data = {'shown_images': [], 'shown_screens': []}

                        # Get actual game resolution with fallback
                        try:
                            import renpy
                            game_width = renpy.config.screen_width
                            game_height = renpy.config.screen_height
                        except Exception:
                            # Fallback to common resolution
                            game_width = 1920
                            game_height = 1080

                        # Build render data with positions and visual info
                        render_data = {
                            'scene_size': {'width': game_width, 'height': game_height},
                            'objects': [],
                            'backgrounds': [],
                            'screens': []
                        }

                        # Process shown images with proper layering and positioning
                        for img in scene_data.get('shown_images', []):
                            obj_data = self._build_object_render_data(img, game_width, game_height)
                            if obj_data:
                                # Proper layer classification
                                layer = obj_data.get('layer', 'master')
                                obj_type = obj_data.get('type', 'unknown')

                                if layer == 'master':
                                    if obj_type == 'background':
                                        render_data['backgrounds'].append(obj_data)
                                    else:
                                        render_data['objects'].append(obj_data)
                                else:
                                    render_data['backgrounds'].append(obj_data)

                        # Process active screens
                        for screen in scene_data.get('active_screens', []):
                            screen_data = self._build_screen_render_data(screen, game_width, game_height)
                            if screen_data:
                                render_data['screens'].append(screen_data)

                        # If no scene data, add some sample objects for testing
                        if not render_data['objects'] and not render_data['backgrounds']:
                            render_data['backgrounds'].append({
                                'id': 'sample_bg',
                                'tag': 'bg',
                                'name': 'Sample Background',
                                'type': 'background',
                                'position': {'x': 0, 'y': 0},
                                'size': {'width': game_width, 'height': game_height},
                                'color': '#99ccff',
                                'draggable': False,
                                'z_index': 1
                            })
                            render_data['objects'].append({
                                'id': 'sample_char',
                                'tag': 'eileen',
                                'name': 'Sample Character',
                                'type': 'character',
                                'position': {'x': game_width//2 - 100, 'y': game_height//2 - 150},
                                'size': {'width': 200, 'height': 300},
                                'color': '#ff9999',
                                'draggable': True,
                                'z_index': 100
                            })

                        return {
                            'action': 'get_scene_render_data',
                            'render_data': render_data,
                            'success': True
                        }

                    except Exception as e:
                        return {'error': str(e)}

                def _handle_get_assets(self, data):
                    """Get available assets for asset browser."""
                    try:
                        asset_type = data.get('type', 'all')  # 'images', 'audio', 'all'

                        assets = {
                            'images': self._get_image_assets(),
                            'audio': self._get_audio_assets(),
                            'backgrounds': self._get_background_assets()
                        }

                        if asset_type != 'all':
                            assets = {asset_type: assets.get(asset_type, [])}

                        return {
                            'action': 'get_assets',
                            'assets': assets,
                            'success': True
                        }

                    except Exception as e:
                        return {'error': str(e)}

                def _build_object_render_data(self, img, game_width, game_height):
                    """Build render data for a scene object with real positioning."""
                    try:
                        name = img.get('name', 'Unknown')
                        tag = img.get('tag', name)
                        layer = img.get('layer', 'master')

                        # Get real position and size from Ren'Py's display system
                        position, size = self._get_real_object_transform(tag, layer, game_width, game_height)

                        # Determine object type and color
                        obj_type, color = self._classify_object(tag, name)

                        # Default hide certain UI elements
                        default_hidden = tag in ['quick_menu', 'say'] or layer == 'screens'

                        return {
                            'id': f"{layer}_{tag}",
                            'tag': tag,
                            'name': name,
                            'layer': layer,
                            'type': obj_type,
                            'position': position,
                            'size': size,
                            'color': color,
                            'attributes': img.get('attributes', []),
                            'transforms': img.get('transforms', []),
                            'draggable': True,
                            'z_index': self._get_layer_z_index(layer, obj_type),
                            'visible': not default_hidden,
                            'image_url': self._build_image_url(tag, img, layer),
                            'image_name': img.get('image_name', tag)  # Include full image name for better lookup
                        }

                    except Exception:
                        return None

                def _get_real_object_transform(self, tag, layer, game_width, game_height):
                    """Get real position and size from Ren'Py's display system."""
                    try:
                        import renpy

                        # Method 1: Try to get from current scene list
                        try:
                            scene_lists = renpy.game.context().scene_lists
                            if hasattr(scene_lists, layer):
                                scene_list = getattr(scene_lists, layer)

                                # Look for the tag in the scene list
                                if hasattr(scene_list, 'layers'):
                                    for layer_item in scene_list.layers:
                                        if hasattr(layer_item, 'tag') and layer_item.tag == tag:
                                            displayable = layer_item.displayable
                                            if displayable:
                                                # Get actual rendered size using multiple methods
                                                width, height = self._extract_displayable_size(displayable)
                                                x, y = self._extract_displayable_position(displayable, game_width, game_height)

                                                if width and height:
                                                    return {'x': x, 'y': y}, {'width': width, 'height': height}
                        except Exception as e:
                            print(f"Method 1 failed: {e}")

                        # Method 2: Try to get from image registry using the image name
                        try:
                            if hasattr(renpy, 'display') and hasattr(renpy.display, 'image'):
                                images = renpy.display.image.images
                                # Try different name formats
                                possible_names = [
                                    tag,
                                    (tag,),
                                    (tag, 'happy'),  # Common default
                                    (tag, 'normal'), # Common default
                                ]

                                for name in possible_names:
                                    if name in images:
                                        displayable = images[name]
                                        if displayable:
                                            width, height = self._extract_displayable_size(displayable)
                                            x, y = self._extract_displayable_position(displayable, game_width, game_height)

                                            if width and height:
                                                print(f"Got size from image registry for {tag}: {width}x{height}")
                                                return {'x': x, 'y': y}, {'width': width, 'height': height}
                                        break
                        except Exception as e:
                            print(f"Method 2 failed: {e}")

                        # Method 3: Try to render the displayable to get its actual size
                        try:
                            # Get the displayable from the scene list or image registry
                            displayable = None

                            # Try to get from scene list first
                            if hasattr(renpy, 'game') and hasattr(renpy.game, 'context'):
                                context = renpy.game.context()
                                if hasattr(context, 'scene_lists') and layer in context.scene_lists:
                                    scene_list = context.scene_lists[layer]
                                    for layer_item in scene_list.layers:
                                        if hasattr(layer_item, 'tag') and layer_item.tag == tag:
                                            displayable = layer_item.displayable
                                            break

                            # Try to get from image registry if not found in scene
                            if not displayable and hasattr(renpy, 'display') and hasattr(renpy.display, 'image'):
                                try:
                                    # Try to get the image definition
                                    if hasattr(renpy.display.image, 'images'):
                                        images = renpy.display.image.images
                                        if tag in images:
                                            displayable = images[tag]
                                        elif (tag,) in images:
                                            displayable = images[(tag,)]
                                except:
                                    pass

                            if displayable and hasattr(renpy, 'display') and hasattr(renpy.display, 'render'):
                                # Render the displayable to get its actual size
                                render_obj = renpy.display.render.render(displayable, game_width, game_height, 0, 0)
                                if render_obj and hasattr(render_obj, 'width') and hasattr(render_obj, 'height'):
                                    width = int(render_obj.width)
                                    height = int(render_obj.height)
                                    x, y = self._extract_displayable_position(displayable, game_width, game_height)

                                    if width > 0 and height > 0:
                                        print(f"SUCCESS: Got actual rendered size for {tag}: {width}x{height} at ({x}, {y})")
                                        return {'x': x, 'y': y}, {'width': width, 'height': height}
                        except Exception as e:
                            print(f"Method 3 (render) failed for {tag}: {e}")

                        # Fallback to smart defaults based on tag and type
                        return self._get_smart_default_transform(tag, game_width, game_height)

                    except Exception:
                        return self._get_smart_default_transform(tag, game_width, game_height)

                def _extract_displayable_size(self, displayable):
                    """Extract the actual rendered size from a displayable."""
                    try:
                        # Method 1: Try to render the displayable to get actual size
                        try:
                            import renpy
                            if hasattr(renpy, 'display') and hasattr(renpy.display, 'render'):
                                # Use a reasonable size for rendering
                                render_obj = renpy.display.render.render(displayable, 1920, 1080, 0, 0)
                                if render_obj and hasattr(render_obj, 'width') and hasattr(render_obj, 'height'):
                                    width = int(render_obj.width)
                                    height = int(render_obj.height)
                                    if width > 0 and height > 0:
                                        print(f"Extracted size via render: {width}x{height}")
                                        return width, height
                        except Exception as e:
                            print(f"Render method failed: {e}")

                        # Method 2: Try get_size()
                        if hasattr(displayable, 'get_size'):
                            size = displayable.get_size()
                            if size and len(size) >= 2:
                                return int(size[0]), int(size[1])

                        # Method 3: Try width/height attributes
                        if hasattr(displayable, 'width') and hasattr(displayable, 'height'):
                            width = getattr(displayable, 'width', None)
                            height = getattr(displayable, 'height', None)
                            if width and height:
                                return int(width), int(height)

                        # Method 4: Try to get from child displayable
                        child = getattr(displayable, 'child', None)
                        if child:
                            return self._extract_displayable_size(child)

                        # Method 5: Try to get from image/texture
                        if hasattr(displayable, 'load'):
                            try:
                                surf = displayable.load()
                                if surf and hasattr(surf, 'get_size'):
                                    return surf.get_size()
                            except:
                                pass

                        return None, None
                    except Exception:
                        return None, None

                def _extract_displayable_position(self, displayable, game_width, game_height):
                    """Extract position from displayable transform."""
                    try:
                        x, y = None, None

                        # Try to get transform properties
                        transform = getattr(displayable, 'transform', None)
                        if transform:
                            x = getattr(transform, 'xpos', None) or getattr(transform, 'pos', (None, None))[0]
                            y = getattr(transform, 'ypos', None) or getattr(transform, 'pos', (None, None))[1]

                        # Try alternative methods
                        if x is None and hasattr(displayable, 'xpos'):
                            x = displayable.xpos
                        if y is None and hasattr(displayable, 'ypos'):
                            y = displayable.ypos

                        # Convert relative positions to absolute
                        if x is not None:
                            if isinstance(x, float) and x <= 1.0:
                                x = int(x * game_width)
                        else:
                            x = game_width // 2  # Center default

                        if y is not None:
                            if isinstance(y, float) and y <= 1.0:
                                y = int(y * game_height)
                        else:
                            y = game_height // 2  # Center default

                        return x, y
                    except Exception:
                        return game_width // 2, game_height // 2

                def _build_image_url(self, tag, img, layer):
                    """Build the proper image URL with attributes."""
                    try:
                        # Try to extract attribute from the image name
                        name_tuple = img.get('name')
                        if name_tuple and isinstance(name_tuple, tuple) and len(name_tuple) >= 2:
                            # For ('bg', 'washington') -> /api/debug/image/bg/washington/master
                            # For ('eileen', 'happy') -> /api/debug/image/eileen/happy/master
                            attribute = name_tuple[1]
                            return f"/api/debug/image/{tag}/{attribute}/{layer}"

                        # Fallback to old format
                        return f"/api/debug/image/{tag}/{layer}"
                    except Exception as e:
                        print(f"Error building image URL for {tag}: {e}")
                        return f"/api/debug/image/{tag}/{layer}"

                def _get_smart_default_transform(self, tag, game_width, game_height):
                    """Get smart default position and size based on tag."""
                    # Background images
                    if any(bg in tag.lower() for bg in ['bg', 'background', 'scene']):
                        print(f"Using background defaults for {tag}: {game_width}x{game_height}")
                        return {'x': 0, 'y': 0}, {'width': game_width, 'height': game_height}

                    # Character positions based on common transforms
                    if 'left' in tag.lower():
                        x = game_width // 4
                    elif 'right' in tag.lower():
                        x = (game_width * 3) // 4
                    else:
                        x = game_width // 2  # center

                    y = game_height - 200  # Bottom aligned for characters

                    # Character size - try to make it more realistic
                    # Characters are typically much larger than 300x400
                    # Based on common Ren'Py character sizes
                    width = 800   # More realistic character width
                    height = 1200 # More realistic character height

                    print(f"Using character defaults for {tag}: {width}x{height} at ({x}, {y})")
                    return {'x': x, 'y': y}, {'width': width, 'height': height}

                def _get_layer_z_index(self, layer, obj_type):
                    """Get z-index for proper layering."""
                    layer_z = {
                        'master': 100,
                        'screens': 200,
                        'overlay': 300,
                        'transient': 150
                    }

                    base_z = layer_z.get(layer, 100)

                    # Background objects should be behind characters
                    if obj_type == 'background':
                        return base_z - 50
                    elif obj_type == 'character':
                        return base_z + 10
                    else:
                        return base_z

                def _build_screen_render_data(self, screen, game_width, game_height):
                    """Build render data for a screen."""
                    try:
                        if isinstance(screen, str):
                            name = screen
                        else:
                            name = screen.get('name', 'Unknown')

                        return {
                            'id': f"screen_{name}",
                            'name': name,
                            'type': 'screen',
                            'position': {'x': 0, 'y': 0},
                            'size': {'width': game_width, 'height': game_height},
                            'color': '#e0e0e0',
                            'draggable': False,
                            'z_index': 200  # Screens on top
                        }

                    except Exception:
                        return None

                def _get_object_position(self, tag):
                    """Get current position of an object."""
                    try:
                        # Try to get position from Ren'Py's display system
                        # This is a simplified approach - in reality we'd need to
                        # access the displayable's transform properties

                        # Default positions based on common transforms
                        default_positions = {
                            'left': {'x': 300, 'y': 500},
                            'center': {'x': 960, 'y': 500},
                            'right': {'x': 1620, 'y': 500}
                        }

                        # For now, return center position
                        # TODO: Integrate with actual Ren'Py transform system
                        return {'x': 960, 'y': 500}

                    except Exception:
                        return {'x': 960, 'y': 500}

                def _classify_object(self, tag, name):
                    """Classify object type and assign color."""
                    try:
                        # Common character/object classification
                        if any(char in tag.lower() for char in ['eileen', 'lucy', 'character', 'char']):
                            return 'character', '#ff9999'
                        elif any(bg in tag.lower() for bg in ['bg', 'background', 'scene']):
                            return 'background', '#99ccff'
                        elif any(obj in tag.lower() for obj in ['prop', 'object', 'item']):
                            return 'prop', '#99ff99'
                        else:
                            return 'unknown', '#cccccc'

                    except Exception:
                        return 'unknown', '#cccccc'

                def _get_image_assets(self):
                    """Get available image assets."""
                    try:
                        assets = []

                        # Try to get available image tags from Ren'Py
                        try:
                            import renpy

                            # Try different methods to get image data
                            image_tags = []

                            # Method 1: Try get_available_image_tags (newer versions)
                            if hasattr(renpy, 'get_available_image_tags'):
                                image_tags = renpy.get_available_image_tags()
                            # Method 2: Try accessing image registry directly
                            elif hasattr(renpy, 'display') and hasattr(renpy.display, 'image'):
                                try:
                                    image_tags = list(renpy.display.image.images.keys())
                                except:
                                    pass
                            # Method 3: Try config.images
                            elif hasattr(renpy, 'config') and hasattr(renpy.config, 'images'):
                                try:
                                    image_tags = list(renpy.config.images.keys())
                                except:
                                    pass

                            for tag in image_tags:
                                if isinstance(tag, tuple):
                                    tag = tag[0]  # Take first part if it's a tuple
                                if str(tag).startswith('_'):
                                    continue  # Skip internal tags

                                # Get attributes for this tag
                                try:
                                    if hasattr(renpy, 'get_ordered_image_attributes'):
                                        attributes = renpy.get_ordered_image_attributes(tag, [])
                                    else:
                                        attributes = []
                                except:
                                    attributes = []

                                asset = {
                                    'tag': str(tag),
                                    'name': str(tag).title(),
                                    'type': 'character' if any(char in str(tag).lower() for char in ['eileen', 'lucy', 'character']) else 'image',
                                    'attributes': attributes,
                                    'thumbnail': f'/api/debug/thumbnail/{tag}',  # TODO: Implement thumbnail endpoint
                                    'category': self._categorize_asset(str(tag))
                                }
                                assets.append(asset)
                        except Exception as e:
                            print(f"Warning: Could not get image assets from Ren'Py: {e}")
                            # If get_available_image_tags fails, get assets from current scene
                            from renpy.testing.state_inspector import StateInspector
                            inspector = StateInspector()
                            scene_data = inspector.get_scene_info()

                            # Extract unique tags from current scene
                            seen_tags = set()
                            for img in scene_data.get('shown_images', []):
                                tag = img.get('tag')
                                if tag and tag not in seen_tags and not tag.startswith('_'):
                                    seen_tags.add(tag)
                                    asset = {
                                        'tag': tag,
                                        'name': tag.title(),
                                        'type': 'character' if any(char in tag.lower() for char in ['eileen', 'lucy', 'character']) else 'image',
                                        'attributes': img.get('attributes', []),
                                        'thumbnail': f'/api/debug/thumbnail/{tag}',
                                        'category': self._categorize_asset(tag)
                                    }
                                    assets.append(asset)

                        # If still no assets, add some common ones
                        if not assets:
                            common_assets = [
                                {'tag': 'eileen', 'name': 'Eileen', 'type': 'character', 'attributes': ['happy', 'concerned'], 'category': 'Characters'},
                                {'tag': 'bg', 'name': 'Background', 'type': 'background', 'attributes': [], 'category': 'Backgrounds'},
                                {'tag': 'side', 'name': 'Side Image', 'type': 'character', 'attributes': [], 'category': 'Characters'}
                            ]
                            for asset_data in common_assets:
                                asset = {
                                    'tag': asset_data['tag'],
                                    'name': asset_data['name'],
                                    'type': asset_data['type'],
                                    'attributes': asset_data['attributes'],
                                    'thumbnail': f'/api/debug/thumbnail/{asset_data["tag"]}',
                                    'category': asset_data['category']
                                }
                                assets.append(asset)

                        return assets

                    except Exception:
                        return []

                def _get_audio_assets(self):
                    """Get available audio assets."""
                    try:
                        # This would scan the game directory for audio files
                        # For now, return common audio channels
                        return [
                            {'name': 'music', 'type': 'channel', 'files': []},
                            {'name': 'sound', 'type': 'channel', 'files': []},
                            {'name': 'voice', 'type': 'channel', 'files': []}
                        ]

                    except Exception:
                        return []

                def _get_background_assets(self):
                    """Get available background assets."""
                    try:
                        backgrounds = []

                        # Try to get background tags from Ren'Py
                        try:
                            for tag in renpy.get_available_image_tags():
                                if any(bg in tag.lower() for bg in ['bg', 'background', 'scene']):
                                    backgrounds.append({
                                        'tag': tag,
                                        'name': tag.replace('_', ' ').title(),
                                        'type': 'background',
                                        'thumbnail': f'/api/debug/thumbnail/{tag}',
                                        'category': 'Backgrounds'
                                    })
                        except Exception:
                            # If that fails, get from current scene
                            from renpy.testing.state_inspector import StateInspector
                            inspector = StateInspector()
                            scene_data = inspector.get_scene_info()

                            # Extract background objects from current scene
                            seen_tags = set()
                            for img in scene_data.get('shown_images', []):
                                tag = img.get('tag')
                                if tag and any(bg in tag.lower() for bg in ['bg', 'background', 'scene']) and tag not in seen_tags:
                                    seen_tags.add(tag)
                                    backgrounds.append({
                                        'tag': tag,
                                        'name': tag.replace('_', ' ').title(),
                                        'type': 'background',
                                        'thumbnail': f'/api/debug/thumbnail/{tag}',
                                        'category': 'Backgrounds'
                                    })

                        # Add some common background options if none found
                        if not backgrounds:
                            common_bgs = ['bg room', 'bg black', 'bg white', 'scene bg']
                            for bg_name in common_bgs:
                                backgrounds.append({
                                    'tag': bg_name.replace(' ', '_'),
                                    'name': bg_name.title(),
                                    'type': 'background',
                                    'thumbnail': f'/api/debug/thumbnail/{bg_name.replace(" ", "_")}',
                                    'category': 'Backgrounds'
                                })

                        return backgrounds

                    except Exception:
                        return []

                def _categorize_asset(self, tag):
                    """Categorize an asset by its tag."""
                    tag_lower = tag.lower()

                    if any(char in tag_lower for char in ['eileen', 'lucy', 'character', 'char']):
                        return 'Characters'
                    elif any(bg in tag_lower for bg in ['bg', 'background', 'scene']):
                        return 'Backgrounds'
                    elif any(prop in tag_lower for prop in ['prop', 'object', 'item']):
                        return 'Props'
                    else:
                        return 'Other'

                def _handle_debug_info(self):
                    """Return debug server connection info."""
                    info = {
                        'dap_port': self.server.unified_server.ports['dap'],
                        'http_port': self.server.unified_server.ports['http'],
                        'websocket_port': self.server.unified_server.ports['websocket'],
                        'status': 'running'
                    }
                    self._send_json_response(info)
                
                def _handle_webview_request(self):
                    """Handle webview HTML requests."""
                    parsed_url = urlparse(self.path)
                    path = parsed_url.path
                    
                    if path == '/webview/scene-objects':
                        self._serve_scene_objects_webview()
                    elif path == '/webview/visual-builder':
                        self._serve_visual_builder_webview()
                    elif path == '/webview/property-editor':
                        self._serve_property_editor_webview()
                    else:
                        self._send_error(404, "Webview not found")
                
                def _serve_scene_objects_webview(self):
                    """Serve the scene objects webview."""
                    # Get scene data
                    try:
                        from renpy.testing.state_inspector import StateInspector
                        inspector = StateInspector()
                        scene_data = inspector.get_scene_info() or {}
                    except Exception as e:
                        scene_data = {'error': str(e)}

                    # Render HTML
                    html = self._render_scene_objects_html(scene_data)
                    self._send_html_response(html)

                def _serve_property_editor_webview(self):
                    """Serve the property editor webview."""
                    # Get current selection or default
                    try:
                        from renpy.testing.state_inspector import StateInspector
                        inspector = StateInspector()
                        scene_data = inspector.get_scene_info() or {}

                        # For now, show a simple property editor
                        html = self._render_property_editor_html(scene_data)
                        self._send_html_response(html)
                    except Exception as e:
                        self._send_error(500, f"Failed to load property editor: {e}")

                def _render_property_editor_html(self, scene_data):
                    """Render property editor HTML."""
                    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Ren'Py Property Editor</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #1e1e1e; color: #fff; }}
        .property-form {{ background: #2d2d2d; padding: 15px; border-radius: 5px; margin: 10px 0; }}
        .form-group {{ margin: 10px 0; }}
        label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
        input, select {{ width: 100%; padding: 8px; border: 1px solid #555; background: #333; color: #fff; }}
        button {{ background: #007acc; color: white; padding: 10px 15px; border: none; border-radius: 3px; cursor: pointer; }}
        button:hover {{ background: #005a9e; }}
    </style>
</head>
<body>
    <h1>Ren'Py Property Editor</h1>

    <div class="property-form">
        <h2>Move Object</h2>
        <form action="/api/debug/move-object" method="post">
            <div class="form-group">
                <label for="layer">Layer:</label>
                <select name="layer" id="layer">
                    <option value="master">master</option>
                    <option value="screens">screens</option>
                    <option value="overlay">overlay</option>
                </select>
            </div>
            <div class="form-group">
                <label for="tag">Tag:</label>
                <input type="text" name="tag" id="tag" placeholder="Object tag">
            </div>
            <div class="form-group">
                <label for="x">X Position:</label>
                <input type="number" name="x" id="x" value="0">
            </div>
            <div class="form-group">
                <label for="y">Y Position:</label>
                <input type="number" name="y" id="y" value="0">
            </div>
            <button type="submit">Move Object</button>
        </form>
    </div>

    <div class="property-form">
        <h2>Show/Hide Object</h2>
        <form action="/api/debug/toggle-object" method="post">
            <div class="form-group">
                <label for="action">Action:</label>
                <select name="action" id="action">
                    <option value="show">Show</option>
                    <option value="hide">Hide</option>
                </select>
            </div>
            <div class="form-group">
                <label for="layer2">Layer:</label>
                <select name="layer" id="layer2">
                    <option value="master">master</option>
                    <option value="screens">screens</option>
                    <option value="overlay">overlay</option>
                </select>
            </div>
            <div class="form-group">
                <label for="tag2">Tag:</label>
                <input type="text" name="tag" id="tag2" placeholder="Object tag">
            </div>
            <button type="submit">Apply</button>
        </form>
    </div>

    <script>
        // WebSocket connection for real-time updates
        const ws = new WebSocket('ws://localhost:{self.server.unified_server.ports["websocket"]}');

        ws.onmessage = function(event) {{
            const data = JSON.parse(event.data);
            if (data.type === 'property_update') {{
                // Update form fields with new values
                updatePropertyFields(data);
            }}
        }};

        function updatePropertyFields(data) {{
            // Update form fields based on server data
            if (data.selected_object) {{
                document.getElementById('tag').value = data.selected_object.tag || '';
                document.getElementById('layer').value = data.selected_object.layer || 'master';
            }}
        }}
    </script>
</body>
</html>
"""
                    return html
                
                def _render_scene_objects_html(self, scene_data):
                    """Render scene objects HTML with interactive controls."""
                    # Enhanced server-side rendered HTML with Interactive Director features
                    html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Ren'Py Scene Objects - Interactive Director</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .section {{ background: white; margin-bottom: 20px; padding: 15px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        .object-card {{ border: 1px solid #ddd; padding: 15px; margin: 10px 0; border-radius: 3px; background: #fafafa; }}
        .object-name {{ font-weight: bold; font-size: 1.1em; color: #333; }}
        .object-meta {{ color: #666; font-size: 0.9em; margin: 5px 0; }}
        .controls {{ margin-top: 10px; }}
        .btn {{ margin: 2px; padding: 8px 12px; border: none; border-radius: 3px; cursor: pointer; font-size: 0.9em; }}
        .btn-primary {{ background: #007acc; color: white; }}
        .btn-primary:hover {{ background: #005a9e; }}
        .btn-secondary {{ background: #6c757d; color: white; }}
        .btn-secondary:hover {{ background: #545b62; }}
        .btn-danger {{ background: #dc3545; color: white; }}
        .btn-danger:hover {{ background: #c82333; }}
        .btn-success {{ background: #28a745; color: white; }}
        .btn-success:hover {{ background: #218838; }}
        .form-inline {{ display: inline-block; margin: 5px; }}
        .form-inline input, .form-inline select {{ margin: 0 5px; padding: 5px; border: 1px solid #ccc; border-radius: 3px; }}
        .toolbar {{ background: #e9ecef; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .toolbar h3 {{ margin: 0 0 10px 0; }}
        .attribute-list {{ margin: 10px 0; }}
        .attribute-tag {{ display: inline-block; background: #e7f3ff; padding: 3px 8px; margin: 2px; border-radius: 3px; font-size: 0.8em; }}
        .transform-list {{ margin: 10px 0; }}
        .transform-tag {{ display: inline-block; background: #fff3cd; padding: 3px 8px; margin: 2px; border-radius: 3px; font-size: 0.8em; }}
        .status-bar {{ position: fixed; bottom: 0; left: 0; right: 0; background: #343a40; color: white; padding: 10px; text-align: center; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Ren'Py Scene Objects - Interactive Director</h1>

        <div class="toolbar">
            <h3>Quick Actions</h3>
            <button class="btn btn-primary" onclick="refreshScene()">🔄 Refresh Scene</button>
            <button class="btn btn-secondary" onclick="showAddDialog()">➕ Add Object</button>
            <button class="btn btn-secondary" onclick="showAudioControls()">🔊 Audio Controls</button>
            <button class="btn btn-success" onclick="showApplyDialog()">💾 Apply Changes</button>
            <button class="btn btn-secondary" onclick="showChangesDialog()">📋 View Changes</button>
        </div>

        <div id="content">
            {self._render_scene_objects_content(scene_data)}
        </div>

        <!-- Add Object Dialog -->
        <div id="addDialog" style="display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; padding: 20px; border-radius: 5px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); z-index: 1000;">
            <h3>Add Scene Object</h3>
            <div class="form-inline">
                <label>Action:</label>
                <select id="addAction">
                    <option value="show">Show</option>
                    <option value="scene">Scene</option>
                </select>
            </div>
            <div class="form-inline">
                <label>Tag:</label>
                <select id="addTag">
                    {self._render_tag_options(scene_data)}
                </select>
            </div>
            <div class="form-inline">
                <label>Transform:</label>
                <select id="addTransform">
                    <option value="">None</option>
                    {self._render_transform_options(scene_data)}
                </select>
            </div>
            <div style="margin-top: 15px;">
                <button class="btn btn-success" onclick="executeAdd()">Add</button>
                <button class="btn btn-secondary" onclick="hideAddDialog()">Cancel</button>
            </div>
        </div>

        <!-- Audio Controls Dialog -->
        <div id="audioDialog" style="display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; padding: 20px; border-radius: 5px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); z-index: 1000;">
            <h3>Audio Controls</h3>
            <div class="form-inline">
                <label>Action:</label>
                <select id="audioAction">
                    <option value="play">Play</option>
                    <option value="stop">Stop</option>
                    <option value="queue">Queue</option>
                </select>
            </div>
            <div class="form-inline">
                <label>Channel:</label>
                <select id="audioChannel">
                    {self._render_audio_channel_options(scene_data)}
                </select>
            </div>
            <div class="form-inline">
                <label>File:</label>
                <select id="audioFile">
                    {self._render_audio_file_options(scene_data)}
                </select>
            </div>
            <div style="margin-top: 15px;">
                <button class="btn btn-success" onclick="executeAudio()">Execute</button>
                <button class="btn btn-secondary" onclick="hideAudioDialog()">Cancel</button>
            </div>
        </div>

        <!-- Apply Changes Dialog -->
        <div id="applyDialog" style="display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; padding: 20px; border-radius: 5px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); z-index: 1000; min-width: 400px;">
            <h3>Apply Changes to Script</h3>
            <p>This will permanently modify your script files. Are you sure?</p>
            <div id="applyChangesPreview" style="background: #f8f9fa; padding: 10px; border-radius: 3px; margin: 10px 0; max-height: 200px; overflow-y: auto;">
                <em>Loading changes...</em>
            </div>
            <div class="form-inline">
                <label>Target File:</label>
                <input type="text" id="applyFilename" value="game/script.rpy" style="width: 200px;">
            </div>
            <div style="margin-top: 15px;">
                <button class="btn btn-success" onclick="executeApply()">💾 Apply to Script</button>
                <button class="btn btn-secondary" onclick="hideApplyDialog()">Cancel</button>
            </div>
        </div>

        <!-- View Changes Dialog -->
        <div id="changesDialog" style="display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; padding: 20px; border-radius: 5px; box-shadow: 0 4px 20px rgba(0,0,0,0.3); z-index: 1000; min-width: 500px;">
            <h3>Pending Changes</h3>
            <div id="changesList" style="background: #f8f9fa; padding: 10px; border-radius: 3px; margin: 10px 0; max-height: 300px; overflow-y: auto;">
                <em>Loading changes...</em>
            </div>
            <div style="margin-top: 15px;">
                <button class="btn btn-danger" onclick="clearAllChanges()">🗑️ Clear All</button>
                <button class="btn btn-secondary" onclick="hideChangesDialog()">Close</button>
            </div>
        </div>

        <div class="status-bar" id="statusBar">
            Ready - Scene Objects: {len(scene_data.get('shown_images', []))} | Screens: {len(scene_data.get('active_screens', []))}
        </div>
    </div>
    
    <script>
        // WebSocket connection for real-time updates
        const ws = new WebSocket('ws://localhost:{self.server.unified_server.ports["websocket"]}');
        
        ws.onmessage = function(event) {{
            const data = JSON.parse(event.data);
            if (data.type === 'scene_update') {{
                updateSceneObjects(data.scene_data);
            }}
        }};
        
        function updateSceneObjects(sceneData) {{
            // Refresh the page to get updated content
            location.reload();
        }}

        function refreshScene() {{
            fetch('/api/debug/action', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{'action': 'refresh_scene'}})
            }}).then(() => location.reload());
        }}

        function showAddDialog() {{
            document.getElementById('addDialog').style.display = 'block';
        }}

        function hideAddDialog() {{
            document.getElementById('addDialog').style.display = 'none';
        }}

        function showAudioControls() {{
            document.getElementById('audioDialog').style.display = 'block';
        }}

        function hideAudioDialog() {{
            document.getElementById('audioDialog').style.display = 'none';
        }}

        function executeAdd() {{
            const action = document.getElementById('addAction').value;
            const tag = document.getElementById('addTag').value;
            const transform = document.getElementById('addTransform').value;

            const data = {{
                tag: tag,
                attributes: [],
                transforms: transform ? [transform] : [],
                layer: 'master'
            }};

            fetch(`/api/debug/scene/${{action}}`, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }}).then(() => {{
                hideAddDialog();
                location.reload();
            }});
        }}

        function executeAudio() {{
            const action = document.getElementById('audioAction').value;
            const channel = document.getElementById('audioChannel').value;
            const filename = document.getElementById('audioFile').value;

            const data = {{
                channel: channel,
                filename: action !== 'stop' ? filename : undefined
            }};

            fetch(`/api/debug/audio/${{action}}`, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }}).then(() => {{
                hideAudioDialog();
                updateStatus(`Audio ${{action}} executed on ${{channel}}`);
            }});
        }}

        function showObject(tag, attributes = []) {{
            const data = {{
                tag: tag,
                attributes: attributes,
                layer: 'master'
            }};

            fetch('/api/debug/scene/show', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }}).then(() => location.reload());
        }}

        function hideObject(tag) {{
            const data = {{
                tag: tag,
                layer: 'master'
            }};

            fetch('/api/debug/scene/hide', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }}).then(() => location.reload());
        }}

        function moveObject(tag, x, y) {{
            const data = {{
                tag: tag,
                x: x,
                y: y
            }};

            fetch('/api/debug/set-position', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }}).then(() => location.reload());
        }}

        function setProperties(tag, properties) {{
            const data = {{
                tag: tag,
                properties: properties
            }};

            fetch('/api/debug/set-properties', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify(data)
            }}).then(() => location.reload());
        }}

        function hideScreen(name) {{
            // Screen hiding functionality
            fetch('/api/debug/action', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{'action': 'hide_screen', 'screen': name}})
            }}).then(() => location.reload());
        }}

        function updateStatus(message) {{
            document.getElementById('statusBar').textContent = message;
            setTimeout(() => {{
                document.getElementById('statusBar').textContent = 'Ready';
            }}, 3000);
        }}

        function showObjectEditor(tag) {{
            // Simple property editor
            const alpha = prompt('Enter alpha value (0.0 - 1.0):', '1.0');
            const zoom = prompt('Enter zoom value:', '1.0');

            if (alpha !== null && zoom !== null) {{
                setProperties(tag, {{
                    alpha: parseFloat(alpha),
                    zoom: parseFloat(zoom)
                }});
            }}
        }}

        function inspectScreen(name) {{
            // Show screen information
            alert(`Screen: ${{name}}\\nType: Active Screen\\nActions: Hide available`);
        }}

        function showApplyDialog() {{
            // Load pending changes preview
            fetch('/api/debug/script/get-changes', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{}})
            }})
            .then(response => response.json())
            .then(data => {{
                const preview = document.getElementById('applyChangesPreview');
                if (data.changes && data.changes.length > 0) {{
                    let html = '<h4>Changes to be applied:</h4><ul>';
                    data.changes.forEach(change => {{
                        const desc = describeChange(change);
                        html += `<li>${{desc}}</li>`;
                    }});
                    html += '</ul>';
                    preview.innerHTML = html;
                }} else {{
                    preview.innerHTML = '<em>No pending changes to apply.</em>';
                }}
                document.getElementById('applyDialog').style.display = 'block';
            }})
            .catch(error => {{
                console.error('Error loading changes:', error);
                document.getElementById('applyChangesPreview').innerHTML = '<em>Error loading changes.</em>';
                document.getElementById('applyDialog').style.display = 'block';
            }});
        }}

        function hideApplyDialog() {{
            document.getElementById('applyDialog').style.display = 'none';
        }}

        function showChangesDialog() {{
            // Load and display all pending changes
            fetch('/api/debug/script/get-changes', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{}})
            }})
            .then(response => response.json())
            .then(data => {{
                const changesList = document.getElementById('changesList');
                if (data.changes && data.changes.length > 0) {{
                    let html = '<h4>All Pending Changes:</h4>';
                    data.changes.forEach((change, index) => {{
                        const desc = describeChange(change);
                        const timestamp = new Date(change.timestamp * 1000).toLocaleTimeString();
                        html += `<div style="border: 1px solid #ddd; padding: 8px; margin: 5px 0; border-radius: 3px;">`;
                        html += `<strong>${{change.type.toUpperCase()}}</strong> - ${{desc}}`;
                        html += `<br><small>Time: ${{timestamp}} | ID: ${{change.id}}</small>`;
                        html += `</div>`;
                    }});
                    html += `<p><strong>Summary:</strong> ${{JSON.stringify(data.summary)}}</p>`;
                    changesList.innerHTML = html;
                }} else {{
                    changesList.innerHTML = '<em>No pending changes.</em>';
                }}
                document.getElementById('changesDialog').style.display = 'block';
            }})
            .catch(error => {{
                console.error('Error loading changes:', error);
                document.getElementById('changesList').innerHTML = '<em>Error loading changes.</em>';
                document.getElementById('changesDialog').style.display = 'block';
            }});
        }}

        function hideChangesDialog() {{
            document.getElementById('changesDialog').style.display = 'none';
        }}

        function executeApply() {{
            const filename = document.getElementById('applyFilename').value;

            // Get pending changes and commit them
            fetch('/api/debug/script/get-changes', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{}})
            }})
            .then(response => response.json())
            .then(data => {{
                if (data.changes && data.changes.length > 0) {{
                    // Commit the changes
                    return fetch('/api/debug/script/commit-changes', {{
                        method: 'POST',
                        headers: {{'Content-Type': 'application/json'}},
                        body: JSON.stringify({{
                            changes: data.changes.map(c => c.data),
                            filename: filename
                        }})
                    }});
                }} else {{
                    throw new Error('No changes to apply');
                }}
            }})
            .then(response => response.json())
            .then(result => {{
                if (result.success) {{
                    updateStatus(`Applied ${{result.committed.length}} changes to ${{result.filename}}`);
                    hideApplyDialog();
                    // Clear changes after successful application
                    clearAllChanges();
                }} else {{
                    alert(`Error applying changes: ${{result.error}}`);
                }}
            }})
            .catch(error => {{
                console.error('Error applying changes:', error);
                alert(`Error applying changes: ${{error.message}}`);
            }});
        }}

        function clearAllChanges() {{
            if (confirm('Clear all pending changes? This cannot be undone.')) {{
                // Clear changes on server side
                fetch('/api/debug/action', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{'action': 'clear_changes'}})
                }})
                .then(() => {{
                    updateStatus('All changes cleared');
                    hideChangesDialog();
                }})
                .catch(error => {{
                    console.error('Error clearing changes:', error);
                }});
            }}
        }}

        function describeChange(change) {{
            const data = change.data;
            switch (change.type) {{
                case 'show':
                    let desc = `Show ${{data.tag}}`;
                    if (data.attributes && data.attributes.length > 0) {{
                        desc += ` with attributes: ${{data.attributes.join(', ')}}`;
                    }}
                    if (data.transforms && data.transforms.length > 0) {{
                        desc += ` at ${{data.transforms.join(', ')}}`;
                    }}
                    return desc;
                case 'hide':
                    return `Hide ${{data.tag}}`;
                case 'scene':
                    if (data.tag) {{
                        return `Scene with ${{data.tag}}`;
                    }} else {{
                        return 'Clear scene';
                    }}
                case 'audio':
                    return `${{data.action}} audio on ${{data.channel}}`;
                default:
                    return `${{change.type}} action`;
            }}
        }}

        // Close dialogs when clicking outside
        window.onclick = function(event) {{
            const addDialog = document.getElementById('addDialog');
            const audioDialog = document.getElementById('audioDialog');
            const applyDialog = document.getElementById('applyDialog');
            const changesDialog = document.getElementById('changesDialog');

            if (event.target === addDialog) {{
                hideAddDialog();
            }}
            if (event.target === audioDialog) {{
                hideAudioDialog();
            }}
            if (event.target === applyDialog) {{
                hideApplyDialog();
            }}
            if (event.target === changesDialog) {{
                hideChangesDialog();
            }}
        }}
    </script>
</body>
</html>
"""
                    return html
                
                def _render_scene_objects_content(self, scene_data):
                    """Render scene objects content."""
                    content = ""
                    
                    # Render shown images
                    shown_images = scene_data.get('shown_images', [])
                    if shown_images:
                        content += '<div class="section"><h2>Shown Images</h2>'
                        for img in shown_images:
                            name = img.get('name', 'Unknown')
                            layer = img.get('layer', 'master')
                            tag = img.get('tag', name)
                            attributes = img.get('attributes', [])
                            transforms = img.get('transforms', [])

                            content += f'''
                            <div class="object-card">
                                <div class="object-name">{name}</div>
                                <div class="object-meta">Layer: {layer}, Tag: {tag}</div>
                                {'<div class="attribute-list">Attributes: ' + ", ".join([f'<span class="attribute-tag">{attr}</span>' for attr in attributes]) + '</div>' if attributes else ''}
                                {'<div class="transform-list">Transforms: ' + ", ".join([f'<span class="transform-tag">{trans}</span>' for trans in transforms]) + '</div>' if transforms else ''}
                                <div class="controls">
                                    <button class="btn btn-primary" onclick="showObjectEditor('{tag}')">✏️ Edit</button>
                                    <button class="btn btn-secondary" onclick="moveObject('{tag}', 100, 100)">📍 Move</button>
                                    <button class="btn btn-danger" onclick="hideObject('{tag}')">👁️ Hide</button>
                                    <button class="btn btn-secondary" onclick="setProperties('{tag}', {{'alpha': 0.5}})">🔍 Fade</button>
                                </div>
                            </div>
                            '''
                        content += '</div>'
                    
                    # Render active screens
                    active_screens = scene_data.get('active_screens', [])
                    if active_screens:
                        content += '<div class="section"><h2>Active Screens</h2>'
                        for screen in active_screens:
                            # Handle both string names and dict objects
                            if isinstance(screen, str):
                                name = screen
                            elif isinstance(screen, dict):
                                name = screen.get('name', 'Unknown')
                            else:
                                name = str(screen)
                            content += f'''
                            <div class="object-card">
                                <div class="object-name">{name}</div>
                                <div class="object-meta">Type: Screen</div>
                                <div class="controls">
                                    <button class="btn btn-danger" onclick="hideScreen('{name}')">👁️ Hide Screen</button>
                                    <button class="btn btn-secondary" onclick="inspectScreen('{name}')">🔍 Inspect</button>
                                </div>
                            </div>
                            '''
                        content += '</div>'
                    
                    return content

                def _render_tag_options(self, scene_data):
                    """Render tag options for dropdowns."""
                    options = ""
                    for tag in scene_data.get('available_tags', []):
                        options += f'<option value="{tag}">{tag}</option>'
                    return options

                def _render_transform_options(self, scene_data):
                    """Render transform options for dropdowns."""
                    options = ""
                    for transform in scene_data.get('available_transforms', []):
                        options += f'<option value="{transform}">{transform}</option>'
                    return options

                def _render_audio_channel_options(self, scene_data):
                    """Render audio channel options for dropdowns."""
                    options = ""
                    for channel in scene_data.get('audio_channels', []):
                        options += f'<option value="{channel}">{channel}</option>'
                    return options

                def _render_audio_file_options(self, scene_data):
                    """Render audio file options for dropdowns."""
                    options = ""
                    audio_files = scene_data.get('audio_files', {})
                    for channel, files in audio_files.items():
                        if files:
                            options += f'<optgroup label="{channel}">'
                            for file in files:
                                options += f'<option value="{file}">{file}</option>'
                            options += '</optgroup>'
                    return options

                def _serve_visual_builder_webview(self):
                    """Serve the visual scene builder webview."""
                    try:
                        # Load HTML template from file
                        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'visual_builder.html')
                        with open(template_path, 'r', encoding='utf-8') as f:
                            html = f.read()
                        self._send_html_response(html)
                    except Exception as e:
                        self._send_error(500, f"Error rendering visual builder: {str(e)}")

                def _serve_static_file(self, file_path):
                    """Serve static files (CSS, JS)."""
                    try:
                        static_path = os.path.join(os.path.dirname(__file__), 'static', file_path)

                        # Determine content type
                        if file_path.endswith('.css'):
                            content_type = 'text/css'
                        elif file_path.endswith('.js'):
                            content_type = 'application/javascript'
                        else:
                            content_type = 'text/plain'

                        with open(static_path, 'r', encoding='utf-8') as f:
                            content = f.read()

                        self.send_response(200)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(content.encode('utf-8'))

                    except FileNotFoundError:
                        self._send_error(404, f"Static file not found: {file_path}")
                    except Exception as e:
                        self._send_error(500, f"Error serving static file: {str(e)}")

                def _handle_static_request(self):
                    """Handle static file requests."""
                    parsed_url = urlparse(self.path)
                    path = parsed_url.path

                    if path.startswith('/static/'):
                        file_path = path[8:]  # Remove '/static/' prefix
                        self._serve_static_file(file_path)
                    else:
                        self._send_error(404, "Static file not found")

                def _handle_image_request(self):
                    """Handle image serving requests."""
                    parsed_url = urlparse(self.path)
                    path = parsed_url.path

                    # Extract image info from /api/debug/image/tag/attribute/layer
                    # or /api/debug/image/tag/layer (for backward compatibility)
                    path_parts = path.split('/')
                    if len(path_parts) >= 5:
                        tag = path_parts[4]
                        if len(path_parts) >= 7:
                            # New format: /api/debug/image/tag/attribute/layer
                            attribute = path_parts[5]
                            layer = path_parts[6]
                            self._serve_displayable_image_with_attribute(tag, attribute, layer)
                        else:
                            # Old format: /api/debug/image/tag/layer
                            layer = path_parts[5] if len(path_parts) > 5 else 'master'
                            self._serve_displayable_image(tag, layer)
                    else:
                        self._send_error(400, "Invalid image request format")

                def _serve_displayable_image(self, tag, layer='master'):
                    """Serve the actual image data for a displayable."""
                    try:
                        import renpy
                        print(f"Attempting to serve image for tag: {tag}, layer: {layer}")

                        # Method 1: Try to serve the image file directly by patterns
                        print(f"Method 1: Trying direct file patterns for {tag}")
                        if self._serve_image_file_direct(tag):
                            return

                        # Method 2: Get displayable info and extract file path
                        print(f"Method 2: Getting displayable for {tag}")
                        displayable = self._get_displayable(tag, layer)
                        if displayable:
                            print(f"Found displayable for {tag}: {type(displayable)}")
                            # Try to get the image file path from the displayable
                            image_path = self._extract_image_path(displayable)
                            print(f"Extracted image path for {tag}: {image_path}")
                            if image_path:
                                # Try the exact path first
                                if self._serve_file_by_path(image_path):
                                    return

                                # Try variations of the path
                                variations = [
                                    image_path.replace(' ', '_'),  # Replace spaces with underscores
                                    image_path.replace(' ', ''),   # Remove spaces
                                    image_path.replace(' ', '-'),  # Replace spaces with dashes
                                ]

                                for variation in variations:
                                    print(f"Trying path variation: {variation}")
                                    if self._serve_file_by_path(variation):
                                        return
                        else:
                            print(f"No displayable found for {tag}")

                        # Method 3: Try with complex image names from scene data
                        print(f"Method 3: Trying complex image names for {tag}")
                        if self._serve_by_scene_data(tag, layer):
                            return

                        # Method 4: Fallback to file serving by name patterns
                        print(f"Method 4: Trying fallback patterns for {tag}")
                        if self._try_serve_image_file(tag):
                            return

                        print(f"All methods failed for {tag}")
                        self._send_error(404, f"Image not found for: {tag}")

                    except Exception as e:
                        print(f"Error serving displayable image {tag}: {e}")
                        import traceback
                        traceback.print_exc()
                        self._send_error(500, f"Error serving image: {str(e)}")

                def _serve_displayable_image_with_attribute(self, tag, attribute, layer='master'):
                    """Serve image with specific attribute (e.g., bg/washington or eileen/happy)."""
                    try:
                        print(f"Attempting to serve image for tag: {tag}, attribute: {attribute}, layer: {layer}")

                        # Build the full image name
                        full_name = f"{tag} {attribute}"

                        # Try direct file patterns with the full name
                        patterns = [
                            f"images/{full_name}.png",
                            f"images/{full_name}.jpg",
                            f"images/{full_name}.jpeg",
                            f"images/{full_name}.webp",
                            f"images/{tag}_{attribute}.png",
                            f"images/{tag}_{attribute}.jpg",
                            f"images/{tag}/{attribute}.png",
                            f"images/{tag}/{attribute}.jpg",
                            f"{full_name}.png",
                            f"{full_name}.jpg",
                        ]

                        for pattern in patterns:
                            print(f"Trying attribute pattern: {pattern}")
                            if self._serve_file_by_path(pattern):
                                return

                        print(f"All attribute patterns failed for {tag}/{attribute}")
                        self._send_error(404, f"Image not found for: {tag}/{attribute}")

                    except Exception as e:
                        print(f"Error serving displayable image {tag}/{attribute}: {e}")
                        import traceback
                        traceback.print_exc()
                        self._send_error(500, f"Error serving image: {str(e)}")

                def _get_displayable(self, tag, layer):
                    """Get displayable from scene or image registry."""
                    try:
                        import renpy

                        # Try image registry first (more reliable)
                        if hasattr(renpy, 'display') and hasattr(renpy.display, 'image'):
                            images = renpy.display.image.images

                            # Try different name formats
                            possible_names = [
                                tag,
                                (tag,),
                                (tag, 'happy'),
                                (tag, 'normal'),
                                (tag, 'vhappy'),
                                ('bg', tag) if tag != 'bg' else None,
                                ('eileen', tag) if tag != 'eileen' else None,
                            ]

                            for name in [n for n in possible_names if n is not None]:
                                if name in images:
                                    print(f"Found displayable for {tag} using name: {name}")
                                    return images[name]

                        return None
                    except Exception as e:
                        print(f"Failed to get displayable for {tag}: {e}")
                        return None

                def _extract_image_path(self, displayable):
                    """Extract the file path from a displayable."""
                    try:
                        # Method 1: Check if it's a simple Image displayable
                        if hasattr(displayable, 'filename'):
                            return displayable.filename

                        # Method 2: Check for image attribute
                        if hasattr(displayable, 'image'):
                            return displayable.image

                        # Method 3: Check for child displayables
                        if hasattr(displayable, 'child'):
                            return self._extract_image_path(displayable.child)

                        # Method 4: Check for args (common in Image displayables)
                        if hasattr(displayable, 'args') and displayable.args:
                            first_arg = displayable.args[0]
                            if isinstance(first_arg, str):
                                return first_arg

                        return None
                    except Exception as e:
                        print(f"Failed to extract image path: {e}")
                        return None

                def _serve_by_scene_data(self, tag, layer):
                    """Try to serve image using scene data information."""
                    try:
                        # Get the current scene data to find the actual image name
                        unified_server = self.server.unified_server
                        if unified_server and hasattr(unified_server, 'state_inspector'):
                            scene_data = unified_server.state_inspector.get_scene_info()
                            shown_images = scene_data.get('shown_images', [])

                            # Find the image with matching tag
                            for img in shown_images:
                                if img.get('tag') == tag and img.get('layer') == layer:
                                    # Try the full image name
                                    image_name = img.get('image_name')
                                    if image_name:
                                        print(f"Found image_name for {tag}: {image_name}")
                                        # Parse the image name - it might be like "('eileen', 'vhappy')"
                                        if image_name.startswith("(") and image_name.endswith(")"):
                                            # It's a tuple string, try to parse it
                                            try:
                                                import ast
                                                parsed_name = ast.literal_eval(image_name)
                                                if isinstance(parsed_name, tuple) and len(parsed_name) >= 2:
                                                    # Try patterns like "eileen_vhappy.png"
                                                    file_patterns = [
                                                        f"images/{'_'.join(parsed_name)}.png",
                                                        f"images/{'_'.join(parsed_name)}.jpg",
                                                        f"images/{parsed_name[0]}/{parsed_name[1]}.png",
                                                        f"images/{parsed_name[0]}/{parsed_name[1]}.jpg",
                                                        f"{'_'.join(parsed_name)}.png",
                                                        f"{'/'.join(parsed_name)}.png",
                                                    ]

                                                    for pattern in file_patterns:
                                                        print(f"Trying pattern: {pattern}")
                                                        if self._serve_file_by_path(pattern):
                                                            return True
                                            except Exception as e:
                                                print(f"Failed to parse image name {image_name}: {e}")

                                    # Try the name tuple directly
                                    name_tuple = img.get('name')
                                    if name_tuple and isinstance(name_tuple, tuple):
                                        print(f"Found name tuple for {tag}: {name_tuple}")
                                        file_patterns = [
                                            f"images/{'_'.join(name_tuple)}.png",
                                            f"images/{'_'.join(name_tuple)}.jpg",
                                            f"images/{name_tuple[0]}/{name_tuple[1] if len(name_tuple) > 1 else 'default'}.png",
                                            f"images/{name_tuple[0]}/{name_tuple[1] if len(name_tuple) > 1 else 'default'}.jpg",
                                        ]

                                        for pattern in file_patterns:
                                            print(f"Trying name pattern: {pattern}")
                                            if self._serve_file_by_path(pattern):
                                                return True
                                    break

                        return False
                    except Exception as e:
                        print(f"Scene data method failed for {tag}: {e}")
                        return False

                def _serve_image_file_direct(self, tag):
                    """Try to serve image file directly by common patterns."""
                    try:
                        print(f"Direct file serving for tag: {tag}")

                        # Special handling for background images
                        if tag == 'bg':
                            # Try to get the actual background name from scene data
                            bg_name = self._get_current_bg_name()
                            if bg_name:
                                print(f"Found current background: {bg_name}")
                                bg_patterns = [
                                    f"images/bg {bg_name}.jpg",
                                    f"images/bg {bg_name}.png",
                                    f"images/bg_{bg_name}.jpg",
                                    f"images/bg_{bg_name}.png",
                                    f"images/{bg_name}.jpg",
                                    f"images/{bg_name}.png",
                                ]

                                for pattern in bg_patterns:
                                    print(f"Trying background pattern: {pattern}")
                                    if self._serve_file_by_path(pattern):
                                        return True

                        # Common image file patterns
                        patterns = [
                            f"images/{tag}.png",
                            f"images/{tag}.jpg",
                            f"images/{tag}.jpeg",
                            f"images/{tag}.webp",
                            f"{tag}.png",
                            f"{tag}.jpg",
                            f"images/characters/{tag}.png",
                            f"images/characters/{tag}.jpg",
                        ]

                        for pattern in patterns:
                            print(f"Trying pattern: {pattern}")
                            if self._serve_file_by_path(pattern):
                                return True

                        return False
                    except Exception as e:
                        print(f"Direct file serving failed for {tag}: {e}")
                        return False

                def _get_current_bg_name(self):
                    """Get the current background name from scene data."""
                    try:
                        unified_server = self.server.unified_server
                        if unified_server and hasattr(unified_server, 'state_inspector'):
                            scene_data = unified_server.state_inspector.get_scene_info()
                            shown_images = scene_data.get('shown_images', [])

                            # Find background images
                            for img in shown_images:
                                if img.get('tag') == 'bg' and img.get('layer') == 'master':
                                    # Try to extract the background name
                                    name_tuple = img.get('name')
                                    if name_tuple and isinstance(name_tuple, tuple) and len(name_tuple) >= 2:
                                        return name_tuple[1]  # e.g., 'washington' from ('bg', 'washington')

                                    # Try image_name
                                    image_name = img.get('image_name')
                                    if image_name and 'washington' in image_name:
                                        return 'washington'

                        return None
                    except Exception as e:
                        print(f"Failed to get current background name: {e}")
                        return None

                def _serve_file_by_path(self, file_path):
                    """Serve a file by its path using multiple methods."""
                    try:
                        print(f"Attempting to load file: {file_path}")

                        # Method 1: Try Ren'Py's loader
                        try:
                            import renpy
                            if hasattr(renpy, 'loader') and hasattr(renpy.loader, 'get'):
                                file_data = renpy.loader.get(file_path)
                                if file_data:
                                    print(f"Successfully loaded via Ren'Py loader: {file_path} ({len(file_data)} bytes)")
                                    return self._send_image_data(file_data, file_path)
                                else:
                                    print(f"Ren'Py loader: File not found or empty: {file_path}")
                        except Exception as load_error:
                            print(f"Ren'Py loader error for {file_path}: {load_error}")

                        # Method 2: Try direct file system access
                        try:
                            import os
                            # Try different base paths
                            possible_bases = [
                                "",  # Current directory
                                "game/",  # Relative to game directory
                                "tutorial/game/",  # Tutorial game directory
                                "../tutorial/game/",  # Up one level
                                "renpy/tutorial/game/",  # Full path from project root
                            ]

                            for base in possible_bases:
                                full_path = os.path.join(base, file_path)
                                print(f"Trying direct file access: {full_path}")
                                if os.path.exists(full_path):
                                    with open(full_path, 'rb') as f:
                                        file_data = f.read()
                                    print(f"Successfully loaded via direct access: {full_path} ({len(file_data)} bytes)")
                                    return self._send_image_data(file_data, file_path)
                        except Exception as fs_error:
                            print(f"Direct file system error for {file_path}: {fs_error}")

                        print(f"All methods failed for: {file_path}")
                        return False
                    except Exception as e:
                        print(f"Failed to serve file {file_path}: {e}")
                        return False

                def _send_image_data(self, file_data, file_path):
                    """Send image data with proper headers."""
                    try:
                        # Determine content type
                        if file_path.lower().endswith(('.jpg', '.jpeg')):
                            content_type = 'image/jpeg'
                        elif file_path.lower().endswith('.png'):
                            content_type = 'image/png'
                        elif file_path.lower().endswith('.webp'):
                            content_type = 'image/webp'
                        else:
                            content_type = 'image/png'

                        # Send the file
                        self.send_response(200)
                        self.send_header('Content-Type', content_type)
                        self.send_header('Content-Length', str(len(file_data)))
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.send_header('Cache-Control', 'no-cache')
                        self.end_headers()
                        self.wfile.write(file_data)
                        print(f"Successfully served image: {file_path}")
                        return True
                    except Exception as e:
                        print(f"Failed to send image data for {file_path}: {e}")
                        return False

                def _try_serve_image_file(self, tag):
                    """Try to serve an image directly from file as fallback."""
                    try:
                        import renpy

                        # Common image extensions
                        extensions = ['.png', '.jpg', '.jpeg', '.webp']

                        # Try to find the image file
                        for ext in extensions:
                            # Try common paths
                            possible_paths = [
                                f"images/{tag}{ext}",
                                f"images/{tag.replace(' ', '_')}{ext}",
                                f"{tag}{ext}",
                                f"{tag.replace(' ', '_')}{ext}",
                            ]

                            for path in possible_paths:
                                try:
                                    # Use Ren'Py's loader to find the file
                                    if hasattr(renpy, 'loader') and hasattr(renpy.loader, 'get'):
                                        file_data = renpy.loader.get(path)
                                        if file_data:
                                            # Determine content type
                                            if ext.lower() in ['.jpg', '.jpeg']:
                                                content_type = 'image/jpeg'
                                            elif ext.lower() == '.png':
                                                content_type = 'image/png'
                                            elif ext.lower() == '.webp':
                                                content_type = 'image/webp'
                                            else:
                                                content_type = 'image/png'

                                            # Send the file
                                            self.send_response(200)
                                            self.send_header('Content-Type', content_type)
                                            self.send_header('Access-Control-Allow-Origin', '*')
                                            self.send_header('Cache-Control', 'no-cache')
                                            self.end_headers()
                                            self.wfile.write(file_data)
                                            print(f"Served image file for {tag}: {path}")
                                            return True
                                except Exception:
                                    continue

                        return False

                    except Exception as e:
                        print(f"Error in fallback image serving for {tag}: {e}")
                        return False

                def _send_html_response(self, html):
                    """Send HTML response."""
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8'))

                def _handle_get_request(self):
                    """Handle GET requests for webviews and static files."""
                    parsed_url = urlparse(self.path)
                    path = parsed_url.path

                    if path.startswith('/static/'):
                        self._handle_static_request()
                    elif path.startswith('/webview/'):
                        self._handle_webview_request()
                    else:
                        self._send_error(404, "Not found")

                def _send_json_response(self, data):
                    """Send JSON response."""
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode('utf-8'))

                def _send_error(self, code, message):
                    """Send error response."""
                    self.send_response(code)
                    self.send_header('Content-Type', 'text/plain')
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.end_headers()
                    self.wfile.write(message.encode('utf-8'))

            # Create the HTTP server
            server = socketserver.TCPServer(('localhost', self.ports['http']), UnifiedHTTPHandler)
            server.unified_server = self  # Add reference to unified server
            self.http_server = server

            # Start server in background thread
            import threading
            server_thread = threading.Thread(target=server.serve_forever)
            server_thread.daemon = True
            server_thread.start()

            print(f"HTTP API server started on port {self.ports['http']}")

        except Exception as e:
            print(f"Failed to start HTTP server: {e}")
            self.http_server = None

    def _start_websocket_server(self):
        """Start WebSocket server for real-time communication."""
        try:
            # WebSocket server implementation would go here
            # For now, we'll skip WebSocket functionality
            print("WebSocket server functionality not implemented yet")
            self.websocket_server = None
            self.websocket_clients = []  # List to store connected clients
        except Exception as e:
            print(f"Failed to start WebSocket server: {e}")
            self.websocket_server = None
            self.websocket_clients = []

    def broadcast_websocket_message(self, message):
        """Broadcast message to all connected WebSocket clients."""
        try:
            # For now, just log the message since WebSocket is not implemented
            print(f"DEBUG: Would broadcast WebSocket message: {message}")

            # TODO: When WebSocket is implemented, broadcast to all clients
            # for client in self.websocket_clients:
            #     try:
            #         client.send(json.dumps(message))
            #     except Exception as e:
            #         print(f"Failed to send message to WebSocket client: {e}")
            #         self.websocket_clients.remove(client)

        except Exception as e:
            print(f"Error broadcasting WebSocket message: {e}")

    def _write_debug_info_file(self):
        """Write debug info file for extension discovery."""
        try:
            import tempfile
            import json
            import time

            debug_info = {
                'dap_port': self.ports['dap'],
                'http_port': self.ports['http'],
                'websocket_port': self.ports['websocket'],
                'status': 'running',
                'timestamp': int(time.time())
            }

            # Write to workspace directory if possible
            try:
                import renpy
                if hasattr(renpy, 'config') and hasattr(renpy.config, 'basedir'):
                    debug_info_path = os.path.join(renpy.config.basedir, '.renpy-debug-info.json')
                    with open(debug_info_path, 'w') as f:
                        json.dump(debug_info, f, indent=2)
            except:
                pass

            # Also write to temp directory as fallback
            temp_info_path = os.path.join(tempfile.gettempdir(), 'renpy-debug-info.json')
            with open(temp_info_path, 'w') as f:
                json.dump(debug_info, f, indent=2)

        except Exception as e:
            print(f"Warning: Failed to write debug info file: {e}")

    def _print_startup_info(self):
        """Print startup information to console."""
        print("\n🐛 Ren'Py Debug Server Started")
        print("=" * 40)
        print(f"   DAP Server:     localhost:{self.ports['dap']}")
        print(f"   HTTP API:       http://localhost:{self.ports['http']}")
        print(f"   WebSocket:      ws://localhost:{self.ports['websocket']}")
        print(f"   Scene Objects:  http://localhost:{self.ports['http']}/webview/scene-objects")
        print(f"   Visual Builder: http://localhost:{self.ports['http']}/webview/visual-builder")
        print(f"   API Docs:       http://localhost:{self.ports['http']}/docs")
        print("=" * 40)

    def stop(self):
        """Stop all servers."""
        print("Stopping unified debug server...")

        # Stop HTTP server
        if hasattr(self, 'http_server') and self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()

        # Stop WebSocket server
        if hasattr(self, 'websocket_server') and self.websocket_server:
            # WebSocket server cleanup would go here
            pass

        # Stop DAP server
        if hasattr(self, 'dap_server') and self.dap_server:
            self.dap_server.stop()

        print("Unified debug server stopped")

# Global server instance
_unified_server = None

def start_unified_debug_server(preferred_ports=None):
    """Start the unified debug server."""
    global _unified_server

    if _unified_server is not None:
        print("Unified debug server already running")
        return _unified_server

    try:
        _unified_server = UnifiedDebugServer(preferred_ports)
        _unified_server.start()
        return _unified_server
    except Exception as e:
        print(f"Failed to start unified debug server: {e}")
        return None

def stop_unified_debug_server():
    """Stop the unified debug server."""
    global _unified_server

    if _unified_server is None:
        return

    try:
        _unified_server.stop()
        _unified_server = None

        # Clean up renpy module reference
        try:
            if hasattr(renpy, '_unified_debug_server'):
                delattr(renpy, '_unified_debug_server')
        except:
            pass

    except Exception as e:
        print(f"Error stopping unified debug server: {e}")

def get_unified_debug_server():
    """Get the current unified debug server instance."""
    return _unified_server
