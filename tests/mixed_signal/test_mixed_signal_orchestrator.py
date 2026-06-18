"""Unit tests for MixedSignalOrchestrator — Slice 1: Analog-leading."""

import asyncio
import pytest

from toffee.mixed_signal.mixed_signal_orchestrator import MixedSignalOrchestrator
from toffee.mixed_signal.port_mapping import PortMapping, PortDirection


class MockPin:
    def __init__(self, value=0):
        self.value = value


class MockDut:
    def __init__(self, pins=None):
        for name, val in (pins or {}).items():
            setattr(self, name, MockPin(val))
        self.refresh_comb_called = 0
        self.step_called = 0

    def RefreshComb(self):
        self.refresh_comb_called += 1

    def Step(self, cycles=1):
        self.step_called += cycles


class MockAnalogSimulator:
    def __init__(self, voltages=None, next_events=None):
        self._node_voltages = voltages or {}
        self._vsrc_values = {}
        self._params = {}
        self._current_time = 0.0
        self._finished = False
        self._events = list(next_events or ["clock_edge"])
        self._events.reverse()
        self._triggers = {}  # node_name -> threshold
        self._next_event_calls = []  # track target_time args

    @property
    def current_time(self) -> float:
        return self._current_time

    def read(self, name):
        keys = [name, name.lower()]
        for k in keys:
            if k in self._node_voltages:
                return self._node_voltages[k]
        raise KeyError(name)

    def set_vsrc(self, name, voltage):
        self._vsrc_values[name] = float(voltage)

    set_source = set_vsrc

    def set_source_waveform(self, name, times, values):
        self._vsrc_values[name] = float(values[-1])

    def setCircuitParameter(self, name, value):
        self._params[name] = value

    set_parameter = setCircuitParameter

    def add_async_trigger(self, node_name, threshold):
        self._triggers[node_name] = threshold

    register_trigger = add_async_trigger

    def remove_async_trigger(self, node_name):
        self._triggers.pop(node_name, None)

    unregister_trigger = remove_async_trigger

    async def next_event(self, target_time=None):
        self._next_event_calls.append(target_time)
        if not self._events:
            return "clock_edge"
        event_type = self._events.pop()
        if target_time is not None:
            self._current_time = target_time
        else:
            self._current_time += 1e-9
        return event_type

    def step_time(self, dt):
        self._current_time += dt

    def finish(self):
        self._finished = True


class TestOrchestratorSkeleton:
    """P0: Constructor and ABC properties."""

    def test_clock_event_is_asyncio_event(self):
        orch = MixedSignalOrchestrator(MockDut(), MockAnalogSimulator(), PortMapping())
        assert isinstance(orch.clock_event, asyncio.Event)


class TestA2D:
    """A2D bridge: analog voltage → threshold → digital pin."""

    @pytest.mark.asyncio
    async def test_voltage_above_threshold_sets_pin_high(self):
        dut = MockDut({"in_pin": 0})
        analog = MockAnalogSimulator(voltages={"in_node": 0.9})
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        assert dut.in_pin.value == 1

    @pytest.mark.asyncio
    async def test_voltage_below_threshold_sets_pin_low(self):
        dut = MockDut({"in_pin": 1})
        analog = MockAnalogSimulator(voltages={"in_node": 0.3})
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        assert dut.in_pin.value == 0

    @pytest.mark.asyncio
    async def test_invert_flips_threshold_result(self):
        dut = MockDut({"in_pin": 0})
        analog = MockAnalogSimulator(voltages={"in_node": 0.9})
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6, invert=True)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        assert dut.in_pin.value == 0  # 0.9 ≥ 0.6 → 1 → invert → 0


