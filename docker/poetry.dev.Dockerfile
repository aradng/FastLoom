ARG SYSTEM_VERSION=latest

FROM git.netall.live:5050/microservice/core-bluprint/system:$SYSTEM_VERSION

COPY pyproject.toml poetry.lock ./

RUN poetry install --no-root --only=dev
