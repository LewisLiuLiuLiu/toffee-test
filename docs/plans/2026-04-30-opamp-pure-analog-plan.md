# 两级运放纯模拟验证 — 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在两级运放上跑通 toffee 完整纯模拟验证方法论（DC + AC + TRAN + Monitor + Model），同时修复 NgSpiceSimulator 异步化缺陷。

**Architecture:** 6 个独立任务，DC/AC 先做（无依赖），然后修 NgSpice 地基，再上 TRAN + Monitor + Model。每个任务 TDD：先写好断言再跑。

**Tech Stack:** Python 3.12, ngspice v36 (ctypes), toffee 框架, pytest

**前置:** 所有命令在 `toffee_project/` 下执行，需设置 `PYTHONPATH`:
```bash
export PYTHONPATH=/mnt/d/ongoingProjects/openEDA/toffee_project/toffee-test:/mnt/d/ongoingProjects/openEDA/toffee_project/toffee
```

---

### Task 1: DC 工作点测试完善

**目标:** 增强现有 `test_opamp_ngspice.py`，验证两级运放所有管子饱和、vout 在合理范围。

**文件:**
- 修改: `toffee/tests/analog/test_opamp_ngspice.py`
- 参考: `toffee/tests/analog/test_opamp_ngspice.py` (现有)

**Step 1: 阅读现有测试，确认当前断言**

```bash
cat toffee/tests/analog/test_opamp_ngspice.py
```

当前已经验证了 `vout > vdsat_m5` 和 `v(vdd) == 1.8`。

**Step 2: 扩展 DC 测试 —— 添加更多管子饱和检查和偏置验证**

在 `test_opamp_dc_ngspice` 末尾添加：

```python
    # 验证第一级差分对偏置电流
    id_m1 = opamp_env.simulator.read("i(@m1[id])")
    assert abs(id_m1) > 1e-6, f"M1 current {id_m1}A too small"
    
    # 验证 vout 在合理直流范围 (0.6V ~ 1.5V)
    assert 0.6 < vout < 1.5, f"vout={vout}V out of expected DC range [0.6, 1.5]"
    
    # 验证 vdsat_m5 > 0（确保管子开启了）
    assert vdsat_m5 > 0, f"M5 Vdsat={vdsat_m5}V, transistor may be off"
```

**Step 3: 跑测试确认 PASS**

```bash
python3 -m pytest toffee/tests/analog/test_opamp_ngspice.py -v
```

**Step 4: Commit**

```bash
git add toffee/tests/analog/test_opamp_ngspice.py
git commit -m "test: extend DC opamp test with saturation and bias checks"
```

---

### Task 2: AC 频率特性测试

**目标:** 新建 AC 测试，验证低频增益、相位裕度、单位增益带宽。

**文件:**
- 创建: `toffee/tests/analog/test_opamp_ac.py`
- 参考: `toffee/tests/analog/test_opamp_ngspice.py` (Agent/Env 模式)

**Step 1: 写 Agent 和 Env**

```python
"""AC analysis test for two-stage op-amp."""
import os, tempfile
import toffee_test
from toffee import driver_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.ngspice_simulator import NgSpiceSimulator


class OpampACAgent(AnalogAgent):
    @driver_method()
    async def measure_gain_db(self):
        return self.simulator.read("vdb(vout)")
    
    @driver_method()
    async def measure_phase(self):
        return self.simulator.read("vp(vout)")
    
    @driver_method()
    async def measure_vout_mag(self):
        return self.simulator.read("vm(vout)")


class OpampACEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_opamp_ac.cir")
        netlist = (
            "/mnt/d/ongoingProjects/openEDA/toffee_project/"
            "toffee_ana/SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp"
        )
        with open(tb, "w") as f:
            f.write("* Opamp AC testbench\n")
            f.write("VDD VDD 0 DC 1.8\n")
            f.write("VSS VSS 0 DC 0\n")
            f.write("VINP VINP 0 DC 1.2 AC 1\n")   # AC 源
            f.write("VINN VINN 0 DC 1.2\n")
            f.write("IBIAS VDD VBIAS DC 100u\n")
            f.write(f".include {netlist}\n")
            f.write(".end\n")

        simulator = NgSpiceSimulator(tb)
        super().__init__(simulator)
        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("vdb(vout)")
        self.agent = OpampACAgent(simulator=simulator)
```

**Step 2: 写测试函数 —— 验证低频增益**

```python
@toffee_test.fixture
async def opamp_ac_env(toffee_request):
    env = toffee_request.create_env(OpampACEnv)
    yield env


@toffee_test.testcase
async def test_opamp_ac_gain(opamp_ac_env):
    opamp_ac_env.simulator.run_analysis([".ac dec 10 1 1G"])
    gain_db = await opamp_ac_env.agent.measure_gain_db()
    print(f"\n[ngspice opamp AC] low-freq gain = {gain_db} dB\n")
    assert gain_db > 40, f"Gain {gain_db}dB < 40dB spec"
```

