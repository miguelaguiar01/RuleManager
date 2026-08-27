#!/usr/bin/env python3
"""
Corporate Action Swift Code Enrichment Rule Manager - TUI Edition
Interactive terminal UI for managing enrichment rules
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

import rule_semantics

from rich.console import Console
from rich.panel import Panel
from rich.tree import Tree
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.layout import Layout
from rich.live import Live
from rich import box
from rich.text import Text


console = Console()


@dataclass
class ValidationResult:
    is_valid: bool
    overlaps: List[Tuple[str, str]]
    errors: List[str]
    warnings: List[str]


class RuleManager:
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.rules: Dict[str, Any] = {}
        self.current_swift_code: Optional[str] = None
        self.current_path: List[int] = []  # Track position in nested conditions
        self.load_rules()
    
    def load_rules(self):
        if self.filepath.exists():
            with open(self.filepath, 'r') as f:
                self.rules = json.load(f)
        else:
            console.print(f"[yellow]File {self.filepath} not found. Starting fresh.[/yellow]")
            self.rules = {}
    
    def save_rules(self):
        with open(self.filepath, 'w') as f:
            json.dump(self.rules, f, indent=2)
        console.print(f"[green]✓ Saved to {self.filepath}[/green]")
    
    def get_current_rule(self) -> Optional[Dict]:
        if not self.current_swift_code or self.current_swift_code not in self.rules:
            return None
        return self.rules[self.current_swift_code]
    
    def get_current_condition_block(self) -> Optional[Dict]:
        """Get the current condition block we're editing based on path"""
        rule = self.get_current_rule()
        if not rule:
            return None
        
        if "filters" not in rule or not rule["filters"]:
            return None
        
        current = rule["filters"][0]
        for index in self.current_path:
            if "conditions" in current and index < len(current["conditions"]):
                current = current["conditions"][index]
            else:
                return None
        return current
    
    def add_swift_code(self, swift_code: str):
        if swift_code in self.rules:
            console.print(f"[yellow]'{swift_code}' already exists[/yellow]")
            return False
        
        self.rules[swift_code] = {
            "DEPENDENCIES": [],
            "filters": [{
                "logic": "or",
                "conditions": []
            }]
        }
        self.current_swift_code = swift_code
        self.current_path = []
        return True
    
    def delete_swift_code(self, swift_code: str):
        if swift_code in self.rules:
            del self.rules[swift_code]
            if self.current_swift_code == swift_code:
                self.current_swift_code = None
                self.current_path = []
            return True
        return False
    
    def select_swift_code(self, swift_code: str):
        if swift_code in self.rules:
            self.current_swift_code = swift_code
            self.current_path = []
            return True
        return False
    
    def add_dependency(self, dependency: str):
        rule = self.get_current_rule()
        if rule and dependency not in rule["DEPENDENCIES"]:
            rule["DEPENDENCIES"].append(dependency)
            return True
        return False
    
    def remove_dependency(self, dependency: str):
        rule = self.get_current_rule()
        if rule and dependency in rule["DEPENDENCIES"]:
            rule["DEPENDENCIES"].remove(dependency)
            return True
        return False
    
    def add_condition(self, column: str, operator: str, value: Any):
        """Add condition to current block"""
        block = self.get_current_condition_block()
        if not block:
            return False
        
        condition = {
            "column": column,
            "operator": operator,
            "value": value
        }
        
        if "conditions" not in block:
            block["conditions"] = []
        block["conditions"].append(condition)
        return True
    
    def add_column_comparison(self, column1: str, operator: str, column2: str):
        """Add column vs column comparison to current block"""
        block = self.get_current_condition_block()
        if not block:
            return False
        
        condition = {
            "comparison": "column_vs_column",
            "column1": column1,
            "operator": operator,
            "column2": column2
        }
        
        if "conditions" not in block:
            block["conditions"] = []
        block["conditions"].append(condition)
        return True
    
    def add_nested_block(self, logic: str):
        """Add nested AND/OR block to current block"""
        block = self.get_current_condition_block()
        if not block:
            return False
        
        nested = {
            "logic": logic.lower(),
            "conditions": []
        }
        
        if "conditions" not in block:
            block["conditions"] = []
        block["conditions"].append(nested)
        return True
    
    def navigate_into(self, index: int):
        """Navigate into a nested block"""
        block = self.get_current_condition_block()
        if not block or "conditions" not in block:
            return False
        
        if index < len(block["conditions"]):
            condition = block["conditions"][index]
            if "logic" in condition:  # It's a nested block
                self.current_path.append(index)
                return True
        return False
    
    def navigate_up(self):
        """Navigate up one level"""
        if self.current_path:
            self.current_path.pop()
            return True
        return False
    
    def navigate_root(self):
        """Navigate to root"""
        self.current_path = []
    
    def edit_condition(self, index: int) -> bool:
        """Edit condition at index in current block"""
        block = self.get_current_condition_block()
        if not block or "conditions" not in block:
            return False
        
        if index >= len(block["conditions"]):
            return False
        
        condition = block["conditions"][index]
        
        # Check if it's a nested block (can't edit those this way)
        if "logic" in condition:
            console.print("[yellow]Cannot edit nested blocks - navigate into them instead[/yellow]")
            return False
        
        # Show current values
        if "comparison" in condition:
            console.print(f"Current: {condition['column1']} {condition['operator']} {condition['column2']}")
            console.print("\n[dim]Leave blank to keep current value[/dim]")
            
            column1 = Prompt.ask("First column", default=condition['column1'])
            operator = Prompt.ask("Operator", default=condition['operator'])
            column2 = Prompt.ask("Second column", default=condition['column2'])
            
            condition['column1'] = column1
            condition['operator'] = operator
            condition['column2'] = column2
        else:
            # Regular condition
            current_value = condition.get('value', '')
            if isinstance(current_value, list):
                current_value = ','.join(map(str, current_value))
            
            console.print(f"Current: {condition['column']} {condition['operator']} {current_value}")
            console.print("\n[dim]Leave blank to keep current value[/dim]")
            
            column = Prompt.ask("Column name", default=condition['column'])
            operator = Prompt.ask("Operator", default=condition['operator'])
            value_str = Prompt.ask("Value", default=str(current_value))
            
            if ',' in value_str:
                value = [v.strip() for v in value_str.split(',')]
            else:
                try:
                    value = float(value_str) if '.' in value_str else int(value_str)
                except ValueError:
                    value = value_str
            
            condition['column'] = column
            condition['operator'] = operator
            condition['value'] = value
        
        return True
    
    def delete_condition(self, index: int):
        """Delete condition at index in current block"""
        block = self.get_current_condition_block()
        if not block or "conditions" not in block:
            return False
        
        if index < len(block["conditions"]):
            block["conditions"].pop(index)
            return True
        return False
    
    def change_logic(self, logic: str):
        """Change logic of current block"""
        block = self.get_current_condition_block()
        if block and "logic" in block:
            block["logic"] = logic.lower()
            return True
        return False
    
    def build_tree_view(self) -> Panel:
        """Build a rich tree visualization of current Swift code"""
        if not self.current_swift_code:
            return Panel("[yellow]No Swift code selected[/yellow]", title="Current Rule")
        
        rule = self.get_current_rule()
        if not rule:
            return Panel("[red]Error: Rule not found[/red]", title="Current Rule")
        
        tree = Tree(f"[bold cyan]{self.current_swift_code}[/bold cyan]")
        
        # Dependencies
        if rule["DEPENDENCIES"]:
            dep_branch = tree.add("[yellow]DEPENDENCIES[/yellow]")
            for dep in rule["DEPENDENCIES"]:
                dep_branch.add(f"[green]{dep}[/green]")
        
        # Filters
        if rule["filters"]:
            filters_branch = tree.add("[yellow]FILTERS[/yellow]")
            self._build_filter_tree(filters_branch, rule["filters"][0], [])
        
        # Show current position
        path_str = " → ".join([f"[{i}]" for i in self.current_path]) if self.current_path else "ROOT"
        position = Text(f"Current position: {path_str}", style="dim")
        
        return Panel(
            tree,
            title=f"[bold]{self.current_swift_code}[/bold]",
            subtitle=position,
            border_style="cyan"
        )
    
    def _build_filter_tree(self, parent_tree, filters: Dict, path: List[int]):
        """Recursively build filter tree"""
        is_current = path == self.current_path
        
        logic_style = "bold magenta" if is_current else "magenta"
        parent_tree.add(f"[{logic_style}]Logic: {filters.get('logic', 'or').upper()}[/{logic_style}]")
        
        if "conditions" in filters:
            conditions_branch = parent_tree.add(
                f"[{logic_style}]Conditions ({len(filters['conditions'])})[/{logic_style}]"
            )
            
            for i, condition in enumerate(filters["conditions"]):
                item_style = "bold green" if is_current else "white"
                
                if "logic" in condition:
                    # Nested block
                    nested_branch = conditions_branch.add(
                        f"[{item_style}][{i}] {condition['logic'].upper()} block[/{item_style}]"
                    )
                    self._build_filter_tree(nested_branch, condition, path + [i])
                elif "comparison" in condition:
                    # Column comparison
                    conditions_branch.add(
                        f"[{item_style}][{i}] {condition['column1']} "
                        f"{condition['operator']} {condition['column2']}[/{item_style}]"
                    )
                else:
                    # Regular condition
                    value_str = str(condition.get('value', ''))
                    if isinstance(condition.get('value'), list):
                        value_str = f"[{', '.join(map(str, condition['value']))}]"
                    conditions_branch.add(
                        f"[{item_style}][{i}] {condition['column']} "
                        f"{condition['operator']} {value_str}[/{item_style}]"
                    )
    
    def validate_rules(self) -> ValidationResult:
        errors = []
        warnings = []
        overlaps = []
        
        for swift_code, rule in self.rules.items():
            # Skip non-Swift code entries
            if swift_code == "EXDATE":
                continue
            
            if "filters" not in rule:
                errors.append(f"{swift_code}: Missing 'filters'")
            elif not isinstance(rule["filters"], list):
                errors.append(f"{swift_code}: 'filters' must be an array")
            elif len(rule["filters"]) == 0:
                errors.append(f"{swift_code}: 'filters' array is empty")
            
            if "DEPENDENCIES" not in rule:
                warnings.append(f"{swift_code}: Missing 'DEPENDENCIES'")
            
            if "filters" in rule and rule["filters"]:
                errors.extend(self._validate_filter_structure(rule["filters"][0], swift_code))
        
        # Basic overlap detection - only check actual Swift codes
        swift_codes = [k for k in self.rules.keys() if k != "EXDATE"]
        for i, code1 in enumerate(swift_codes):
            for code2 in swift_codes[i+1:]:
                if self._check_potential_overlap(code1, code2):
                    overlaps.append((code1, code2))
        
        is_valid = len(errors) == 0 and len(overlaps) == 0
        return ValidationResult(is_valid, overlaps, errors, warnings)
    
    def _validate_filter_structure(self, filters: Dict, swift_code: str) -> List[str]:
        errors = []
        
        if "logic" in filters and filters["logic"] not in ["and", "or"]:
            errors.append(f"{swift_code}: Invalid logic '{filters['logic']}'")
        
        if "conditions" in filters:
            for i, condition in enumerate(filters["conditions"]):
                if "logic" in condition:
                    errors.extend(self._validate_filter_structure(condition, swift_code))
                elif "comparison" in condition:
                    required = ["column1", "operator", "column2"]
                    for req in required:
                        if req not in condition:
                            errors.append(f"{swift_code}[{i}]: Missing '{req}'")
                    if "operator" in condition and condition["operator"] not in self.CANONICAL_OPERATORS:
                        errors.append(f"{swift_code}[{i}]: Invalid operator {condition['operator']!r}")
                else:
                    required = ["column", "operator", "value"]
                    for req in required:
                        if req not in condition:
                            errors.append(f"{swift_code}[{i}]: Missing '{req}'")
                    if "operator" in condition and condition["operator"] not in self.CANONICAL_OPERATORS:
                        errors.append(f"{swift_code}[{i}]: Invalid operator {condition['operator']!r}")
        
        return errors
    
    def _check_potential_overlap(self, code1: str, code2: str) -> bool:

        rule1 = self.rules[code1]
        rule2 = self.rules[code2]
        
        if not rule1.get("filters") or not rule2.get("filters"):
            return False

        paths1 = self._extract_or_paths(rule1["filters"][0])
        paths2 = self._extract_or_paths(rule2["filters"][0])
        
        for path1 in paths1:
            for path2 in paths2:
                if self._paths_can_overlap(path1, path2):
                    return True
        
        return False

    def _extract_or_paths(self, filters: Dict) -> List[List[Dict]]:

        if "conditions" not in filters:
            return [[]]
        
        logic = filters.get("logic", "or")
        
        if logic == "or":
            # Each top-level condition becomes its own path
            paths = []
            for condition in filters["conditions"]:
                if "logic" in condition:
                    # It's a nested block
                    if condition["logic"] == "and":
                        # AND block: all conditions must be true, this is one path
                        and_conditions = self._flatten_and_block(condition)
                        paths.append(and_conditions)
                    elif condition["logic"] == "or":
                        # Nested OR block: recursively get its paths
                        nested_paths = self._extract_or_paths(condition)
                        paths.extend(nested_paths)
                else:
                    # Simple condition: it's a path by itself
                    paths.append([condition])
            return paths
        
        elif logic == "and":
            # AND at root level: all conditions together form a single path
            and_conditions = self._flatten_and_block(filters)
            return [and_conditions]
        
        return [[]]

    def _flatten_and_block(self, and_block: Dict) -> List[Dict]:
        """
        Flatten an AND block into a list of all leaf conditions.
        Recursively processes nested AND blocks.
        """
        conditions = []
        
        if "conditions" not in and_block:
            return conditions
        
        for condition in and_block["conditions"]:
            if "logic" in condition:
                if condition["logic"] == "and":
                    # Nested AND: flatten it
                    conditions.extend(self._flatten_and_block(condition))
                elif condition["logic"] == "or":
                    # Nested OR inside AND: this is complex, treat conservatively
                    # For now, we'll skip this case or handle it separately
                    # This would represent: (A AND B AND (C OR D))
                    # We'd need to expand this into multiple paths: (A AND B AND C) OR (A AND B AND D)
                    conditions.append(condition)  # Keep as-is for now
            else:
                # Leaf condition
                conditions.append(condition)

        return conditions

    def _extract_all_conditions(self, block: Dict) -> List[Dict]:
        """Recursively collect every leaf condition from a block, regardless
        of its logic (used by the comparison view to list an OR block's
        conditions)."""
        conditions = []

        if "conditions" not in block:
            return conditions

        for condition in block["conditions"]:
            if "logic" in condition:
                conditions.extend(self._extract_all_conditions(condition))
            else:
                conditions.append(condition)

        return conditions

    def _paths_can_overlap(self, path1: List[Dict], path2: List[Dict]) -> bool:
        """
        Check if two paths (lists of AND conditions) could both be satisfied by the same data.
        
        Returns True if there's no contradiction between the paths.
        Returns False if there's a clear contradiction (they can't both be true).
        """
        # Build a map of column -> conditions for each path
        path1_by_column = {}
        path2_by_column = {}
        
        for cond in path1:
            col = cond.get("column") or cond.get("column1")
            if col:
                if col not in path1_by_column:
                    path1_by_column[col] = []
                path1_by_column[col].append(cond)
        
        for cond in path2:
            col = cond.get("column") or cond.get("column1")
            if col:
                if col not in path2_by_column:
                    path2_by_column[col] = []
                path2_by_column[col].append(cond)
        
        # Check each column that appears in both paths
        common_columns = set(path1_by_column.keys()) & set(path2_by_column.keys())
        
        for column in common_columns:
            conditions1 = path1_by_column[column]
            conditions2 = path2_by_column[column]
            
            # Check if all conditions on this column are compatible
            for cond1 in conditions1:
                for cond2 in conditions2:
                    if self._are_contradictory(cond1, cond2):
                        # Found a contradiction on this column
                        # These paths definitely can't overlap
                        return False
        
        # No contradictions found
        # The paths COULD overlap (conservative approach)
        return True

    # Canonical operators the comparison logic understands (shared with the
    # data analyzer via rule_semantics).
    CANONICAL_OPERATORS = rule_semantics.CANONICAL_OPERATORS

    @staticmethod
    def _values_equal(a, b):
        """Type-tolerant equality (shared with the data analyzer)."""
        return rule_semantics.values_equal(a, b)

    @staticmethod
    def _value_in_list(value, values):
        return rule_semantics.value_in_list(value, values)

    def _are_contradictory(self, cond1: Dict, cond2: Dict) -> bool:
        """Check if two conditions on the same column are contradictory"""
        
        # Handle column vs column comparisons specially
        if "comparison" in cond1 and "comparison" in cond2:
            # Both are column comparisons
            col1_left = cond1.get("column1")
            col1_right = cond1.get("column2")
            col2_left = cond2.get("column1")
            col2_right = cond2.get("column2")
            op1 = cond1.get("operator")
            op2 = cond2.get("operator")
            
            # Check if they're comparing the same columns
            if col1_left == col2_left and col1_right == col2_right:
                # Same columns, check if operators are contradictory
                # e.g., A > B and A < B
                if (op1 == ">" and op2 in ["<", "<="]) or \
                (op1 == ">=" and op2 == "<") or \
                (op1 == "<" and op2 in [">", ">="]) or \
                (op1 == "<=" and op2 == ">"):
                    return True
                
                # Also check for equality contradictions
                if op1 == "==" and op2 == "!=":
                    return True
                if op1 == "!=" and op2 == "==":
                    return True
            
            return False
        
        # If either is a column comparison, skip (too complex for now)
        if "comparison" in cond1 or "comparison" in cond2:
            return False
        
        op1 = cond1.get("operator")
        op2 = cond2.get("operator")
        val1 = cond1.get("value")
        val2 = cond2.get("value")

        # Both equality checks with different values
        if op1 == "==" and op2 == "==":
            return val1 != val2
        
        # Equality vs inequality on same value
        if op1 == "==" and op2 == "!=":
            return val1 == val2
        if op1 == "!=" and op2 == "==":
            return val1 == val2
        
        # Equality vs "in" list
        if op1 == "==" and op2 == "in":
            if isinstance(val2, list):
                return not self._value_in_list(val1, val2)
        if op1 == "in" and op2 == "==":
            if isinstance(val1, list):
                return not self._value_in_list(val2, val1)
        
        # Both "in" lists with no overlap
        if op1 == "in" and op2 == "in":
            if isinstance(val1, list) and isinstance(val2, list):
                return len(set(val1) & set(val2)) == 0

        # Equality vs "not in" list: contradictory if the value is excluded
        if op1 == "==" and op2 == "not in":
            if isinstance(val2, list):
                return self._value_in_list(val1, val2)
        if op1 == "not in" and op2 == "==":
            if isinstance(val1, list):
                return self._value_in_list(val2, val1)

        # "in" list vs "not in" list: contradictory only if every allowed
        # value is excluded (the in-set is a subset of the not-in set)
        if op1 == "in" and op2 == "not in":
            if isinstance(val1, list) and isinstance(val2, list):
                return all(self._value_in_list(x, val2) for x in val1)
        if op1 == "not in" and op2 == "in":
            if isinstance(val1, list) and isinstance(val2, list):
                return all(self._value_in_list(x, val1) for x in val2)

        # Numeric contradictions (only for value comparisons, not column comparisons)
        if op1 == ">" and op2 == "<":
            try:
                if float(val1) >= float(val2):
                    return True
            except (ValueError, TypeError):
                pass
        
        if op1 == ">=" and op2 == "<":
            try:
                if float(val1) >= float(val2):
                    return True
            except (ValueError, TypeError):
                pass
        
        if op1 == ">" and op2 == "<=":
            try:
                if float(val1) >= float(val2):
                    return True
            except (ValueError, TypeError):
                pass
        
        if op1 == "<" and op2 == ">":
            try:
                if float(val1) <= float(val2):
                    return True
            except (ValueError, TypeError):
                pass
        
        if op1 == "<=" and op2 == ">":
            try:
                if float(val1) <= float(val2):
                    return True
            except (ValueError, TypeError):
                pass
        
        if op1 == "<" and op2 == ">=":
            try:
                if float(val1) <= float(val2):
                    return True
            except (ValueError, TypeError):
                pass
        
        # Equality vs numeric range
        if op1 == "==" and op2 in [">", ">=", "<", "<="]:
            try:
                num1 = float(val1)
                num2 = float(val2)
                if op2 == ">" and num1 <= num2:
                    return True
                if op2 == ">=" and num1 < num2:
                    return True
                if op2 == "<" and num1 >= num2:
                    return True
                if op2 == "<=" and num1 > num2:
                    return True
            except (ValueError, TypeError):
                pass
        
        if op2 == "==" and op1 in [">", ">=", "<", "<="]:
            try:
                num1 = float(val1)
                num2 = float(val2)
                if op1 == ">" and num2 <= num1:
                    return True
                if op1 == ">=" and num2 < num1:
                    return True
                if op1 == "<" and num2 >= num1:
                    return True
                if op1 == "<=" and num2 > num1:
                    return True
            except (ValueError, TypeError):
                pass
        
        # No contradiction detected
        return False

    def display_validation_results(self, result: ValidationResult):
        """Display validation results in a formatted way with detailed overlap information"""
        console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
        console.print(f"[bold]Validation Results[/bold]")
        console.print(f"[bold cyan]{'='*60}[/bold cyan]\n")
        
        if result.errors:
            console.print(f"[bold red]Errors:[/bold red]")
            for error in result.errors:
                console.print(f"  ✗ {error}")
            console.print()
        
        if result.warnings:
            console.print(f"[bold yellow]Warnings:[/bold yellow]")
            for warning in result.warnings:
                console.print(f"  ⚠ {warning}")
            console.print()
        
        if result.overlaps:
            console.print(f"[bold red]Potential Overlaps Detected:[/bold red]\n")
            for code1, code2 in result.overlaps:
                self._display_overlap_details(code1, code2)
            console.print()
        
        if result.is_valid:
            console.print(f"[bold green]✓ All rules are valid! No overlaps detected.[/bold green]\n")
        else:
            console.print(f"[bold red]✗ Validation failed. Please fix the issues above.[/bold red]\n")

    def _display_overlap_details(self, code1: str, code2: str):
        from rich.panel import Panel
        from rich.columns import Columns
        
        console.print(f"[bold red]⚠ {code1} ↔ {code2}[/bold red]")
        
        # Extract paths from both rules
        rule1 = self.rules[code1]
        rule2 = self.rules[code2]
        
        paths1 = self._extract_or_paths(rule1["filters"][0])
        paths2 = self._extract_or_paths(rule2["filters"][0])
        
        # Find which specific paths overlap
        overlapping_paths = []
        for i, path1 in enumerate(paths1):
            for j, path2 in enumerate(paths2):
                if self._paths_can_overlap(path1, path2):
                    overlapping_paths.append((i, path1, j, path2))
        
        # Display each overlapping path pair
        for idx, (i, path1, j, path2) in enumerate(overlapping_paths, 1):
            console.print(f"\n  [yellow]Overlap #{idx}:[/yellow]")
            
            # Build path descriptions
            path1_desc = self._format_path_description(path1)
            path2_desc = self._format_path_description(path2)
            
            # Create side-by-side panels
            panel1 = Panel(
                path1_desc,
                title=f"[cyan]{code1}[/cyan] - Path {i+1}",
                border_style="cyan",
                padding=(0, 1),
                expand=False
            )

            panel2 = Panel(
                path2_desc,
                title=f"[cyan]{code2}[/cyan] - Path {j+1}",
                border_style="cyan",
                padding=(0, 1),
                expand=False
            )

            # Content-sized panels side-by-side with a small gap (stable at any width)
            grid = Table.grid(padding=(0, 2))
            grid.add_column()
            grid.add_column()
            grid.add_row(panel1, panel2)
            console.print(grid)

            # Show why they overlap
            console.print(f"  [dim]→ These paths could both match the same corporate action[/dim]")
        
        console.print()

    def _format_path_description(self, path: List[Dict]) -> str:
        """Format a path as a readable description"""
        if not path:
            return "[dim]No conditions[/dim]"
        
        lines = []
        for condition in path:
            if "comparison" in condition:
                # Column vs column
                lines.append(
                    f"[green]{condition['column1']}[/green] "
                    f"[yellow]{condition['operator']}[/yellow] "
                    f"[green]{condition['column2']}[/green]"
                )
            else:
                # Regular condition
                column = condition.get("column", "?")
                operator = condition.get("operator", "?")
                value = condition.get("value", "?")
                
                if isinstance(value, list):
                    value_str = f"[{', '.join(map(str, value))}]"
                else:
                    value_str = str(value)
                
                lines.append(
                    f"[green]{column}[/green] "
                    f"[yellow]{operator}[/yellow] "
                    f"[magenta]{value_str}[/magenta]"
                )
        
        return "\n".join(lines)

    def _build_comparison_tree(self, code: str, filters: Dict) -> str:
        """Build a simple text representation of the filter tree for comparison"""
        lines = []
        
        logic = filters.get("logic", "or")
        lines.append(f"[bold magenta]ROOT: {logic.upper()}[/bold magenta]")
        
        if "conditions" in filters:
            for i, condition in enumerate(filters["conditions"], 1):
                lines.append(f"\n[yellow]Path {i}:[/yellow]")
                if "logic" in condition:
                    # Nested block
                    lines.append(f"  [magenta]{condition['logic'].upper()} block:[/magenta]")
                    nested_conditions = self._flatten_and_block(condition) if condition['logic'] == 'and' else self._extract_all_conditions(condition)
                    for cond in nested_conditions:
                        lines.append("    " + self._format_condition(cond))
                else:
                    # Simple condition
                    lines.append("  " + self._format_condition(condition))
        
        return "\n".join(lines)


    def _format_condition(self, condition: Dict) -> str:
        """Format a single condition as a string"""
        if "comparison" in condition:
            return f"[green]{condition['column1']}[/green] [yellow]{condition['operator']}[/yellow] [green]{condition['column2']}[/green]"
        else:
            column = condition.get("column", "?")
            operator = condition.get("operator", "?")
            value = condition.get("value", "?")
            
            if isinstance(value, list):
                value_str = f"[{', '.join(map(str, value))}]"
            else:
                value_str = str(value)
            
            return f"[green]{column}[/green] [yellow]{operator}[/yellow] [magenta]{value_str}[/magenta]"


