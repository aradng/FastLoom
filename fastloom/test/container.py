import os
from collections.abc import Generator
from contextlib import contextmanager

from testcontainers.core.auth import DockerAuthInfo
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import WaitStrategy


class PrivateRegistryDocker(DockerContainer):
    def _configure(self) -> None:
        self._docker.login(
            auth_config=DockerAuthInfo(
                os.getenv("REGISTRY_ADDRESS"),
                os.getenv("REGISTRY_USERNAME"),
                os.getenv("REGISTRY_PASSWORD"),
            )
        )


@contextmanager
def create_container(
    image: str,
    port: int,
    env_vars: dict[str, str] | None = None,
    commands: str | None = None,
    volumes: dict[str, str] | None = None,
    wait_strategy: WaitStrategy | None = None,
) -> Generator[tuple[PrivateRegistryDocker, str]]:
    """
    Example:
        >>> with create_container(
        ...     image="redis:alpine",
        ...     port=6379,
        ...     env_vars={'MAXMEMORY': '256mb'},
        ...     volumes={'/data/redis': '/data'}
        ... ) as (container, port):
        ...     print(f"Redis running on port {port}")
    """
    env_vars = env_vars or {}
    volumes = volumes or {}
    container = PrivateRegistryDocker(image, _wait_strategy=wait_strategy)
    for key, value in env_vars.items():
        container.with_env(key, value)
    for host_path, container_path in volumes.items():
        container.with_volume_mapping(host_path, container_path)
    if port:
        container.with_exposed_ports(port)
    if commands:
        container.with_command(commands)
    container.start()
    try:
        port_str = str(container.get_exposed_port(port))
        yield container, port_str
    finally:
        container.stop()
