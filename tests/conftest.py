import sys

import pytest


def _maybe_reset_quant_backend() -> None:
    """Reset the quant backend, but only if a test actually loaded it.

    Importing it unconditionally would pull in torch for every test in the suite,
    breaking the daemon's torch-free guarantee (tests/daemon/test_daemon_import_safety.py)
    for tests that never touch quantization at all.
    """
    if "freetoken.layers.quantization" not in sys.modules:
        return
    from freetoken.layers.quantization import QuantBackend, set_quant_backend

    set_quant_backend(QuantBackend())


@pytest.fixture(autouse=True)
def _default_quant_backend():
    """Tests that install kernel requests must not leak them into the next test."""
    yield
    _maybe_reset_quant_backend()
