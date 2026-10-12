"""Publication policy; Docker Buildx handles registry authentication and transport.

All writers must hold the reusable workflow's repository-wide concurrency lock.
Buildx copies existing indexes, preserving digests and attestations.
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

COMPONENTS = ("backend", "frontend")
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
SEMVER = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)


def version(value):
    """Validate SemVer; metadata has no effect on version precedence."""
    match = SEMVER.fullmatch(value)
    if not match or (
        match[4]
        and any(p.isdigit() and len(p) > 1 and p[0] == "0" for p in match[4].split("."))
    ):
        raise ValueError(f"Invalid release version: {value}")
    canonical = value.removeprefix("v")
    if len(canonical.replace("+", "_build_")) > 128:
        raise ValueError("Release version exceeds the registry tag length limit")
    return canonical, tuple(int(match[i]) for i in (1, 2, 3)), bool(match[4])


def release_tag(value):
    """An underscore cannot occur in SemVer, making this metadata encoding injective."""
    return version(value)[0].replace("+", "_build_")


def validate(channel, release, sha):
    if not SHA.fullmatch(sha):
        raise ValueError("Source must be an immutable 40-character commit SHA")
    if channel == "release":
        return "v" + version(release)[0]
    if channel != "edge" or release:
        raise ValueError("Expected edge with no version, or release with a SemVer tag")
    return "edge-" + sha


@dataclass(frozen=True)
class Manifest:
    digest: str
    identity: tuple | None = None


def buildx(*arguments):
    return subprocess.run(
        ["docker", "buildx", "imagetools", *arguments],
        capture_output=True,
        text=True,
        timeout=60,
    )


def missing_manifest(error, ref):
    """Accept explicit absence only; mixed and unrecognized errors fail closed."""
    absence = r"\b(?:manifest|name)[_ ]unknown\b"
    detail = re.sub(absence, "", error, flags=re.IGNORECASE).replace(ref, "")
    if re.search(
        r"\b(?:401|403|429|5\d\d|unauthori[sz]ed|forbidden|denied|auth\w*|"
        r"credential\w*|token|dial|connection|network|timeout|timed out|deadline|"
        r"unreachable|no such host|tls|certificate|server error|unavailable|"
        r"unexpected|unknown|unsupported|cancel\w*|eof)\b",
        detail,
        re.IGNORECASE,
    ):
        return False
    return bool(
        re.search(absence, error, re.IGNORECASE)
        or re.search(
            re.escape(ref) + r"[\"'`]?:\s*not found\.?\s*$", error, re.IGNORECASE
        )
    )


class Registry:
    """Use the runner's Docker credentials and native Buildx registry commands."""

    def __init__(self, repository):
        self.prefix = "ghcr.io/" + repository

    def get(self, component, reference):
        image = f"{self.prefix}/{component}"
        ref = image + ("@" if DIGEST.fullmatch(reference) else ":") + reference
        result = buildx(
            "inspect",
            ref,
            "--format",
            '{"manifest": {{json .Manifest}}, "images": {{json .Image}}}',
        )
        if result.returncode == 1 and missing_manifest(result.stderr, ref):
            # Formatted inspection also fetches child/config blobs. Confirm that
            # the target index itself is absent, rather than a broken child.
            probe = buildx("inspect", ref, "--raw")
            if probe.returncode == 1 and missing_manifest(probe.stderr, ref):
                return None
            probe.check_returncode()
        result.check_returncode()
        data = json.loads(result.stdout)
        digest = data["manifest"]["digest"]
        if not DIGEST.fullmatch(digest) or ("@" in ref and digest != reference):
            raise ValueError("Registry returned a different or invalid digest")
        runtime = [
            d["platform"]
            for d in data["manifest"]["manifests"]
            if d.get("platform", {}).get("os") != "unknown"
        ]
        expected = {("linux", "amd64"), ("linux", "arm64")}
        configs = list(data["images"].values())
        if (
            len(runtime) != 2
            or len(configs) != 2
            or {(p["os"], p["architecture"]) for p in runtime} != expected
            or {(p["os"], p["architecture"]) for p in configs} != expected
        ):
            raise ValueError(
                f"{component}: expected exactly linux/amd64 and linux/arm64"
            )
        identities = {
            (
                c["config"].get("Labels", {}).get("org.opencontainers.image.revision"),
                c["config"].get("Labels", {}).get("org.opencontainers.image.version"),
            )
            for c in configs
        }
        if len(identities) != 1:
            raise ValueError(f"{component}: architectures have inconsistent identities")
        return Manifest(digest, identities.pop())

    def put(self, component, tag, manifest):
        image = f"{self.prefix}/{component}"
        buildx(
            "create", "--tag", image + ":" + tag, image + "@" + manifest.digest
        ).check_returncode()
        if self.get(component, tag) != manifest:
            raise RuntimeError(f"Verification failed for {component}:{tag}")

    def identity(self, component, manifest):
        return manifest.identity


