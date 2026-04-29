"""E2E mixed-signal test configuration: marker registration + environment detection."""
import os
import shutil

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end mixed-signal test")
    config.addinivalue_line("markers", "sky130: requires SKY130 PDK")
    config.addinivalue_line("markers", "xyce: requires Xyce simulator")
    config.addinivalue_line("markers", "ngspice: requires ngspice + libngspice")
    config.addinivalue_line("markers", "picker: requires picker-generated DUT")


HAS_XYCE = shutil.which("xyce") is not None


def _can_load_libngspice() -> bool:
    try:
        from ctypes import cdll
        cdll.LoadLibrary("libngspice.so")
        return True
    except OSError:
        return False


HAS_NGSPICE = _can_load_libngspice()


_SKY130_CANDIDATES = [
    os.environ.get("SKY130_PDK", ""),
    "/mnt/d/ongoingProjects/layoutProjects/skywater-pdk",
]


def _find_sky130_pdk():
    for candidate in _SKY130_CANDIDATES:
        if candidate and os.path.isfile(
            os.path.join(
                candidate,
                "libraries/sky130_fd_pr/latest/models/sky130.lib.spice",
            )
        ):
            return candidate
    return None


SKY130_PDK_ROOT = _find_sky130_pdk()
HAS_SKY130 = SKY130_PDK_ROOT is not None

HAS_PICKER = shutil.which("picker") is not None


def pytest_collection_modifyitems(items):
    for item in items:
        if "sky130" in item.keywords and not HAS_SKY130:
            item.add_marker(pytest.mark.skip(reason="SKY130 PDK not found"))
        if "xyce" in item.keywords and not HAS_XYCE:
            item.add_marker(pytest.mark.skip(reason="Xyce not available"))
        if "ngspice" in item.keywords and not HAS_NGSPICE:
            item.add_marker(pytest.mark.skip(reason="libngspice not available"))
        if "picker" in item.keywords and not HAS_PICKER:
            item.add_marker(pytest.mark.skip(reason="picker not available"))
