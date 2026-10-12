# Publishing a release

What `release.yml` does on its own, and the one step it cannot do.

## Cutting the release

First run the [full candidate CI](../reference/ci.md#exact-release-candidate-validation) and
wait for **CI passed** to succeed. Record its `headSha` and create the release tag on that
exact commit in `main` history. A green CodeQL-only push run or a PR check on a different SHA
does not satisfy this release gate.
Use canonical SemVer: `vMAJOR.MINOR.PATCH`, optionally with a prerelease such as `-rc.1`.
A bare version is normalized to the same container tag. Numeric identifiers cannot have leading
zeroes. Build metadata remains supported: `+` is encoded as `_build_` in container tags, so
`v1.2.3+meta` becomes `1.2.3_build_meta` and cannot collide with prerelease `1.2.3-meta`.
The encoded tag must fit Docker's 128-character limit. Publish each distinct release version from a
distinct commit: the immutable `sha-<commit>` tag cannot represent two frontend build versions.

Publishing a GitHub release triggers `release.yml`. Before building, it verifies an existing
successful manual full CI on the tag's resolved SHA. It does not rerun the suite. Without that
proof, image publication stops; the GitHub release itself is already published, but existing
container tags remain unchanged. After completing the missing validation, rerun the failed
release workflow. Builds use the validated immutable SHA, rather than resolving the tag again.

The workflow then builds both images for `linux/amd64` and
`linux/arm64` from the `production` targets. It pushes candidates by digest, scans them, records a
CycloneDX SBOM and build provenance, and only then promotes both images in GHCR. A stable release
tagged `vMAJOR.MINOR.PATCH` produces five tags per image:

| Tag     | Moves? |
|---------|--------|
| `MAJOR.MINOR.PATCH` | never — this is the one to pin |
| `sha-<commit>` | never — identifies the exact source commit |
| `MAJOR.MINOR`   | only to a newer patch in that minor line |
| `MAJOR`         | only to a newer version in that major line |
| `latest`| only to a newer stable version, including across a breaking change |

Prereleases receive only their exact version and `sha-<commit>` tags. They never move `latest` or
the floating major/minor tags.

`VITE_APP_VERSION` is passed the release tag at build time, so the version shown in the UI comes
from the tag rather than from a file somebody has to remember to bump.
The builder normalizes the `v` prefix for consistent version labels on both images.
Metadata stays intact in version labels and the application version. Since SemVer ignores
metadata for precedence, a different metadata build at the same version receives immutable tags
but does not replace existing floating aliases. Legacy ambiguous metadata/prerelease tags remain
protected; an identity conflict requires explicit inspection rather than an automatic overwrite.

## Promotion, retries and recovery

The reusable publisher serializes edge and release runs with one GHCR concurrency group.
Its `queue: max` retains up to 100 waiting publications; further runs are canceled when the queue
is full. A canceled or interrupted publication can be rerun; version checks still prevent downgrades.
Before building, it validates the source SHA and version and checks both components' exact/SHA
tags. An existing tag with another source, version or conflicting digest stops publication.
Matching existing immutable images are reused and rescanned on **both architectures**; rerunning
a successful release does not rebuild or overwrite those tags. A partially published immutable
pair can be completed using its existing digest. Release aliases are compared independently by
numeric SemVer, so publishing an older maintenance release cannot reset `latest` or a newer line.

After scans, preflight fetches both approved multi-platform indexes, verifies each architecture's
source/version labels, and checks every destination before any public write. Docker Buildx
inspects and copies the existing indexes, preserving digests, SBOMs and provenance; Docker's
login action handles registry credentials. Image metadata comes from Docker's metadata action.
The policy helper only implements the version, immutability and recovery rules. A mixed existing backend/frontend
pair stops promotion until it is recovered. The `promotion-preflight-<attempt>` artifact records
old and new digests **before** writing; `promotion-outcome-<attempt>` records the final result.
A verified pair produces `publication-release` (or `publication-edge`) with both digests and its
source SHA. These artifacts are retained for 90 days.

GHCR's [registry API](https://distribution.github.io/distribution/spec/api/) updates one package
tag at a time and has no transaction spanning backend and frontend. There can be a short mixed
pair while aliases change. Deploy using the paired digests in `publication.json` when consistency
is essential; independently resolving two floating tags cannot provide an atomic snapshot.

On an ordinary promotion error, the publisher restores **all attempted existing floating tags**,
including a PUT whose response was lost. Newly created immutable tags stay as retry anchors.
On a first publication there may be no previous tag to restore; rerun to finish that initial pair.
For a timeout, killed runner, or failed rollback, download the preflight/outcome journal, ensure
no publisher is running or queued, and restore existing aliases from a trusted checkout:

```bash
export GITHUB_REPOSITORY=Tyron2k/Capado
# Log in privately with a credential that can read and write these packages.
docker login ghcr.io
python3 .github/scripts/publication.py recover /path/to/promotion-journal.json
```

Recovery validates all current aliases against the journal before restoring them; it refuses to
overwrite a later publication. Do not delete immutable tags to force a conflicting retry. Resolve
an unexpected source/version conflict explicitly or publish a new version from a new validated
commit. Rerun the original release workflow after recovery; no new GitHub release is required. Approved
digest artifacts last one day; after that, rerun **all jobs** to regenerate or reuse and rescan
the candidates. Scan and digest artifact uploads replace their previous attempt, so full reruns
do not collide with existing artifacts.

## Making the images pullable — this is manual

**A public repository does not make its images public.** GitHub's own documentation is explicit:

> By default, if you publish a package that is linked to a repository, the package automatically
> inherits the access permissions (but not the visibility) of the linked repository.

Permissions are inherited, visibility is not. So after the first release the images are still
private, and anyone who is not a collaborator gets:

```
Error response from daemon: unauthorized
```

with no indication that visibility is the reason. Somebody following the README's Quick Start will
conclude Capado is broken, because nothing in that message says "this package is private".

Fix it once per image, in the web UI: **Packages → `backend` → Package settings → Danger Zone →
Change visibility → Public**, then the same for `frontend`. Newly pushed tags inherit the
package's visibility, so this is a one-time step per image and not per release.

Verify from a shell with no credentials for the repository:

```bash
docker logout ghcr.io
docker pull ghcr.io/<owner>/capado/backend:latest
```

If that succeeds, a stranger can run Capado. If it does not, the Quick Start does not work for
anybody but you — and that failure is invisible from inside the account that owns the packages,
which is why it is worth actually running the check rather than assuming.

## After moving to an organisation

The images live under the account that owns the repository, so moving the repository moves the
package path with it. Two consequences:

- `CAPADO_IMAGE_PREFIX` in `.env.example` and the `curl` URLs in the README both name the old
  owner and need updating.
- The visibility step above has to be repeated: the packages are new under the new owner.
