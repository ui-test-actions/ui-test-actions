"""Read one exploration request and relay the current agent's JSON decision."""

import json
from pathlib import Path
import sys
import time


inbox = Path(sys.argv[1])
request = json.load(sys.stdin)
key = request["remaining_decisions"]
pending = inbox / f"request-{key}.tmp"
pending.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
pending.replace(inbox / f"request-{key}.json")
decision = inbox / f"decision-{key}.json"
deadline = time.monotonic() + 150
while time.monotonic() < deadline:
    if decision.is_file():
        sys.stdout.write(decision.read_text(encoding="utf-8"))
        sys.exit(0)
    time.sleep(.25)
sys.exit(1)
