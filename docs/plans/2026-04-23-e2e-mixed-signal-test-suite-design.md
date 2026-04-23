# End-to-End Mixed-Signal Test Suite Design

## Goal

Create a comprehensive end-to-end test suite that validates toffee's mixed-signal co-simulation infrastructure using real SPICE simulators (Xyce and ngspice) with real circuit netlists from `toffee_ana/`. Tests are placed in `toffee-test/tests/e2e/`.

Two-phase approach:
- **Phase 1**: Real analog simulators + Python DUT (fake digital logic)
- **Phase 2**: Real analog simulators + Picker-generated Verilator DUT (real digital logic)

## Environment

| Component | Status | Path |
|-----------|--------|------|
| Xyce | Installed | `/mnt/d/ongoingProjects/openEDA/install/xyce/bin/xyce` |
| ngspice | Installed (v36) | `/usr/bin/ngspice`, `libngspice.so` loads via ctypes |
| SKY130 PDK | Available (raw skywater-pdk) | `/mnt/d/ongoingProjects/layoutProjects/skywater-pdk/` |
| SKY130 device models | `sky130.lib.spice` | `.../sky130_fd_pr/latest/models/sky130.lib.spice` |
| SKY130 HVL std cells | All needed cells present | `.../sky130_fd_sc_hvl/latest/cells/` |
| Verilator | Installed | `/usr/local/bin/verilator` |
| Picker | Installed (v0.9.0) | `/usr/local/bin/picker` |

## Directory Structure

```
toffee-test/
  tests/
    e2e/
      __init__.py
      conftest.py              # markers, skipif, simulator/PDK detection
      fixtures.py              # SimulatorFactory, pdk_path(), netlist helpers
      netlists/
        rc_simple.cir          # Minimal RC (no PDK, Xyce+ngspice compatible)
        opamp_inv_gain.cir     # Inverting amp (inline LEVEL=1 models)
        ldo_loadstep.cir       # LDO load step (inline LEVEL=1 models)
        sar_adc_tb.cir         # SAR ADC testbench (SKY130, full transistor-level)
        tt05_dac_tb.cir        # TT05 3-bit DAC testbench (SKY130)
        tt03_tempsens_tb.cir   # TT03 temp sensor testbench (SKY130)
      test_smoke.py            # Layer 0: Pure analog smoke tests
      test_sar_adc.py          # Layer 1: SAR ADC mixed-signal
      test_tt05_dac.py         # Layer 2: TT05 DAC + Ring Oscillator
      test_tt03_tempsensor.py  # Layer 3: TT03 Temperature Sensor
```

## Infrastructure

### conftest.py

```python
import shutil
import pytest

def pytest_configure(config):
    config.addinivalue_line("markers", "e2e: end-to-end mixed-signal test")
    config.addinivalue_line("markers", "sky130: requires SKY130 PDK")
    config.addinivalue_line("markers", "xyce: requires Xyce simulator")
    config.addinivalue_line("markers", "ngspice: requires ngspice + libngspice")
    config.addinivalue_line("markers", "picker: requires picker-generated DUT")

HAS_XYCE = shutil.which("xyce") is not None

def _can_load_libngspice():
    try:
        from ctypes import cdll
        cdll.LoadLibrary("libngspice.so")
        return True
    except OSError:
        return False

HAS_NGSPICE = _can_load_libngspice()

def _find_sky130_pdk():
    import os
    for candidate in [
        os.environ.get("SKY130_PDK", ""),
        "/mnt/d/ongoingProjects/layoutProjects/skywater-pdk",
    ]:
        if candidate and os.path.isfile(
            os.path.join(candidate, "libraries/sky130_fd_pr/latest/models/sky130.lib.spice")
        ):
            return candidate
    return None

SKY130_PDK_ROOT = _find_sky130_pdk()
HAS_SKY130 = SKY130_PDK_ROOT is not None

def pytest_collection_modifyitems(items):
    for item in items:
        if "sky130" in item.keywords and not HAS_SKY130:
            item.add_marker(pytest.mark.skip(reason="SKY130 PDK not found"))
        if "xyce" in item.keywords and not HAS_XYCE:
            item.add_marker(pytest.mark.skip(reason="Xyce not available"))
        if "ngspice" in item.keywords and not HAS_NGSPICE:
            item.add_marker(pytest.mark.skip(reason="libngspice not available"))
```

### fixtures.py