class TestD2A:
    """D2A bridge: digital pin → scale+offset → analog source."""

    @pytest.mark.asyncio
    async def test_d2a_sets_vsrc_with_scale_and_offset(self):
        dut = MockDut({"dac_out": 7})
        analog = MockAnalogSimulator(voltages={"dummy_in": 0.0})
        mapping = PortMapping()
        mapping.add_digital("dac_out", PortDirection.OUT)
        mapping.add_analog("out_node", PortDirection.IN)
        mapping.d2a("dac_out", "out_node", scale=0.5, offset=1.0)
        # Dummy A2D to activate analog-leading path
        mapping.add_analog("dummy_in", PortDirection.OUT)
        mapping.add_digital("dummy_pin", PortDirection.IN)
        mapping.a2d("dummy_in", "dummy_pin", threshold=0.5)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        # 7 * 0.5 + 1.0 = 4.5
        assert analog._vsrc_values["out_node"] == 4.5

    @pytest.mark.asyncio
    async def test_d2a_param_maps_code_to_value(self):
        dut = MockDut({"mode": 2})
        analog = MockAnalogSimulator(voltages={"dummy_in": 0.0})
        mapping = PortMapping()
        mapping.add_digital("mode", PortDirection.OUT)
        mapping.add_analog("dummy", PortDirection.IN)
        mapping.d2a_param("mode", "resistance", {1: 1000.0, 2: 5000.0, 3: 10000.0})
        # Dummy A2D to activate analog-leading path
        mapping.add_analog("dummy_in", PortDirection.OUT)
        mapping.add_digital("dummy_pin", PortDirection.IN)
        mapping.a2d("dummy_in", "dummy_pin", threshold=0.5)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        assert analog._params["resistance"] == 5000.0


class TestNextEventDispatch:
    """Event kind dispatch: clock_edge vs threshold_crossed."""

    @pytest.mark.asyncio
    async def test_clock_edge_calls_step_not_refresh_comb(self):
        dut = MockDut()
        analog = MockAnalogSimulator(
            voltages={"in_node": 0.0}, next_events=["clock_edge"]
        )
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        assert dut.step_called == 1
        assert dut.refresh_comb_called == 0

    @pytest.mark.asyncio
    async def test_threshold_crossed_calls_refresh_comb_not_step(self):
        dut = MockDut()
        analog = MockAnalogSimulator(
            voltages={"in_node": 0.0}, next_events=["threshold_crossed"]
        )
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        assert dut.refresh_comb_called == 1
        assert dut.step_called == 0

    @pytest.mark.asyncio
    async def test_unknown_event_kind_raises_value_error(self):
        dut = MockDut()
        analog = MockAnalogSimulator(
            voltages={"in_node": 0.0}, next_events=["bogus_event"]
        )
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        with pytest.raises(ValueError, match="Unknown event kind"):
            await orch.next_event()


class TestAnalogLeadingTriggers:
    """Auto-registration of A2D ports as async triggers + clock boundary tracking."""

    def test_init_auto_registers_a2d_as_async_triggers(self):
        dut = MockDut({"in_pin": 0})
        analog = MockAnalogSimulator(voltages={"in_node": 0.0})
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)

        assert "in_node" in analog._triggers
        assert analog._triggers["in_node"] == 0.6

    def test_init_registers_multiple_a2d_with_correct_thresholds(self):
        dut = MockDut({"in_pin": 0, "rst_pin": 0})
        analog = MockAnalogSimulator(voltages={"in_node": 0.0, "rst_node": 0.0})
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_digital("rst_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.add_analog("rst_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)
        mapping.a2d("rst_node", "rst_pin", threshold=1.2)

        orch = MixedSignalOrchestrator(dut, analog, mapping)

        assert analog._triggers == {"in_node": 0.6, "rst_node": 1.2}
        assert orch._registered_triggers == ["in_node", "rst_node"]

    @pytest.mark.asyncio
    async def test_threshold_crossed_does_not_advance_clock_boundary(self):
        dut = MockDut({"in_pin": 0})
        analog = MockAnalogSimulator(
            voltages={"in_node": 0.0},
            next_events=["threshold_crossed", "clock_edge"],
        )
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        boundary_after_init = orch._clock_boundary

        await orch.next_event()  # threshold_crossed

        assert orch._clock_boundary == boundary_after_init  # no advance
        # Next next_event should use the same boundary as target_time
        await orch.next_event()  # clock_edge (same boundary)
        assert analog._next_event_calls[-1] == boundary_after_init

    @pytest.mark.asyncio
    async def test_consecutive_clock_edges_increment_boundary_by_1ns(self):
        dut = MockDut({"in_pin": 0})
        analog = MockAnalogSimulator(
            voltages={"in_node": 0.0},
            next_events=["clock_edge", "clock_edge"],
        )
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        boundary0 = orch._clock_boundary

        await orch.next_event()  # first clock_edge
        assert orch._clock_boundary == boundary0 + 1e-9

        await orch.next_event()  # second clock_edge
        assert orch._clock_boundary == boundary0 + 2e-9

    @pytest.mark.asyncio
    async def test_no_a2d_skips_trigger_registration_and_boundary_tracking(self):
        dut = MockDut({"dac_out": 10})
        analog = MockAnalogSimulator()
        mapping = PortMapping()
        mapping.add_digital("dac_out", PortDirection.OUT)
        mapping.add_analog("vout", PortDirection.IN)
        mapping.d2a("dac_out", "vout", scale=0.5)
        # No A2D mappings → digital-leading path

        orch = MixedSignalOrchestrator(dut, analog, mapping)

        assert len(analog._triggers) == 0
        assert len(orch._registered_triggers) == 0
        # Digital-leading path: next_event does not use _clock_boundary
        boundary_before = orch._clock_boundary
        await orch.next_event()
        assert orch._clock_boundary == boundary_before  # unchanged


