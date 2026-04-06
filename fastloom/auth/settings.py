from fastapi.openapi.models import OAuthFlow, OAuthFlows
from pydantic import (
    BaseModel,
    Field,
    HttpUrl,
    computed_field,
)

from fastloom.types import Str


class OAuth2MergedScheme(OAuthFlow):
    authorizationUrl: Str[HttpUrl] | None = None
    tokenUrl: Str[HttpUrl] | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def flows(self) -> OAuthFlows:
        if self.authorizationUrl is None and self.tokenUrl is None:
            return OAuthFlows()
        return OAuthFlows.model_validate(
            dict(
                authorizationCode=self.model_dump(
                    exclude_computed_fields=True
                ),
            )
        )
        # ^ implicit & ROPC are deprecated in OAUTH2.1

    @computed_field  # type: ignore[prop-decorator]
    @property
    def oauth2_enabled(self) -> bool:
        return self.authorizationUrl is not None and self.tokenUrl is not None


class OIDCCScheme(BaseModel):
    OIDC_URL: Str[HttpUrl] | None = None

    @computed_field  # type: ignore[misc]
    @property
    def oidc_enabled(self) -> bool:
        return self.OIDC_URL is not None


class IntrospectionResponse(BaseModel):
    active: bool


class IAMSettings(OAuth2MergedScheme, OIDCCScheme):
    INTROSPECT: bool = False
    ACL: bool = False
    IAM_SIDECAR_URL: Str[HttpUrl] | None = Field(None, validate_default=True)
