# system
FROM python:3.13-slim AS base

ENV TZ=UTC \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=2.1.3

RUN apt-get update && apt-get install -y \
    git jq curl\
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip --retries 10 install --upgrade pip setuptools wheel
RUN pip --retries 10 install poetry

ARG USERNAME=
ARG PASSWORD=

RUN poetry config http-basic.nexus-registry "$USERNAME" "$PASSWORD"

FROM base AS builder-dev

RUN pip install pre-commit
COPY .pre-commit-config.yaml ./
RUN git init .
RUN pre-commit install-hooks
RUN rm -rf .git .pre-commit-config.yaml