class TestFinish:
    def test_finish_calls_analog_finish(self):
        analog = MockAnalogSimulator()
        orch = MixedSignalOrchestrator(MockDut(), analog, PortMapping())
        orch.finish()
        assert analog._finished is True

    def test_finish_removes_all_registered_triggers(self):
        dut = MockDut({"in_pin": 0, "clk_pin": 0})
        analog = MockAnalogSimulator(voltages={"in_node": 0.0, "clk_node": 0.0})
        mapping = PortMapping()
        mapping.add_digital("in_pin", PortDirection.IN)
        mapping.add_digital("clk_pin", PortDirection.IN)
        mapping.add_analog("in_node", PortDirection.OUT)
        mapping.add_analog("clk_node", PortDirection.OUT)
        mapping.a2d("in_node", "in_pin", threshold=0.6)
        mapping.a2d("clk_node", "clk_pin", threshold=1.2)

        orch = MixedSignalOrchestrator(dut, analog, mapping)

        # Triggers should be registered at init
        assert "in_node" in analog._triggers
        assert "clk_node" in analog._triggers

        orch.finish()

        # All triggers should be removed
        assert "in_node" not in analog._triggers
        assert "clk_node" not in analog._triggers
        assert len(analog._triggers) == 0

    def test_finish_with_no_triggers_still_calls_analog_finish(self):
        """Pure D2A (no A2D) — no triggers to remove, but analog.finish() must still be called."""
        dut = MockDut({"dac_out": 10})
        analog = MockAnalogSimulator()
        mapping = PortMapping()
        mapping.add_digital("dac_out", PortDirection.OUT)
        mapping.add_analog("vout", PortDirection.IN)
        mapping.d2a("dac_out", "vout", scale=0.5)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        assert len(orch._registered_triggers) == 0

        orch.finish()

        assert analog._finished is True
        assert len(orch._registered_triggers) == 0


class TestDigitalLeading:
    """No A2D mappings → digital leads, analog catches up."""

    @pytest.mark.asyncio
    async def test_no_a2d_digital_leads_step_before_analog(self):
        dut = MockDut({"dac_out": 10})
        analog = MockAnalogSimulator()
        mapping = PortMapping()
        mapping.add_digital("dac_out", PortDirection.OUT)
        mapping.add_analog("vout", PortDirection.IN)
        mapping.d2a("dac_out", "vout", scale=0.5)
        # No A2D mappings → digital-leading

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        assert dut.step_called == 1
        assert dut.refresh_comb_called == 0
        assert analog._vsrc_values["vout"] == 5.0
        assert analog.current_time == pytest.approx(1e-9)