```python
import pytest
from dataclasses import dataclass
from pathlib import Path

@dataclass
class SimContext:
    backend: str  # "xyce" or "ngspice"
    create: callable  # factory(netlist_content: str) -> simulator instance
    pdk_root: str  # SKY130 PDK path or ""

@pytest.fixture(params=["xyce", "ngspice"])
def analog_sim(request, tmp_path):
    backend = request.param
    if backend == "xyce" and not HAS_XYCE:
        pytest.skip("Xyce not available")
    if backend == "ngspice" and not HAS_NGSPICE:
        pytest.skip("ngspice not available")

    def factory(netlist_content: str):
        path = tmp_path / "circuit.cir"
        path.write_text(netlist_content)
        if backend == "xyce":
            from toffee.analog.xyce_simulator import XyceSimulator
            return XyceSimulator(str(path))
        else:
            from toffee.analog.ngspice_simulator import NgSpiceSimulator
            return NgSpiceSimulator(str(path))

    return SimContext(
        backend=backend,
        create=factory,
        pdk_root=SKY130_PDK_ROOT or "",
    )

def netlist_path(name: str) -> Path:
    return Path(__file__).parent / "netlists" / name
```

## Layer 0: Smoke Tests (test_smoke.py)

No PDK required. Uses inline LEVEL=1 placeholder models. Always runnable.

### Circuits

| Circuit | Source | Description |
|---------|--------|-------------|
| `rc_simple.cir` | New (trivial) | R=1k, C=1p RC lowpass |
| `opamp_inv_gain.cir` | Adapted from `SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp` | Inverting amplifier with feedback |
| `ldo_loadstep.cir` | Adapted from `SPICE-Netlists/ldo_1p2Vout_1p8VDD_tsmc180.sp` | LDO with load step test |

### Tests

| Test | Bridge | Assertion |
|------|--------|-----------|
| `test_rc_d2a_voltage` | D2A voltage: `vin_ctrl=1` → `V(in)=1.8V` | `V(out) > 1.5V` after 5RC |
| `test_opamp_d2a_param` | D2A param: `gain_sel` → `.param R2` | Output changes with gain code |
| `test_ldo_a2d_threshold` | A2D: `V(vout)` → `power_good` | `power_good=1` after startup |
| `test_rc_bidirectional` | D2A + A2D closed loop | Digital drive → analog charge → digital feedback |

## Layer 1: SAR ADC (test_sar_adc.py) — @pytest.mark.sky130

The flagship mixed-signal test. Uses the full transistor-level SKY130 12-bit SAR ADC.

### Source circuits

- Analog: `toffee_ana/sky130_ef_ip__adc3v_12bit/netlist/schematic/sky130_ef_ip__adc3v_12bit.spice` (full 288-line hierarchical netlist)
- Digital: `toffee_ana/sky130_ef_ip__adc3v_12bit/verilog/sar_ctrl.v` (115-line RTL)

### SKY130 dependencies

- Device models: `.lib "sky130.lib.spice" tt`
- Standard cells: `sky130_fd_sc_hvl__lsbuflv2hv_1`, `sky130_fd_sc_hvl__inv_2`, `sky130_fd_sc_hvl__nor2_1`, `sky130_fd_sc_hvl__diode_2`, `sky130_fd_sc_hvl__decap_4`, `sky130_fd_sc_hvl__decap_8`

### Testbench netlist (sar_adc_tb.cir)

Wraps the full ADC subcircuit with:
- Power: VDDA=3.3V, VCCD=1.8V, VSSA=VSSD=0
- References: VREFH=3.3V, VREFL=0V, VCM=1.65V
- Analog input: V_AIN (set per test)
- 16 digital control voltage sources (12x dac_val + ena + reset + hold + sample_n) driven by MixedSignalSimulator via D2A

### PortMapping

| Direction | Digital Signal | Analog Node | Bridge |
|-----------|---------------|-------------|--------|
| D2A | `dac_val[0..11]` | 12 voltage sources | `d2a(scale=1.8)` |
| D2A | `ena` | `adc_ena` | `d2a(scale=1.8)` |
| D2A | `dac_rst` | `adc_reset` | `d2a(scale=1.8)` |
| D2A | `sample_n` | `adc_hold` | `d2a(scale=1.8)` |
| A2D | `cmp` | `V(comp_out)` | `a2d(threshold=0.9)` |

### Python DUT (Phase 1)

