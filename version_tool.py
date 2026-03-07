#!/usr/bin/env python
"""AST-based version tool for PyBuilder build.py files.

Reads and modifies the `version` variable in a PyBuilder build.py using AST
analysis to ensure correctness. No external dependencies (stdlib only).

Compatible with Python 3.9 - 3.15+.
"""

import ast
import json
import re
import sys


# PEP 440 version regex, derived from the spec.
# Accepts bare `.dev` (no trailing number) as a PyBuilder convention.
_PEP440_RE = re.compile(
    r"^(?:(?P<epoch>[0-9]+)!)?"          # epoch
    r"(?P<release>[0-9]+(?:\.[0-9]+)*)"  # release segment
    r"(?P<pre>"                           # pre-release
    r"[-_.]?"
    r"(?P<pre_type>a|alpha|b|beta|c|rc|preview)"
    r"[-_.]?"
    r"(?P<pre_num>[0-9]+)?"
    r")?"
    r"(?P<post>"                          # post-release
    r"(?:-(?P<post_num1>[0-9]+))"
    r"|"
    r"(?:[-_.]?(?:post|rev|r)[-_.]?(?P<post_num2>[0-9]+)?)"
    r")?"
    r"(?P<dev>"                           # dev release
    r"[-_.]?dev[-_.]?(?P<dev_num>[0-9]+)?"
    r")?"
    r"$",
    re.IGNORECASE,
)

# Canonical pre-release type mapping
_PRE_TYPE_MAP = {
    "a": "a", "alpha": "a",
    "b": "b", "beta": "b",
    "c": "rc", "rc": "rc", "preview": "rc",
}


def _parse_pep440(version_str):
    """Parse a PEP 440 version string into components.

    Returns a dict with keys: epoch, release (list of ints), pre_type, pre_num,
    post_num, dev_num, is_dev, raw.
    Raises ValueError if the version doesn't match PEP 440.
    """
    m = _PEP440_RE.match(version_str)
    if not m:
        raise ValueError("Not a valid PEP 440 version: %r" % version_str)

    epoch = int(m.group("epoch")) if m.group("epoch") is not None else None
    release = [int(x) for x in m.group("release").split(".")]

    pre_type = None
    pre_num = None
    if m.group("pre") is not None:
        pre_type = _PRE_TYPE_MAP[m.group("pre_type").lower()]
        pre_num = int(m.group("pre_num")) if m.group("pre_num") is not None else 0

    post_num = None
    if m.group("post") is not None:
        raw_post = m.group("post_num1")
        if raw_post is None:
            raw_post = m.group("post_num2")
        post_num = int(raw_post) if raw_post is not None else 0

    dev_num = None
    is_dev = m.group("dev") is not None
    if is_dev:
        dev_num = int(m.group("dev_num")) if m.group("dev_num") is not None else None

    return {
        "epoch": epoch,
        "release": release,
        "pre_type": pre_type,
        "pre_num": pre_num,
        "post_num": post_num,
        "dev_num": dev_num,
        "is_dev": is_dev,
        "raw": version_str,
    }


def _format_version(parts):
    """Format parsed version parts back into a canonical PEP 440 string.

    Uses bare `.dev` (no number) for the dev segment, matching PyBuilder convention.
    """
    result = ""
    if parts["epoch"] is not None:
        result += "%d!" % parts["epoch"]
    result += ".".join(str(x) for x in parts["release"])
    if parts["pre_type"] is not None:
        result += "%s%d" % (parts["pre_type"], parts["pre_num"])
    if parts["post_num"] is not None:
        result += ".post%d" % parts["post_num"]
    if parts["is_dev"]:
        result += ".dev"
    return result


