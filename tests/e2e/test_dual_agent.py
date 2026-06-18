"""E2E: Mixed-signal dual-Agent integration."""
import os
import tempfile

import pytest
import toffee

from toffee.analog.ngspice_simulator import NgSpiceSimulator
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_model import AnalogModel
from toffee.analog.analog_env import AnalogEnv
from toffee.agent import Agent, driver_method
from toffee.model import driver_hook
from toffee.bundle import Bundle, Signals
from toffee._compare import tolerance_compare


RC_NETLIST = """\
* RC circuit for dual-agent E2E test
V_IN in 0 DC 0 external
R1 in out 1k
C1 out 0 1p
.end
"""


class DigitalBundle(Bundle):
    vin_ctrl, charge_done = Signals(2)


@pytest.mark.ngspice
def test_dual_agent_analog_and_digital():
    """Analog Agent + Digital Agent coexist in one AnalogEnv."""

    netlist_dir = tempfile.mkdtemp(prefix="toffee_dual_")
    netlist_path = os.path.join(netlist_dir, "rc.cir")
    with open(netlist_path, "w") as f:
        f.write(RC_NETLIST)

    def env_handle():
        sim = NgSpiceSimulator(netlist_path)
        toffee.start_callback_executor(sim)

        # Analog Bundle + Agent
        analog_bundle = AnalogBundle(sim)
        analog_bundle.bind_stimulus("vin", "V_IN")
        analog_bundle.bind_observation("vout", "v(out)")

        class AnalogModelRC(AnalogModel):
            @driver_hook(agent_name="analog_agent")
            def charge(self, vin_val):
                return vin_val * 1.0

        class AnalogRC(AnalogAgent):
            @driver_method()
            async def charge(self, vin_val):
                self.bundle.vin.value = vin_val
                sim.step_time(2e-9)
                return self.bundle.vout.voltage

        analog_agent = AnalogRC(analog_bundle, compare_func=tolerance_compare(0.3))
        analog_model = AnalogModelRC()

        # Digital Bundle + Agent
        class FakePin:
            xdata = type("X", (), {"XData": 0})()
            event = None
            value = 0
            mIOType = 0

        class FakeDut:
            def __init__(self):
                self.vin_ctrl = FakePin()
                self.charge_done = FakePin()

            def StepRis(self, *a, **kw): pass
            Step = StepRis
            RefreshComb = StepRis

        dut = FakeDut()
        digital_bundle = DigitalBundle()
        digital_bundle.bind(dut)

        class DigitalCtrl(Agent):
            @driver_method()
            async def set_charge(self, val):
                self.bundle.vin_ctrl.value = val
                return val

        digital_agent = DigitalCtrl(digital_bundle)

        # Env with both
        env = AnalogEnv(sim)
        env.analog_agent = analog_agent
        env.digital_agent = digital_agent
        env.attach(analog_model)
        return env

    async def test(env):
        # Digital Agent works
        d = await env.digital_agent.set_charge(1)
        assert d == 1

        # Analog Agent works with Model comparison
        a = await env.analog_agent.charge(1.8)
        assert 0.5 < a < 1.8, f"Unexpected VOUT: {a}"
        env.finish()

    toffee.run(test, env_handle)
