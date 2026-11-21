# The image of a pack

Each pack runs its code in one container image. The generic pack's image is
in `packs/generic/image/`:

| File | What it is |
| --- | --- |
| `Dockerfile` | Python 3.12 on `python:3.12-slim-bookworm`, pinned by digest, with numpy, pandas, scikit-learn and matplotlib, and a non-root user `utux` |
| `requirements.txt` | Every package the image installs, the dependencies included, pinned by version and by hash; the Dockerfile installs them with `--require-hashes` and wheels only |
| `digest.txt` | The id of the image the maintainer built and committed. Empty until then |

Nothing in the image needs the network at run time; runs have none.

## Building it

```bash
uv run utux image build packs/generic/image
```

`utux image build [DIRECTORY] [--docker COMMAND]` runs `docker build` on the
directory, with its output shown, and, if the build succeeds, writes the new
image id to `digest.txt` with the atomic writer. A failed build records
nothing. Building fetches the base image and the packages, so it needs the
network; runs never build or pull.

## The recorded digest

`digest.txt` is empty, or holds one line, the local image id, for example
(a synthetic id):

```text
sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

`utux.executors.image.require_recorded_image(directory, digest)` refuses a
run whose image differs from the recorded one, and one for which no image is
recorded yet. The id is the local image id, so it differs between machines
that build the image separately ([The sandbox](sandbox.md)): to reproduce a
run elsewhere, use the same image, not a rebuild.

## Locked packages

`utux.executors.image.image_packages(digest)` lists the installed Python
packages by name and version from inside the image, running the listing in
the hardened sandbox like any step. A run manifest's
`container.locked_packages` is taken from it, never from the Dockerfile or
`requirements.txt`.

## Licences

The image is not part of the core; its packages run only inside the
sandbox. All are permissive: numpy, scipy, pandas, scikit-learn, joblib,
threadpoolctl, cloudpickle, contourpy, cycler and kiwisolver (BSD),
matplotlib (its own BSD-style licence), fonttools, pyparsing and pytz (MIT),
pillow (MIT-CMU), python-dateutil and packaging (Apache-2.0 or BSD), and
tzdata (Apache-2.0).
