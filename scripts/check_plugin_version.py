"""Sync plugin.json version to match pyproject.toml [project] version.

pyproject.toml is the source of truth. When the two diverge, this script
rewrites plugin.json to match and exits non-zero so the pre-commit run
fails — re-stage the file and commit again (same shape as poetry-lock).
"""

import json
import sys
import tomllib
from pathlib import Path

PYPROJECT = Path("pyproject.toml")
PLUGIN = Path("plugins/fastloom-sdk/.claude-plugin/plugin.json")


def main() -> int:
    py_version = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    plugin_data = json.loads(PLUGIN.read_text())
    plugin_version = plugin_data["version"]

    if py_version == plugin_version:
        return 0

    plugin_data["version"] = py_version
    PLUGIN.write_text(json.dumps(plugin_data, indent=4) + "\n")
    print(f"Fixing {PLUGIN}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