def matching(registry, component, manifest, sha, app_version):
    actual_sha, actual_version = registry.identity(component, manifest)
    # Existing pre-refactor releases used either a v-prefixed or bare version.
    if actual_sha != sha or (actual_version or "").removeprefix(
        "v"
    ) != app_version.removeprefix("v"):
        raise ValueError(
            f"{component}: immutable tag belongs to a different source/version"
        )


def reusable(registry, channel, release, sha):
    app_version = validate(channel, release, sha)
    result = {}
    for component in COMPONENTS:
        if channel == "edge":
            result[component] = ""
            continue
        exact = registry.get(component, release_tag(release))
        source = registry.get(component, "sha-" + sha)
        for manifest in (exact, source):
            if manifest:
                matching(registry, component, manifest, sha, app_version)
        if exact and source and exact.digest != source.digest:
            raise ValueError(
                f"{component}: version and SHA tags disagree; repair before retrying"
            )
        existing = exact or source
        result[component] = existing.digest if existing else ""
    return result


def promotion_plan(registry, channel, release, sha, digests):
    """Read and validate every destination before changing any public tag."""
    app_version = validate(channel, release, sha)
    candidates = {}
    for component in COMPONENTS:
        if not DIGEST.fullmatch(digests[component]):
            raise ValueError(f"{component}: invalid approved digest")
        manifest = registry.get(component, digests[component])
        if manifest is None:
            raise ValueError(f"{component}: approved digest is unavailable")
        matching(registry, component, manifest, sha, app_version)
        candidates[component] = manifest
    immutable = (
        ["edge-" + sha] if channel == "edge" else [release_tag(release), "sha-" + sha]
    )
    writes = []
    for tag in immutable:
        for component in COMPONENTS:
            existing = registry.get(component, tag)
            if existing:
                if (
                    channel == "release"
                    and existing.digest != candidates[component].digest
                ):
                    raise ValueError(
                        f"{component}:{tag} is immutable and already has another digest"
                    )
                if channel == "edge":
                    matching(registry, component, existing, sha, app_version)
            else:
                writes.append((component, tag, candidates[component], None, True))
    floats = ["edge"]
    if channel == "release":
        _, numbers, prerelease = version(release)
        floats = (
            []
            if prerelease
            else [f"{numbers[0]}.{numbers[1]}", str(numbers[0]), "latest"]
        )
    for tag in floats:
        previous = {component: registry.get(component, tag) for component in COMPONENTS}
        identities = [
            registry.identity(c, previous[c]) if previous[c] else None
            for c in COMPONENTS
        ]
        if identities[0] != identities[1] and not (
            None in identities
            and all(
                identity is None or identity == (sha, app_version)
                for identity in identities
            )
        ):
            raise ValueError(
                f"{tag}: backend/frontend versions disagree; restore the previous pair first"
            )
        if channel == "release" and identities[0]:
            current_version, current_numbers, current_prerelease = version(
                identities[0][1]
            )
            if current_prerelease:
                raise ValueError(
                    f"{tag}: a floating release tag points to a prerelease"
                )
            if current_numbers > numbers:
                continue
            if current_numbers == numbers and current_version != version(release)[0]:
                # Metadata cannot decide which build is newer. Preserve the first
                # publication at this precedence instead of arbitrarily replacing it.
                continue
            if current_numbers == numbers and any(
                previous[c] and previous[c].digest != candidates[c].digest
                for c in COMPONENTS
            ):
                raise ValueError(f"{tag}: the same release has different image digests")
        for component in COMPONENTS:
            if previous[component] != candidates[component]:
                writes.append(
                    (component, tag, candidates[component], previous[component], False)
                )
    return writes


