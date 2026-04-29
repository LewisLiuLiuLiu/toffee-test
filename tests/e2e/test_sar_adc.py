"""Layer 1: SAR ADC full mixed-signal test with SKY130 transistor-level analog.

Requires: SKY130 PDK, Xyce or ngspice. Marked with @sky130 for auto-skip.
"""
import os
import tempfile

import pytest
import toffee_test

from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection
from toffee.mixed_signal.step_strategy import StepExactStrategy

from .fixtures import analog_sim, sky130_model_lib, sky130_hvl_cell, netlist_path  # noqa: F401
from .conftest import HAS_SKY130
from .sar_ctrl_dut import SarCtrlDut


# HVL standard cells needed by the ADC netlist
_HVL_CELLS = [
    "lsbuflv2hv_1", "inv_2", "nor2_1", "diode_2", "decap_4", "decap_8",
]

# Clock period for SAR (100 MHz -> 10ns period -> 5ns half-cycle)
CLK_HALF_PERIOD = 5e-9


def _generate_sar_testbench(backend: str, v_ain: float) -> str:
    """Generate a testbench netlist wrapping the full SKY130 ADC analog."""
    adc_netlist = str(netlist_path("sky130_ef_ip__adc3v_12bit.spice"))
    model_lib = sky130_model_lib()

    lines = []
    lines.append("* SAR ADC E2E testbench (auto-generated)")

    # Model library
    lines.append(f'.lib "{model_lib}" tt')

    # HVL standard cell includes
    for cell in _HVL_CELLS:
        lines.append(f'.include "{sky130_hvl_cell(cell)}"')

    # ADC subcircuit
    lines.append(f'.include "{adc_netlist}"')
    lines.append("")

    # Power and references
    lines.append("VDDA vdda 0 DC 3.3")
    lines.append("VCCD vccd 0 DC 1.8")
    lines.append("VSSA vssa 0 DC 0")
    lines.append("VSSD vssd 0 DC 0")
    lines.append("VREFH vrefh 0 DC 3.3")
    lines.append("VREFL vrefl 0 DC 0")
    lines.append("VCM vcm 0 DC 1.65")
    lines.append("VTRIM trim 0 DC 0")
    lines.append(f"V_AIN adc_in 0 DC {v_ain}")
    lines.append("")

    # Digital control voltage sources (driven by D2A)
    if backend == "xyce":
        for i in range(12):
            lines.append(f"ydac V_D{i} dac_val{i} 0")
        lines.append("ydac V_ENA adc_ena 0")
        lines.append("ydac V_RST adc_reset 0")
        lines.append("ydac V_HOLD adc_hold 0")
    else:
        for i in range(12):
            lines.append(f"V_D{i} dac_val{i} 0 DC 0 external")
        lines.append("V_ENA adc_ena 0 DC 0 external")
        lines.append("V_RST adc_reset 0 DC 0 external")
        lines.append("V_HOLD adc_hold 0 DC 0 external")
    lines.append("")

    # ADC instance -- pin order from subcircuit:
    # vdda vssa vccd vssd adc_vrefH adc_vrefL adc_in adc_ena
    # adc_dac_val[11:0] adc_comp_out adc_reset adc_vCM adc_trim adc_hold
    lines.append("XADC vdda vssa vccd vssd vrefh vrefl adc_in adc_ena")
    lines.append("+    dac_val11 dac_val10 dac_val9 dac_val8")
    lines.append("+    dac_val7 dac_val6 dac_val5 dac_val4")
    lines.append("+    dac_val3 dac_val2 dac_val1 dac_val0")
    lines.append("+    comp_out adc_reset vcm trim adc_hold")
    lines.append("+    sky130_ef_ip__adc3v_12bit")
    lines.append("")

    if backend == "xyce":
        lines.append(".tran 1n 500n")
        lines.append(".print tran V(comp_out)")
    # ngspice: lazy sync handles transient internally

    lines.append(".end")

    path = os.path.join(tempfile.mkdtemp(prefix="toffee_sar_"), "sar_adc_tb.cir")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


def _build_sar_mapping(size: int = 12) -> PortMapping:
    """Build the PortMapping for SAR ADC digital-analog bridge."""
    m = PortMapping()

    # D2A: 12 data bits
    for i in range(size):
        d_name = f"data_{i}"
        a_name = f"V_D{i}"
        m.add_digital(d_name, PortDirection.OUT)
        m.add_analog(a_name, PortDirection.IN)
        m.d2a(d_name, a_name, scale=1.8)

    # D2A: control signals
    for d_name, a_name in [("ena_out", "V_ENA"), ("dac_rst", "V_RST"), ("sample_n", "V_HOLD")]:
        m.add_digital(d_name, PortDirection.OUT)
        m.add_analog(a_name, PortDirection.IN)
        m.d2a(d_name, a_name, scale=1.8)

    # A2D: comparator output
    m.add_digital("cmp", PortDirection.IN)
    m.add_analog("V(comp_out)", PortDirection.OUT)
    m.a2d("V(comp_out)", "cmp", threshold=0.9)

    return m


