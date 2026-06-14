from __future__ import annotations

from openfin.cli import app


def test_main_module_import_exposes_cli_app() -> None:
    import openfin.__main__ as main

    assert main.app is app
