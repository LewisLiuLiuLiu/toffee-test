"""Layer 3: TT03 temperature sensor -- ngspice only, SKY130 PEX.

Requires: SKY130 PDK (for the PEX netlist primitives), ngspice.
Circuit: hpretl_tt03_temperature_sensor PEX extraction from toffee_ana/tt03-tempsensor
  - Temperature-to-digital converter using ring oscillator + counter
  - 6-bit configuration (ts_cfg[5:0]), 8-bit thermometer output (st[7:0])
  - 10kHz clock, ~30ms settling time in full sim (we test fewer cycles)

Uses the reduced model library (sky130.lib.spice.tt.red) which must be
placed in the SKY130 PDK path (see fixtures.reduced_model_lib).
"""
import os
import tempfile

import pytest
import toffee_test

from toffee.mixed_signal.mixed_signal_simulator import MixedSignalSimulator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection
from toffee.mixed_signal.step_strategy import StepExactStrategy

from .fixtures import netlist_path, reduced_model_lib  # noqa: F401
from .conftest import HAS_NGSPICE, HAS_SKY130


class TempSensorDut:
    """Fake digital DUT for temperature sensor."""

    def __init__(self):
        self.clk = 0
        self.rst = 1  # active high reset
        self.ts_cfg0 = 0
        self.ts_cfg1 = 0
        self.ts_cfg2 = 0
        self.ts_cfg3 = 1  # cfg=0b001100 = 12
        self.ts_cfg4 = 1
        self.ts_cfg5 = 0
        # A2D outputs (thermometer code)
        self.st0 = 0
        self.st1 = 0
        self.st2 = 0
        self.st3 = 0
        self.st4 = 0
        self.st5 = 0
        self.st6 = 0
        self.st7 = 0


def _generate_tt03_testbench() -> str:
    """Generate TT03 testbench for toffee-driven simulation (ngspice only).

    Pin order from PEX subcircuit:
      io_in[1]=rst, io_in[2..7]=ts_cfg0..5, io_out[0..7]=st0..7,
      io_in[0]=clk, vccd1=VDD, vssd1=GND
    """
    pex_path = str(netlist_path("hpretl_tt03_temperature_sensor_golden.pex.spice"))
    model_lib = reduced_model_lib()

    lines = []
    lines.append("* TT03 temperature sensor testbench (toffee-driven)")
    lines.append(f'.lib "{model_lib}" tt')
    lines.append(f'.include "{pex_path}"')
    lines.append(".param fclk=10k")
    lines.append(".options method=gear maxord=2")
    lines.append(".temp 30")
    lines.append(".GLOBAL VDD")
    lines.append(".GLOBAL GND")
    lines.append("")
    lines.append("VDD1 VDD GND 1.8")

    # Digital control as external voltage sources
    for name in ["clk", "rst", "ts_cfg0", "ts_cfg1", "ts_cfg2",
                  "ts_cfg3", "ts_cfg4", "ts_cfg5"]:
        lines.append(f"V_{name} {name} GND DC 0 external")

    # Load caps on segment outputs
    for i in range(8):
        lines.append(f"C_st{i} st{i} GND 10f")

    # Instantiate PEX subcircuit (positional mapping matches .subckt header)
    lines.append("x1 rst ts_cfg0 ts_cfg1 ts_cfg2 ts_cfg3 ts_cfg4 ts_cfg5")
    lines.append("+   st0 st1 st2 st3 st4 st5 st6 st7 clk VDD GND")
    lines.append("+   hpretl_tt03_temperature_sensor")
    lines.append("")
    lines.append(".end")

    path = os.path.join(tempfile.mkdtemp(prefix="toffee_tt03_"), "tt03_tb.cir")
    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path


@pytest.fixture(params=["ngspice"])
def ngspice_sim(request, tmp_path):
    """ngspice-only fixture for TT03."""
    if not HAS_NGSPICE:
        pytest.skip("ngspice not available")

    def factory(netlist_file: str):
        from toffee.analog.ngspice_simulator import NgSpiceSimulator
        return NgSpiceSimulator(netlist_file)

    from .fixtures import SimContext
    from .conftest import SKY130_PDK_ROOT
    return SimContext(
        backend="ngspice", create=factory, pdk_root=SKY130_PDK_ROOT or ""
    )


@pytest.mark.e2e
@pytest.mark.sky130
@toffee_test.testcase
async def test_tempsensor_circuit_loads(ngspice_sim):
    """Verify PEX circuit loads in ngspice and MixedSignalSimulator initializes.

    The PEX netlist (17k transistors) loads in <1s, but the DC operating point
    computation takes >2min, making step-by-step simulation infeasible in CI.
    This test only verifies the circuit + model library can be parsed by ngspice
    and the mixed-signal bridge mapping is valid.
    """
    if not HAS_SKY130:
        pytest.skip("SKY130 PDK not found")

    netlist = _generate_tt03_testbench()
    sim = ngspice_sim.create(netlist)
    # If we get here, the circuit loaded successfully in ngspice
    dut = TempSensorDut()
    mapping = PortMapping()

    # D2A: digital control signals
    for name in ["clk", "rst", "ts_cfg0", "ts_cfg1", "ts_cfg2",
                  "ts_cfg3", "ts_cfg4", "ts_cfg5"]:
        mapping.add_digital(name, PortDirection.OUT)
        mapping.add_analog(f"V_{name}", PortDirection.IN)
        mapping.d2a(name, f"V_{name}", scale=1.8)

    # A2D: segment outputs
    for i in range(8):
        d_name = f"st{i}"
        mapping.add_digital(d_name, PortDirection.IN)
        mapping.add_analog(f"V(st{i})", PortDirection.OUT)
        mapping.a2d(f"V(st{i})", d_name, threshold=0.9)

    # Construct the MixedSignalSimulator (no simulation step)
    ms = MixedSignalSimulator(
        sim, dut, mapping,
        step_strategy=StepExactStrategy(max_step=50e-6),
    )
    # NOTE: We intentionally do NOT call ms.advance_to() because the PEX
    # netlist's DC operating point analysis takes >2min in ngspice.
    # The circuit loads correctly; only transient simulation is slow.
    sim.finish()
