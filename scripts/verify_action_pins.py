"""Check that every ``uses: owner/repo@<sha> # vX.Y.Z`` pin points to the commit of that tag.

Runs in CI (job ``action-pins``) with the ``gh`` CLI and ``GH_TOKEN``. Exit 1 on any mismatch,
unpinned action or missing version comment. Stdlib + ``gh`` only.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USES = re.compile(r"uses:\s*([\w.-]+/[\w.-]+)(/[\w./-]+)?@(\S+)(?:\s*#\s*(v\S+))?")


def _tag_commit(repo: str, tag: str) -> str:
    raw = subprocess.run(  # noqa: S603 - fixed program, arguments from our own workflow files
        ["gh", "api", f"repos/{repo}/git/ref/tags/{tag}"],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    ref = json.loads(raw)["object"]
    if ref["type"] == "tag":  # annotated tag: dereference to the commit
        raw = subprocess.run(  # noqa: S603
            ["gh", "api", f"repos/{repo}/git/tags/{ref['sha']}"],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        ref = json.loads(raw)["object"]
    return str(ref["sha"])


def main() -> int:
    problems: list[str] = []
    checked: dict[tuple[str, str], str] = {}
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.y*ml")):
        for number, line in enumerate(workflow.read_text("utf-8").splitlines(), 1):
            match = USES.search(line)
            if not match:
                continue
            repo, _subpath, ref, tag = match.groups()
            where = f"{workflow.name}:{number}"
            if not re.fullmatch(r"[0-9a-f]{40}", ref):
                problems.append(f"{where}: {repo}@{ref} is not pinned to a commit SHA")
                continue
            if not tag:
                problems.append(f"{where}: {repo}@{ref} has no '# vX.Y.Z' comment")
                continue
            key = (repo, tag)
            if key not in checked:
                checked[key] = _tag_commit(repo, tag)
            if checked[key] != ref:
                problems.append(f"{where}: {repo} {tag} is {checked[key]}, pinned {ref}")
    for problem in problems:
        print(problem)
    print(f"checked {len(checked)} action tags, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
