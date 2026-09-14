# Publishing a release

What `release.yml` does on its own, and the one step it cannot do.

## Cutting the release

Publishing a GitHub release triggers `release.yml`, which builds both images for `linux/amd64` and
`linux/arm64` from the `production` targets and pushes them to GHCR. A release tagged `vMAJOR.MINOR.PATCH`
produces four tags per image:

| Tag     | Moves? |
|---------|--------|
| `MAJOR.MINOR.PATCH` | never — this is the one to pin |
| `MAJOR.MINOR`   | on every patch release |
| `MAJOR`         | on every minor release |
| `latest`| on every release, including across a breaking change |

`VITE_APP_VERSION` is passed the release tag at build time, so the version shown in the UI comes
from the tag rather than from a file somebody has to remember to bump.

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
