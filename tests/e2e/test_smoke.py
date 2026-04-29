"""Layer 0: Smoke tests using simple circuits with inline models.

No PDK required. Tests D2A voltage, D2A param, A2D threshold, and
bidirectional closed-loop bridges. Each test runs on both Xyce and ngspice.
"""
import os
import tempfile

import pytest
import toffee_test

from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection
from toffee.mixed_signal.step_strategy import StepExactStrategy

from .fixtures import analog_sim  # noqa: F401 -- pytest fixture


def _write_netlist(backend: str, content_xyce: str, content_ngspice: str) -> str:
    """Write backend-appropriate netlist to a temp file and return its path."""
    path = os.path.join(tempfile.mkdtemp(prefix="toffee_e2e_"), "circuit.cir")
    content = content_xyce if backend == "xyce" else content_ngspice
    with open(path, "w") as f:
        f.write(content)
    return path


# ---- RC D2A voltage bridge ----

RC_XYCE = """\
* RC smoke test (Xyce)
* YDAC provides a voltage source controllable via updateTimeVoltagePairs
ydac V_IN in 0
R1 in out 1k
C1 out 0 1p
.tran 0.1n 10n
.print tran V(out)
.end
"""

RC_NGSPICE = """\
* RC smoke test (ngspice)
V_IN in 0 DC 0 external
R1 in out 1k
C1 out 0 1p
.end
"""


class RcDut:
    def __init__(self):
        self.vin_ctrl = 0


@pytest.mark.e2e
@toffee_test.testcase
async def test_rc_d2a_voltage(analog_sim):
    """D2A voltage bridge: digital 1 -> 1.8V drives RC, output charges."""
    netlist = _write_netlist(analog_sim.backend, RC_XYCE, RC_NGSPICE)
    sim = analog_sim.create(netlist)
    try:
        dut = RcDut()
        dut.vin_ctrl = 1

        mapping = PortMapping()
        mapping.add_digital("vin_ctrl", PortDirection.OUT)
        mapping.add_analog("V_IN", PortDirection.IN)
        mapping.d2a("vin_ctrl", "V_IN", scale=1.8)

        ms = MixedSignalSimulator(
            sim, dut, mapping, step_strategy=StepExactStrategy(max_step=1e-9)
        )
        ms.advance_to(5e-9)  # 5 * RC = 5 * 1k * 1p = 5ns
        vout = ms.read("V(out)")
        assert vout > 1.0, f"Expected V(out) > 1.0V after 5ns, got {vout:.4f}"
    finally:
        sim.finish()


# ---- RC bidirectional closed-loop ----

class RcBidirDut:
    def __init__(self):
        self.vin_ctrl = 0
        self.charge_done = 0


RC_BIDIR_XYCE = """\
* RC bidirectional (Xyce)
ydac V_IN in 0
R1 in out 1k
C1 out 0 1p
.tran 0.1n 10n
.print tran V(out)
.end
"""

RC_BIDIR_NGSPICE = """\
* RC bidirectional (ngspice)
V_IN in 0 DC 0 external
R1 in out 1k
C1 out 0 1p
.end
"""


@pytest.mark.e2e
@toffee_test.testcase
async def test_rc_bidirectional(analog_sim):
    """Closed loop: D2A drives voltage, A2D reads charge status."""
    netlist = _write_netlist(analog_sim.backend, RC_BIDIR_XYCE, RC_BIDIR_NGSPICE)
    sim = analog_sim.create(netlist)
    try:
        dut = RcBidirDut()
        dut.vin_ctrl = 1

        mapping = PortMapping()
        mapping.add_digital("vin_ctrl", PortDirection.OUT)
        mapping.add_analog("V_IN", PortDirection.IN)
        mapping.d2a("vin_ctrl", "V_IN", scale=1.8)
        mapping.add_digital("charge_done", PortDirection.IN)
        mapping.add_analog("V(out)", PortDirection.OUT)
        mapping.a2d("V(out)", "charge_done", threshold=0.9)

        ms = MixedSignalSimulator(
            sim, dut, mapping, step_strategy=StepExactStrategy(max_step=1e-9)
        )

        # At t=0 capacitor is uncharged
        assert dut.charge_done == 0

        # Advance past RC time constant
        ms.advance_to(5e-9)
        assert dut.charge_done == 1, "Expected charge_done=1 after 5ns"
    finally:
        sim.finish()


# ---- D2A param gain select (Xyce only) ----
# ngspice alterparam does not take effect during lazy-sync transient,
# so this test is restricted to the Xyce backend.

class GainDut:
    def __init__(self):
        self.gain_sel = 0


GAIN_XYCE = """\
* Opamp gain select (Xyce) -- voltage divider with variable R2
V1 in 0 DC 1.0
R1 in out 1k
R2 out 0 1k
.tran 0.1n 2n
.print tran V(out)
.end
"""


@pytest.fixture(params=["xyce"])
def xyce_sim(request, tmp_path):
    """Xyce-only fixture for tests that use setCircuitParameter."""
    from .conftest import HAS_XYCE
    if not HAS_XYCE:
        pytest.skip("Xyce not available")

    def factory(netlist_file: str):
        from toffee.analog.xyce_simulator import XyceSimulator
        return XyceSimulator(netlist_file)

    from .fixtures import SimContext
    from .conftest import SKY130_PDK_ROOT
    return SimContext(backend="xyce", create=factory, pdk_root=SKY130_PDK_ROOT or "")


@pytest.mark.e2e
@pytest.mark.xfail(
    reason="Xyce setCircuitParameter for linear device params (R:R) updates the "
           "stored value but does not restamp the conductance matrix during transient. "
           "This is a Xyce engine limitation, not a toffee bug.",
    strict=False,
)
@toffee_test.testcase
async def test_d2a_param_gain_select(xyce_sim):
    """D2A param bridge: digital code selects resistor value, changing output."""
    netlist = _write_netlist(xyce_sim.backend, GAIN_XYCE, GAIN_XYCE)
    sim = xyce_sim.create(netlist)
    try:
        dut = GainDut()

        mapping = PortMapping()
        mapping.add_digital("gain_sel", PortDirection.OUT)
        mapping.add_analog("R2:R", PortDirection.IN)
        # code 0 -> R2=1k (Vout=0.5V), code 1 -> R2=10k (Vout~0.91V)
        mapping.d2a_param("gain_sel", "R2:R", mapping={0: 1e3, 1: 10e3})

        ms = MixedSignalSimulator(
            sim, dut, mapping, step_strategy=StepExactStrategy(max_step=0.5e-9)
        )

        # Code 0: R2=1k, divider = 1k/(1k+1k) = 0.5
        dut.gain_sel = 0
        ms.advance_to(1e-9)
        v0 = ms.read("V(out)")

        # Code 1: R2=10k, divider = 10k/(1k+10k) ~ 0.91
        dut.gain_sel = 1
        ms.advance_to(2e-9)
        v1 = ms.read("V(out)")

        assert v1 > v0, f"Expected v1 ({v1:.3f}) > v0 ({v0:.3f}) after gain change"
    finally:
        sim.finish()