class SarDutWrapper:
    """Wraps SarCtrlDut to expose ena_out (renamed from en to avoid conflict)."""

    def __init__(self, size=12):
        self._ctrl = SarCtrlDut(size=size)
        self.ena_out = 0

    def __getattr__(self, name):
        if name.startswith("_") or name == "ena_out":
            raise AttributeError(name)
        return getattr(self._ctrl, name)

    def __setattr__(self, name, value):
        if name in ("_ctrl", "ena_out"):
            super().__setattr__(name, value)
        else:
            setattr(self._ctrl, name, value)

    def start_conversion(self):
        self._ctrl.en = 1
        self.ena_out = 1
        self._ctrl.soc = 1

    def clear_soc(self):
        self._ctrl.soc = 0

    def clock_step(self):
        self._ctrl.clock_step()
        self.ena_out = self._ctrl.en


@pytest.mark.e2e
@pytest.mark.sky130
@pytest.mark.xfail(
    reason="SKY130 full transistor-level model library has parameter resolution issues "
           "with both Xyce (unresolved .param cascades) and ngspice (complex .lib parsing). "
           "Requires PDK integration debugging.",
    strict=False,
)
@toffee_test.testcase
async def test_sar_full_conversion(analog_sim):
    """Full SAR conversion: V_AIN=1.5V, expect data ~ 1862."""
    v_ain = 1.5
    netlist = _generate_sar_testbench(analog_sim.backend, v_ain)
    sim = analog_sim.create(netlist)
    try:
        dut = SarDutWrapper(size=12)
        mapping = _build_sar_mapping(size=12)
        ms = MixedSignalSimulator(
            sim, dut, mapping, step_strategy=StepExactStrategy(max_step=CLK_HALF_PERIOD)
        )

        t = 0.0

        # Startup: enable and start conversion
        dut.start_conversion()
        t += CLK_HALF_PERIOD
        ms.advance_to(t)
        dut.clock_step()

        t += CLK_HALF_PERIOD
        ms.advance_to(t)
        dut.clear_soc()
        dut.clock_step()

        # Run through SAMPLE + RST + START + CONV (12 bits) + DONE
        # Max cycles: 1 (SAMPLE) + swidth+1 (RST) + 1 (START) + 12 (CONV) + 1 (DONE) ~ 20
        for _ in range(30):
            t += CLK_HALF_PERIOD
            ms.advance_to(t)
            dut.clock_step()
            if dut.eoc:
                break

        assert dut.eoc == 1, "Conversion did not complete"
        # Expected: 1.5 / 3.3 * 4096 ~ 1862
        expected = int(v_ain / 3.3 * 4096)
        tolerance = 100  # generous for transistor-level sim
        actual = dut.data
        assert abs(actual - expected) < tolerance, (
            f"ADC result {actual} too far from expected {expected} "
            f"(tolerance={tolerance})"
        )
    finally:
        sim.finish()


@pytest.mark.e2e
@pytest.mark.sky130
@pytest.mark.xfail(
    reason="SKY130 full transistor-level model library has parameter resolution issues "
           "with both Xyce (unresolved .param cascades) and ngspice (complex .lib parsing). "
           "Requires PDK integration debugging.",
    strict=False,
)
@toffee_test.testcase
async def test_sar_midscale(analog_sim):
    """SAR at midscale: V_AIN=1.65V (VCM), expect data ~ 2048."""
    v_ain = 1.65
    netlist = _generate_sar_testbench(analog_sim.backend, v_ain)
    sim = analog_sim.create(netlist)
    try:
        dut = SarDutWrapper(size=12)
        mapping = _build_sar_mapping(size=12)
        ms = MixedSignalSimulator(
            sim, dut, mapping, step_strategy=StepExactStrategy(max_step=CLK_HALF_PERIOD)
        )

        t = 0.0
        dut.start_conversion()
        t += CLK_HALF_PERIOD
        ms.advance_to(t)
        dut.clock_step()
        t += CLK_HALF_PERIOD
        ms.advance_to(t)
        dut.clear_soc()
        dut.clock_step()

        for _ in range(30):
            t += CLK_HALF_PERIOD
            ms.advance_to(t)
            dut.clock_step()
            if dut.eoc:
                break

        assert dut.eoc == 1
        expected = int(v_ain / 3.3 * 4096)
        actual = dut.data
        assert abs(actual - expected) < 100, (
            f"ADC midscale result {actual} too far from expected {expected}"
        )
    finally:
        sim.finish()


# ---- Picker DUT variant (Task 12) ----