def show_swift_list(manager: RuleManager):
    """Show list of all Swift codes"""
    # Filter out non-Swift code entries (like "swift_code")
    actual_swift_codes = {k: v for k, v in manager.rules.items() 
                          if k != "EXDATE" and isinstance(v.get("filters"), list)}
    
    if not actual_swift_codes:
        console.print("[yellow]No Swift codes defined[/yellow]\n")
        return
    
    table = Table(title="Swift Codes", box=box.ROUNDED)
    table.add_column("Code", style="cyan bold")
    table.add_column("Dependencies", style="green")
    table.add_column("Conditions", style="yellow")
    
    for swift_code in sorted(actual_swift_codes.keys()):
        rule = actual_swift_codes[swift_code]
        dep_count = len(rule.get("DEPENDENCIES", []))
        
        # Safely get condition count
        try:
            cond_count = len(rule["filters"][0].get("conditions", []))
        except (KeyError, IndexError, AttributeError):
            cond_count = 0
        
        table.add_row(
            swift_code,
            str(dep_count),
            str(cond_count)
        )
    
    console.print(table)
    console.print()


def edit_mode(manager: RuleManager):
    """Interactive edit mode for current Swift code"""
    while True:
        console.clear()
        console.print(manager.build_tree_view())
        console.print()
        
        console.print("[bold]Actions:[/bold]")
        console.print("  [cyan]c[/cyan]  Add condition (column op value)")
        console.print("  [cyan]cc[/cyan] Add column comparison")
        console.print("  [cyan]n[/cyan]  Add nested AND/OR block")
        console.print("  [cyan]d[/cyan]  Add dependency")
        console.print("  [cyan]rd[/cyan] Remove dependency")
        console.print("  [cyan]del[/cyan] Delete condition by index")
        console.print("  [cyan]in[/cyan] Navigate into block [index]")
        console.print("  [cyan]up[/cyan] Navigate up one level")
        console.print("  [cyan]root[/cyan] Navigate to root")
        console.print("  [cyan]logic[/cyan] Change current block logic")
        console.print("  [cyan]q[/cyan]  Back to main menu")
        console.print()
        
        action = Prompt.ask("Action").strip().lower()
        
        if action == "q":
            break
        
        elif action == "c":
            column = Prompt.ask("Column name")
            operator = Prompt.ask("Operator (in, not in, ==, !=, >, <, >=, <=)")
            value_str = Prompt.ask("Value (comma-separated for list)")
            
            if ',' in value_str:
                value = [v.strip() for v in value_str.split(',')]
            else:
                # Try to convert to number if possible
                try:
                    value = float(value_str) if '.' in value_str else int(value_str)
                except ValueError:
                    value = value_str
            
            if manager.add_condition(column, operator, value):
                console.print("[green]✓ Added condition[/green]")
            else:
                console.print("[red]✗ Failed to add condition[/red]")
        
        elif action == "cc":
            column1 = Prompt.ask("First column")
            operator = Prompt.ask("Operator (>, <, >=, <=, ==, !=)")
            column2 = Prompt.ask("Second column")
            
            if manager.add_column_comparison(column1, operator, column2):
                console.print("[green]✓ Added comparison[/green]")
            else:
                console.print("[red]✗ Failed to add comparison[/red]")
        
        elif action == "n":
            logic = Prompt.ask("Logic type", choices=["and", "or"])
            
            if manager.add_nested_block(logic):
                console.print("[green]✓ Added nested block[/green]")
                # Auto-navigate into it
                block = manager.get_current_condition_block()
                if block and "conditions" in block:
                    manager.navigate_into(len(block["conditions"]) - 1)
            else:
                console.print("[red]✗ Failed to add block[/red]")
        
        elif action == "d":
            dependency = Prompt.ask("Dependency name")
            if manager.add_dependency(dependency):
                console.print("[green]✓ Added dependency[/green]")
            else:
                console.print("[yellow]Already exists or error[/yellow]")
        
        elif action == "rd":
            rule = manager.get_current_rule()
            if rule and rule["DEPENDENCIES"]:
                console.print(f"Dependencies: {', '.join(rule['DEPENDENCIES'])}")
                dependency = Prompt.ask("Dependency to remove")
                if manager.remove_dependency(dependency):
                    console.print("[green]✓ Removed dependency[/green]")
                else:
                    console.print("[red]✗ Not found[/red]")
            else:
                console.print("[yellow]No dependencies[/yellow]")
        
        elif action == "del":
            try:
                index = int(Prompt.ask("Condition index to delete"))
                if manager.delete_condition(index):
                    console.print("[green]✓ Deleted[/green]")
                else:
                    console.print("[red]✗ Invalid index[/red]")
            except ValueError:
                console.print("[red]Invalid number[/red]")
        
        elif action == "in":
            try:
                index = int(Prompt.ask("Block index to enter"))
                if manager.navigate_into(index):
                    console.print("[green]✓ Navigated into block[/green]")
                else:
                    console.print("[red]✗ Not a nested block[/red]")
            except ValueError:
                console.print("[red]Invalid number[/red]")
        
        elif action == "up":
            if manager.navigate_up():
                console.print("[green]✓ Moved up[/green]")
            else:
                console.print("[yellow]Already at root[/yellow]")
        
        elif action == "root":
            manager.navigate_root()
            console.print("[green]✓ At root[/green]")
        
        elif action == "logic":
            logic = Prompt.ask("New logic", choices=["and", "or"])
            if manager.change_logic(logic):
                console.print("[green]✓ Changed logic[/green]")
            else:
                console.print("[red]✗ Cannot change logic here[/red]")
        
        else:
            console.print("[red]Unknown action[/red]")
        
        console.input("\nPress Enter to continue...")