def journal_for(plan):
    return {
        "status": "prepared",
        "writes": [
            {
                "component": c,
                "tag": t,
                "candidate": new.digest,
                "previous": old.digest if old else None,
                "immutable": immutable,
            }
            for c, t, new, old, immutable in plan
        ],
    }


def recover(registry, journal):
    """Restore a failed pair, refusing to overwrite later successful publications."""
    restores = []
    for write in journal["writes"]:
        if write["immutable"] or not write["previous"]:
            continue
        component, tag = write["component"], write["tag"]
        current = registry.get(component, tag)
        if current is None or current.digest not in {
            write["candidate"],
            write["previous"],
        }:
            raise ValueError(
                f"{component}:{tag}: changed since this journal; refusing recovery"
            )
        previous = registry.get(component, write["previous"])
        if previous is None:
            raise ValueError("Previous digest is unavailable; stop and inspect GHCR")
        restores.append((component, tag, previous))
    for component, tag, previous in restores:
        registry.put(component, tag, previous)


def promote(registry, plan, journal_path):
    """Restore existing floating tags on failure; retain new immutable recovery anchors."""
    journal = journal_for(plan)
    journal_path.write_text(json.dumps(journal, indent=2) + "\n")
    attempted = []
    try:
        for component, tag, candidate, previous, immutable in plan:
            # Record before PUT: a timeout can occur after the server accepted it.
            attempted.append((component, tag, candidate, previous, immutable))
            registry.put(component, tag, candidate)
        journal["status"] = "committed"
    except Exception:
        recovery = []
        for component, tag, _candidate, previous, immutable in reversed(attempted):
            if immutable:
                continue
            if previous is None:
                recovery.append(
                    f"{component}:{tag}: no previous tag; rerun to finish the initial pair"
                )
                continue
            try:
                registry.put(component, tag, previous)
            except Exception:
                recovery.append(
                    f"{component}:{tag}: restore {previous.digest} from the journal"
                )
        journal.update(status="failed", recovery=recovery)
        raise
    finally:
        journal_path.write_text(json.dumps(journal, indent=2) + "\n")


def output(values):
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        for key, value in values.items():
            print(f"{key}={value}", file=stream)


def main():
    if sys.argv[1] == "recover":
        recover(
            Registry(os.environ["GITHUB_REPOSITORY"].lower()),
            json.loads(Path(sys.argv[2]).read_text()),
        )
        return
    channel = os.environ["CHANNEL"]
    release = os.environ.get("RELEASE_VERSION", "")
    sha = os.environ["SOURCE_SHA"]
    app_version = validate(channel, release, sha)
    registry = Registry(os.environ["GITHUB_REPOSITORY"].lower())
    if sys.argv[1] == "prepare":
        reused = reusable(registry, channel, release, sha)
        output(
            {
                "app-version": app_version,
                **{c + "-digest": d for c, d in reused.items()},
            }
        )
    elif sys.argv[1] in {"plan", "promote"}:
        if channel == "edge" and sys.argv[1] == "promote":
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{os.environ['GITHUB_REPOSITORY']}/git/ref/heads/main",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            if json.loads(result.stdout)["object"]["sha"] != sha:
                output({"published": "false"})
                print(
                    "Main advanced during the build; skipping obsolete edge publication."
                )
                return
        digests = {c: Path("digests", c).read_text().strip() for c in COMPONENTS}
        plan = promotion_plan(registry, channel, release, sha, digests)
        if sys.argv[1] == "plan":
            Path("promotion-journal.json").write_text(
                json.dumps(journal_for(plan), indent=2) + "\n"
            )
            return
        promote(registry, plan, Path("promotion-journal.json"))
        Path("publication.json").write_text(
            json.dumps(
                {
                    "source_sha": sha,
                    "version": app_version,
                    "digests": digests,
                    "published_at": datetime.now(UTC).isoformat(),
                    "channel": channel,
                },
                indent=2,
            )
            + "\n"
        )
        output({"published": "true"})
    else:
        raise ValueError("Expected prepare or promote")


if __name__ == "__main__":
    main()
