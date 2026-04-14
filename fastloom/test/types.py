from collections.abc import Generator

from testcontainers.core.container import DockerContainer

ContainerData = tuple[DockerContainer, str, str]
ContainerDataFixture = Generator[ContainerData]
