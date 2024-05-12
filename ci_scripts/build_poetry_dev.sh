CI_REGISTRY_IMAGE=$1

export SYSTEM_VERSION=$(cat docker/system.Dockerfile | md5sum | cut -d' ' -f1)
export POETRY_IMAGE_VERSION=$(cat docker/system.Dockerfile docker/poetry.dev.Dockerfile poetry.lock | md5sum | cut -d' ' -f1)
export POETRY_IMAGE=$CI_REGISTRY_IMAGE/poetry.dev

docker build -f docker/poetry.dev.Dockerfile -t $POETRY_IMAGE:$POETRY_IMAGE_VERSION --build-arg SYSTEM_VERSION=$SYSTEM_VERSION .
docker push $POETRY_IMAGE:$POETRY_IMAGE_VERSION
docker tag $POETRY_IMAGE:$POETRY_IMAGE_VERSION $POETRY_IMAGE:latest
docker push $POETRY_IMAGE:latest