def show_all_dependencies(manager: RuleManager):
    """Show all dependencies across all Swift codes"""
    from rich.table import Table
    
    # Collect all dependencies
    all_deps = {}
    for swift_code, rule in manager.rules.items():
        if swift_code == "EXDATE":
            continue
        
        deps = rule.get("DEPENDENCIES", [])
        for dep in deps:
            if dep not in all_deps:
                all_deps[dep] = []
            all_deps[dep].append(swift_code)
    
    if not all_deps:
        console.print("[yellow]No dependencies found[/yellow]\n")
        return
    
    table = Table(title="All Dependencies", box=box.ROUNDED)
    table.add_column("Dependency", style="cyan bold")
    table.add_column("Used By", style="green")
    table.add_column("Count", style="yellow")
    
    for dep in sorted(all_deps.keys()):
        swift_codes = all_deps[dep]
        table.add_row(
            dep,
            ", ".join(sorted(swift_codes)),
            str(len(swift_codes))
        )
    
    console.print(table)
    console.print()

def compare_swift_codes(manager: RuleManager, code1: str, code2: str):
    """Compare two Swift codes side-by-side"""
    from rich.columns import Columns
    from rich.panel import Panel
    from rich.table import Table
    
    # Validate both exist
    if code1 not in manager.rules:
        console.print(f"[red]'{code1}' not found[/red]")
        return
    if code2 not in manager.rules:
        console.print(f"[red]'{code2}' not found[/red]")
        return
    
    rule1 = manager.rules[code1]
    rule2 = manager.rules[code2]
    
    console.print(f"\n[bold cyan]Comparing {code1} ↔ {code2}[/bold cyan]\n")
    
    # 1. Compare Dependencies
    deps1 = set(rule1.get("DEPENDENCIES", []))
    deps2 = set(rule2.get("DEPENDENCIES", []))
    
    only_in_1 = deps1 - deps2
    only_in_2 = deps2 - deps1
    common = deps1 & deps2
    
    if deps1 or deps2:
        console.print("[bold yellow]Dependencies:[/bold yellow]")
        
        dep_table = Table(box=box.SIMPLE)
        dep_table.add_column(code1, style="cyan")
        dep_table.add_column("Status", style="dim", justify="center")
        dep_table.add_column(code2, style="cyan")
        
        # Show common dependencies
        for dep in sorted(common):
            dep_table.add_row(dep, "✓", dep)
        
        # Show unique to code1
        for dep in sorted(only_in_1):
            dep_table.add_row(dep, "→", "[dim]-[/dim]")
        
        # Show unique to code2
        for dep in sorted(only_in_2):
            dep_table.add_row("[dim]-[/dim]", "←", dep)
        
        console.print(dep_table)
        console.print()
    
    # 2. Compare Filter Structure
    console.print("[bold yellow]Filter Structure:[/bold yellow]\n")
    
    # Build tree representations
    tree1 = manager._build_comparison_tree(code1, rule1["filters"][0])
    tree2 = manager._build_comparison_tree(code2, rule2["filters"][0])
    
    panel1 = Panel(
        tree1,
        title=f"[bold cyan]{code1}[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
        expand=False
    )

    panel2 = Panel(
        tree2,
        title=f"[bold cyan]{code2}[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
        expand=False
    )

    grid = Table.grid(padding=(0, 2))
    grid.add_column()
    grid.add_column()
    grid.add_row(panel1, panel2)
    console.print(grid)
    console.print()

    # 3. Summary of differences
    console.print("[bold yellow]Summary:[/bold yellow]")
    
    differences = []
    
    if only_in_1:
        differences.append(f"• {code1} has {len(only_in_1)} unique dependencies")
    if only_in_2:
        differences.append(f"• {code2} has {len(only_in_2)} unique dependencies")
    
    logic1 = rule1["filters"][0].get("logic", "or")
    logic2 = rule2["filters"][0].get("logic", "or")
    if logic1 != logic2:
        differences.append(f"• Different root logic: {code1} uses {logic1.upper()}, {code2} uses {logic2.upper()}")
    
    paths1 = manager._extract_or_paths(rule1["filters"][0])
    paths2 = manager._extract_or_paths(rule2["filters"][0])
    if len(paths1) != len(paths2):
        differences.append(f"• Different number of paths: {code1} has {len(paths1)}, {code2} has {len(paths2)}")
    
    if differences:
        for diff in differences:
            console.print(f"  {diff}")
    else:
        console.print("  [green]Rules are structurally similar[/green]")
    
    console.print()