def _find_version_assignment(source):
    """Find the last top-level `version = "..."` assignment in source.

    Returns (node, value_str) or raises an error.
    Implements the full safety analysis described in the plan.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        raise ValueError("Failed to parse build.py: %s" % e)

    # Collect top-level assignments to `version`
    assignments = []  # list of (index, node)
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.AugAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "version":
                raise ValueError(
                    "Augmented assignment to `version` (line %d) is not supported"
                    % node.lineno
                )
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "version":
                    assignments.append((i, node))
                    break
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "version":
                if node.value is not None:
                    assignments.append((i, node))

    if not assignments:
        raise ValueError(
            "No top-level `version = \"...\"` assignment found in build.py"
        )

    last_idx, last_node = assignments[-1]

    # Check that the value is a string literal
    if isinstance(last_node, ast.Assign):
        value_node = last_node.value
    else:
        value_node = last_node.value

    if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
        raise ValueError(
            "version assignment on line %d is not a string literal"
            % last_node.lineno
        )

    # Post-assignment safety scan: check all nodes after the last assignment
    for j in range(last_idx + 1, len(tree.body)):
        _safety_scan(tree.body[j])

    return last_node, value_node


def _safety_scan(node):
    """Recursively scan an AST node for constructs that could modify `version`."""
    for child in ast.walk(node):
        # Assignment to `version` inside control flow
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name) and target.id == "version":
                    raise ValueError(
                        "Conditional/nested assignment to `version` on line %d "
                        "makes the version unprovable" % child.lineno
                    )
        if isinstance(child, ast.AugAssign):
            if isinstance(child.target, ast.Name) and child.target.id == "version":
                raise ValueError(
                    "Augmented assignment to `version` on line %d "
                    "makes the version unprovable" % child.lineno
                )
        if isinstance(child, ast.AnnAssign):
            if (isinstance(child.target, ast.Name) and child.target.id == "version"
                    and child.value is not None):
                raise ValueError(
                    "Annotated assignment to `version` on line %d "
                    "makes the version unprovable" % child.lineno
                )
        # del version
        if isinstance(child, ast.Delete):
            for target in child.targets:
                if isinstance(target, ast.Name) and target.id == "version":
                    raise ValueError(
                        "`del version` on line %d makes the version unprovable"
                        % child.lineno
                    )
        # exec() / eval() calls
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id in ("exec", "eval"):
                raise ValueError(
                    "`%s()` call on line %d makes the version unprovable"
                    % (func.id, child.lineno)
                )
            # globals(), vars(), locals()
            if isinstance(func, ast.Name) and func.id in ("globals", "vars", "locals"):
                raise ValueError(
                    "`%s()` call on line %d makes the version unprovable"
                    % (func.id, child.lineno)
                )
        # from X import *
        if isinstance(child, ast.ImportFrom):
            for alias in child.names:
                if alias.name == "*":
                    raise ValueError(
                        "Star import on line %d makes the version unprovable"
                        % child.lineno
                    )


def _replace_version_in_source(source, value_node, new_version_str):
    """Replace the version string literal in source using AST positions.

    Returns the modified source text.
    """
    lines = source.splitlines(True)

    # AST positions are 1-based for lines, 0-based for columns
    start_line = value_node.lineno - 1
    start_col = value_node.col_offset
    end_line = value_node.end_lineno - 1
    end_col = value_node.end_col_offset

    # Extract the original string literal to determine quote style
    if start_line == end_line:
        original_literal = lines[start_line][start_col:end_col]
    else:
        # Multi-line string literal (unusual for version but handle it)
        parts = [lines[start_line][start_col:]]
        for ln in range(start_line + 1, end_line):
            parts.append(lines[ln])
        parts.append(lines[end_line][:end_col])
        original_literal = "".join(parts)

    # Determine quote style from the original literal
    if original_literal.startswith('"""') or original_literal.startswith("'''"):
        quote = original_literal[:3]
    elif original_literal.startswith('"'):
        quote = '"'
    elif original_literal.startswith("'"):
        quote = "'"
    else:
        quote = '"'

    new_literal = quote + new_version_str + quote

    # Reconstruct the source with the replacement
    if start_line == end_line:
        line = lines[start_line]
        lines[start_line] = line[:start_col] + new_literal + line[end_col:]
    else:
        # Replace multi-line span
        lines[start_line] = lines[start_line][:start_col] + new_literal + lines[end_line][end_col:]
        del lines[start_line + 1:end_line + 1]

    return "".join(lines)


