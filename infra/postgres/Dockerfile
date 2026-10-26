# The bundled Postgres, plus pgvector — the one extension the official image
# doesn't carry and recall needs (see apps/api/src/app/services/embeddings.py).
#
# Built on the SAME alpine image the stack has always run, rather than
# switching to `pgvector/pgvector:pg18`, which is Debian. The data directory
# an existing install already has was initialised against musl's collation;
# glibc sorts text differently, and an index built under one and read under
# the other is silently wrong rather than loudly broken. Compiling one
# extension is cheaper than asking every self-hoster to dump and restore.
FROM postgres:18-alpine

ARG PGVECTOR_VERSION=v0.8.7

# Build dependencies in a virtual package and removed in the same layer, so
# the image grows by the extension and nothing else. `clang`/`llvm` are what
# PGXS asks for when the server was built with JIT, as the official image is —
# and **the version is whatever that build used**, not whatever is newest:
# `pg_config --configure` names it (`CLANG=clang-21`). When the base image
# moves to a new Alpine and this fails with "no such package", that is the
# command that says what to change it to.
#
# `OPTFLAGS=""` drops pgvector's default `-march=native`, which would tune the
# binary to whichever CPU happened to build it and crash with an illegal
# instruction on a server that has a different one.
RUN apk add --no-cache --virtual .pgvector-build git build-base clang21 llvm21 \
 && git clone --depth 1 --branch "$PGVECTOR_VERSION" https://github.com/pgvector/pgvector.git /tmp/pgvector \
 && make -C /tmp/pgvector OPTFLAGS="" \
 && make -C /tmp/pgvector install \
 && rm -rf /tmp/pgvector \
 && apk del .pgvector-build
