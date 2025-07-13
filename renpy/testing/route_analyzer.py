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
    
    def invalidate_cache(self):
        """Invalidate cached analysis data."""
        self._cache_valid = False
        self.script_cache = None
        self.route_graph = None
        self.word_counts = None
        self.choice_requirements = None
    
    def analyze_script(self, force_refresh=False):
        """
        Analyze the entire script for routes and choices.
        
        Args:
            force_refresh (bool): Force re-analysis even if cache is valid
            
        Returns:
            dict: Complete route analysis data
        """
        if not force_refresh and self._cache_valid and self.route_graph:
            return self.route_graph
        
        try:
            # Get script data
            if not renpy.game.script:
                raise RuntimeError("No script loaded")
            
            # Build route graph
            self.route_graph = self._build_route_graph()
            self.word_counts = self._calculate_word_counts()
            self.choice_requirements = self._analyze_choice_requirements()
            
            # Combine all analysis data
            analysis_data = {
                'route_graph': self.route_graph,
                'word_counts': self.word_counts,
                'choice_requirements': self.choice_requirements,
                'metadata': {
                    'total_labels': len(self.route_graph.get('nodes', [])),
                    'total_choices': len([n for n in self.route_graph.get('nodes', []) if n.get('type') == 'menu']),
                    'total_words': sum(self.word_counts.values()) if self.word_counts else 0
                }
            }
            
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
    
    def _calculate_word_counts(self):
        """
        Calculate word counts for each label/scene.

        Returns:
            dict: Mapping of label names to word counts
        """
        word_counts = {}

        try:
            script = renpy.game.script
            if not script or not script.namemap:
                return word_counts

            for label_name, start_node in script.namemap.items():
                if isinstance(label_name, str) and not label_name.startswith('_'):
                    word_count = self._count_words_in_label(start_node)
                    if word_count > 0:
                        word_counts[label_name] = word_count

        except Exception as e:
            print(f"Word count calculation error: {e}")

        return word_counts

    def _count_words_in_label(self, start_node):
        """Count words in a specific label's dialogue."""
        word_count = 0
        current_node = start_node

        while current_node:
            if hasattr(current_node, '__class__'):
                node_type = current_node.__class__.__name__

                if node_type == 'Say' and hasattr(current_node, 'what'):
                    # Count words in dialogue text
                    dialogue_text = current_node.what
                    if dialogue_text:
                        # Remove Ren'Py markup and count words
                        clean_text = self._clean_dialogue_text(dialogue_text)
                        words = len(clean_text.split())
                        word_count += words

                elif node_type == 'Menu' and hasattr(current_node, 'items'):
                    # Count words in menu choices
                    for choice_text, _condition, choice_block in current_node.items:
                        if choice_text:
                            clean_text = self._clean_dialogue_text(choice_text)
                            words = len(clean_text.split())
                            word_count += words

                        # Count words in choice blocks
                        if choice_block:
                            for choice_node in choice_block:
                                word_count += self._count_words_in_node(choice_node)

            # Move to next node
            current_node = getattr(current_node, 'next', None)

        return word_count

    def _count_words_in_node(self, node):
        """Count words in a single node (recursive helper)."""
        word_count = 0

        if hasattr(node, '__class__'):
            node_type = node.__class__.__name__

            if node_type == 'Say' and hasattr(node, 'what'):
                dialogue_text = node.what
                if dialogue_text:
                    clean_text = self._clean_dialogue_text(dialogue_text)
                    word_count += len(clean_text.split())

        return word_count

    def _clean_dialogue_text(self, text):
        """Remove Ren'Py markup from dialogue text."""
        if not text:
            return ""

        # Remove common Ren'Py markup
        # Remove {tags}
        text = re.sub(r'\{[^}]*\}', '', text)
        # Remove [tags]
        text = re.sub(r'\[[^\]]*\]', '', text)
        # Remove interpolation markers
        text = re.sub(r'\[([^\]]*)\]', r'\1', text)
        # Clean up extra whitespace
        text = re.sub(r'\s+', ' ', text).strip()

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
        try:
            # Get current label and position
            current_label = self._get_current_label()
            if not current_label:
                return {
                    'current_label': None,
                    'progress_percentage': 0.0,
                    'estimated_remaining_words': 0,
                    'estimated_reading_time_minutes': 0
                }

            # Calculate progress metrics
            total_words = sum(self.word_counts.values()) if self.word_counts else 0
            remaining_words = self._calculate_remaining_words(current_label)
            progress_percentage = ((total_words - remaining_words) / total_words * 100) if total_words > 0 else 0

            # Estimate reading time (average 200 words per minute)
            reading_time_minutes = remaining_words / 200.0

            return {
                'current_label': current_label,
                'progress_percentage': round(progress_percentage, 2),
                'estimated_remaining_words': remaining_words,
                'estimated_reading_time_minutes': round(reading_time_minutes, 1),
                'total_words': total_words
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
        """Get the current label name."""
        try:
            context = renpy.game.context()
            if context and context.current:
                node = renpy.game.script.lookup(context.current)
                if hasattr(node, 'name'):
                    return node.name
                return str(context.current)
            return None
        except Exception:
            return None

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
