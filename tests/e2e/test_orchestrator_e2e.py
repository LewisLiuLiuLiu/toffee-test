"""E2E tests for MixedSignalOrchestrator with both ngspice and Xyce backends.

These tests verify the event-driven orchestrator (start_clock + clock_event.wait)
instead of the polling MixedSignalSimulator.advance_to() approach.
"""
import os
import shutil
import tempfile

import pytest
import toffee_test

from toffee.analog.ngspice_simulator import NgSpiceSimulator
from toffee.asynchronous import start_clock
from toffee.mixed_signal.mixed_signal_orchestrator import MixedSignalOrchestrator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection

from .conftest import HAS_NGSPICE, HAS_XYCE


# ---------------------------------------------------------------------------
# Helper: minimal DUT with Pin objects for A2D targets
# ---------------------------------------------------------------------------


class Pin:
    """Lightweight pin that the orchestrator can read/write via .value."""

    def __init__(self, value=0):
        self.value = value


class FakeRcDut:
    """Fake DUT for the RC bidirectional test.

    Attributes
    ----------
    vin_ctrl : int
        Digital output pin (D2A source). Set as plain int; the orchestrator
        reads it via ``pin.value if hasattr(pin, 'value') else pin``.
    charge_done : Pin
        Digital input pin (A2D target). The orchestrator writes
        ``charge_done.value = <0 or 1>``.
    """

    def __init__(self):
        self.vin_ctrl = 0
        self.charge_done = Pin(0)
        self.step_count = 0

    def Step(self, n):
        self.step_count += n

    def RefreshComb(self):
        pass


class FakeOpampDut:
    """Fake DUT for the opamp comparator test.

    Attributes
    ----------
    vinn_ctrl : int
        Digital output pin (D2A source). Set as plain int.
    comp_out : Pin
        Digital input pin (A2D target). The orchestrator writes
        ``comp_out.value = <0 or 1>``.
    """

    def __init__(self):
        self.vinn_ctrl = 0
        self.comp_out = Pin(0)
        self.step_count = 0

    def Step(self, n):
        self.step_count += n

    def RefreshComb(self):
        pass


# ---------------------------------------------------------------------------
# Netlist helpers
# ---------------------------------------------------------------------------

RC_NGSPICE = """\
* RC bidirectional orchestrator test (ngspice)
V_IN in 0 DC 0 external
R1 in out 1k
C1 out 0 1p
.end
"""

RC_XYCE = """\
* RC bidirectional orchestrator test (Xyce)
V_IN in 0 DC 0
R1 in out 1k
C1 out 0 1p
.tran 1n 500n
.print tran V(out)
.end
"""

OPAMP_NETLIST = os.path.join(
    os.path.dirname(__file__), "netlists", "opamp_2stage_180nm_comparator.sp"
)


def _write_netlist(backend: str, content_xyce: str, content_ngspice: str) -> str:
    """Write backend-appropriate netlist to a temp file and return its path."""
    path = os.path.join(tempfile.mkdtemp(prefix="toffee_e2e_"), "circuit.cir")
    content = content_xyce if backend == "xyce" else content_ngspice
    with open(path, "w") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# Parametrized fixture
# ---------------------------------------------------------------------------


@pytest.fixture(params=["ngspice", "xyce"])
def orch_backend(request):
    """Parametrized fixture: provides backend name for orchestrator E2E tests.

    Backends that are unavailable are automatically skipped.
    """
    backend = request.param
    if backend == "xyce" and not HAS_XYCE:
        pytest.skip("Xyce not available")
    if backend == "ngspice" and not HAS_NGSPICE:
        pytest.skip("libngspice not available")
    return backend


