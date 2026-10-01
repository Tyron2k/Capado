"""Regression cases for the pre-commit auto-merge fallback."""

import unittest

from classify_pre_commit import classify


def change(before, after, **overrides):
    """Build the GitHub API shape for one changed rev."""
    return {
        "filename": ".pre-commit-config.yaml",
        "status": "modified",
        "patch": f"@@ -1 +1 @@\n-{before}\n+{after}",
        "deletions": 1,
        "additions": 1,
        **overrides,
    }


class ClassifierTests(unittest.TestCase):
    """Only verifiable minor/patch rev-only changes may bypass missing metadata."""

    def test_sha_pinned_ruff_patch(self):
        old = "    rev: 2eeb5678de71a00c0902cbda7105d328432f72cb # v0.16.8"
        new = "    rev: a56c0b927e6465d37cae3e97d35d4d18ab2b96cd # v0.16.9"
        self.assertEqual(classify([change(old, new)]), "version-update:semver-patch")

    def test_minor_tag(self):
        self.assertEqual(
            classify([change("    rev: v1.2.3", "    rev: v1.3.0")]),
            "version-update:semver-minor",
        )

    def test_unsafe_or_unverifiable_versions(self):
        for new in ("v2.0.0", "v1.2.2", "v1.2.3", "v1.2.4rc1", "main", "a" * 40):
            with self.subTest(new=new):
                self.assertEqual(
                    classify([change("    rev: v1.2.3", f"    rev: {new}")]), ""
                )

    def test_conflicting_version_comment(self):
        self.assertEqual(
            classify([change("    rev: v1.2.3", "    rev: v2.0.0 # v1.2.4")]), ""
        )

    def test_other_changes_or_missing_patch(self):
        valid = change("    rev: v1.2.3", "    rev: v1.2.4")
        for overrides in (
            {"filename": "backend/pyproject.toml"},
            {"status": "added"},
            {"patch": ""},
            {"additions": 2},
            {"patch": "-    args: []\n+    args: [--unsafe]"},
            {"patch": valid["patch"] + "\n+    args: [--unsafe]", "additions": 2},
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(classify([{**valid, **overrides}]), "")
        self.assertEqual(classify([valid, valid]), "")
        self.assertEqual(classify([]), "")

    def test_group_with_major_update_is_rejected(self):
        file = change("    rev: v1.2.3", "    rev: v1.2.4")
        file["patch"] += "\n-    rev: v3.2.1\n+    rev: v4.0.0"
        file["deletions"] = file["additions"] = 2
        self.assertEqual(classify([file]), "")


if __name__ == "__main__":
    unittest.main()
