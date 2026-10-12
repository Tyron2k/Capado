"""Offline regression tests: no live registries, tags, releases or credentials."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from publication import (  # noqa: E402
    COMPONENTS,
    Manifest,
    Registry,
    journal_for,
    main,
    matching,
    promote,
    promotion_plan,
    recover,
    release_tag,
    reusable,
    validate,
    version,
)

SHA = "1" * 40
OTHER_SHA = "2" * 40


class FakeRegistry:
    def __init__(self):
        self.tags = {}
        self.identities = {}
        self.writes = []
        self.fail_on = None
        self.rollback_fails = False

    def image(self, component, sha=SHA, value="v1.2.3", salt=""):
        manifest = Manifest(
            "sha256:"
            + hashlib.sha256(
                json.dumps([component, sha, value, salt]).encode()
            ).hexdigest()
        )
        self.tags[component, manifest.digest] = manifest
        self.identities[component, manifest.digest] = sha, value
        return manifest

    def pair(self, tag, sha=SHA, value="v1.2.3", salt=""):
        for component in COMPONENTS:
            self.tags[component, tag] = self.image(component, sha, value, salt)

    def get(self, component, reference):
        return self.tags.get((component, reference))

    def identity(self, component, manifest):
        return self.identities[component, manifest.digest]

    def put(self, component, tag, manifest):
        self.writes.append((component, tag, manifest.digest))
        self.tags[component, tag] = manifest
        if (component, tag) == self.fail_on:
            self.fail_on = None
            raise RuntimeError("Lost response after accepted PUT")
        if self.rollback_fails and len(self.writes) > 2:
            raise RuntimeError("Recovery connection failed")


class VersionTests(unittest.TestCase):
    def test_valid_versions(self):
        for value in (
            "v0.0.0",
            "1.2.3",
            "v1.2.3-rc.1",
            "v1.2.3-beta-x",
            "v1.2.3+build.00",
            "v1.2.3-build+meta",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    validate("release", value, SHA), "v" + value.removeprefix("v")
                )

    def test_reject_ambiguous_or_invalid_versions(self):
        for value in (
            "v01.2.3",
            "1.2",
            "1.2.3+",
            "1.2.3+build+meta",
            "1.2.3_build_meta",
            "1.2.3-01",
            "1.2.3-",
            "1.2.3-rc..1",
            "1.2.3;echo x",
            "1.2.3\nlatest",
            "1.2.3-" + "x" * 129,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                version(value)

    def test_metadata_encoding_cannot_collide_with_prereleases(self):
        self.assertEqual(release_tag("v1.2.3+build.1"), "1.2.3_build_build.1")
        self.assertNotEqual(
            release_tag("v1.2.3+build.1"), release_tag("v1.2.3-build.1")
        )
        self.assertNotEqual(
            release_tag("v1.2.3-rc.1+build.1"), release_tag("v1.2.3-rc.1-build.1")
        )

    def test_invalid_channels_sha_and_edge_version(self):
        for channel, release, sha in (
            ("other", "", SHA),
            ("edge", "v1.2.3", SHA),
            ("edge", "", "main"),
            ("release", "v1.2.3", "a" * 39),
        ):
            with self.subTest(channel=channel, sha=sha), self.assertRaises(ValueError):
                validate(channel, release, sha)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.registry = FakeRegistry()
        self.candidates = {c: self.registry.image(c) for c in COMPONENTS}
        self.digests = {c: m.digest for c, m in self.candidates.items()}

    def plan(self, release="v1.2.3", channel="release"):
        return promotion_plan(self.registry, channel, release, SHA, self.digests)

    def test_initial_stable_release_has_all_tags(self):
        plan = self.plan()
        self.assertEqual(len(plan), 10)
        self.assertEqual(
            {w[1] for w in plan}, {"1.2.3", "sha-" + SHA, "1.2", "1", "latest"}
        )

    def test_prerelease_never_changes_stable_aliases(self):
        self.digests = {
            c: self.registry.image(c, value="v1.2.3-rc.1").digest for c in COMPONENTS
        }
        self.assertEqual(
            {w[1] for w in self.plan("v1.2.3-rc.1")}, {"1.2.3-rc.1", "sha-" + SHA}
        )

    def test_stable_metadata_builds_receive_exact_and_stable_tags(self):
        self.digests = {
            c: self.registry.image(c, value="v1.2.3+build-1").digest for c in COMPONENTS
        }
        self.assertEqual(
            {w[1] for w in self.plan("v1.2.3+build-1")},
            {"1.2.3_build_build-1", "sha-" + SHA, "1.2", "1", "latest"},
        )

    def test_metadata_does_not_reset_equal_precedence_aliases(self):
        self.digests = {
            c: self.registry.image(c, value="v1.2.3+build.2").digest for c in COMPONENTS
        }
        for tag in ("1.2", "1", "latest"):
            self.registry.pair(tag, OTHER_SHA, "v1.2.3+build.1")
        self.assertEqual(
            {w[1] for w in self.plan("v1.2.3+build.2")},
            {"1.2.3_build_build.2", "sha-" + SHA},
        )

    def test_legacy_metadata_sha_is_reused_without_touching_ambiguous_tag(self):
        self.registry.pair("sha-" + SHA, value="v1.2.3+build.1")
        self.registry.pair("1.2.3-build.1", value="v1.2.3+build.1")
        reused = reusable(self.registry, "release", "v1.2.3+build.1", SHA)
        self.assertTrue(all(reused.values()))
        with self.assertRaises(ValueError):
            reusable(self.registry, "release", "v1.2.3-build.1", OTHER_SHA)

    def test_retry_reuses_both_immutable_tags_and_is_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            promote(self.registry, self.plan(), Path(directory, "journal.json"))
        self.assertEqual(reusable(self.registry, "release", "1.2.3", SHA), self.digests)
        self.assertEqual(self.plan(), [])

    def test_partial_immutable_pair_can_be_completed(self):
        self.registry.tags["backend", "1.2.3"] = self.candidates["backend"]
        reused = reusable(self.registry, "release", "v1.2.3", SHA)
        self.assertEqual(reused["backend"], self.digests["backend"])
        self.assertEqual(reused["frontend"], "")
        self.assertNotIn(("backend", "1.2.3"), {(w[0], w[1]) for w in self.plan()})

    def test_same_sha_with_another_release_version_is_rejected(self):
        self.registry.pair("sha-" + SHA, value="v1.2.2")
        with self.assertRaises(ValueError):
            reusable(self.registry, "release", "v1.2.3", SHA)
        self.assertEqual(self.registry.writes, [])

    def test_disagreeing_version_and_sha_tags_are_rejected(self):
        self.registry.pair("1.2.3")
        self.registry.pair("sha-" + SHA, salt="different build")
        with self.assertRaises(ValueError):
            reusable(self.registry, "release", "v1.2.3", SHA)

    def test_immutable_digest_conflict_aborts_before_any_writes(self):
        self.registry.pair("1.2.3", salt="existing")
        with self.assertRaises(ValueError):
            self.plan()
        self.assertEqual(self.registry.writes, [])

    def test_newer_aliases_do_not_roll_back(self):
        for tag in ("1.2", "1", "latest"):
            self.registry.pair(tag, sha=OTHER_SHA, value="v1.2.10")
        self.assertTrue(all(w[4] for w in self.plan()))

    def test_aliases_are_compared_independently_across_major_versions(self):
        self.registry.pair("latest", sha=OTHER_SHA, value="v2.0.0")
        tags = {w[1] for w in self.plan()}
        self.assertEqual(tags, {"1.2.3", "sha-" + SHA, "1.2", "1"})

    def test_mixed_existing_pair_is_rejected(self):
        self.registry.tags["backend", "latest"] = self.registry.image(
            "backend", OTHER_SHA, "v1.2.2"
        )
        with self.assertRaises(ValueError):
            self.plan()

    def test_initial_partial_float_can_finish_if_it_matches_candidate(self):
        self.registry.tags["backend", "latest"] = self.candidates["backend"]
        self.assertIn(("frontend", "latest"), {(w[0], w[1]) for w in self.plan()})

    def test_same_version_changed_digest_on_float_is_rejected(self):
        self.registry.pair("latest", salt="different")
        with self.assertRaises(ValueError):
            self.plan()

    def test_missing_or_invalid_candidate_digest_fails_preflight(self):
        for digest in ("main", "sha256:" + "a" * 64):
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                promotion_plan(
                    self.registry,
                    "release",
                    "v1.2.3",
                    SHA,
                    self.digests | {"frontend": digest},
                )

    def test_candidate_source_or_version_mismatch_fails_preflight(self):
        for sha, value in ((OTHER_SHA, "v1.2.3"), (SHA, "v1.2.4")):
            with self.subTest(sha=sha, value=value), self.assertRaises(ValueError):
                matching(
                    self.registry,
                    "backend",
                    self.registry.image("backend", sha, value),
                    SHA,
                    "v1.2.3",
                )

    def test_edge_security_rebuild_preserves_original_sha_tag(self):
        old = {}
        for c in COMPONENTS:
            old[c] = self.registry.image(c, value="edge-" + SHA, salt="old")
            self.registry.tags[c, "edge-" + SHA] = old[c]
            self.registry.tags[c, "edge"] = old[c]
        self.digests = {
            c: self.registry.image(c, value="edge-" + SHA, salt="fresh").digest
            for c in COMPONENTS
        }
        plan = self.plan("", "edge")
        self.assertEqual({w[1] for w in plan}, {"edge"})
        self.assertEqual(
            reusable(self.registry, "edge", "", SHA), {c: "" for c in COMPONENTS}
        )

    def test_failed_second_component_restores_both_previous_floats(self):
        self.registry.pair("latest", OTHER_SHA, "v1.2.2")
        previous = {c: self.registry.get(c, "latest") for c in COMPONENTS}
        plan = [w for w in self.plan() if w[1] == "latest"]
        self.registry.fail_on = ("frontend", "latest")
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory, "journal.json")
            with self.assertRaises(RuntimeError):
                promote(self.registry, plan, journal)
            self.assertEqual(json.loads(journal.read_text())["status"], "failed")
        self.assertEqual(
            {c: self.registry.get(c, "latest") for c in COMPONENTS}, previous
        )

    def test_failed_initial_pair_retains_recovery_instructions(self):
        self.registry.fail_on = ("frontend", "latest")
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory, "journal.json")
            with self.assertRaises(RuntimeError):
                promote(self.registry, self.plan(), journal)
            self.assertEqual(len(json.loads(journal.read_text())["recovery"]), 6)

    def test_recovery_failure_is_reported_in_journal(self):
        self.registry.pair("latest", OTHER_SHA, "v1.2.2")
        plan = [w for w in self.plan() if w[1] == "latest"]
        self.registry.fail_on = ("frontend", "latest")
        self.registry.rollback_fails = True
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory, "journal.json")
            with self.assertRaises(RuntimeError):
                promote(self.registry, plan, journal)
            self.assertEqual(len(json.loads(journal.read_text())["recovery"]), 2)

    def test_recovery_restores_previous_pair_but_refuses_newer_publication(self):
        self.registry.pair("latest", OTHER_SHA, "v1.2.2")
        plan = [w for w in self.plan() if w[1] == "latest"]
        journal = journal_for(plan)
        for c in COMPONENTS:
            self.registry.tags[c, "latest"] = self.candidates[c]
        recover(self.registry, journal)
        self.assertEqual(
            self.registry.identity("backend", self.registry.get("backend", "latest"))[
                1
            ],
            "v1.2.2",
        )
        self.registry.pair("latest", OTHER_SHA, "v1.2.4")
        before = len(self.registry.writes)
        with self.assertRaises(ValueError):
            recover(self.registry, journal)
        self.assertEqual(len(self.registry.writes), before)


class ApiTests(unittest.TestCase):
    def test_stale_edge_sha_stops_before_registry_writes(self):
        with (
            patch.dict(
                "os.environ",
                {
                    "CHANNEL": "edge",
                    "SOURCE_SHA": SHA,
                    "GITHUB_REPOSITORY": "owner/repo",
                },
            ),
            patch("publication.sys.argv", ["publication.py", "promote"]),
            patch("publication.subprocess.run") as run,
            patch("publication.output") as output,
            patch("publication.promotion_plan") as plan,
        ):
            run.return_value.stdout = json.dumps({"object": {"sha": OTHER_SHA}})
            main()
            output.assert_called_once_with({"published": "false"})
            plan.assert_not_called()

    def test_explicit_absence_formats_require_confirmation_of_target_manifest(self):
        registry = Registry("owner/repo")
        ref = "ghcr.io/owner/repo/backend:1.2.3"
        for error in (
            f"ERROR: {ref}: not found",
            f"error: failed to resolve source metadata for '{ref}': not found.",
            f"ERROR: manifest for {ref} not found: manifest unknown: manifest unknown",
            'ERROR: {"errors":[{"code":"MANIFEST_UNKNOWN","message":"manifest unknown"}]}',
            f"ERROR: {ref}: NAME_UNKNOWN: repository name not known",
        ):
            result = subprocess.CompletedProcess([], 1, "", error)
            with (
                self.subTest(error=error),
                patch("publication.subprocess.run", return_value=result) as run,
            ):
                self.assertIsNone(registry.get("backend", "1.2.3"))
                self.assertEqual(run.call_count, 2)
                self.assertEqual(run.call_args.args[0][-3:], ["inspect", ref, "--raw"])

    def test_registry_auth_network_timeout_server_and_unknown_errors_fail_closed(self):
        registry = Registry("owner/repo")
        ref = "ghcr.io/owner/repo/backend:1.2.3"
        for error in (
            "ERROR: unauthorized: authentication required",
            "ERROR: 401 Unauthorized",
            "ERROR: 403 Forbidden",
            "ERROR: denied: requested access to the resource is denied",
            "ERROR: dial tcp: connection refused",
            "ERROR: no such host",
            "ERROR: TLS certificate verification failed",
            "ERROR: i/o timeout",
            "ERROR: context deadline exceeded",
            "ERROR: 500 Internal Server Error",
            "ERROR: 502 Bad Gateway",
            "ERROR: 503 Service Unavailable",
            "ERROR: unexpected registry response",
            "ERROR: 404 Not Found",
            "ERROR: another-reference: not found",
            f"ERROR: {ref}: not found\n401 Unauthorized",
            "ERROR: MANIFEST_UNKNOWN: 403 Forbidden",
            "ERROR: manifest unknown: connection reset by peer",
            "ERROR: MANIFEST_UNKNOWN: 500 Internal Server Error",
            "ERROR: MANIFEST_UNKNOWN: UNKNOWN: unspecified error",
        ):
            result = subprocess.CompletedProcess([], 1, "", error)
            with (
                self.subTest(error=error),
                patch("publication.subprocess.run", return_value=result) as run,
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    registry.get("backend", "1.2.3")
                self.assertEqual(run.call_count, 1)
        with patch(
            "publication.subprocess.run",
            side_effect=subprocess.TimeoutExpired("docker", 60),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                registry.get("backend", "1.2.3")

    def test_crashed_or_unrecognized_process_exit_is_not_tag_absence(self):
        registry = Registry("owner/repo")
        for code in (-9, 2):
            result = subprocess.CompletedProcess(
                [], code, "", "ERROR: manifest unknown"
            )
            with (
                self.subTest(code=code),
                patch("publication.subprocess.run", return_value=result) as run,
            ):
                with self.assertRaises(subprocess.CalledProcessError):
                    registry.get("backend", "1.2.3")
                self.assertEqual(run.call_count, 1)

    def test_missing_child_does_not_mean_target_index_is_absent(self):
        registry = Registry("owner/repo")
        missing = subprocess.CompletedProcess([], 1, "", "ERROR: manifest unknown")
        exists = subprocess.CompletedProcess([], 0, '{"manifests": []}', "")
        with patch("publication.subprocess.run", side_effect=[missing, exists]):
            with self.assertRaises(subprocess.CalledProcessError):
                registry.get("backend", "1.2.3")

    def test_failed_or_timed_out_confirmation_does_not_mean_absence(self):
        registry = Registry("owner/repo")
        missing = subprocess.CompletedProcess([], 1, "", "ERROR: MANIFEST_UNKNOWN")
        for confirmation in (
            subprocess.CompletedProcess([], 1, "", "ERROR: 403 Forbidden"),
            subprocess.CompletedProcess([], 1, "", "ERROR: 503 Service Unavailable"),
            subprocess.CompletedProcess([], 1, "", "ERROR: unexpected response"),
            subprocess.TimeoutExpired("docker", 60),
        ):
            with (
                self.subTest(confirmation=confirmation),
                patch(
                    "publication.subprocess.run", side_effect=[missing, confirmation]
                ),
            ):
                with self.assertRaises(
                    (subprocess.CalledProcessError, subprocess.TimeoutExpired)
                ):
                    registry.get("backend", "1.2.3")

    def test_publisher_queue_remains_serial_and_keeps_multiple_pending_runs(self):
        workflow = (
            Path(__file__).resolve().parents[2] / "workflows/publish-images.yml"
        ).read_text()
        concurrency = workflow.split("\nconcurrency:\n", 1)[1].split("\njobs:\n", 1)[0]
        self.assertEqual(
            concurrency.strip(),
            "group: ghcr-publication-${{ github.repository }}\n  cancel-in-progress: false\n  queue: max",
        )

    def test_buildx_identity_requires_both_architectures_and_matching_labels(self):
        registry = Registry("owner/repo")
        configs = {
            f"linux/{arch}": {
                "os": "linux",
                "architecture": arch,
                "config": {
                    "Labels": {
                        "org.opencontainers.image.revision": SHA,
                        "org.opencontainers.image.version": "v1.2.3",
                    }
                },
            }
            for arch in ("amd64", "arm64")
        }
        data = {
            "manifest": {
                "digest": "sha256:" + "a" * 64,
                "manifests": [
                    {"platform": {"os": "linux", "architecture": arch}}
                    for arch in ("amd64", "arm64")
                ]
                + [{"platform": {"os": "unknown", "architecture": "unknown"}}],
            },
            "images": configs,
        }

        def inspect():
            result = subprocess.CompletedProcess([], 0, json.dumps(data), "")
            with patch("publication.subprocess.run", return_value=result):
                return registry.get("backend", "1.2.3")

        self.assertEqual(inspect().identity, (SHA, "v1.2.3"))
        configs["linux/arm64"]["config"]["Labels"][
            "org.opencontainers.image.revision"
        ] = OTHER_SHA
        with self.assertRaises(ValueError):
            inspect()
        configs["linux/arm64"]["config"]["Labels"][
            "org.opencontainers.image.revision"
        ] = SHA
        data["manifest"]["manifests"][1] = data["manifest"]["manifests"][0]
        with self.assertRaises(ValueError):
            inspect()
        data["manifest"]["manifests"].pop(1)
        with self.assertRaises(ValueError):
            inspect()

    def test_native_copy_uses_only_one_digest_source_and_verifies_destination(self):
        registry = Registry("owner/repo")
        candidate = Manifest("sha256:" + "a" * 64, (SHA, "v1.2.3"))
        with (
            patch("publication.subprocess.run") as run,
            patch.object(registry, "get", return_value=candidate),
        ):
            registry.put("backend", "1.2.3", candidate)
            self.assertEqual(
                run.call_args.args[0],
                [
                    "docker",
                    "buildx",
                    "imagetools",
                    "create",
                    "--tag",
                    "ghcr.io/owner/repo/backend:1.2.3",
                    "ghcr.io/owner/repo/backend@" + candidate.digest,
                ],
            )
        with (
            patch("publication.subprocess.run"),
            patch.object(registry, "get", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                registry.put("backend", "1.2.3", candidate)

    def test_inspected_digest_must_match_requested_digest(self):
        registry = Registry("owner/repo")
        result = subprocess.CompletedProcess(
            [], 0, json.dumps({"manifest": {"digest": "sha256:" + "a" * 64}}), ""
        )
        with (
            patch("publication.subprocess.run", return_value=result),
            self.assertRaises(ValueError),
        ):
            registry.get("backend", "sha256:" + "f" * 64)


if __name__ == "__main__":
    unittest.main()
