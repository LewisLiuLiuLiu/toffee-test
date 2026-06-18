"""E2E: RC circuit with AnalogAgent + AnalogModel + Env.attach."""
import os
import tempfile

import pytest
import toffee

from toffee.analog.ngspice_simulator import NgSpiceSimulator
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_model import AnalogModel
from toffee.analog.analog_env import AnalogEnv
from toffee._compare import tolerance_compare
from toffee.agent import driver_method
from toffee.model import driver_hook


RC_NETLIST = """\
* RC circuit for Agent E2E test
V_IN in 0 DC 0 external
R1 in out 1k
C1 out 0 1p
.end
"""


@pytest.mark.ngspice
def test_rc_agent_driver():
    """Agent with @driver_method drives ngspice, returns VOUT — no model."""

    netlist_dir = tempfile.mkdtemp(prefix="toffee_rc_ag_")
    netlist_path = os.path.join(netlist_dir, "rc.cir")
    with open(netlist_path, "w") as f:
        f.write(RC_NETLIST)

    def env_handle():
        sim = NgSpiceSimulator(netlist_path)
        bundle = AnalogBundle(sim)
        bundle.bind_stimulus("vin", "V_IN")
        bundle.bind_observation("vout", "v(out)")
        toffee.start_callback_executor(sim)

        class RCAgent(AnalogAgent):
            @driver_method()
            async def charge(self, vin_val):
                self.bundle.vin.value = vin_val
                sim.step_time(2e-9)
                return self.bundle.vout.voltage

        env = AnalogEnv(sim)
        env.rc_agent = RCAgent(bundle)
        return env

    async def test(env):
        result = await env.rc_agent.charge(1.8)
        assert 0.5 < result < 1.8, f"Unexpected VOUT: {result}"
        env.finish()

    toffee.run(test, env_handle)


@pytest.mark.ngspice
def test_rc_agent_with_model():
    """Env.attach(Model) → driver_hook compared with DUT via compare_func."""

    netlist_dir = tempfile.mkdtemp(prefix="toffee_rc_mdl_")
    netlist_path = os.path.join(netlist_dir, "rc.cir")
    with open(netlist_path, "w") as f:
        f.write(RC_NETLIST)

    def env_handle():
        sim = NgSpiceSimulator(netlist_path)
        bundle = AnalogBundle(sim)
        bundle.bind_stimulus("vin", "V_IN")
        bundle.bind_observation("vout", "v(out)")
        toffee.start_callback_executor(sim)

        class RCModel(AnalogModel):
            @driver_hook(agent_name="rc_agent")
            def charge(self, vin_val):
                return vin_val * 1.0

        class RCAgent(AnalogAgent):
            @driver_method()
            async def charge(self, vin_val):
                self.bundle.vin.value = vin_val
                sim.step_time(2e-9)
                return self.bundle.vout.voltage

        agent = RCAgent(bundle, compare_func=tolerance_compare(0.3))
        model = RCModel()

        env = AnalogEnv(sim)
        env.rc_agent = agent
        env.attach(model)
        return env

    async def test(env):
        result = await env.rc_agent.charge(1.8)
        assert 0.5 < result < 1.8, f"Unexpected VOUT: {result}"
        env.finish()

    toffee.run(test, env_handle)
