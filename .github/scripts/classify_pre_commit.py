"""Conservatively classify pre-commit rev-only changes from the GitHub files API."""

import json
import re
import sys


def version(line):
    """Read a stable version from a tag or the comment on a SHA-pinned rev."""
    match = re.fullmatch(
        r"(?P<indent>\s+)rev: (?P<ref>v?\d+\.\d+\.\d+|[0-9a-f]{40})"
        r"(?:\s+# v?(?P<version>\d+\.\d+\.\d+))?",
        line,
    )
    if not match:
        return None
    ref = match["ref"]
    tag = ref.lstrip("v") if len(ref) != 40 else None
    comment = match["version"]
    if tag and comment and tag != comment:
        return None
    value = tag or comment
    if not value:
        return None
    return match["indent"], tuple(map(int, value.split(".")))


def classify(files):
    """Accept only forward, same-major updates that modify nothing except revs."""
    if len(files) != 1:
        return ""
    file = files[0]
    if (
        file.get("filename") != ".pre-commit-config.yaml"
        or file.get("status") != "modified"
    ):
        return ""
    patch = file.get("patch", "")
    removed = [line[1:] for line in patch.splitlines() if line.startswith("-")]
    added = [line[1:] for line in patch.splitlines() if line.startswith("+")]
    # Missing/truncated patches and extra changes must fail closed.
    if not removed or len(removed) != len(added):
        return ""
    if len(removed) != file.get("deletions") or len(added) != file.get("additions"):
        return ""
    update_type = "version-update:semver-patch"
    for before, after in zip(removed, added, strict=True):
        old, new = version(before), version(after)
        if not old or not new or old[0] != new[0]:
            return ""
        previous, current = old[1], new[1]
        if current <= previous or current[0] != previous[0]:
            return ""
        if current[1] != previous[1]:
            update_type = "version-update:semver-minor"
    return update_type


if __name__ == "__main__":
    # --paginate --slurp produces one array per page; inspect every changed file.
    print(classify([file for page in json.load(sys.stdin) for file in page]))
