from pathlib import Path


def format_path(path: Path, **kwargs: int | str) -> Path:
    return Path(str(path).format(**kwargs))