class PickerSarWrapper:
    """Adapts picker DUTsar_ctrl (SIZE=8) to plain-attribute interface.

    The MixedSignalSimulator reads/writes DUT attributes by name.
    Picker DUT uses XPin objects; this wrapper bridges them with
    individual bit properties for D2A mapping.
    """

    def __init__(self, picker_dut):
        object.__setattr__(self, '_dut', picker_dut)
        # Initialize digital inputs
        self._dut.rst_n.value = 1
        self._dut.en.value = 0
        self._dut.soc.value = 0
        self._dut.swidth.value = 4
        self._dut.cmp.value = 0

    # -- D2A outputs: individual data bits --
    def _get_data_bit(self, i):
        return (self._dut.data.value >> i) & 1

    @property
    def data_0(self): return self._get_data_bit(0)
    @property
    def data_1(self): return self._get_data_bit(1)
    @property
    def data_2(self): return self._get_data_bit(2)
    @property
    def data_3(self): return self._get_data_bit(3)
    @property
    def data_4(self): return self._get_data_bit(4)
    @property
    def data_5(self): return self._get_data_bit(5)
    @property
    def data_6(self): return self._get_data_bit(6)
    @property
    def data_7(self): return self._get_data_bit(7)

    # -- D2A outputs: control signals --
    @property
    def ena_out(self): return self._dut.en.value
    @property
    def dac_rst(self): return self._dut.dac_rst.value
    @property
    def sample_n(self): return self._dut.sample_n.value

    # -- A2D input --
    @property
    def cmp(self): return self._dut.cmp.value
    @cmp.setter
    def cmp(self, v): self._dut.cmp.value = v

    # -- Read-only status --
    @property
    def eoc(self): return self._dut.eoc.value
    @property
    def data(self): return self._dut.data.value

    def step_clock(self):
        """Advance the picker DUT by one clock edge."""
        self._dut.Step(1)


def _build_picker_sar_mapping(size: int = 8) -> PortMapping:
    """Build PortMapping for picker SAR DUT (SIZE=8, using only 8 DAC bits)."""
    m = PortMapping()

    for i in range(size):
        d_name = f"data_{i}"
        a_name = f"V_D{i}"
        m.add_digital(d_name, PortDirection.OUT)
        m.add_analog(a_name, PortDirection.IN)
        m.d2a(d_name, a_name, scale=1.8)

    for d_name, a_name in [("ena_out", "V_ENA"), ("dac_rst", "V_RST"), ("sample_n", "V_HOLD")]:
        m.add_digital(d_name, PortDirection.OUT)
        m.add_analog(a_name, PortDirection.IN)
        m.d2a(d_name, a_name, scale=1.8)

    m.add_digital("cmp", PortDirection.IN)
    m.add_analog("V(comp_out)", PortDirection.OUT)
    m.a2d("V(comp_out)", "cmp", threshold=0.9)

    return m


@pytest.mark.e2e
@pytest.mark.sky130
@pytest.mark.xfail(
    reason="SKY130 full transistor-level model library has parameter resolution issues "
           "with both Xyce and ngspice. Also, picker DUT uses SIZE=8 (default) while "
           "the analog ADC is 12-bit; only 8 of 12 DAC bits are connected.",
    strict=False,
)
@toffee_test.testcase
async def test_sar_full_conversion_picker(analog_sim):
    """Full SAR conversion using real Verilator DUT (picker-generated, SIZE=8)."""
    try:
        from .picker_out_sar_ctrl import DUTsar_ctrl
    except ImportError:
        pytest.skip("picker_out_sar_ctrl not built")

    if not HAS_SKY130:
        pytest.skip("SKY130 PDK not found")

    v_ain = 1.5
    netlist = _generate_sar_testbench(analog_sim.backend, v_ain)
    sim_analog = analog_sim.create(netlist)
    try:
        picker_dut = DUTsar_ctrl()
        picker_dut.InitClock("clk")
        dut = PickerSarWrapper(picker_dut)
        mapping = _build_picker_sar_mapping(size=8)

        ms = MixedSignalSimulator(
            sim_analog, dut, mapping,
            step_strategy=StepExactStrategy(max_step=CLK_HALF_PERIOD)
        )

        # Release reset
        picker_dut.rst_n.value = 1
        picker_dut.en.value = 1
        picker_dut.soc.value = 1

        t = CLK_HALF_PERIOD
        ms.advance_to(t)
        dut.step_clock()

        t += CLK_HALF_PERIOD
        picker_dut.soc.value = 0
        ms.advance_to(t)
        dut.step_clock()

        # Run conversion
        for _ in range(30):
            t += CLK_HALF_PERIOD
            ms.advance_to(t)
            dut.step_clock()
            if dut.eoc == 1:
                break

        assert dut.eoc == 1, "Conversion did not complete"
        # With SIZE=8: expected = 1.5/3.3 * 256 ~ 116
        expected = int(v_ain / 3.3 * (1 << 8))
        actual = dut.data
        assert abs(actual - expected) < 20, (
            f"Picker DUT: ADC result {actual} too far from expected {expected}"
        )
    finally:
        sim_analog.finish()