`SarCtrlDut`: Faithful Python translation of `sar_ctrl.v` FSM with SIZE=12.

### Picker DUT (Phase 2)

```
picker export sar_ctrl.v --toffee --sname DUTSarCtrl
```

Generates `picker_out_sar_ctrl/DUTSarCtrl` Python wrapper around Verilator-compiled shared library.

### Tests

| Test | Input | Assertion |
|------|-------|-----------|
| `test_sar_full_conversion` | V_AIN=1.5V | `data ≈ 1862 ± 50 LSB` |
| `test_sar_midscale` | V_AIN=1.65V | `data ≈ 2048 ± 50 LSB` |
| `test_sar_near_zero` | V_AIN=0.1V | `data` near low end |
| `test_sar_monotonicity` | Ramp of voltages | Output codes monotonically increasing |

### Closed-loop timing

Each SAR clock cycle:
1. Python DUT `clock_step()` → updates `data[11:0]`, `sample_n`, `dac_rst`, `ena`
2. MixedSignalSimulator `advance_to(t)` → D2A drives voltage sources → Xyce/ngspice transient → A2D reads comparator output
3. Python DUT reads `cmp` → next FSM state

## Layer 2: TT05 DAC + Ring Oscillator (test_tt05_dac.py) — @pytest.mark.sky130

### Source

`toffee_ana/tt05-analog-test/lvs/netlist/tt_um_tt05_analog_test.spice`

TinyTapeout standard pinout with:
- 3-bit R-2R DAC: `ui_in[2:0]` → `ua[1]`
- Ring oscillator: `ui_in[6]` enable → `ua[0]`
- Transmission gate muxing via `ui_in[3]` (DAC TG), `ui_in[5]` (ringo TG)

### Tests

| Test | Bridge | Assertion |
|------|--------|-----------|
| `test_dac_3bit_codes` | D2A: `ui_in[2:0]` | 8 output voltages linearly increasing |
| `test_ringo_enable` | D2A: `ui_in[6]=1` | `V(ua_0)` oscillates (period ~2us) |
| `test_dac_a2d_readback` | D2A + A2D | Digital code → analog → threshold → digital |

## Layer 3: TT03 Temperature Sensor (test_tt03_tempsensor.py) — @pytest.mark.sky130

### Source

- SPICE: `toffee_ana/tt03-tempsensor/sim/simulation/tb_tempsens.spice`
- PEX netlist: `toffee_ana/tt03-tempsensor/sim/simulation/hpretl_tt03_temperature_sensor_golden.pex.spice`
- Reference: `toffee_ana/tt03-tempsensor/src/test.py` (cocotb test with expected values)

### Note

ngspice only (uses `.control` block in original testbench). Testbench needs adaptation for toffee-driven simulation.

### Tests

| Test | Bridge | Assertion |
|------|--------|-----------|
| `test_tempsensor_digital_readout` | D2A: clk/rst/cfg; A2D: segments | Segment codes match expected |
| `test_tempsensor_config_sweep` | D2A param: cfg values | Different configs produce different readings |

## Coverage Matrix

| | Xyce | ngspice | Python DUT | Picker DUT |
|---|:---:|:---:|:---:|:---:|
| Layer 0: Smoke (RC/LDO/Opamp) | x | x | x | - |
| Layer 1: SAR ADC | x | x | x | x |
| Layer 2: TT05 DAC+Ringo | x | x | x | - |
| Layer 3: TT03 Temp Sensor | - | x | x | - |

## Bridge Path Coverage

| Bridge Path | Covered By |
|-------------|------------|
| D2A voltage (`d2a(scale=...)`) | Smoke RC, TT05 DAC, SAR ADC |
| D2A parameter (`d2a_param(mapping=...)`) | Smoke Opamp, SAR ADC |
| A2D threshold (`a2d(threshold=...)`) | Smoke LDO, SAR ADC, TT05 Ringo |
| A2D YADC (`a2d(yadc_device=...)`) | SAR ADC (Xyce only, if YADC supported) |
| Bidirectional closed loop | Smoke RC, SAR ADC (full conversion) |

## Dependencies

- `pytoffee` (toffee framework with mixed_signal module)
- `toffee-test` (test framework)
- `pytest`, `pytest-asyncio`
- Xyce Python API (`xyce_interface.py`)
- `libngspice.so` (ctypes)
- SKY130 PDK (for layers 1-3)
- Picker + Verilator (for Phase 2 picker DUT tests)
