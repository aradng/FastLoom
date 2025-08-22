from pathlib import Path
from typing import Protocol

from pydantic import AnyHttpUrl


class OAuth2Settings(Protocol):
    IAM_TOKEN_URL: AnyHttpUrl | Path


class SidecarSettings(OAuth2Settings, Protocol):
    IAM_SIDECAR_URL: AnyHttpUrl
