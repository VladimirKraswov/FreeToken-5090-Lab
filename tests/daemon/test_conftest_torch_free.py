"""The root conftest's autouse quant-backend reset must not force torch onto the daemon
suite: tests/conftest.py used to import freetoken.layers.quantization unconditionally on
every test's teardown, which transitively imports torch and broke every test in this
directory on a torch-less box, defeating tests/daemon/test_daemon_import_safety.py's promise."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CONFTEST_PATH = Path(__file__).resolve().parents[1] / "conftest.py"


def _load_root_conftest():
    spec = importlib.util.spec_from_file_location("_root_conftest_under_test", _CONFTEST_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reset_is_skipped_when_quantization_was_never_imported():
    conftest = _load_root_conftest()
    sys.modules.pop("freetoken.layers.quantization", None)

    conftest._maybe_reset_quant_backend()

    assert "freetoken.layers.quantization" not in sys.modules
