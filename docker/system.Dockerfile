FROM git.netall.live:5050/microservice/iam/python:3.12-slim

ENV TZ=UTC \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=1.8.2

RUN apt-get update -o Acquire::Check-Valid-Until=false \
    && apt-get install -y \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip --retries 10 install --upgrade pip setuptools wheel
RUN pip --retries 10 install poetry