def _validate_replacement(new_source, expected_version):
    """Re-parse the modified source and confirm the version matches."""
    _, value_node = _find_version_assignment(new_source)
    actual = value_node.value
    if actual != expected_version:
        raise ValueError(
            "Verification failed: expected version %r but got %r after replacement"
            % (expected_version, actual)
        )


def cmd_read(build_py_path):
    """Read and print the version from build.py."""
    with open(build_py_path, "r") as f:
        source = f.read()

    _, value_node = _find_version_assignment(source)
    version_str = value_node.value
    parsed = _parse_pep440(version_str)

    result = {
        "version": version_str,
        "is_dev": parsed["is_dev"],
        "line": value_node.lineno,
    }
    print(json.dumps(result))


def cmd_set_release(build_py_path, explicit_version=None):
    """Set the release version by stripping .dev or setting an explicit version."""
    with open(build_py_path, "r") as f:
        source = f.read()

    _, value_node = _find_version_assignment(source)
    old_version = value_node.value
    old_parsed = _parse_pep440(old_version)

    if explicit_version is not None:
        # Validate the explicit version
        explicit_parsed = _parse_pep440(explicit_version)
        if explicit_parsed["is_dev"]:
            raise ValueError(
                "Explicit release version %r has a dev segment; "
                "release versions must not be dev versions" % explicit_version
            )
        new_version = explicit_version
    else:
        # Strip .dev suffix
        if not old_parsed["is_dev"]:
            raise ValueError(
                "Current version %r does not have a .dev segment; "
                "cannot strip it" % old_version
            )
        old_parsed["is_dev"] = False
        old_parsed["dev_num"] = None
        new_version = _format_version(old_parsed)

    new_source = _replace_version_in_source(source, value_node, new_version)
    _validate_replacement(new_source, new_version)

    with open(build_py_path, "w") as f:
        f.write(new_source)

    result = {"old_version": old_version, "new_version": new_version}
    print(json.dumps(result))


def cmd_bump_dev(build_py_path):
    """Bump the rightmost numeric segment and append .dev."""
    with open(build_py_path, "r") as f:
        source = f.read()

    _, value_node = _find_version_assignment(source)
    old_version = value_node.value
    parsed = _parse_pep440(old_version)

    if parsed["is_dev"]:
        raise ValueError(
            "Current version %r already has a .dev segment; "
            "bump-dev expects a release version" % old_version
        )

    # Bump the rightmost numeric segment
    if parsed["post_num"] is not None:
        parsed["post_num"] += 1
    elif parsed["pre_type"] is not None:
        parsed["pre_num"] += 1
    else:
        # Bump the last release segment
        parsed["release"][-1] += 1

    parsed["is_dev"] = True
    new_version = _format_version(parsed)

    new_source = _replace_version_in_source(source, value_node, new_version)
    _validate_replacement(new_source, new_version)

    with open(build_py_path, "w") as f:
        f.write(new_source)

    result = {"old_version": old_version, "new_version": new_version}
    print(json.dumps(result))


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: %s {read|set-release|bump-dev} BUILD_PY [VERSION]" % sys.argv[0],
            file=sys.stderr,
        )
        sys.exit(2)

    command = sys.argv[1]
    build_py_path = sys.argv[2]

    try:
        if command == "read":
            cmd_read(build_py_path)
        elif command == "set-release":
            explicit_version = sys.argv[3] if len(sys.argv) > 3 else None
            cmd_set_release(build_py_path, explicit_version)
        elif command == "bump-dev":
            cmd_bump_dev(build_py_path)
        else:
            print("Unknown command: %s" % command, file=sys.stderr)
            sys.exit(2)
    except (ValueError, OSError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
