# The image of the generic pack: Python and the scientific stack.
#
# Built with `utux image build packs/generic/image`, which records the image id
# in digest.txt beside this file. Runs refuse any other image.
#
# The base image is pinned by digest, and every package by version and hash,
# so that two builds install the same files. Nothing in the image needs the
# network at run time: runs have none (--network=none).

FROM python:3.12-slim-bookworm@sha256:e697c81897302a4c4333bade000d98038fbb21eb064f8ee1fd42d02ebcd9d337

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp

COPY requirements.txt /opt/utux/requirements.txt
RUN python -m pip install --require-hashes --only-binary=:all: -r /opt/utux/requirements.txt

# A non-root user. utux runs the container as the host user's id in any case.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin utux
USER utux

WORKDIR /project
