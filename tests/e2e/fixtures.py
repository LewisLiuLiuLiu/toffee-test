"""Shared fixtures for E2E mixed-signal tests."""
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from .conftest import HAS_XYCE, HAS_NGSPICE, SKY130_PDK_ROOT


NETLISTS_DIR = Path(__file__).parent / "netlists"


def netlist_path(name: str) -> Path:
    """Return the absolute path to a netlist in the netlists/ directory."""
    p = NETLISTS_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"Netlist not found: {p}")
    return p


def sky130_model_lib() -> str:
    """Return the path to sky130.lib.spice."""
    if not SKY130_PDK_ROOT:
        raise RuntimeError("SKY130 PDK not found")
    return os.path.join(
        SKY130_PDK_ROOT,
        "libraries/sky130_fd_pr/latest/models/sky130.lib.spice",
    )


def reduced_model_lib() -> str:
    """Return the path to the reduced SKY130 model library (sky130.lib.spice.tt.red).

    Looks in PDK path first, then falls back to tests/e2e/netlists/.
    """
    if SKY130_PDK_ROOT:
        pdk_path = os.path.join(
            SKY130_PDK_ROOT,
            "libraries/sky130_fd_pr/latest/models/sky130.lib.spice.tt.red",
        )
        if os.path.isfile(pdk_path):
            return pdk_path
    raise RuntimeError(
        "Reduced SKY130 model library not found. "
        "Place sky130.lib.spice.tt.red in the PDK at "
        "<PDK_ROOT>/libraries/sky130_fd_pr/latest/models/ "
        "or set the SKY130_PDK environment variable."
    )


def sky130_hvl_cell(cell_name: str) -> str:
    """Return the SPICE path for an HVL standard cell.

    E.g. sky130_hvl_cell("inv_2") returns the path to
    sky130_fd_sc_hvl__inv_2.spice.
    """
    if not SKY130_PDK_ROOT:
        raise RuntimeError("SKY130 PDK not found")
    category = cell_name.rsplit("_", 1)[0]
    return os.path.join(
        SKY130_PDK_ROOT,
        f"libraries/sky130_fd_sc_hvl/latest/cells/{category}",
        f"sky130_fd_sc_hvl__{cell_name}.spice",
    )


@dataclass
class SimContext:
    """Holds the backend name and a factory to create simulator instances."""
    backend: str  # "xyce" or "ngspice"
    create: Callable  # factory(netlist_path: str) -> simulator instance
    pdk_root: str  # SKY130 PDK root or ""


@pytest.fixture(params=["xyce", "ngspice"])
def analog_sim(request, tmp_path) -> SimContext:
    """Parametrized fixture: creates a SimContext for each backend.

    Tests using this fixture automatically run twice (once per backend).
    Backends that are unavailable are skipped.
    """
    backend = request.param
    if backend == "xyce" and not HAS_XYCE:
        pytest.skip("Xyce not available")
    if backend == "ngspice" and not HAS_NGSPICE:
        pytest.skip("ngspice not available")

    def factory(netlist_file: str):
        if backend == "xyce":
            from toffee.analog.xyce_simulator import XyceSimulator
            return XyceSimulator(netlist_file)
        else:
            from toffee.analog.ngspice_simulator import NgSpiceSimulator
            return NgSpiceSimulator(netlist_file)

    return SimContext(
        backend=backend,
        create=factory,
        pdk_root=SKY130_PDK_ROOT or "",
    )