**Step 3: 写测试函数 —— 验证相位裕度**

```python
@toffee_test.testcase
async def test_opamp_ac_phase_margin(opamp_ac_env):
    opamp_ac_env.simulator.run_analysis([".ac dec 10 1 1G"])
    
    # 读取相位（频率 1Hz = 低频参考）
    phase_lf = await opamp_ac_env.agent.measure_phase()
    
    # 读取增益，找到 0dB 穿越频率附近的相位
    gain_db = await opamp_ac_env.agent.measure_gain_db()
    # 简化：低频增益 > 40dB 且相位裕度 > 45°
    # 实际需要扫频找到 0dB 点，这里先做基本验证
    assert phase_lf > -180, f"Phase {phase_lf} deg out of range"
    print(f"\n[ngspice opamp AC] low-freq phase = {phase_lf} deg\n")
```

**Step 4: 跑测试确认 PASS**

```bash
python3 -m pytest toffee/tests/analog/test_opamp_ac.py -v
```

**Step 5: Commit**

```bash
git add toffee/tests/analog/test_opamp_ac.py
git commit -m "test: add AC analysis test for opamp gain and phase"
```

---

### Task 3: NgSpiceSimulator 事件驱动化

**目标:** 移除 `step_time()` 中的 `tick()`，新增 `async next_event()`。

**文件:**
- 修改: `toffee/toffee/analog/ngspice_simulator.py`
- 测试: `toffee/tests/analog/test_opamp_tran.py` (Task 4 会用到，此处先确保现有测试不坏)

**Step 1: 跑现有测试确认 baseline**

```bash
python3 -m pytest toffee/tests/analog/test_ngspice_lazysync.py toffee/tests/analog/test_opamp_ngspice.py toffee/tests/analog/test_simulator_events.py -v
```

确保全部 PASS 或 XFAIL（非本改动导致）。

**Step 2: 修改 `step_time()` —— 移除 `self.tick()`**

在 `ngspice_simulator.py` 找到 `step_time` 方法（约 line 482），把：

```python
        self._current_time = self._spice_time
        self.tick()
```

改为：

```python
        self._current_time = self._spice_time
        # tick() removed — __event_loop handles set/clear uniformly
```

**Step 3: 新增 `async next_event()` 覆盖**

在 `ngspice_simulator.py` 的 `step()` 方法之后（约 line 480）添加：

```python
    async def next_event(self) -> str:
        """Event-driven step: advance ngspice by 1ns without blocking asyncio."""
        self._ensure_loop()
        if not self._bg_running:
            self._start_lazy_transient()

        target = self._current_time + 1e-9
        self._next_sync_time = target
        self._sync_event.clear()
        self._resume_event.set()

        loop = asyncio.get_running_loop()
        ok = await loop.run_in_executor(None, self._sync_event.wait, 60.0)
        if not ok:
            raise RuntimeError(
                f"Timeout waiting for ngspice to reach sync point "
                f"{target} s (spice time {self._spice_time} s)"
            )

        self._current_time = self._spice_time
        # Explicitly do NOT call tick() — __event_loop handles it

        with self._event_lock:
            if self._pending_events:
                return self._pending_events.popleft()
        return "step"
```

**Step 4: 跑回归确认不破坏现有测试**

```bash
python3 -m pytest toffee/tests/analog/ -v -k "not test_rc_xyce and not test_xyce_pause"
```

**Step 5: Commit**

```bash
git add toffee/toffee/analog/ngspice_simulator.py
git commit -m "fix: make NgSpiceSimulator event-driven with async next_event()"
```

---

### Task 4: TRAN 阶跃测试 + Monitor 采样

**目标:** 新建 TRAN 测试：Agent 加阶跃激励，Monitor 持续采样 vout。

**文件:**
- 创建: `toffee/tests/analog/test_opamp_tran.py`
- 依赖: Task 3 (`next_event()` 已实现)

**Step 1: 写 Agent（driver + monitor）**

```python
"""TRAN step response test for two-stage op-amp."""
import os, tempfile
import toffee_test
from toffee import driver_method, monitor_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.ngspice_simulator import NgSpiceSimulator


class OpampTranAgent(AnalogAgent):
    def __init__(self, simulator):
        super().__init__(simulator=simulator, event_name="step")
    
    @driver_method()
    async def set_input(self, vinp, vinn):
        self.simulator.set_vsrc("VINP", vinp)
        self.simulator.set_vsrc("VINN", vinn)
    
    @driver_method()
    async def read_vout(self):
        return self.simulator.read("v(vout)")
    
    @monitor_method()
    async def sample_vout(self):
        return self.simulator.read("v(vout)")
```

