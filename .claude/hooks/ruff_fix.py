#!/usr/bin/env python3
"""PostToolUse: format + lint-fix each Python file Claude writes or edits."""

import json
import subprocess
import sys

path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
if path.endswith(".py"):
    for cmd in (["ruff", "format", path], ["ruff", "check", "--fix", "--quiet", path]):
        subprocess.run(["uv", "run", "--quiet", *cmd], capture_output=True)