class TestStepAndStepTime:
    """Synchronous advance (fallback)."""

    def test_step_without_a2d_advances_analog(self):
        dut = MockDut({"dac_out": 10})
        analog = MockAnalogSimulator()
        mapping = PortMapping()
        mapping.add_digital("dac_out", PortDirection.OUT)
        mapping.add_analog("vout", PortDirection.IN)
        mapping.d2a("dac_out", "vout", scale=0.5)

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        orch.step(3)
        assert analog.current_time == pytest.approx(3e-9)
        assert dut.step_called == 3

    def test_step_time_advances_analog(self):
        dut = MockDut()
        analog = MockAnalogSimulator()
        orch = MixedSignalOrchestrator(dut, analog, PortMapping())
        orch.step_time(5e-6)
        assert analog.current_time == pytest.approx(5e-6)

    def test_advance_to_jumps_to_target_time(self):
        dut = MockDut()
        analog = MockAnalogSimulator()
        orch = MixedSignalOrchestrator(dut, analog, PortMapping())
        orch.advance_to(5e-9)
        assert analog.current_time == pytest.approx(5e-9)

    def test_advance_to_backward_is_noop(self):
        dut = MockDut()
        analog = MockAnalogSimulator()
        orch = MixedSignalOrchestrator(dut, analog, PortMapping())
        orch.advance_to(5e-9)
        orch.advance_to(2e-9)
        assert analog.current_time == pytest.approx(5e-9)


class TestYADCPortsNoLongerSkipped:
    """YADC ports must be treated identically to non-YADC ports after removing
    the 'if yadc: continue' lines from both __init__ and _a2d()."""

    def test_yadc_port_trigger_registered_on_init(self):
        """A port with yadc_device set must still have its async trigger registered."""
        dut = MockDut({"yadc_pin": 0})
        analog = MockAnalogSimulator(voltages={"yadc_node": 0.0})
        mapping = PortMapping()
        mapping.add_digital("yadc_pin", PortDirection.IN)
        mapping.add_analog("yadc_node", PortDirection.OUT)
        mapping.a2d("yadc_node", "yadc_pin", threshold=0.5, yadc_device="my_yadc")

        MixedSignalOrchestrator(dut, analog, mapping)

        assert "yadc_node" in analog._triggers
        assert analog._triggers["yadc_node"] == 0.5

    def test_yadc_port_in_registered_triggers_list(self):
        """A YADC port must appear in _registered_triggers (used by finish() to clean up)."""
        dut = MockDut({"yadc_pin": 0})
        analog = MockAnalogSimulator(voltages={"yadc_node": 0.0})
        mapping = PortMapping()
        mapping.add_digital("yadc_pin", PortDirection.IN)
        mapping.add_analog("yadc_node", PortDirection.OUT)
        mapping.a2d("yadc_node", "yadc_pin", threshold=0.5, yadc_device="my_yadc")

        orch = MixedSignalOrchestrator(dut, analog, mapping)

        assert "yadc_node" in orch._registered_triggers

    @pytest.mark.asyncio
    async def test_yadc_port_read_called_in_a2d_bridge(self):
        """_a2d() must call read() for YADC ports and apply threshold comparison."""
        dut = MockDut({"yadc_pin": 0})
        analog = MockAnalogSimulator(voltages={"yadc_node": 1.2})
        mapping = PortMapping()
        mapping.add_digital("yadc_pin", PortDirection.IN)
        mapping.add_analog("yadc_node", PortDirection.OUT)
        mapping.a2d("yadc_node", "yadc_pin", threshold=0.6, yadc_device="my_yadc")

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        # 1.2 >= 0.6 → digital value = 1
        assert dut.yadc_pin.value == 1

    @pytest.mark.asyncio
    async def test_yadc_port_read_below_threshold_in_a2d_bridge(self):
        """_a2d() must call read() for YADC ports — voltage below threshold sets 0."""
        dut = MockDut({"yadc_pin": 1})
        analog = MockAnalogSimulator(voltages={"yadc_node": 0.2})
        mapping = PortMapping()
        mapping.add_digital("yadc_pin", PortDirection.IN)
        mapping.add_analog("yadc_node", PortDirection.OUT)
        mapping.a2d("yadc_node", "yadc_pin", threshold=0.6, yadc_device="my_yadc")

        orch = MixedSignalOrchestrator(dut, analog, mapping)
        await orch.next_event()

        # 0.2 < 0.6 → digital value = 0
        assert dut.yadc_pin.value == 0

    @pytest.mark.asyncio
    async def test_mixed_yadc_and_non_yadc_both_registered(self):
        """Both YADC and non-YADC ports must have triggers registered and _a2d() applied."""
        dut = MockDut({"normal_pin": 0, "yadc_pin": 0})
        analog = MockAnalogSimulator(voltages={"normal_node": 0.9, "yadc_node": 1.1})
        mapping = PortMapping()
        mapping.add_digital("normal_pin", PortDirection.IN)
        mapping.add_digital("yadc_pin", PortDirection.IN)
        mapping.add_analog("normal_node", PortDirection.OUT)
        mapping.add_analog("yadc_node", PortDirection.OUT)
        mapping.a2d("normal_node", "normal_pin", threshold=0.6)
        mapping.a2d("yadc_node", "yadc_pin", threshold=0.6, yadc_device="my_yadc")

        orch = MixedSignalOrchestrator(dut, analog, mapping)

        # Both triggers registered
        assert analog._triggers == {"normal_node": 0.6, "yadc_node": 0.6}
        assert set(orch._registered_triggers) == {"normal_node", "yadc_node"}

        # Both pins updated after next_event
        await orch.next_event()
        assert dut.normal_pin.value == 1
        assert dut.yadc_pin.value == 1


