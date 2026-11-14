#!/usr/bin/env python3
"""Stop: ask for one concision pass when the turn changed Python code.

Fires once per distinct diff; stop_hook_active and a diff hash prevent loops.
"""

import hashlib
import json
import pathlib
import subprocess
import sys

event = json.load(sys.stdin)
if event.get("stop_hook_active"):
    sys.exit(0)

diff = subprocess.run(["git", "diff", "HEAD", "--", "*.py"], capture_output=True, text=True).stdout
untracked = subprocess.run(
    ["git", "ls-files", "--others", "--exclude-standard", "--", "*.py"],
    capture_output=True,
    text=True,
).stdout
changed = (
    diff
    + untracked
    + "".join(pathlib.Path(p).read_text(errors="ignore") for p in untracked.split())
)
if not changed.strip():
    sys.exit(0)

state = pathlib.Path(".claude/.concise_state")
digest = hashlib.sha256(changed.encode()).hexdigest()
if state.exists() and state.read_text() == digest:
    sys.exit(0)
state.write_text(digest)

print(
    json.dumps(
        {
            "decision": "block",
            "reason": (
                "Concision pass on the Python you changed this turn (git diff + new files). "
                "Make it concise and readable without changing behavior: drop dead code, "
                "redundant comments and needless abstractions; merge duplicated logic; use "
                "clear names and early returns; keep public APIs and tests passing. "
                "Run the tests after editing. If it is already tight, say so briefly and stop."
            ),
        }
    )
)