# ---------------------------------------------------------------------------
# Test 1: RC bidirectional orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@toffee_test.testcase
async def test_rc_bidirectional_orchestrator(orch_backend):
    """Closed-loop RC circuit driven by MixedSignalOrchestrator + start_clock.

    Runs on both ngspice and Xyce backends. For Xyce, port_mapping is passed
    to XyceSimulator so YDAC/YADC devices are auto-injected into the netlist.

    Flow:
      1. Write inline RC netlist to a temp file.
      2. Create simulator (NgSpiceSimulator or XyceSimulator with port_mapping).
      3. Build PortMapping (D2A + A2D; Xyce adds yadc_device for A2D).
      4. Create MixedSignalOrchestrator, start_clock.
      5. Drive vin_ctrl=1 and wait for charge_done==1 via clock_event.wait().
    """
    netlist_dir = tempfile.mkdtemp(prefix="toffee_e2e_orch_")
    netlist_path = os.path.join(netlist_dir, "circuit.cir")
    orch = None
    try:
        content = RC_XYCE if orch_backend == "xyce" else RC_NGSPICE
        with open(netlist_path, "w") as f:
            f.write(content)

        # Build PortMapping -- Xyce uses yadc_device for A2D threshold detection
        mapping = PortMapping()
        mapping.add_digital("vin_ctrl", PortDirection.OUT)
        mapping.add_analog("V_IN", PortDirection.IN)
        mapping.d2a("vin_ctrl", "V_IN", scale=1.8)
        mapping.add_digital("charge_done", PortDirection.IN)
        mapping.add_analog("V(out)", PortDirection.OUT)
        if orch_backend == "xyce":
            mapping.a2d("V(out)", "charge_done", threshold=0.9,
                        yadc_device="charge_done_adc")
        else:
            mapping.a2d("V(out)", "charge_done", threshold=0.9)

        # Create simulator
        if orch_backend == "ngspice":
            sim = NgSpiceSimulator(netlist_path)
        else:
            from toffee.analog.xyce_simulator import XyceSimulator
            sim = XyceSimulator(netlist_path, port_mapping=mapping)

        dut = FakeRcDut()
        orch = MixedSignalOrchestrator(dut, sim, mapping)
        start_clock(orch)

        dut.vin_ctrl = 1

        for _ in range(100):
            await orch.clock_event.wait()
            if dut.charge_done.value == 1:
                break

        assert dut.charge_done.value == 1, (
            "Expected charge_done=1 (RC voltage crossed 0.9V threshold)"
        )
    finally:
        if orch is not None:
            orch.finish()
        shutil.rmtree(netlist_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 2: Opamp comparator orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@toffee_test.testcase
async def test_opamp_comparator_orchestrator(orch_backend):
    """Opamp comparator driven by MixedSignalOrchestrator + start_clock.

    Runs on both ngspice and Xyce backends. For Xyce, port_mapping is passed
    to XyceSimulator so YDAC/YADC devices are auto-injected into the netlist.

    Flow:
      1. Load opamp_2stage_180nm_comparator.sp netlist.
      2. Create simulator (NgSpiceSimulator or XyceSimulator with port_mapping).
      3. Build PortMapping (D2A + A2D; Xyce adds yadc_device for A2D).
      4. Create MixedSignalOrchestrator, start_clock.
      5. Drive vinn_ctrl=1 (VINN -> 1.8V) and wait for comp_out==0.
    """
    # Build PortMapping -- Xyce uses yadc_device for A2D threshold detection
    mapping = PortMapping()
    mapping.add_digital("vinn_ctrl", PortDirection.OUT)
    mapping.add_analog("V_INN", PortDirection.IN)
    mapping.d2a("vinn_ctrl", "V_INN", scale=1.8)
    mapping.add_digital("comp_out", PortDirection.IN)
    mapping.add_analog("V(vout)", PortDirection.OUT)
    if orch_backend == "xyce":
        mapping.a2d("V(vout)", "comp_out", threshold=0.9,
                    yadc_device="comp_out_adc")
    else:
        mapping.a2d("V(vout)", "comp_out", threshold=0.9)

    # Create simulator
    if orch_backend == "ngspice":
        sim = NgSpiceSimulator(OPAMP_NETLIST)
    else:
        from toffee.analog.xyce_simulator import XyceSimulator
        sim = XyceSimulator(
            OPAMP_NETLIST,
            port_mapping=mapping,
            analysis_cmds=[".tran 1n 500n", ".print tran V(vout)"],
        )

    orch = None
    try:
        dut = FakeOpampDut()
        orch = MixedSignalOrchestrator(dut, sim, mapping)
        start_clock(orch)

        dut.vinn_ctrl = 1

        for _ in range(200):
            await orch.clock_event.wait()
            if dut.comp_out.value == 0:
                break

        assert dut.comp_out.value == 0, (
            "Expected comp_out=0 (comparator output flipped low)"
        )
    finally:
        if orch is not None:
            orch.finish()
