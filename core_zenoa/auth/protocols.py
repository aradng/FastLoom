from pathlib import Path
from typing import Protocol

from pydantic import HttpUrl


class OAuth2Settings(Protocol):
    IAM_TOKEN_URL: Path


class SidecarSettings(OAuth2Settings, Protocol):
    IAM_SIDECAR_URL: HttpUrl
