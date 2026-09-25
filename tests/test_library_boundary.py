"""Keep the boldsmartlock package independent, so it can become a library."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

LIBRARY = Path(__file__).parent.parent / "custom_components" / "bold" / "boldsmartlock"


def _imports(path: Path) -> list[tuple[int, str, int]]:
    """Return (line, module, relative level) of every import, even in functions."""
    imports: list[tuple[int, str, int]] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append((node.lineno, node.module or "", node.level))
    return imports


@pytest.mark.parametrize("path", sorted(LIBRARY.glob("*.py")), ids=lambda p: p.name)
def test_library_is_independent(path: Path) -> None:
    """Test the library doesn't use Home Assistant or the integration."""
    for line, module, level in _imports(path):
        assert not module.startswith(("homeassistant", "custom_components")), (
            f"{path.name}:{line} imports {module}"
        )
        assert level <= 1, f"{path.name}:{line} imports from outside the library"
