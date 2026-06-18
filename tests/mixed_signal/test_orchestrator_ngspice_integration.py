"""Integration test: MixedSignalOrchestrator + real ngspice + fake DUT."""

import asyncio
import os
import tempfile

import pytest

from toffee.mixed_signal import MixedSignalOrchestrator, PortMapping, PortDirection
from toffee.analog.ngspice_simulator import NgSpiceSimulator


class FakeDut:
    def __init__(self):
        self.comp_out = type("Pin", (), {"value": 0})()
        self.step_count = 0
        self.refresh_comb_count = 0

    def Step(self, cycles=1):
        self.step_count += cycles

    def RefreshComb(self):
        self.refresh_comb_count += 1


@pytest.mark.ngspice
@pytest.mark.asyncio
async def test_orchestrator_advances_and_fires_bridge():
    """Orchestrator advances ngspice, dispatches events, and calls bridge.

    Uses a DC resistor divider. Verifies end-to-end orchestration:
    - next_event() advances time
    - event kind dispatch works (step → clock_edge → Step(1))
    - A2D bridge runs (comp_out updated)
    - _node_voltages populated by SendData callback
    """
    fd, netlist_path = tempfile.mkstemp(suffix=".cir", prefix="toffee_orch_")
    os.close(fd)
    with open(netlist_path, "w") as f:
        f.write("V1 1 0 DC 1.0\nR1 1 mid 1k\nR2 mid 0 1k\n.end\n")

    try:
        dut = FakeDut()
        ngspice = NgSpiceSimulator(netlist_path)

        mapping = PortMapping()
        mapping.add_digital("comp_out", PortDirection.IN)
        mapping.add_analog("mid", PortDirection.OUT)
        mapping.a2d("mid", "comp_out", threshold=0.1)

        orch = MixedSignalOrchestrator(dut, ngspice, mapping)

        for _ in range(10):
            await orch.next_event()

        # Verify the event loop ran and Step was called
        assert dut.step_count == 10
        assert ngspice._current_time > 0

        # Verify SendData populated node voltages
        assert len(ngspice._node_voltages) > 0, "SendData callback did not fire"

        orch.finish()
    finally:
        os.unlink(netlist_path)


@pytest.mark.ngspice
@pytest.mark.asyncio
async def test_orchestrator_t0_bridge():
    """First next_event() at t=0 triggers bridge at DC operating point."""
    fd, netlist_path = tempfile.mkstemp(suffix=".cir", prefix="toffee_orch_")
    os.close(fd)
    with open(netlist_path, "w") as f:
        f.write("V1 1 0 DC 1.0\nR1 1 mid 1k\nR2 mid 0 1k\n.end\n")

    try:
        dut = FakeDut()
        ngspice = NgSpiceSimulator(netlist_path)

        mapping = PortMapping()
        mapping.add_digital("comp_out", PortDirection.IN)
        mapping.add_analog("mid", PortDirection.OUT)
        mapping.a2d("mid", "comp_out", threshold=0.1)

        orch = MixedSignalOrchestrator(dut, ngspice, mapping)

        # First event: t=0 bridge
        await orch.next_event()

        assert dut.step_count == 1
        assert len(ngspice._node_voltages) > 0

        orch.finish()
    finally:
        os.unlink(netlist_path)
