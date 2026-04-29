"""Layer 2: TT05 3-bit DAC + Ring Oscillator mixed-signal test.

Requires: SKY130 PDK, Xyce or ngspice.
Circuit: tt_um_tt05_analog_test from toffee_ana/tt05-analog-test
  - 3-bit R-2R DAC with transmission-gate output on ua[1]
  - Ring oscillator on ua[0] (not tested here)
  - ui_in[0:2] = DAC code, ui_in[3] = DAC TG enable
"""
import os
import tempfile

import pytest
import toffee_test

from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection
from toffee.mixed_signal.step_strategy import StepExactStrategy

from .fixtures import analog_sim, sky130_model_lib, netlist_path  # noqa: F401
from .conftest import HAS_SKY130


class DacDut:
    """Fake digital DUT for TT05 DAC."""

    def __init__(self):
        self.ui_in_0 = 0  # DAC bit 0
        self.ui_in_1 = 0  # DAC bit 1
        self.ui_in_2 = 0  # DAC bit 2
        self.ui_in_3 = 1  # Enable TG for DAC
        self.ui_in_4 = 0
        self.ui_in_5 = 0  # Enable TG for ringo (off)
        self.ui_in_6 = 0  # Enable ringo (off)
        self.ui_in_7 = 0  # Bypass (off)
        self.ena = 1
        self.clk = 0
        self.rst_n = 1


def _generate_tt05_testbench(backend: str) -> str:
    """Generate TT05 testbench netlist.

    The TT05 subcircuit uses sky130_fd_pr__nfet_01v8, pfet_01v8, and
    res_xhigh_po_0p35 -- all covered by sky130.lib.spice tt corner.
    """
    tt05_netlist = str(netlist_path("tt_um_tt05_analog_test.spice"))
    model_lib = sky130_model_lib()

    lines = []
    lines.append("* TT05 DAC E2E testbench")
    lines.append(f'.lib "{model_lib}" tt')
    lines.append(f'.include "{tt05_netlist}"')
    lines.append("")
    lines.append("VPWR vpwr 0 DC 1.8")
    lines.append("VGND vgnd 0 DC 0")

    # Digital inputs as controllable voltage sources (D2A mapped)
    if backend == "xyce":
        for i in range(8):
            lines.append(f"ydac V_UI{i} ui_in_{i} 0")
        lines.append("ydac V_ENA ena 0")
        lines.append("ydac V_CLK clk 0")
        lines.append("ydac V_RSTN rst_n 0")
    else:
        for i in range(8):
            lines.append(f"V_UI{i} ui_in_{i} 0 DC 0 external")
        lines.append("V_ENA ena 0 DC 1.8 external")
        lines.append("V_CLK clk 0 DC 0 external")
        lines.append("V_RSTN rst_n 0 DC 1.8 external")

    # Load caps on analog outputs
    lines.append("C_UA0 ua_0 0 10f")
    lines.append("C_UA1 ua_1 0 10f")

    # Unused analog pins tied via high-impedance resistors
    for i in range(2, 8):
        lines.append(f"R_UA{i} ua_{i} 0 1G")

    # uo_out pins: load resistors (digital outputs, not read)
    for i in range(8):
        lines.append(f"R_UO{i} uo_out_{i} 0 1G")

    # uio_in: tied low (static DC sources)
    for i in range(8):
        lines.append(f"V_UIO{i} uio_in_{i} 0 DC 0")

    # uio_out and uio_oe: load resistors
    for i in range(8):
        lines.append(f"R_UIOO{i} uio_out_{i} 0 1G")
    for i in range(8):
        lines.append(f"R_UIOE{i} uio_oe_{i} 0 1G")

    lines.append("")

    # TT05 instance -- pin order matches .subckt definition:
    # VPWR VGND ua[0] ena clk rst_n ua[1..7]
    # uo_out[0..7] ui_in[0..7] uio_in[0..7] uio_out[0..7] uio_oe[0..7]
    lines.append("X1 vpwr vgnd ua_0 ena clk rst_n ua_1 ua_2 ua_3 ua_4 ua_5 ua_6 ua_7")
    lines.append("+   uo_out_0 uo_out_1 uo_out_2 uo_out_3 uo_out_4 uo_out_5 uo_out_6 uo_out_7")
    lines.append("+   ui_in_0 ui_in_1 ui_in_2 ui_in_3 ui_in_4 ui_in_5 ui_in_6 ui_in_7")
    lines.append("+   uio_in_0 uio_in_1 uio_in_2 uio_in_3 uio_in_4 uio_in_5 uio_in_6 uio_in_7")
    lines.append("+   uio_out_0 uio_out_1 uio_out_2 uio_out_3 uio_out_4 uio_out_5 uio_out_6 uio_out_7")
    lines.append("+   uio_oe_0 uio_oe_1 uio_oe_2 uio_oe_3 uio_oe_4 uio_oe_5 uio_oe_6 uio_oe_7")
    lines.append("+   tt_um_tt05_analog_test")

    if backend == "xyce":
        lines.append(".tran 1n 100n")
        lines.append(".print tran V(ua_1)")

    lines.append(".end")

    path = os.path.join(tempfile.mkdtemp(prefix="toffee_tt05_"), "tt05_tb.cir")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def _build_dac_mapping() -> PortMapping:
    """Build PortMapping for the TT05 DAC test."""
    m = PortMapping()

    # D2A: 8 ui_in bits
    for i in range(8):
        d_name = f"ui_in_{i}"
        a_name = f"V_UI{i}"
        m.add_digital(d_name, PortDirection.OUT)
        m.add_analog(a_name, PortDirection.IN)
        m.d2a(d_name, a_name, scale=1.8)

    # D2A: ena, rst_n (static high via DUT defaults)
    for d_name, a_name in [("ena", "V_ENA"), ("rst_n", "V_RSTN")]:
        m.add_digital(d_name, PortDirection.OUT)
        m.add_analog(a_name, PortDirection.IN)
        m.d2a(d_name, a_name, scale=1.8)

    return m


