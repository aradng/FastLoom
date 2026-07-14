from fastloom.settings.base import ProjectSettings


class MCPSettings(ProjectSettings):
    MCP_ENABLED: bool = False
    MCP_OPENAPI: bool = False
    MCP_SESSION_STORE_ENABLED: bool = True