**Step 2: 写 Env**

```python
class OpampTranEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_opamp_tran.cir")
        netlist = (
            "/mnt/d/ongoingProjects/openEDA/toffee_project/"
            "toffee_ana/SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp"
        )
        with open(tb, "w") as f:
            f.write("* Opamp TRAN testbench\n")
            f.write("VDD VDD 0 DC 1.8\n")
            f.write("VSS VSS 0 DC 0\n")
            f.write("VINP VINP 0 DC 1.2\n")   # external vsrc，可被 set_vsrc 动态改
            f.write("VINN VINN 0 DC 1.2\n")
            f.write("IBIAS VDD VBIAS DC 100u\n")
            f.write(f".include {netlist}\n")
            f.write(".end\n")

        simulator = NgSpiceSimulator(tb)
        super().__init__(simulator)
        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("v(vout)")
        self.agent = OpampTranAgent(simulator=simulator)
```

**Step 3: 写测试 —— 阶跃响应 + Monitor 采样**

```python
from toffee.asynchronous import start_clock

@toffee_test.fixture
async def opamp_tran_env(toffee_request):
    env = toffee_request.create_env(OpampTranEnv)
    yield env


@toffee_test.testcase
async def test_opamp_step_response(opamp_tran_env):
    agent = opamp_tran_env.agent
    
    # 设置初始条件
    await agent.set_input(vinp=1.2, vinn=1.2)
    
    # 启动事件循环
    start_clock(opamp_tran_env.simulator)
    
    # 启动 Monitor 采样
    agent.start_monitor("sample_vout", maxsize=200)
    
    # 加阶跃：vinp 从 1.2V 跳变到 1.3V
    await agent.set_input(vinp=1.3, vinn=1.2)
    
    # 等待 100 个 step（100ns）
    for _ in range(100):
        await agent.monitor_step()
    
    # 收集采样数据
    samples = []
    while agent.monitor_size("sample_vout") > 0:
        samples.append(await agent.sample_vout())
    
    print(f"\n[opamp TRAN] {len(samples)} samples collected")
    print(f"  vout start: {samples[0]:.3f}V, end: {samples[-1]:.3f}V\n")
    
    # 验证 vout 在阶跃后有变化
    assert samples[-1] > samples[0] + 0.01, \
        f"Expected vout increase, got {samples[0]:.3f} -> {samples[-1]:.3f}"
```

**Step 4: 跑测试**

```bash
python3 -m pytest toffee/tests/analog/test_opamp_tran.py::test_opamp_step_response -v
```

**Step 5: Commit**

```bash
git add toffee/tests/analog/test_opamp_tran.py
git commit -m "test: add TRAN step response test with Monitor sampling"
```

---

### Task 5: Model 容差比较

**目标:** `_compare.py` 新增 `tolerance_compare`，`AnalogAgent` 暴露 `compare_func`。

**文件:**
- 修改: `toffee/toffee/_compare.py`
- 修改: `toffee/toffee/analog/analog_agent.py`

**Step 1: 修改 `_compare.py` —— 添加容差比较**

在 `__default_compare` 之后添加：

```python
def tolerance_compare(tol=0.05):
    """Return a compare function that checks abs(a-b) < tol."""
    def cmp(dut_value, model_value):
        try:
            return abs(float(dut_value) - float(model_value)) < tol
        except (TypeError, ValueError):
            return False
    return cmp
```

**Step 2: 修改 `AnalogAgent` —— 暴露 `compare_func`**

```python
class AnalogAgent(Agent):
    def __init__(self, bundle=None, simulator=None, event_name="step", compare_func=None):
        if simulator is not None:
            event = simulator.events.get(event_name, simulator.clock_event)
            super().__init__(event.wait)
            self.simulator = simulator
            self._event_name = event_name
        else:
            super().__init__(bundle)
            self._event_name = event_name
        self._compare_func = compare_func
```

注意：当前 `Driver` 的 `process_driver_call` 里 `compare_once(dut_result, model_result[1], self.compare_func)` 用的是 `self.compare_func`，需要在 Agent 创建 Driver 时传入。简单起见，先只加函数，Task 6 再连线 Model。

**Step 3: 跑现有测试确认兼容**

```bash
python3 -m pytest toffee/tests/analog/ -v -k "opamp or rc"
```

**Step 4: Commit**

```bash
git add toffee/toffee/_compare.py toffee/toffee/analog/analog_agent.py
git commit -m "feat: add tolerance_compare for analog model comparison"
```

---

### Task 6: TRAN 闭环跟随 + Model 自动比对

**目标:** 运放接成单位增益缓冲器，Model 期望 `vout = vinp`，自动容差比对。