@pytest.mark.e2e
@pytest.mark.sky130
@pytest.mark.xfail(
    reason="SKY130 model library parameter resolution may fail in both Xyce "
           "(unresolved .param cascades) and ngspice (complex .lib parsing). "
           "Requires PDK integration debugging.",
    strict=False,
)
@toffee_test.testcase
async def test_dac_3bit_monotonic(analog_sim):
    """3-bit DAC should produce monotonically increasing output voltages.

    Sweep codes 0..7 on ui_in[2:0] with DAC TG enabled (ui_in[3]=1).
    Read V(ua_1) after each code settles. Voltages must be monotonic.
    """
    if not HAS_SKY130:
        pytest.skip("SKY130 PDK not found")

    netlist = _generate_tt05_testbench(analog_sim.backend)
    sim = analog_sim.create(netlist)
    try:
        dut = DacDut()
        mapping = _build_dac_mapping()

        ms = MixedSignalSimulator(
            sim, dut, mapping, step_strategy=StepExactStrategy(max_step=5e-9)
        )

        voltages = []
        for code in range(8):
            dut.ui_in_0 = code & 1
            dut.ui_in_1 = (code >> 1) & 1
            dut.ui_in_2 = (code >> 2) & 1
            ms.advance_to((code + 1) * 10e-9)
            v = ms.read("V(ua_1)")
            voltages.append(v)

        # Check monotonicity (allow small tolerance for transient settling)
        for i in range(1, len(voltages)):
            assert voltages[i] >= voltages[i - 1] - 0.01, (
                f"DAC not monotonic: code {i} ({voltages[i]:.3f}V) "
                f"< code {i-1} ({voltages[i-1]:.3f}V)"
            )
    finally:
        sim.finish()
