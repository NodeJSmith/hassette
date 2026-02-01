#!/usr/bin/env -S uv run --script
"""
One-off script to add docstrings to Home Assistant state classes in Hassette.

This script scans all state files and adds standardized docstrings to state classes
that don't already have them, following the pattern:
    '''Representation of a Home Assistant {domain} state.

    See: https://www.home-assistant.io/integrations/{domain}/
    '''
"""

import re
from pathlib import Path


def find_state_files(states_dir: Path) -> list[Path]:
    """Find all Python files in the states directory."""
    return [f for f in states_dir.glob("*.py") if f.name != "__init__.py" and f.name != "base.py"]


def extract_state_classes(content: str) -> list[tuple[str, str, int]]:
    """
    Extract state class information from file content.

    Returns list of tuples: (class_name, domain, line_number)
    """
    classes = []
    lines = content.split("\n")

    for i, line in enumerate(lines):
        # Match class definitions that end with 'State'
        class_match = re.match(r"^class (\w+State)\([^)]+\):", line.strip())
        if class_match:
            class_name = class_match.group(1)

            # Look for domain definition in the next few lines
            domain = None
            for j in range(i + 1, len(lines)):
                domain_match = re.search(r'domain: Literal\["([^"]+)"\]', lines[j])
                if domain_match:
                    domain = domain_match.group(1)
                    break

            if domain:
                classes.append((class_name, domain, i))

    return classes


def has_docstring(content: str, class_line: int) -> bool:
    """Check if a class already has a docstring."""
    lines = content.split("\n")

    # Look for docstring in the next few lines after class definition
    for i in range(class_line + 1, min(class_line + 5, len(lines))):
        line = lines[i].strip()
        if line.startswith('"""') and "Representation of a Home Assistant" in line:
            return True
        # If we hit a non-empty line that's not a docstring, stop looking
        if line and not line.startswith('"""') and line != '"""':
            break

    return False


def add_docstring_to_class(content: str, domain: str, class_line: int) -> str:
    """Add a docstring to a state class."""
    lines = content.split("\n")

    # Find the insertion point (after the class definition line)
    insert_line = class_line + 1

    # Create the docstring
    docstring_lines = [
        f'    """Representation of a Home Assistant {domain} state.',
        "",
        f"    See: https://www.home-assistant.io/integrations/{domain}/",
        '    """',
        "",
    ]

    # Insert the docstring
    for i, docstring_line in enumerate(docstring_lines):
        lines.insert(insert_line + i, docstring_line)

    return "\n".join(lines)


def process_file(file_path: Path) -> bool:
    """
    Process a single state file to add missing docstrings.

    Returns True if the file was modified, False otherwise.
    """
    print(f"Processing {file_path.name}...")

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    state_classes = extract_state_classes(content)

    if not state_classes:
        print(f"  No state classes found in {file_path.name}")
        return False

    # Process classes in reverse order to maintain line numbers
    modified = False
    for class_name, domain, class_line in reversed(state_classes):
        if not has_docstring(content, class_line):
            print(f"  Adding docstring to {class_name}")
            content = add_docstring_to_class(content, domain, class_line)
            modified = True
        else:
            print(f"  {class_name} already has docstring, skipping")

    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"  ✓ Updated {file_path.name}")
        return True
    print(f"  No changes needed for {file_path.name}")
    return False


def main():
    """Main function to process all state files."""
    script_dir = Path(__file__).parent
    states_dir = script_dir / "src" / "hassette" / "models" / "states"

    if not states_dir.exists():
        print(f"Error: States directory not found at {states_dir}")
        return

    print(f"Scanning for state files in {states_dir}")
    state_files = find_state_files(states_dir)

    if not state_files:
        print("No state files found!")
        return

    print(f"Found {len(state_files)} state files")
    print()

    modified_files = []
    for file_path in sorted(state_files):
        if process_file(file_path):
            modified_files.append(file_path.name)
        print()

    print("Summary:")
    if modified_files:
        print(f"Modified {len(modified_files)} files:")
        for filename in modified_files:
            print(f"  - {filename}")
    else:
        print("No files were modified (all state classes already have docstrings)")


if __name__ == "__main__":
    main()