def main_menu(manager: RuleManager):
    """Main menu"""
    while True:
        console.clear()
        console.print(Panel.fit(
            "[bold cyan]Corporate Action Swift Code Rule Manager[/bold cyan]",
            border_style="cyan"
        ))
        console.print()
        
        if manager.current_swift_code:
            console.print(f"[green]Current: {manager.current_swift_code}[/green]\n")
        
        console.print("[bold]Menu:[/bold]")
        console.print("  [cyan]\\[l] list[/cyan]            List all Swift codes")
        console.print("  [cyan]\\[d] deps[/cyan]            Show all dependencies")
        console.print("  [cyan]\\[c] compare[/cyan]         Compare two Swift codes")
        console.print("  [cyan]\\[v] view[/cyan]            View Swift code (read-only)")
        console.print("  [cyan]\\[n] new[/cyan]             Create new Swift code")
        console.print("  [cyan]\\[e] edit[/cyan]            Edit Swift code")
        console.print("  [cyan]\\[x] delete[/cyan]          Delete Swift code")
        console.print("  [cyan]\\[t] test/validate[/cyan]   Validate all rules")
        console.print("  [cyan]\\[s] save[/cyan]            Save to file")
        console.print("  [cyan]\\[r] reload[/cyan]          Reload from file")
        console.print("  [cyan]\\[q] quit[/cyan]            Quit")
        console.print()
        
        action = Prompt.ask("Action").strip().lower()

        shortcut_map = {
            'l': 'list',
            'd': 'deps',
            'c': 'compare',
            'v': 'view',
            'n': 'new',
            'e': 'edit',
            'x': 'delete',
            't': 'test',
            's': 'save',
            'r': 'reload',
            'q': 'quit'
        }

        if action in shortcut_map:
            action = shortcut_map[action]
        
        if action in ["exit", "quit"]:
            if Confirm.ask("Save before exit?"):
                manager.save_rules()
            break
        
        elif action == "list":
            show_swift_list(manager)
            Prompt.ask("\n[dim]Press Enter[/dim]", default="")
                    
        elif action == "deps":
            show_all_dependencies(manager)
            Prompt.ask("\n[dim]Press Enter[/dim]", default="")

        elif action == "compare":
            if len([k for k in manager.rules.keys() if k != "EXDATE"]) < 2:
                console.print("[yellow]Need at least 2 Swift codes to compare[/yellow]")
                continue
            
            show_swift_list(manager)
            code1 = Prompt.ask("First Swift code").strip().upper()
            code2 = Prompt.ask("Second Swift code").strip().upper()
            
            compare_swift_codes(manager, code1, code2)
            Prompt.ask("\n[dim]Press Enter[/dim]", default="")
        
        elif action == "view":
            if not manager.rules:
                console.print("[yellow]No Swift codes to view[/yellow]")
                continue
            
            show_swift_list(manager)
            swift_code = Prompt.ask("Swift code to view").strip().upper()
            if manager.select_swift_code(swift_code):
                view_mode(manager)
            else:
                console.print("[red]Not found[/red]")
        
        elif action == "new":
            swift_code = Prompt.ask("Swift code").strip().upper()
            
            if swift_code in manager.rules:
                console.print(f"[yellow]'{swift_code}' already exists[/yellow]")
                if Confirm.ask("Edit it instead?", default=True):
                    manager.select_swift_code(swift_code)
                    edit_mode(manager)
            else:
                logic = Prompt.ask("Root logic type", choices=["and", "or"], default="or")
                manager.rules[swift_code] = {
                    "DEPENDENCIES": [],
                    "filters": [{
                        "logic": logic.lower(),
                        "conditions": []
                    }]
                }
                manager.current_swift_code = swift_code
                manager.current_path = []
                console.print(f"[green]✓ Created {swift_code}[/green]")
                if Confirm.ask("Edit now?", default=True):
                    edit_mode(manager)
        
        elif action == "edit":
            if not manager.rules:
                console.print("[yellow]No Swift codes to edit[/yellow]")
                continue
            
            show_swift_list(manager)
            swift_code = Prompt.ask("Swift code to edit").strip().upper()
            if manager.select_swift_code(swift_code):
                edit_mode(manager)
            else:
                console.print("[red]Not found[/red]")
        
        elif action == "delete":
            if not manager.rules:
                console.print("[yellow]No Swift codes to delete[/yellow]")
                continue
            
            show_swift_list(manager)
            swift_code = Prompt.ask("Swift code to delete").strip().upper()
            if Confirm.ask(f"Delete {swift_code}?"):
                if manager.delete_swift_code(swift_code):
                    console.print(f"[green]✓ Deleted {swift_code}[/green]")
                else:
                    console.print("[red]Not found[/red]")
        
        elif action in ["validate", "test"]:
            with console.status("[bold green]Validating rules..."):
                result = manager.validate_rules()
            
            manager.display_validation_results(result)
            Prompt.ask("\n[dim]Press Enter[/dim]", default="")
        
        elif action == "save":
            manager.save_rules()
        
        elif action == "reload":
            if Confirm.ask("Discard unsaved changes?"):
                manager.load_rules()
                manager.current_swift_code = None
                manager.current_path = []
                console.print("[green]✓ Reloaded[/green]")
        
        else:
            console.print("[red]Unknown action[/red]")


