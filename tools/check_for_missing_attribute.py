#!/usr/bin/env -S uv run --script
import ast
from pathlib import Path
from typing import cast

ROOT = Path("src")


class StateInfo:
    def __init__(self, file, class_name, lineno, has_attributes_field, nested_attr_classes, module_attr_classes):
        self.file = file
        self.class_name = class_name
        self.lineno = lineno
        self.has_attributes_field = has_attributes_field
        self.nested_attr_classes = nested_attr_classes
        self.module_attr_classes = module_attr_classes


def iter_py_files(root: Path):
    for path in root.rglob("*.py"):
        # Skip caches/venv/build-ish
        if any(part in {".venv", "__pycache__", ".nox"} for part in path.parts):
            continue
        yield path


def find_states(path: Path):
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    module_attr_classes = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.endswith("Attributes"):
            module_attr_classes.add(node.name)

    infos = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if not node.name.endswith("State"):
            continue

        has_attributes_field = False
        nested_attr_classes = []
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name) and item.target.id == "attributes":
                has_attributes_field = True
            elif isinstance(item, ast.Assign):
                if any(isinstance(t, ast.Name) and t.id == "attributes" for t in item.targets):
                    has_attributes_field = True
            elif isinstance(item, ast.ClassDef):
                if item.name == "Attributes" or item.name.endswith("Attributes"):
                    nested_attr_classes.append((item.name, item.lineno))

        infos.append(
            StateInfo(
                file=path,
                class_name=node.name,
                lineno=node.lineno,
                has_attributes_field=has_attributes_field,
                nested_attr_classes=nested_attr_classes,
                module_attr_classes=module_attr_classes,
            )
        )

    return infos


def main():
    found_states = 0
    problems = []
    for path in iter_py_files(ROOT):
        for info in find_states(path):
            found_states += 1
            info = cast("StateInfo", info)
            state_prefix = info.class_name[:-5]  # strip 'State'
            expected = state_prefix + "Attributes"

            has_attr_model = False
            if expected in info.module_attr_classes:
                has_attr_model = True
            if info.nested_attr_classes:
                has_attr_model = True

            if has_attr_model and not info.has_attributes_field:
                problems.append((str(info.file), info.class_name, info.lineno, expected, info.nested_attr_classes))

    print(
        f"Found {len(problems)} state(s) with an attributes model but no 'attributes' field out of "
        f"{found_states} states scanned."
    )
    for file, cls, lineno, expected, nested in problems:
        nested_s = ", ".join([f"{n}@{ln}" for n, ln in nested])
        print(f"- {file}:{lineno} {cls} (expected {expected}) nested=[{nested_s}]")


if __name__ == "__main__":
    main()
