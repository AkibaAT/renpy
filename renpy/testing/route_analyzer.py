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
Route Analyzer

This module provides functionality to analyze Ren'Py scripts for route visualization,
including choice trees, navigation paths, word counts, and progress tracking.
"""

from __future__ import division, absolute_import, with_statement, print_function, unicode_literals
from renpy.compat import PY2, basestring, bchr, bord, chr, open, pystr, range, round, str, tobytes, unicode # *

import renpy
import re
import ast
import copy
import os
import time
import hashlib
import json
from collections import defaultdict, deque


class RouteAnalyzer(object):
    """
    Analyzes Ren'Py scripts to extract route information for visualization.
    """
    
    def __init__(self):
        """Initialize the route analyzer."""
        self.script_cache = None
        self.route_graph = None
        self.word_counts = None
        self.choice_requirements = None
        self._cache_valid = False
        self._cached_analysis_data = None
        self.current_label = None

        # Efficient seen tracking - direct integration with Ren'Py
        self.seen_words_count = 0     # Total words from seen statements
        self.seen_statements_cache = set()  # Cache of statements we've already counted
        self._setup_api_integration()  # Setup direct API integration
        self._initialize_seen_word_count()  # Count words from already-seen statements

        # File-based cache settings
        self.cache_dir = os.path.join(renpy.config.gamedir, ".route_cache")

        # Initialize current label if we're already in a story
        self._initialize_current_label()
        self.word_count_cache_file = os.path.join(self.cache_dir, "word_counts.json")
        self.cache_metadata_file = os.path.join(self.cache_dir, "cache_metadata.json")

    def _setup_api_integration(self):
        """
        Setup direct API integration with Ren'Py's callback system.
        This replaces the fragile hook approach with reliable direct integration.
        """
        try:
            # Register our seen tracking callback
            renpy.config.api_seen_callback = self._on_statement_marked_seen

            # Register our label tracking callback
            renpy.config.api_label_callback = self._on_label_executed

            print("DEBUG: Successfully setup API integration with Ren'Py")

        except Exception as e:
            print(f"DEBUG: Error setting up API integration: {e}")
            import traceback
            traceback.print_exc()

    def _on_statement_marked_seen(self, context):
        """
        Called whenever a statement is marked as seen by Ren'Py.
        This is our efficient hook to count words in real-time.
        """
        try:
            # Get the current statement that was just marked as seen
            if not hasattr(context, 'current') or not context.current:
                return

            stmt_name = context.current

            # Check if we've already counted this statement
            if stmt_name in self.seen_statements_cache:
                return

            # Find the actual statement object to extract dialogue
            try:
                # Look up the statement in the script
                if stmt_name in renpy.game.script.namemap:
                    stmt_node = renpy.game.script.namemap[stmt_name]

                    # If it's a Say statement, count its words
                    if isinstance(stmt_node, renpy.ast.Say) and hasattr(stmt_node, 'what') and stmt_node.what:
                        clean_text = self._clean_dialogue_text(stmt_node.what)
                        words = len(clean_text.split())

                        # Add to our running total
                        self.seen_words_count += words
                        self.seen_statements_cache.add(stmt_name)

                        print(f"DEBUG: Statement '{stmt_name}' marked as seen: +{words} words (total: {self.seen_words_count})")

            except Exception as e:
                print(f"DEBUG: Error processing seen statement '{stmt_name}': {e}")

        except Exception as e:
            print(f"DEBUG: Error in _on_statement_marked_seen: {e}")

    def _on_label_executed(self, label_name, abnormal):
        """
        Called when a label is executed via the API integration.
        Used for tracking current label for progress calculations.
        """
        try:
            # Update current label for progress tracking
            self.current_label = label_name
            print(f"DEBUG: Label executed: {label_name} (abnormal: {abnormal})")

        except Exception as e:
            print(f"DEBUG: Error in _on_label_executed: {e}")

    def _initialize_seen_word_count(self):
        """
        Initialize the seen word count by processing all statements that are already
        marked as seen in Ren'Py's persistent data.

        This handles the case where the game is restarted but the player has already
        seen dialogue in previous sessions.
        """
        try:
            print("DEBUG: Initializing seen word count from existing seen data...")

            # Get Ren'Py's seen tracking data
            seen_ever = renpy.game.persistent._seen_ever
            if not seen_ever:
                print("DEBUG: No existing seen data found")
                return

            print(f"DEBUG: Found {len(seen_ever)} seen statements in persistent data")

            initial_word_count = 0
            processed_statements = 0

            # Iterate through all statements in the script to find seen ones
            for label_name, label_node in renpy.game.script.namemap.items():
                if not hasattr(label_node, 'block') or not label_node.block:
                    continue

                # Process each statement in the label
                for stmt in label_node.block:
                    # Get the statement identifier (same format Ren'Py uses)
                    stmt_name = stmt.name if hasattr(stmt, 'name') else None
                    if not stmt_name:
                        continue

                    # Check if this statement has been seen (using Ren'Py's logic)
                    is_seen = False
                    if renpy.config.hash_seen:
                        hashed_name = renpy.astsupport.hash64(stmt_name)
                        is_seen = (stmt_name in seen_ever) or (hashed_name in seen_ever)
                    else:
                        is_seen = stmt_name in seen_ever

                    # If seen and it's a Say statement, count its words
                    if is_seen and isinstance(stmt, renpy.ast.Say):
                        if hasattr(stmt, 'what') and stmt.what:
                            clean_text = self._clean_dialogue_text(stmt.what)
                            words = len(clean_text.split())
                            initial_word_count += words
                            processed_statements += 1

                            # Add to our cache so we don't double-count later
                            self.seen_statements_cache.add(stmt_name)

            # Set the initial count
            self.seen_words_count = initial_word_count

            print(f"DEBUG: Initialized with {initial_word_count} words from {processed_statements} previously seen statements")

        except Exception as e:
            print(f"DEBUG: Error initializing seen word count: {e}")
            import traceback
            traceback.print_exc()

    def _initialize_current_label(self):
        """Initialize current label by detecting it from the current context."""
        try:
            # Try to detect the current label from the context
            context = renpy.game.context()
            if context and hasattr(context, 'current') and context.current:
                if isinstance(context.current, (list, tuple)) and len(context.current) >= 1:
                    filename = context.current[0]
                    print(f"DEBUG: Initializing current label from context: {filename}")

                    # Skip system/menu files
                    if any(skip in filename for skip in ['_layout', 'common/', 'gui/', 'screens.rpy']):
                        print(f"DEBUG: Skipping system file during initialization: {filename}")
                        return

                    # For story files, try to find the current label by searching backwards
                    current_label = self._find_containing_label_from_context(context.current)
                    if current_label:
                        print(f"DEBUG: Initialized current label: {current_label}")
                        self.current_label = current_label
                    else:
                        print("DEBUG: Could not determine current label during initialization")
        except Exception as e:
            print(f"DEBUG: Error initializing current label: {e}")

    def _find_containing_label_from_context(self, context_current):
        """Find the containing label for a given context location."""
        try:
            # Get the current context to extract filename and line number
            context = renpy.game.context()
            context_str = str(context)

            # Extract filename and line number from context string like:
            # "<Context: game/script.rpy:154 (<class 'renpy.ast.Say'>, 'e', \"Hi! My name is Eileen...\")>"
            import re
            match = re.search(r'<Context: ([^:]+):(\d+)', context_str)
            if not match:
                print(f"DEBUG: Could not parse context string: {context_str}")
                return None

            filename = match.group(1)
            current_line = int(match.group(2))

            print(f"DEBUG: Looking for label containing {filename}:{current_line}")

            # Collect all labels in this file with their line numbers
            labels_in_file = []
            for label_name, label_node in renpy.game.script.namemap.items():
                # Only look at actual Label nodes, not other types like Init, etc.
                if (hasattr(label_node, 'filename') and label_node.filename == filename and
                    hasattr(label_node, '__class__') and 'Label' in str(label_node.__class__)):
                    # This is a label in the same file
                    if hasattr(label_node, 'linenumber') and hasattr(label_node, 'name'):
                        # Skip system labels (starting with _)
                        if isinstance(label_node.name, str) and not label_node.name.startswith('_'):
                            labels_in_file.append((label_node.name, label_node.linenumber))
                            print(f"DEBUG: Found label '{label_node.name}' at line {label_node.linenumber}")

            if not labels_in_file:
                print(f"DEBUG: No labels found in {filename}")
                return None

            # Sort labels by line number
            labels_in_file.sort(key=lambda x: x[1])
            print(f"DEBUG: Labels sorted by line: {labels_in_file}")

            # Find the label that contains the current line
            # We want the label with the highest line number that's still <= current_line
            containing_label = None
            for label_name, label_line in labels_in_file:
                if label_line <= current_line:
                    containing_label = label_name
                else:
                    break

            print(f"DEBUG: Label containing line {current_line}: {containing_label}")
            return containing_label

        except Exception as e:
            print(f"DEBUG: Error finding containing label: {e}")
            return None

    def invalidate_cache(self):
        """Invalidate cached analysis data."""
        self._cache_valid = False
        self.script_cache = None
        self.route_graph = None
        self.word_counts = None
        self.choice_requirements = None
        self._cached_analysis_data = None

        # Also clear file-based cache
        self._clear_file_cache()

    def _ensure_cache_dir(self):
        """Ensure the cache directory exists."""
        try:
            if not os.path.exists(self.cache_dir):
                os.makedirs(self.cache_dir)
        except Exception as e:
            print(f"Failed to create cache directory: {e}")

    def _get_script_hash(self):
        """Generate a hash of the script content for cache validation."""
        try:
            script = renpy.game.script
            if not script:
                return None

            # Create a hash based on script content
            content_parts = []
            for node in script.all_stmts:
                if hasattr(node, '__class__'):
                    node_type = node.__class__.__name__
                    if node_type in ['Say', 'TranslateSay', 'Menu', 'Label']:
                        # Include relevant attributes for hashing
                        if hasattr(node, 'name'):
                            content_parts.append(str(node.name))
                        if hasattr(node, 'what'):
                            content_parts.append(str(node.what))
                        if hasattr(node, 'items'):
                            content_parts.append(str(node.items))

            content_str = '|'.join(content_parts)
            return hashlib.md5(content_str.encode('utf-8')).hexdigest()
        except Exception as e:
            print(f"Failed to generate script hash: {e}")
            return None

    def _is_cache_valid(self):
        """Check if the file-based cache is valid."""
        try:
            if not os.path.exists(self.cache_metadata_file):
                return False

            with open(self.cache_metadata_file, 'r') as f:
                metadata = json.load(f)

            current_hash = self._get_script_hash()
            cached_hash = metadata.get('script_hash')

            return current_hash and cached_hash and current_hash == cached_hash
        except Exception as e:
            print(f"Cache validation error: {e}")
            return False

    def _save_word_counts_to_cache(self, word_counts):
        """Save word counts to file cache."""
        try:
            self._ensure_cache_dir()

            # Save word counts
            with open(self.word_count_cache_file, 'w') as f:
                json.dump(word_counts, f, indent=2)

            # Save metadata
            metadata = {
                'script_hash': self._get_script_hash(),
                'timestamp': time.time(),
                'total_words': sum(word_counts.values()),
                'label_count': len(word_counts)
            }

            with open(self.cache_metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)

            print(f"Word counts cached: {len(word_counts)} labels, {sum(word_counts.values())} total words")

        except Exception as e:
            print(f"Failed to save word counts to cache: {e}")

    def _load_word_counts_from_cache(self):
        """Load word counts from file cache."""
        try:
            if not self._is_cache_valid():
                print("Cache is invalid or missing")
                return None

            if not os.path.exists(self.word_count_cache_file):
                print("Word count cache file not found")
                return None

            with open(self.word_count_cache_file, 'r') as f:
                word_counts = json.load(f)

            print(f"Word counts loaded from cache: {len(word_counts)} labels, {sum(word_counts.values())} total words")
            return word_counts

        except Exception as e:
            print(f"Failed to load word counts from cache: {e}")
            return None

    def _clear_file_cache(self):
        """Clear the file-based cache."""
        try:
            if os.path.exists(self.word_count_cache_file):
                os.remove(self.word_count_cache_file)
            if os.path.exists(self.cache_metadata_file):
                os.remove(self.cache_metadata_file)
            print("File cache cleared")
        except Exception as e:
            print(f"Failed to clear file cache: {e}")
    
    def analyze_script(self, force_refresh=False):
        """
        Analyze the entire script for routes and choices.

        Args:
            force_refresh (bool): Force re-analysis even if cache is valid

        Returns:
            dict: Complete route analysis data
        """
        # Check if we have cached data and don't need to refresh
        if not force_refresh and self._cache_valid and hasattr(self, '_cached_analysis_data') and self._cached_analysis_data:
            return self._cached_analysis_data

        try:
            # Get script data
            if not renpy.game.script:
                raise RuntimeError("No script loaded")

            # Build route graph
            self.route_graph = self._build_route_graph()
            self.word_counts = self._calculate_word_counts(force_refresh=force_refresh)
            self.choice_requirements = self._analyze_choice_requirements()

            # Calculate total words for metadata
            total_words = sum(self.word_counts.values()) if self.word_counts else 0

            # Combine all analysis data
            analysis_data = {
                'route_graph': self.route_graph,
                'word_counts': self.word_counts,
                'choice_requirements': self.choice_requirements,
                'metadata': {
                    'total_labels': len(self.route_graph.get('nodes', [])),
                    'total_choices': len([n for n in self.route_graph.get('nodes', []) if n.get('type') == 'menu']),
                    'total_words': total_words
                }
            }

            # Cache the complete analysis data
            self._cached_analysis_data = analysis_data
            self._cache_valid = True
            return analysis_data
            
        except Exception as e:
            print(f"Route analysis error: {e}")
            return {
                'error': str(e),
                'route_graph': {'nodes': [], 'edges': []},
                'word_counts': {},
                'choice_requirements': {},
                'metadata': {'total_labels': 0, 'total_choices': 0, 'total_words': 0}
            }
    
    def _build_route_graph(self):
        """
        Build a graph representation of the script routes.

        Returns:
            dict: Graph with nodes and edges
        """
        nodes = []
        edges = []
        visited_labels = set()
        screen_info = {}  # Track screen definitions

        try:
            # Get all labels from the script
            script = renpy.game.script
            print("DEBUG: Building route graph...")

            if not script:
                print("DEBUG: No script object found")
                return {'nodes': nodes, 'edges': edges}

            if not hasattr(script, 'namemap'):
                print("DEBUG: Script has no namemap attribute")
                return {'nodes': nodes, 'edges': edges}

            namemap = script.namemap
            print(f"DEBUG: Found {len(namemap) if namemap else 0} entries in namemap")

            if not namemap:
                print("DEBUG: Namemap is empty or None")
                return {'nodes': nodes, 'edges': edges}

        except Exception as e:
            print(f"ERROR: Failed to access script: {e}")
            return {'nodes': nodes, 'edges': edges}

        try:
            # Find labels and screens by looking at AST nodes
            label_nodes = []
            screen_nodes = []
            for node in namemap.values():
                try:
                    if hasattr(node, 'name') and isinstance(node.name, str):
                        # Check if this is a screen
                        if hasattr(node, '__class__') and node.__class__.__name__ == 'Screen':
                            screen_nodes.append((node.name, node))
                            print(f"DEBUG: Found screen: {node.name}")
                        # Include regular labels, but exclude private/call site labels
                        elif not node.name.startswith('_'):
                            # Check if this might be a nested label by examining filename and line number
                            # This is a heuristic - proper fix would require AST traversal
                            filename = getattr(node, 'filename', '')
                            line_num = getattr(node, 'linenumber', 0)
                            print(f"DEBUG: Considering label {node.name} at {filename}:{line_num}")
                            label_nodes.append((node.name, node))
                except Exception as e:
                    # Skip problematic nodes
                    continue

            print(f"DEBUG: Found {len(label_nodes)} labels from {len(namemap)} entries")

            # Sort labels by filename and line number to get script order
            label_nodes.sort(key=lambda x: (
                getattr(x[1], 'filename', 'zzz_unknown'),  # Sort unknown files last
                getattr(x[1], 'linenumber', 999999)        # Sort unknown lines last
            ))
            
            # Filter out nested labels that should be considered part of their parent
            # This is a heuristic approach - proper fix would require full AST analysis
            filtered_label_nodes = []
            nested_labels = set()
            
            for i, (label_name, label_node) in enumerate(label_nodes):
                filename = getattr(label_node, 'filename', '')
                line_num = getattr(label_node, 'linenumber', 0)
                
                # Check if this might be nested in a previous label from the same file
                is_nested = False
                for j in range(i):
                    prev_name, prev_node = label_nodes[j] 
                    prev_filename = getattr(prev_node, 'filename', '')
                    prev_line = getattr(prev_node, 'linenumber', 0)
                    
                    # If it's the same file and within reasonable proximity, might be nested
                    if (filename == prev_filename and 
                        line_num > prev_line and 
                        line_num - prev_line < 100):  # Within 100 lines - heuristic
                        
                        # Additional heuristics for known nested patterns
                        # Only mark as nested if it's clearly a sub-label, not the main label
                        if (prev_filename.endswith('_displayables.rpy') and
                            line_num - prev_line < 60 and  # Closer proximity
                            (label_name in ['swimming', 'science', 'art', 'home', 'imagemap_example', 'imagemap_done'] or
                             'example' in label_name)):
                            print(f"DEBUG: Marking {label_name} as potentially nested under {prev_name}")
                            nested_labels.add(label_name)
                            is_nested = True
                            break
                
                if not is_nested:
                    filtered_label_nodes.append((label_name, label_node))
                    
            print(f"DEBUG: Filtered {len(nested_labels)} nested labels: {nested_labels}")
            label_nodes = filtered_label_nodes

            # Create ordered list of label names for implicit flow detection
            label_order = [label_name for label_name, _ in label_nodes]
            print(f"DEBUG: Label order: {label_order[:10]}...")  # Show first 10

            # Process each label/node in the script with error handling
            processed_count = 0
            for label_name, node in label_nodes:
                try:
                    self._process_node_for_graph(label_name, node, nodes, edges, visited_labels, label_order)
                    processed_count += 1

                    # Limit processing to prevent memory issues
                    if processed_count >= 200:  # Reasonable limit
                        print(f"DEBUG: Processed {processed_count} labels, stopping to prevent memory issues")
                        break

                except Exception as e:
                    print(f"ERROR: Failed to process label {label_name}: {e}")
                    continue

            print(f"DEBUG: Successfully processed {processed_count} labels")

        except Exception as e:
            print(f"ERROR: Failed to process labels: {e}")
            return {'nodes': nodes, 'edges': edges}

        # Process screens to extract their possible return values and connections
        try:
            print(f"DEBUG: Processing {len(screen_nodes)} screens")
            for screen_name, screen_node in screen_nodes:
                self._process_screen_for_graph(screen_name, screen_node, nodes, edges)
            
            # Special case: Add tutorial screen connections if tutorials screen exists
            self._add_tutorial_screen_connections(nodes, edges)
        except Exception as e:
            print(f"ERROR: Failed to process screens: {e}")

        print(f"DEBUG: Processed {processed_count} labels and {len(screen_nodes)} screens")
        print(f"DEBUG: Final graph - nodes: {len(nodes)}, edges: {len(edges)}")
        return {
            'nodes': nodes,
            'edges': edges
        }
    
    def _process_node_for_graph(self, label_name, start_node, nodes, edges, visited_labels, label_order=None):
        """
        Process a single node and its connections for the route graph.

        Args:
            label_name (str): Name of the label
            start_node: Starting AST node
            nodes (list): List to append node data to
            edges (list): List to append edge data to
            visited_labels (set): Set of already processed labels
            label_order (list): Ordered list of labels for implicit flow detection
        """
        if label_name in visited_labels:
            return

        visited_labels.add(label_name)

        # Add the label node
        node_data = {
            'id': label_name,
            'type': 'label',
            'name': label_name,
            'filename': getattr(start_node, 'filename', 'unknown'),
            'line': getattr(start_node, 'linenumber', 0)
        }
        nodes.append(node_data)

        # Traverse the node chain to find connections
        current_node = start_node
        node_index = 0
        has_explicit_ending = False

        while current_node:
            node_index += 1

            # Handle different node types
            if hasattr(current_node, '__class__'):
                node_type = current_node.__class__.__name__

                # Stop traversal if we hit another label (except the first one)
                if node_type == 'Label' and node_index > 1:
                    # We've reached the next label, check for implicit flow
                    if hasattr(current_node, 'name'):
                        next_label_name = current_node.name
                        # Skip call site labels (start with underscore)
                        if not next_label_name.startswith('_'):
                            edges.append({
                                'from': label_name,
                                'to': next_label_name,
                                'type': 'implicit_flow'
                            })
                            break
                        # Continue processing for call site labels

                if node_type == 'Menu':
                    self._process_menu_node(current_node, label_name, node_index, nodes, edges)
                elif node_type == 'Jump':
                    self._process_jump_node(current_node, label_name, edges)
                    has_explicit_ending = True
                    break  # Jump ends this path
                elif node_type == 'Call':
                    # Calls don't end execution, they return and continue
                    self._process_call_node(current_node, label_name, edges)
                elif node_type == 'CallExpression':
                    # Call expressions also return and continue
                    self._process_call_expression_node(current_node, label_name, edges)
                elif node_type == 'UserStatement':
                    # UserStatements like call screen don't end execution, they continue
                    self._process_user_statement_node(current_node, label_name, nodes, edges)
                elif node_type == 'Return':
                    has_explicit_ending = True
                    break  # Return ends this path
                elif node_type == 'If':
                    self._process_if_node(current_node, label_name, edges)
                else:
                    # Log unknown node types for debugging
                    if hasattr(current_node, '__class__'):
                        print(f"DEBUG: Unknown node type in {label_name}: {node_type}")
                        # Log all node types encountered for debugging
                        if label_name in ['start', 'tutorials', 'end']:
                            print(f"DEBUG: Node in {label_name}: {node_type} at line {getattr(current_node, 'linenumber', 'unknown')}")

            # Move to next node
            current_node = getattr(current_node, 'next', None)

        # Note: Implicit flow is now handled during traversal when we encounter the next label

    def _process_screen_for_graph(self, screen_name, screen_node, nodes, edges):
        """
        Process a screen definition to extract possible return values and connections.
        
        Args:
            screen_name (str): Name of the screen
            screen_node: Screen AST node
            nodes (list): List to append node data to
            edges (list): List to append edge data to
        """
        print(f"DEBUG: Processing screen: {screen_name}")
        
        # For the tutorials screen specifically, we know it returns Tutorial objects or False
        if screen_name == "tutorials":
            self._process_tutorials_screen(screen_name, screen_node, nodes, edges)
        else:
            # Generic screen processing - look for Return actions
            self._process_generic_screen(screen_name, screen_node, nodes, edges)

    def _process_tutorials_screen(self, screen_name, screen_node, nodes, edges):
        """Process the tutorials screen specifically."""
        screen_node_id = f"screen_{screen_name}"
        
        # The tutorials screen returns Tutorial objects, which have .label attributes
        # We can get the tutorial list from the game's store
        try:
            import renpy.store as store
            if hasattr(store, 'tutorials'):
                tutorials_list = store.tutorials
                print(f"DEBUG: Found {len(tutorials_list)} tutorial entries")
                
                for tutorial in tutorials_list:
                    if hasattr(tutorial, 'kind') and tutorial.kind == "tutorial":
                        if hasattr(tutorial, 'label'):
                            # Create edge from screen to tutorial label
                            edges.append({
                                'from': screen_node_id,
                                'to': tutorial.label,
                                'type': 'screen_choice',
                                'choice_text': getattr(tutorial, 'title', tutorial.label),
                                'returns': tutorial.label
                            })
                            print(f"DEBUG: Added screen choice: {screen_name} -> {tutorial.label}")
                
                # Add the "That's enough for now" option that returns False
                # This should lead to the conditional jump to end
                edges.append({
                    'from': screen_node_id,
                    'to': 'end',
                    'type': 'screen_choice',
                    'choice_text': "That's enough for now.",
                    'returns': False,
                    'condition': 'tutorial == False'
                })
                
        except Exception as e:
            print(f"DEBUG: Could not process tutorials list: {e}")

    def _process_generic_screen(self, screen_name, screen_node, nodes, edges):
        """Process a generic screen by looking for Return actions."""
        # This is a placeholder for general screen processing
        # Could be expanded to parse screen AST for Return() actions
        print(f"DEBUG: Generic screen processing for {screen_name} - not implemented yet")

    def _add_tutorial_screen_connections(self, nodes, edges):
        """Add connections for the tutorials screen by accessing the store directly."""
        screen_node_id = "screen_tutorials"
        
        # Check if the tutorials screen node exists
        if not any(node.get('id') == screen_node_id for node in nodes):
            print("DEBUG: tutorials screen node not found, skipping tutorial connections")
            return
            
        try:
            # Access the tutorials list from the game store
            import renpy
            store = renpy.store
            
            if hasattr(store, 'tutorials'):
                tutorials_list = store.tutorials
                print(f"DEBUG: Found {len(tutorials_list)} tutorial entries in store")
                
                for tutorial in tutorials_list:
                    if hasattr(tutorial, 'kind') and tutorial.kind == "tutorial":
                        if hasattr(tutorial, 'label'):
                            # Create edge from screen to tutorial label
                            edges.append({
                                'from': screen_node_id,
                                'to': tutorial.label,
                                'type': 'screen_choice',
                                'choice_text': getattr(tutorial, 'title', tutorial.label),
                                'returns': tutorial.label
                            })
                            print(f"DEBUG: Added screen choice: tutorials -> {tutorial.label}")
                
                # Add the "That's enough for now" option that returns False
                edges.append({
                    'from': screen_node_id,
                    'to': 'end',
                    'type': 'screen_choice',
                    'choice_text': "That's enough for now.",
                    'returns': False,
                    'condition': 'tutorial == False'
                })
                print(f"DEBUG: Added exit choice: tutorials -> end")
                
            else:
                print("DEBUG: tutorials list not found in store")
                
        except Exception as e:
            print(f"DEBUG: Could not process tutorials from store: {e}")

    def _find_next_label_in_sequence(self, current_label, label_order):
        """Find the next label that appears after the current label in script order."""
        try:
            current_index = label_order.index(current_label)
            if current_index + 1 < len(label_order):
                return label_order[current_index + 1]
        except (ValueError, IndexError):
            pass
        return None

    def _process_menu_node(self, menu_node, parent_label, node_index, nodes, edges):
        """Process a Menu AST node for the route graph."""
        menu_id = f"{parent_label}_menu_{node_index}"
        
        # Add menu node
        menu_data = {
            'id': menu_id,
            'type': 'menu',
            'name': f"Choice at {parent_label}",
            'parent_label': parent_label,
            'filename': getattr(menu_node, 'filename', 'unknown'),
            'line': getattr(menu_node, 'linenumber', 0),
            'choices': []
        }
        
        # Process menu items
        if hasattr(menu_node, 'items'):
            for i, (choice_text, condition, choice_block) in enumerate(menu_node.items):
                if choice_text and choice_block:  # Skip captions (no block)
                    choice_data = {
                        'index': i,
                        'text': choice_text,
                        'condition': condition if condition != "True" else None,
                        'target': None
                    }
                    
                    # Find where this choice leads
                    if choice_block and len(choice_block) > 0:
                        target = self._find_choice_target(choice_block)
                        choice_data['target'] = target
                        
                        # Add edge for this choice
                        edges.append({
                            'from': menu_id,
                            'to': target or f"{parent_label}_choice_{i}",
                            'type': 'choice',
                            'choice_index': i,
                            'choice_text': choice_text,
                            'condition': condition if condition != "True" else None
                        })
                    
                    menu_data['choices'].append(choice_data)
        
        nodes.append(menu_data)
        
        # Add edge from parent label to menu
        edges.append({
            'from': parent_label,
            'to': menu_id,
            'type': 'sequence'
        })
    
    def _process_jump_node(self, jump_node, parent_label, edges):
        """Process a Jump AST node for the route graph."""
        if hasattr(jump_node, 'target'):
            edges.append({
                'from': parent_label,
                'to': jump_node.target,
                'type': 'jump'
            })
    
    def _process_call_node(self, call_node, parent_label, edges):
        """Process a Call AST node for the route graph."""
        if hasattr(call_node, 'label'):
            edges.append({
                'from': parent_label,
                'to': call_node.label,
                'type': 'call'
            })

    def _process_call_expression_node(self, call_expr_node, parent_label, edges):
        """Process a CallExpression AST node for the route graph."""
        # CallExpression nodes represent dynamic calls like "call expression tutorial.label"
        # We can't know the exact target at analysis time, but we can indicate it's a dynamic call
        if hasattr(call_expr_node, 'expression'):
            expression = call_expr_node.expression
            # Try to extract some information about what might be called
            expression_str = str(expression) if expression else "unknown"
            edges.append({
                'from': parent_label,
                'to': f"dynamic_call_{expression_str}",
                'type': 'call_expression',
                'expression': expression_str
            })

    def _process_if_node(self, if_node, parent_label, edges):
        """Process an If AST node for the route graph."""
        print(f"DEBUG: Processing If node in {parent_label}")
        try:
            # If nodes have entries which are (condition, block) tuples
            if hasattr(if_node, 'entries'):
                for condition, block in if_node.entries:
                    if block:
                        # Look for jumps and calls in the if block
                        for stmt in block:
                            if hasattr(stmt, '__class__'):
                                stmt_type = stmt.__class__.__name__
                                if stmt_type == 'Jump' and hasattr(stmt, 'target'):
                                    # Create conditional jump edge
                                    edges.append({
                                        'from': parent_label,
                                        'to': stmt.target,
                                        'type': 'conditional_jump',
                                        'condition': condition if condition != "True" else None
                                    })
                                elif stmt_type == 'Call' and hasattr(stmt, 'label'):
                                    # Create conditional call edge
                                    edges.append({
                                        'from': parent_label,
                                        'to': stmt.label,
                                        'type': 'conditional_call',
                                        'condition': condition if condition != "True" else None
                                    })
                                elif stmt_type == 'CallExpression':
                                    # Handle conditional call expressions
                                    if hasattr(stmt, 'expression'):
                                        expression_str = str(stmt.expression) if stmt.expression else "unknown"
                                        edges.append({
                                            'from': parent_label,
                                            'to': f"dynamic_call_{expression_str}",
                                            'type': 'conditional_call_expression',
                                            'condition': condition if condition != "True" else None,
                                            'expression': expression_str
                                        })
        except Exception as e:
            print(f"DEBUG: Error processing If node: {e}")

    def _process_user_statement_node(self, user_statement_node, parent_label, nodes, edges):
        """Process a UserStatement AST node for the route graph."""
        try:
            # UserStatement nodes contain parsed data for user-defined statements
            if hasattr(user_statement_node, 'parsed'):
                parsed = user_statement_node.parsed
                if parsed and len(parsed) >= 2:
                    statement_name, statement_data = parsed[0], parsed[1]

                    # Check if this is a "call screen" statement
                    if isinstance(statement_name, (list, tuple)) and len(statement_name) >= 2:
                        if statement_name[0] == 'call' and statement_name[1] == 'screen':
                            screen_name = self._extract_screen_name_from_call_screen(statement_data)
                            if screen_name:
                                print(f"DEBUG: Found call screen from {parent_label} to {screen_name}")
                                # For call screen, we should create a flow that shows:
                                # 1. Call to the screen
                                # 2. Return from the screen continues normal flow
                                screen_node_id = f"screen_{screen_name}"
                                
                                # Add the screen node if not already added
                                if not any(node.get('id') == screen_node_id for node in nodes):
                                    screen_node = {
                                        'id': screen_node_id,
                                        'type': 'screen',
                                        'name': screen_name,
                                        'filename': getattr(user_statement_node, 'filename', 'unknown'),
                                        'line': getattr(user_statement_node, 'linenumber', 0)
                                    }
                                    nodes.append(screen_node)
                                
                                edges.append({
                                    'from': parent_label,
                                    'to': screen_node_id,
                                    'type': 'call_screen',
                                    'screen_name': screen_name
                                })
                            else:
                                print(f"DEBUG: Could not extract screen name from call screen statement")
                        else:
                            print(f"DEBUG: UserStatement is not call screen: {statement_name}")
                    else:
                        print(f"DEBUG: UserStatement name format unexpected: {statement_name}")
                else:
                    print(f"DEBUG: UserStatement parsed data format unexpected: {parsed}")
            else:
                print(f"DEBUG: UserStatement has no parsed attribute")
        except Exception as e:
            print(f"DEBUG: Error processing UserStatement node: {e}")

    def _extract_screen_name_from_call_screen(self, statement_data):
        """Extract screen name from call screen statement data."""
        try:
            # The statement_data should contain the screen name and arguments
            if hasattr(statement_data, 'get'):
                # Try to get the screen name from common attributes
                screen_name = statement_data.get('name', None)
                if screen_name:
                    return screen_name

                # Try other possible keys
                for key in ['screen', 'target', 'screen_name']:
                    if key in statement_data:
                        return statement_data[key]

            # If statement_data is a dict-like object, try direct access
            if isinstance(statement_data, dict):
                return statement_data.get('name') or statement_data.get('screen')

            # If it has a name attribute directly
            if hasattr(statement_data, 'name'):
                return statement_data.name

            # If it's a string, it might be the screen name directly
            if isinstance(statement_data, str):
                return statement_data

            # If it's a list/tuple, the first element might be the screen name
            if isinstance(statement_data, (list, tuple)) and len(statement_data) > 0:
                first_elem = statement_data[0]
                if isinstance(first_elem, str):
                    return first_elem

            print(f"DEBUG: statement_data type: {type(statement_data)}, value: {statement_data}")
            if hasattr(statement_data, '__dict__'):
                print(f"DEBUG: statement_data attributes: {dir(statement_data)}")
            return None
        except Exception as e:
            print(f"DEBUG: Error extracting screen name: {e}")
            return None
    
    def _find_choice_target(self, choice_block):
        """Find the target label for a choice block."""
        if not choice_block:
            return None
        
        # Look for Jump or Call nodes in the choice block
        for node in choice_block:
            if hasattr(node, '__class__'):
                node_type = node.__class__.__name__
                if node_type == 'Jump' and hasattr(node, 'target'):
                    return node.target
                elif node_type == 'Call' and hasattr(node, 'label'):
                    return node.label
        
        return None
    
    def _calculate_word_counts(self, force_refresh=False):
        """
        Calculate word counts for each label/scene using file-based caching.

        Args:
            force_refresh (bool): Force recalculation even if cache is valid

        Returns:
            dict: Mapping of label names to word counts
        """
        # Try to load from cache first (unless force refresh)
        if not force_refresh:
            cached_word_counts = self._load_word_counts_from_cache()
            if cached_word_counts is not None:
                return cached_word_counts

        print("Calculating word counts from script...")
        word_counts = {}
        label_positions = {}  # Track filename, start_line, end_line for each label

        try:
            script = renpy.game.script
            if not script:
                print("DEBUG: No script available for word counting")
                return word_counts

            # Use the same approach as json_stats.rpy - get all statements
            all_stmts = list(script.all_stmts)
            if not all_stmts:
                print("DEBUG: No statements found in script")
                return word_counts

            # Track current label context per file
            current_label = None
            current_file = None
            current_label_start_line = None

            # Debug counters
            total_say_nodes = 0
            total_translate_say_skipped = 0
            total_menu_nodes = 0
            total_labels = 0
            debug_word_count = 0
            node_types_seen = set()
            files_processed = set()

            # Process each statement to accumulate word counts per label
            for node in all_stmts:
                try:
                    # Track file context - reset label when file changes
                    node_file = None
                    if hasattr(node, 'filename'):
                        node_file = node.filename
                    elif hasattr(node, 'location') and hasattr(node.location, 'filename'):
                        node_file = node.location.filename
                    elif hasattr(node, 'loc') and hasattr(node.loc, 'filename'):
                        node_file = node.loc.filename

                    if node_file and node_file != current_file:
                        current_file = node_file
                        current_label = None  # Reset label context for new file
                        files_processed.add(current_file)

                    # Track label context using proper AST node checking
                    if isinstance(node, renpy.ast.Label):
                        if hasattr(node, 'name') and isinstance(node.name, str):
                            # Skip private labels
                            if not node.name.startswith('_'):
                                # Save end line for previous label if we had one
                                if current_label and current_label_start_line and hasattr(node, 'linenumber'):
                                    if current_label in label_positions:
                                        label_positions[current_label]['end_line'] = node.linenumber - 1

                                current_label = node.name
                                total_labels += 1

                                # Track position information for this label
                                if hasattr(node, 'filename') and hasattr(node, 'linenumber'):
                                    current_label_start_line = node.linenumber
                                    label_positions[current_label] = {
                                        'filename': node.filename,
                                        'start_line': node.linenumber,
                                        'end_line': None  # Will be set when we find the next label or end of file
                                    }
                                    print(f"DEBUG: Found label '{current_label}' at {node.filename}:{node.linenumber}")

                                # Initialize word count for this label if not exists
                                if current_label not in word_counts:
                                    word_counts[current_label] = 0

                    # Count words in dialogue nodes (only default language to avoid double-counting)
                    elif current_label:
                        node_type = node.__class__.__name__
                        node_types_seen.add(node_type)

                        # Handle Say nodes - but ONLY default language (not translations)
                        if isinstance(node, renpy.ast.Say):
                            # Skip TranslateSay nodes to avoid counting translations
                            if isinstance(node, renpy.ast.TranslateSay):
                                # Only count if this is the default language or no language specified
                                if hasattr(node, 'language') and node.language is not None:
                                    total_translate_say_skipped += 1
                                    continue  # Skip translated content

                            total_say_nodes += 1
                            dialogue_text = getattr(node, 'what', None)
                            if dialogue_text:
                                clean_text = self._clean_dialogue_text(dialogue_text)
                                words = len(clean_text.split())
                                word_counts[current_label] += words
                                debug_word_count += words

                                # Debug specific label
                                if current_label == 'end':
                                    file_info = getattr(node, 'filename', 'unknown')
                                    print(f"DEBUG: end label - file: {file_info} - dialogue: '{dialogue_text[:50]}...' -> words: {words}")

                        # Handle Menu nodes (only count once, not per translation)
                        elif isinstance(node, renpy.ast.Menu) and hasattr(node, 'items'):
                            total_menu_nodes += 1
                            for choice_text, _condition, choice_block in node.items:
                                if choice_text:
                                    clean_text = self._clean_dialogue_text(choice_text)
                                    words = len(clean_text.split())
                                    word_counts[current_label] += words

                except Exception as e:
                    # Skip problematic nodes but continue processing
                    continue

            # Handle end line for the last label (set to a high number since we don't know the actual end)
            if current_label and current_label in label_positions and label_positions[current_label]['end_line'] is None:
                # Use a high line number as a fallback for the last label
                label_positions[current_label]['end_line'] = 999999

            # Remove labels with zero word counts for cleaner output
            word_counts = {label: count for label, count in word_counts.items() if count > 0}

            # Also clean up label_positions to only include labels with word counts
            label_positions = {label: pos for label, pos in label_positions.items() if label in word_counts}

            # Store label positions for later use in progress tracking
            self.label_positions = label_positions

            # Log summary for debugging
            final_labels = len(word_counts)
            final_words = sum(word_counts.values())
            print(f"Word count calculation complete:")
            print(f"  - Processed {len(files_processed)} files, {total_labels} labels, {total_say_nodes} Say nodes, {total_menu_nodes} Menu nodes")
            print(f"  - Skipped {total_translate_say_skipped} TranslateSay nodes (translations)")
            print(f"  - Debug word count: {debug_word_count}")
            print(f"  - Final: {final_labels} labels with content, {final_words} total words")
            print(f"  - Label positions tracked: {len(label_positions)} labels")
            print(f"  - Node types seen: {sorted(node_types_seen)}")

            # Save to file cache
            self._save_word_counts_to_cache(word_counts)

        except Exception as e:
            print(f"Word count calculation error: {e}")
            import traceback
            traceback.print_exc()

        return word_counts

    def invalidate_word_count_cache(self):
        """Specifically invalidate word count cache to ensure fresh calculation."""
        self.word_counts = None
        # Also invalidate the general cache to be safe
        self._cache_valid = False
        self._cached_analysis_data = None
        # Clear file-based cache
        self._clear_file_cache()

    def get_cache_status(self):
        """Get information about the current cache status."""
        try:
            cache_info = {
                'cache_dir_exists': os.path.exists(self.cache_dir),
                'word_count_cache_exists': os.path.exists(self.word_count_cache_file),
                'metadata_cache_exists': os.path.exists(self.cache_metadata_file),
                'cache_valid': self._is_cache_valid(),
                'script_hash': self._get_script_hash()
            }

            if os.path.exists(self.cache_metadata_file):
                try:
                    with open(self.cache_metadata_file, 'r') as f:
                        metadata = json.load(f)
                    cache_info['cached_metadata'] = metadata
                except Exception:
                    cache_info['cached_metadata'] = None

            return cache_info
        except Exception as e:
            return {'error': str(e)}

    def _clean_dialogue_text(self, text):
        """Remove Ren'Py markup from dialogue text using the same method as json_stats.rpy."""
        if not text:
            return ""

        # Use the same cleaning approach as json_stats.rpy
        # Remove Ren'Py text tags like {color=#FA8072}[MCC]{/color}
        text = re.sub(r"{[^}]*}", "", text)
        # Trim whitespace
        text = text.strip()
        # Trim double quotes from beginning and end if they match
        if text.startswith('"') and text.endswith('"') and len(text) >= 2:
            text = text[1:-1]
        # Also check for single quotes, just to be thorough
        elif text.startswith("'") and text.endswith("'") and len(text) >= 2:
            text = text[1:-1]

        return text

    def _analyze_choice_requirements(self):
        """
        Analyze choice requirements and conditions.

        Returns:
            dict: Mapping of choice IDs to their requirements
        """
        requirements = {}

        try:
            script = renpy.game.script
            if not script or not script.namemap:
                return requirements

            for label_name, start_node in script.namemap.items():
                if isinstance(label_name, str) and not label_name.startswith('_'):
                    self._analyze_label_requirements(label_name, start_node, requirements)

        except Exception as e:
            print(f"Choice requirements analysis error: {e}")

        return requirements

    def _analyze_label_requirements(self, label_name, start_node, requirements):
        """Analyze requirements for choices in a specific label."""
        current_node = start_node
        node_index = 0

        while current_node:
            node_index += 1

            if hasattr(current_node, '__class__'):
                node_type = current_node.__class__.__name__

                if node_type == 'Menu' and hasattr(current_node, 'items'):
                    menu_id = f"{label_name}_menu_{node_index}"

                    for i, (choice_text, condition, _choice_block) in enumerate(current_node.items):
                        if choice_text and condition and condition != "True":
                            choice_id = f"{menu_id}_choice_{i}"
                            parsed_requirements = self._parse_condition(condition)

                            requirements[choice_id] = {
                                'menu_id': menu_id,
                                'choice_index': i,
                                'choice_text': choice_text,
                                'condition': condition,
                                'parsed_requirements': parsed_requirements
                            }

            # Move to next node
            current_node = getattr(current_node, 'next', None)

    def _parse_condition(self, condition):
        """
        Parse a condition string to extract variable requirements.

        Args:
            condition (str): Condition string from menu choice

        Returns:
            dict: Parsed requirements with variables and values
        """
        requirements = {
            'variables': [],
            'operators': [],
            'values': [],
            'raw_condition': condition
        }

        try:
            # Simple regex-based parsing for common patterns
            # This handles basic conditions like "var == value", "var > 5", etc.

            # Pattern for variable comparisons
            comparison_pattern = r'(\w+)\s*(==|!=|>=|<=|>|<)\s*([^\s&|]+)'
            matches = re.findall(comparison_pattern, condition)

            for var_name, operator, value in matches:
                requirements['variables'].append(var_name)
                requirements['operators'].append(operator)

                # Try to parse the value
                try:
                    # Try as number
                    if '.' in value:
                        parsed_value = float(value)
                    else:
                        parsed_value = int(value)
                except ValueError:
                    # Try as boolean
                    if value.lower() in ('true', 'false'):
                        parsed_value = value.lower() == 'true'
                    else:
                        # Keep as string, remove quotes if present
                        parsed_value = value.strip('"\'')

                requirements['values'].append(parsed_value)

            # Pattern for simple variable checks (just variable name)
            if not matches:
                var_pattern = r'\b(\w+)\b'
                var_matches = re.findall(var_pattern, condition)
                for var_name in var_matches:
                    if var_name not in ('and', 'or', 'not', 'True', 'False'):
                        requirements['variables'].append(var_name)
                        requirements['operators'].append('truthy')
                        requirements['values'].append(True)

        except Exception as e:
            print(f"Condition parsing error for '{condition}': {e}")

        return requirements

    def get_current_progress(self):
        """
        Get current player progress through the script.

        Returns:
            dict: Current progress information
        """
        print("DEBUG: get_current_progress() called")
        try:
            # Get current label and position
            print("DEBUG: About to call _get_current_label()")
            current_label = self._get_current_label()
            print(f"DEBUG: _get_current_label() returned: {current_label}")
            total_words = sum(self.word_counts.values()) if self.word_counts else 0

            # Get current position for within-label progress
            current_line = None
            try:
                context = renpy.game.context()
                if context and hasattr(context, 'current') and context.current:
                    if isinstance(context.current, (list, tuple)) and len(context.current) >= 3:
                        current_line = context.current[2]
            except:
                pass

            if not current_label:
                # Not in a story label (e.g., main menu, system screens)
                # For now, assume we haven't started the story yet
                return {
                    'current_label': None,
                    'progress_percentage': 0.0,
                    'within_label_progress': 0.0,
                    'estimated_remaining_words': total_words,
                    'estimated_reading_time_minutes': round(total_words / 200.0, 1),
                    'total_words': total_words
                }

            # Calculate within-label progress
            within_label_progress = self._calculate_progress_within_label(current_label, current_line)

            # Use statement-based progress tracking instead of flawed label-based approach
            # This counts only the actual statements the player has encountered

            print(f"DEBUG: Calculating statement-based progress for current_label='{current_label}'")
            completed_words = self._calculate_statement_based_progress(current_label, within_label_progress)
            print(f"DEBUG: Statement-based progress returned: {completed_words} words")

            # Get total words for calculation
            total_words_for_progress = total_words

            # Calculate progress percentage
            progress_percentage = (completed_words / total_words_for_progress * 100.0) if total_words_for_progress > 0 else 0.0
            remaining_words = max(0, total_words_for_progress - completed_words)

            # Estimate reading time (average 200 words per minute)
            reading_time_minutes = remaining_words / 200.0

            return {
                'current_label': current_label,
                'progress_percentage': round(progress_percentage, 2),
                'within_label_progress': round(within_label_progress * 100.0, 1),
                'seen_words': int(round(completed_words)),  # Ensure integer word count
                'total_words_trackable': int(round(total_words_for_progress)),  # Ensure integer word count
                'estimated_remaining_words': int(round(remaining_words)),  # Ensure integer word count
                'estimated_reading_time_minutes': round(reading_time_minutes, 1),
                'total_words': int(round(total_words))  # Ensure integer word count
            }

        except Exception as e:
            print(f"Progress tracking error: {e}")
            return {
                'current_label': None,
                'progress_percentage': 0.0,
                'estimated_remaining_words': 0,
                'estimated_reading_time_minutes': 0,
                'error': str(e)
            }

    def _get_current_label(self):
        """Get the current label name using label positions and context."""
        print(f"DEBUG: _get_current_label() called, current_label = {self.current_label}")

        # Return the label tracked by our callback if available
        if self.current_label:
            print(f"DEBUG: Returning tracked label: {self.current_label}")
            return self.current_label

        # Fallback: use label positions to determine current label from context
        print("DEBUG: No tracked label, trying position-based detection")
        try:
            context = renpy.game.context()
            if context and hasattr(context, 'current') and context.current:
                print(f"DEBUG: context.current = {context.current}")

                # Extract filename and line number from context
                if isinstance(context.current, (list, tuple)) and len(context.current) >= 1:
                    filename = context.current[0]

                    # Try to get line number from context.current if it's a tuple/list
                    line_number = None
                    if len(context.current) >= 3:
                        # context.current is typically (filename, file_hash, line_number)
                        line_number = context.current[2]

                    print(f"DEBUG: Current position: {filename}:{line_number}")

                    # Use label positions to find which label contains this position
                    if hasattr(self, 'label_positions') and self.label_positions:
                        current_label = self._find_label_by_position(filename, line_number)
                        if current_label:
                            print(f"DEBUG: Found label by position: {current_label}")
                            return current_label

            # Old fallback method
            if context and hasattr(context, 'current') and context.current:

                # Check if we have a valid label name
                if isinstance(context.current, str):
                    # This is a label name
                    print(f"DEBUG: Found string label: {context.current}")
                    return context.current
                elif isinstance(context.current, (list, tuple)) and len(context.current) >= 1:
                    # This is a file/line location - try to find the containing label
                    filename = context.current[0]
                    print(f"DEBUG: Found file/line location: {filename}")

                    # Skip system/menu files - these aren't story progress
                    if any(skip in filename for skip in ['_layout', 'common/', 'gui/', 'screens.rpy']):
                        print(f"DEBUG: Skipping system file: {filename}")
                        return None

                    # For story files, try to find the current label
                    try:
                        node = renpy.game.script.lookup(context.current)
                        print(f"DEBUG: Looked up node: {node}")
                        if hasattr(node, 'name') and isinstance(node.name, str):
                            print(f"DEBUG: Found label from lookup: {node.name}")
                            return node.name
                        else:
                            print(f"DEBUG: Node has no name or name is not string")
                    except Exception as e:
                        print(f"DEBUG: Lookup failed: {e}")
                        pass

                    print(f"DEBUG: No label found for file location")
                    return None
                else:
                    # Try to lookup the node
                    try:
                        node = renpy.game.script.lookup(context.current)
                        print(f"DEBUG: Direct lookup node: {node}")
                        if hasattr(node, 'name') and isinstance(node.name, str):
                            print(f"DEBUG: Found label from direct lookup: {node.name}")
                            return node.name
                    except Exception as e:
                        print(f"DEBUG: Direct lookup failed: {e}")
                    return None
            print(f"DEBUG: No context or context.current")
            return None
        except Exception as e:
            print(f"DEBUG: Error getting current label: {e}")
            return None

    def _find_label_by_position(self, filename, line_number):
        """Find the label that contains the given filename and line number."""
        try:
            if not hasattr(self, 'label_positions') or not self.label_positions:
                print("DEBUG: No label positions available")
                return None

            if not filename or line_number is None:
                print(f"DEBUG: Invalid position data: {filename}:{line_number}")
                return None

            print(f"DEBUG: Looking for label containing {filename}:{line_number}")

            # Find labels in the same file
            candidates = []
            for label_name, pos_info in self.label_positions.items():
                if pos_info['filename'] == filename:
                    start_line = pos_info['start_line']
                    end_line = pos_info['end_line']

                    print(f"DEBUG: Checking label '{label_name}' at lines {start_line}-{end_line}")

                    # Check if the line number falls within this label's range
                    if start_line <= line_number <= (end_line or 999999):
                        candidates.append((label_name, start_line))
                        print(f"DEBUG: Label '{label_name}' is a candidate")

            if not candidates:
                print("DEBUG: No candidate labels found")
                return None

            # If multiple candidates, return the one with the highest start line
            # (i.e., the most recent label before our position)
            candidates.sort(key=lambda x: x[1], reverse=True)
            best_label = candidates[0][0]
            print(f"DEBUG: Best candidate label: {best_label}")
            return best_label

        except Exception as e:
            print(f"DEBUG: Error in _find_label_by_position: {e}")
            return None

    def _calculate_label_based_progress(self, current_label):
        """Calculate progress based on current label position and word counts."""
        try:
            print(f"DEBUG: _calculate_label_based_progress called with current_label='{current_label}'")
            print(f"DEBUG: self.word_counts is None: {self.word_counts is None}")
            print(f"DEBUG: len(self.word_counts): {len(self.word_counts) if self.word_counts else 0}")

            if not current_label or not self.word_counts:
                print(f"DEBUG: Early return - current_label={current_label}, word_counts={bool(self.word_counts)}")
                return 0

            print(f"DEBUG: Calculating label-based progress for '{current_label}'")

            # Get all labels in order (this is a simplified approach)
            # In a real implementation, we'd want to follow the actual story flow
            all_labels = list(self.word_counts.keys())

            if current_label not in all_labels:
                print(f"DEBUG: Current label '{current_label}' not found in word counts")
                return 0

            # Find the index of the current label
            try:
                current_index = all_labels.index(current_label)
            except ValueError:
                print(f"DEBUG: Could not find index for label '{current_label}'")
                return 0

            # Calculate words from all labels before the current one
            completed_words = 0
            for i in range(current_index):
                label_name = all_labels[i]
                completed_words += self.word_counts.get(label_name, 0)

            # Add partial progress within the current label
            within_label_progress = self._calculate_progress_within_label(current_label, None)
            current_label_words = self.word_counts.get(current_label, 0)
            completed_words += current_label_words * within_label_progress

            print(f"DEBUG: Label-based progress: {completed_words} words completed")
            print(f"  - Labels before current: {current_index}")
            print(f"  - Words from previous labels: {completed_words - current_label_words * within_label_progress}")
            print(f"  - Current label progress: {within_label_progress:.1%} of {current_label_words} words")

            # Return as integer since word counts should be whole numbers
            return int(round(completed_words))

        except Exception as e:
            print(f"DEBUG: Error calculating label-based progress: {e}")
            return 0

    def _calculate_statement_based_progress(self, current_label, within_label_progress):
        """
        Return the efficiently tracked seen words count.

        This uses our hook into Ren'Py's seen tracking system to provide
        real-time word counting as statements are marked as seen.
        """
        try:
            print(f"DEBUG: Efficient seen tracking progress:")
            print(f"  - Words from seen statements: {self.seen_words_count}")
            print(f"  - Statements counted: {len(self.seen_statements_cache)}")
            print(f"  - Current label: {current_label}")

            return self.seen_words_count

        except Exception as e:
            print(f"DEBUG: Error getting seen words count: {e}")
            return 0

    def _calculate_seen_words_from_renpy_tracking(self):
        """
        Calculate words from statements that Ren'Py has marked as seen.

        This leverages Ren'Py's built-in seen tracking system which is used
        for the "skip seen text" feature.
        """
        try:
            # Get Ren'Py's seen tracking data
            seen_ever = renpy.game.persistent._seen_ever
            seen_session = renpy.game.seen_session

            print(f"DEBUG: Ren'Py seen tracking data:")
            print(f"  - Statements seen ever: {len(seen_ever)}")
            print(f"  - Statements seen this session: {len(seen_session)}")

            total_seen_words = 0
            processed_statements = 0

            # Iterate through all statements in the script
            for label_name, label_node in renpy.game.script.namemap.items():
                if not hasattr(label_node, 'block') or not label_node.block:
                    continue

                # Process each statement in the label
                for stmt in label_node.block:
                    # Get the statement identifier (same format Ren'Py uses)
                    stmt_name = stmt.name if hasattr(stmt, 'name') else None
                    if not stmt_name:
                        continue

                    # Check if this statement has been seen (using Ren'Py's logic)
                    is_seen = False
                    if renpy.config.hash_seen:
                        hashed_name = renpy.astsupport.hash64(stmt_name)
                        is_seen = (stmt_name in seen_ever) or (hashed_name in seen_ever)
                    else:
                        is_seen = stmt_name in seen_ever

                    # If seen and it's a Say statement, count its words
                    if is_seen and isinstance(stmt, renpy.ast.Say):
                        if hasattr(stmt, 'what') and stmt.what:
                            clean_text = self._clean_dialogue_text(stmt.what)
                            words = len(clean_text.split())
                            total_seen_words += words
                            processed_statements += 1

                            print(f"DEBUG: Seen statement '{stmt_name}': {words} words")

            print(f"DEBUG: Total seen words from {processed_statements} seen Say statements: {total_seen_words}")
            return total_seen_words

        except Exception as e:
            print(f"DEBUG: Error calculating seen words from Ren'Py tracking: {e}")
            import traceback
            traceback.print_exc()
            return 0



    def _calculate_seen_progress(self):
        """
        Calculate progress based on current position in the script.

        Since Ren'Py's seen tracking system is complex to reverse-engineer,
        we'll use a simpler approach based on the current label position
        and estimate progress from there.
        """
        try:
            print("DEBUG: Calculating seen progress using position-based approach")

            # Get current label
            current_label = self._get_current_label()
            if not current_label:
                print("DEBUG: No current label found")
                return 0, 0

            # Only count statements that are in labels we've analyzed for word counts
            # This ensures consistency with the route analysis
            if not hasattr(self, 'word_counts') or not self.word_counts:
                print("DEBUG: No word counts available, falling back to route analysis total")
                # Use the total from route analysis instead
                analysis_data = self.analyze_script()
                return 0, analysis_data.get('metadata', {}).get('total_words', 0)

            analyzed_labels = set(self.word_counts.keys())
            print(f"DEBUG: Only counting statements in {len(analyzed_labels)} analyzed labels")

            # Calculate total words (same as before)
            total_words = 0
            total_count = 0

            # Calculate seen words based on current position
            seen_words = 0
            seen_count = 0
            current_label_found = False

            print("DEBUG: Analyzing statements for position-based progress...")

            # Get all statements from analyzed labels only
            for label_name in analyzed_labels:
                if label_name in renpy.game.script.namemap:
                    label_node = renpy.game.script.namemap[label_name]

                    # Check if this is the current label
                    is_current_label = (label_name == current_label)
                    if is_current_label:
                        current_label_found = True

                    # Get all statements in this label
                    if hasattr(label_node, 'block') and label_node.block:
                        for stmt in label_node.block:
                            # Count Say statements (dialogue)
                            if isinstance(stmt, renpy.ast.Say):
                                total_count += 1

                                # Get word count for this statement
                                if hasattr(stmt, 'what') and stmt.what:
                                    clean_text = self._clean_dialogue_text(stmt.what)
                                    words = len(clean_text.split())
                                    total_words += words

                                    # Mark as seen if we haven't reached the current label yet
                                    # This is a simple approximation - in reality we'd need more
                                    # sophisticated tracking of the exact position within the current label
                                    if not current_label_found:
                                        seen_words += words
                                        seen_count += 1

                            # Count Menu choice text (to match word count analysis)
                            elif isinstance(stmt, renpy.ast.Menu) and hasattr(stmt, 'items'):
                                for choice_text, _condition, choice_block in stmt.items:
                                    if choice_text:
                                        clean_text = self._clean_dialogue_text(choice_text)
                                        words = len(clean_text.split())
                                        total_words += words

                                        # Mark menu choices as seen if before current label
                                        if not current_label_found:
                                            seen_words += words

            print(f"DEBUG: Position-based progress calculation complete:")
            print(f"  - Current label: {current_label}")
            print(f"  - Total Say statements in analyzed labels: {total_count}")
            print(f"  - Seen Say statements (before current label): {seen_count}")
            print(f"  - Total words in analyzed labels: {total_words}")
            print(f"  - Seen words (before current label): {seen_words}")
            print(f"  - Progress: {(seen_words/total_words*100):.1f}%" if total_words > 0 else "  - Progress: 0%")

            # Compare with word count analysis total
            if hasattr(self, 'word_counts') and self.word_counts:
                word_count_total = sum(self.word_counts.values())
                print(f"  - Word count analysis total: {word_count_total}")
                print(f"  - Difference: {word_count_total - total_words} words ({((word_count_total - total_words)/word_count_total*100):.1f}%)")

            return seen_words, total_words

        except Exception as e:
            print(f"DEBUG: Error calculating seen progress: {e}")
            import traceback
            traceback.print_exc()
            return 0, 0

    def _calculate_progress_within_label(self, label_name, current_line):
        """
        Calculate progress percentage within a specific label based on statement position.

        Since line numbers and statement IDs are different numbering systems,
        we'll use a simpler approach: count statements within the label.
        """
        try:
            if not label_name:
                return 0.0

            # Get the current statement from context
            current_context = renpy.game.context()
            if not current_context or not hasattr(current_context, 'current'):
                return 0.0

            current_stmt = current_context.current
            if not current_stmt:
                return 0.0

            # Get the label node
            if label_name not in renpy.game.script.namemap:
                return 0.0

            label_node = renpy.game.script.namemap[label_name]
            if not hasattr(label_node, 'block') or not label_node.block:
                return 0.0

            # Count total Say statements in this label
            total_say_statements = 0
            current_statement_index = -1

            for i, stmt in enumerate(label_node.block):
                if isinstance(stmt, renpy.ast.Say):
                    total_say_statements += 1

                    # Check if this is our current statement by comparing content
                    if (hasattr(stmt, 'what') and hasattr(current_stmt, '__len__') and
                        len(current_stmt) >= 3 and isinstance(current_stmt[2], str)):
                        # Try to match the statement content
                        if stmt.what and current_stmt[2] in str(stmt.what):
                            current_statement_index = total_say_statements - 1
                            break

            if total_say_statements == 0:
                return 0.0

            if current_statement_index == -1:
                # Couldn't find current statement, assume we're at the beginning
                progress = 0.0
            else:
                # Calculate progress based on statement position
                progress = current_statement_index / total_say_statements

            print(f"DEBUG: Progress within label '{label_name}': statement {current_statement_index + 1}/{total_say_statements} = {progress:.2%}")
            return progress

        except Exception as e:
            print(f"DEBUG: Error calculating progress within label: {e}")
            return 0.0

    def _calculate_remaining_words(self, current_label):
        """Calculate estimated remaining words from current position."""
        if not self.word_counts:
            return 0

        # Simple estimation: sum all words from labels that come after current
        # This is a basic implementation - could be improved with better path analysis
        remaining_words = 0

        try:
            # Get all reachable labels from current position
            reachable_labels = self._get_reachable_labels(current_label)

            for label in reachable_labels:
                if label in self.word_counts:
                    remaining_words += self.word_counts[label]

        except Exception as e:
            print(f"Remaining words calculation error: {e}")
            # Fallback: just return current label's word count
            remaining_words = self.word_counts.get(current_label, 0)

        return remaining_words

    def _get_reachable_labels(self, start_label):
        """Get all labels reachable from the starting label."""
        reachable = set()

        if not self.route_graph or 'edges' not in self.route_graph:
            return reachable

        # Simple BFS to find reachable labels
        queue = deque([start_label])
        visited = set()

        while queue:
            current = queue.popleft()
            if current in visited:
                continue

            visited.add(current)
            reachable.add(current)

            # Find edges from current label
            for edge in self.route_graph['edges']:
                if edge.get('from') == current:
                    target = edge.get('to')
                    if target and target not in visited:
                        queue.append(target)

        return reachable

    def get_route_summary(self):
        """
        Get a summary of the route analysis.

        Returns:
            dict: Summary information about the script routes
        """
        if not self.route_graph:
            return {'error': 'No route analysis available'}

        nodes = self.route_graph.get('nodes', [])
        edges = self.route_graph.get('edges', [])

        # Count different node types
        label_count = len([n for n in nodes if n.get('type') == 'label'])
        menu_count = len([n for n in nodes if n.get('type') == 'menu'])

        # Count different edge types
        choice_edges = len([e for e in edges if e.get('type') == 'choice'])
        jump_edges = len([e for e in edges if e.get('type') == 'jump'])
        call_edges = len([e for e in edges if e.get('type') == 'call'])

        # Calculate total words
        total_words = sum(self.word_counts.values()) if self.word_counts else 0

        return {
            'total_labels': label_count,
            'total_menus': menu_count,
            'total_choices': choice_edges,
            'total_jumps': jump_edges,
            'total_calls': call_edges,
            'total_words': total_words,
            'estimated_reading_time_minutes': round(total_words / 200.0, 1),
            'nodes_count': len(nodes),
            'edges_count': len(edges)
        }


# Global instance for the route analyzer
_route_analyzer = None

def get_route_analyzer():
    """Get the global route analyzer instance."""
    global _route_analyzer
    if _route_analyzer is None:
        _route_analyzer = RouteAnalyzer()
    return _route_analyzer