def edit_mode(manager: RuleManager):
    while True:
        console.clear()
        console.print(manager.build_tree_view())
        console.print()
        
        console.print("[bold]Actions:[/bold]")
        console.print("  [cyan]c[/cyan]    Add condition (column op value)")
        console.print("  [cyan]cc[/cyan]   Add column comparison")
        console.print("  [cyan]n[/cyan]    Add nested AND/OR block")
        console.print("  [cyan]d[/cyan]    Add dependency")
        console.print("  [cyan]rd[/cyan]   Remove dependency")
        console.print("  [cyan]edit[/cyan] Edit condition by index")
        console.print("  [cyan]del[/cyan]  Delete condition by index")
        console.print("  [cyan]in[/cyan]   Navigate into block [index]")
        console.print("  [cyan]up[/cyan]   Navigate up one level")
        console.print("  [cyan]root[/cyan] Navigate to root")
        console.print("  [cyan]logic[/cyan] Change current block logic")
        console.print("  [cyan]q[/cyan]    Back to main menu")
        console.print()
        
        action = Prompt.ask("Action").strip().lower()
        
        if action == "q":
            break
        
        elif action == "c":
            column = Prompt.ask("Column name")
            operator = Prompt.ask("Operator (==, !=, in, >, <, >=, <=)")
            value_str = Prompt.ask("Value (comma-separated for list)")
            
            if ',' in value_str:
                value = [v.strip() for v in value_str.split(',')]
            else:
                # Try to convert to number if possible
                try:
                    value = float(value_str) if '.' in value_str else int(value_str)
                except ValueError:
                    value = value_str
            
            if manager.add_condition(column, operator, value):
                console.print("[green]✓ Added condition[/green]")
            else:
                console.print("[red]✗ Failed to add condition[/red]")
        
        elif action == "cc":
            column1 = Prompt.ask("First column")
            operator = Prompt.ask("Operator (>, <, >=, <=, ==, !=)")
            column2 = Prompt.ask("Second column")
            
            if manager.add_column_comparison(column1, operator, column2):
                console.print("[green]✓ Added comparison[/green]")
            else:
                console.print("[red]✗ Failed to add comparison[/red]")
        
        elif action == "n":
            logic = Prompt.ask("Logic type", choices=["and", "or"])
            
            if manager.add_nested_block(logic):
                console.print("[green]✓ Added nested block[/green]")
                # Auto-navigate into it
                block = manager.get_current_condition_block()
                if block and "conditions" in block:
                    manager.navigate_into(len(block["conditions"]) - 1)
            else:
                console.print("[red]✗ Failed to add block[/red]")
        
        elif action == "d":
            dependency = Prompt.ask("Dependency name")
            if manager.add_dependency(dependency):
                console.print("[green]✓ Added dependency[/green]")
            else:
                console.print("[yellow]Already exists or error[/yellow]")
        
        elif action == "rd":
            rule = manager.get_current_rule()
            if rule and rule["DEPENDENCIES"]:
                console.print(f"Dependencies: {', '.join(rule['DEPENDENCIES'])}")
                dependency = Prompt.ask("Dependency to remove")
                if manager.remove_dependency(dependency):
                    console.print("[green]✓ Removed dependency[/green]")
                else:
                    console.print("[red]✗ Not found[/red]")
            else:
                console.print("[yellow]No dependencies[/yellow]")
        
        elif action == "edit":
            try:
                index = int(Prompt.ask("Condition index to edit"))
                if manager.edit_condition(index):
                    console.print("[green]✓ Edited condition[/green]")
                else:
                    console.print("[red]✗ Failed to edit[/red]")
            except ValueError:
                console.print("[red]Invalid number[/red]")
        
        elif action == "del":
            try:
                index = int(Prompt.ask("Condition index to delete"))
                if manager.delete_condition(index):
                    console.print("[green]✓ Deleted[/green]")
                else:
                    console.print("[red]✗ Invalid index[/red]")
            except ValueError:
                console.print("[red]Invalid number[/red]")
        
        elif action == "in":
            try:
                index = int(Prompt.ask("Block index to enter"))
                if manager.navigate_into(index):
                    continue  # Immediately refresh
                else:
                    console.print("[red]✗ Not a nested block[/red]")
            except ValueError:
                console.print("[red]Invalid number[/red]")
        
        elif action == "up":
            if manager.navigate_up():
                continue  # Immediately refresh
            else:
                console.print("[yellow]Already at root[/yellow]")
        
        elif action == "root":
            manager.navigate_root()
            continue  # Immediately refresh
        
        elif action == "logic":
            logic = Prompt.ask("New logic", choices=["and", "or"])
            if manager.change_logic(logic):
                console.print("[green]✓ Changed logic[/green]")
            else:
                console.print("[red]✗ Cannot change logic here[/red]")
        
        else:
            console.print("[red]Unknown action[/red]")

def view_mode(manager: RuleManager):
    """View-only mode for current Swift code"""
    while True:
        console.clear()
        console.print(manager.build_tree_view())
        console.print()
        
        console.print("[bold]Actions:[/bold]")
        console.print("  [cyan]e[/cyan] Edit this Swift code")
        console.print("  [cyan]q[/cyan] Back to main menu")
        console.print()
        
        action = Prompt.ask("Action").strip().lower()
        
        if action == "q":
            break
        elif action == "e":
            edit_mode(manager)
            break  # After editing, return to main menu
        else:
            console.print("[red]Unknown action. Use 'e' to edit or 'q' to quit.[/red]")



def main():
    if len(sys.argv) < 2:
        console.print("[red]Usage: python rule_manager.py <rules_file.json>[/red]")
        sys.exit(1)
    
    filepath = sys.argv[1]
    manager = RuleManager(filepath)
    
    try:
        main_menu(manager)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()