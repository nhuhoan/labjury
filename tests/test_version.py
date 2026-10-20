import tomllib
from pathlib import Path

import labjury


def test_version_matches_pyproject():
    root = Path(__file__).resolve().parent.parent
    data = tomllib.loads((root / "pyproject.toml").read_text())
    assert labjury.__version__ == data["project"]["version"]
