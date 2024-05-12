CI_REGISTRY_IMAGE=$1

export SYSTEM_VERSION=$(cat docker/system.Dockerfile | md5sum | cut -d' ' -f1)
export SYSTEM_IMAGE=$CI_REGISTRY_IMAGE/system

docker build -f docker/system.Dockerfile -t $SYSTEM_IMAGE:$SYSTEM_VERSION . && \
docker push $SYSTEM_IMAGE:$SYSTEM_VERSION && \
docker tag $SYSTEM_IMAGE:$SYSTEM_VERSION $SYSTEM_IMAGE:latest && \
docker push $SYSTEM_IMAGE:latest