class TestStepStrategy:
    """StepStrategy sub-step A2D checking."""

    def test_accepts_step_strategy(self):
        """Orchestrator stores step_strategy when provided."""
        from toffee.mixed_signal.step_strategy import StepExactStrategy
        dut = MockDut({"dac_out": 1})
        analog = MockAnalogSimulator()
        mapping = PortMapping()
        mapping.add_digital("dac_out", PortDirection.OUT)
        mapping.add_analog("vout", PortDirection.IN)
        mapping.d2a("dac_out", "vout", scale=0.5)

        strategy = StepExactStrategy(max_step=2e-9)
        orch = MixedSignalOrchestrator(dut, analog, mapping, step_strategy=strategy)
        assert orch._step_strategy is strategy

    def test_none_by_default(self):
        """Without step_strategy, _step_strategy is None."""
        dut = MockDut()
        analog = MockAnalogSimulator()
        mapping = PortMapping()
        orch = MixedSignalOrchestrator(dut, analog, mapping)
        assert orch._step_strategy is None

    def test_step_time_with_strategy_subdivides(self):
        """step_time(10ns) with max_step=3ns should produce 4 sub-steps."""
        from toffee.mixed_signal.step_strategy import StepExactStrategy
        dut = MockDut({"dac_out": 1, "a2d_pin": 0})
        analog = MockAnalogSimulator(voltages={"a2d_node": 0.0})
        mapping = PortMapping()
        mapping.add_digital("dac_out", PortDirection.OUT)
        mapping.add_analog("vout", PortDirection.IN)
        mapping.d2a("dac_out", "vout", scale=0.5)
        mapping.add_digital("a2d_pin", PortDirection.IN)
        mapping.add_analog("a2d_node", PortDirection.OUT)
        mapping.a2d("a2d_node", "a2d_pin", threshold=0.5)

        strategy = StepExactStrategy(max_step=3e-9)
        orch = MixedSignalOrchestrator(dut, analog, mapping, step_strategy=strategy)

        # Track step_time calls to analog
        step_calls = []
        def record_step(dt):
            step_calls.append(dt)
            analog._current_time += dt
        analog.step_time = record_step

        orch.step_time(10e-9)

        # max_step=3ns, window=10ns → 3+3+3+1 = 4 steps
        assert len(step_calls) == 4, f"Expected 4 sub-steps, got {step_calls}"
        assert sum(step_calls) == pytest.approx(10e-9)