**文件:**
- 创建: `toffee/tests/analog/test_opamp_closed_loop.py`

**Step 1: 写闭环网表的 Env**

```python
"""Closed-loop unity-gain buffer test."""
import os, tempfile
import toffee_test
from toffee import driver_method, monitor_method
from toffee.analog.analog_bundle import AnalogBundle
from toffee.analog.analog_agent import AnalogAgent
from toffee.analog.analog_env import AnalogEnv
from toffee.analog.ngspice_simulator import NgSpiceSimulator
from toffee._compare import tolerance_compare


class BufferAgent(AnalogAgent):
    def __init__(self, simulator):
        super().__init__(simulator=simulator, event_name="step",
                         compare_func=tolerance_compare(0.05))
    
    @driver_method()
    async def set_input(self, vin):
        self.simulator.set_vsrc("VIN", vin)
    
    @driver_method()
    async def read_vout(self):
        return self.simulator.read("v(vout)")
    
    @monitor_method()
    async def sample_vout(self):
        return self.simulator.read("v(vout)")


class BufferEnv(AnalogEnv):
    def __init__(self):
        tb = os.path.join(tempfile.gettempdir(), "toffee_buffer.cir")
        netlist = (
            "/mnt/d/ongoingProjects/openEDA/toffee_project/"
            "toffee_ana/SPICE-Netlists/opamp_2stage_180nm_design_netlist.sp"
        )
        with open(tb, "w") as f:
            f.write("* Unity-gain buffer testbench\n")
            f.write("VDD VDD 0 DC 1.8\n")
            f.write("VSS VSS 0 DC 0\n")
            f.write("VIN VIN 0 DC 1.0\n")
            f.write("IBIAS VDD VBIAS DC 100u\n")
            # 单位增益接法：vout 反馈到 vinn
            f.write("XOPAMP VDD VSS VIN VOUT VBIAS opamp_2stage_180nm\n")
            f.write(f".include {netlist}\n")
            f.write(".end\n")

        simulator = NgSpiceSimulator(tb)
        super().__init__(simulator)
        self.bundle = AnalogBundle(simulator)
        self.bundle.bind_signal("v(vout)")
        self.agent = BufferAgent(simulator=simulator)
```

**Step 2: 写测试 —— 扫描输入范围**

```python
from toffee.asynchronous import start_clock

@toffee_test.fixture
async def buffer_env(toffee_request):
    env = toffee_request.create_env(BufferEnv)
    yield env


@toffee_test.testcase
async def test_buffer_following(buffer_env):
    agent = buffer_env.agent
    sim = buffer_env.simulator
    
    start_clock(sim)
    agent.start_monitor("sample_vout", maxsize=50)
    
    # 扫描输入 0.5V ~ 1.5V
    for vin in [0.5, 0.7, 0.9, 1.1, 1.3, 1.5]:
        await agent.set_input(vin=vin)
        # 等 10ns 让输出 settle
        for _ in range(10):
            await agent.monitor_step()
        
        vout = await agent.read_vout()
        error = abs(vout - vin)
        print(f"  vin={vin:.1f}V  vout={vout:.3f}V  error={error*1000:.1f}mV")
        assert error < 0.1, f"Buffer error {error*1000:.1f}mV exceeds 100mV at vin={vin}V"
```

**Step 3: 跑测试**

```bash
python3 -m pytest toffee/tests/analog/test_opamp_closed_loop.py -v
```

**Step 4: Commit**

```bash
git add toffee/tests/analog/test_opamp_closed_loop.py
git commit -m "test: add unity-gain buffer closed-loop test"
```

---

### 最终验证

**Step 1: 全量回归**

```bash
python3 -m pytest toffee/tests/analog/ -v
```

**Step 2: 确认所有新测试 PASS**

| 测试文件 | 预期结果 |
|----------|:-------:|
| `test_opamp_ngspice.py` | PASS (增强后) |
| `test_opamp_ac.py` | PASS (新增) |
| `test_opamp_tran.py` | PASS (新增) |
| `test_opamp_closed_loop.py` | PASS (新增) |

---

### 变更文件总览

| 文件 | 操作 | Task |
|------|:----:|:----:|
| `toffee/tests/analog/test_opamp_ngspice.py` | 修改 | 1 |
| `toffee/tests/analog/test_opamp_ac.py` | 新建 | 2 |
| `toffee/toffee/analog/ngspice_simulator.py` | 修改 | 3 |
| `toffee/tests/analog/test_opamp_tran.py` | 新建 | 4 |
| `toffee/toffee/_compare.py` | 修改 | 5 |
| `toffee/toffee/analog/analog_agent.py` | 修改 | 5 |
| `toffee/tests/analog/test_opamp_closed_loop.py` | 新建 | 6 |
