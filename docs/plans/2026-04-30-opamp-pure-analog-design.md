# 两级运放纯模拟验证 — 设计文档

> 日期: 2026-04-30
> 状态: 设计完成，待实现

---

## 1. 背景

Toffee 框架目前支持纯数字验证（Picker 编译 .so + Agent/Bundle/Monitor/Model 方法论）。目标是将同样的方法论拓展到纯模拟验证，用两级运放作为验证载体。

两级运放是模拟电路的基础模块，其验证覆盖了 DC 工作点、AC 频率响应、TRAN 瞬态响应——对应模拟验证的核心场景。

---

## 2. 设计目标

1. 在两级运放上跑通 toffee 完整方法论：Env → Bundle → Agent → driver_method / monitor_method → Model
2. NgSpiceSimulator 事件驱动化，使 TRAN 仿真能接入 `__event_loop`
3. Model 比较从数字的精确匹配升级为模拟的容差比较

---

## 3. 实现步骤与依赖

```
Part 1 (NgSpice 事件驱动)
  │
  ├──► 步骤1 — DC 测试完善 (无依赖，现在就能做)
  ├──► 步骤2 — AC 测试 (无依赖，现在就能做)
  │
  └──► 步骤3 — NgSpice next_event() 异步化 + 修复 double-trigger
         │
         ├──► 步骤4 — TRAN 阶跃 + Monitor 采样
         │
         └──► 步骤5 — _compare.py 容差比较
                │
                └──► 步骤6 — TRAN 闭环跟随 + Model 自动比对
```

### 3.1 步骤 1：DC 测试完善

**改动文件**: `toffee/tests/analog/test_opamp_dc.py`（增强现有 `test_opamp_ngspice.py`）

**内容**:
- 验证所有管子工作在饱和区（`vds > vdsat`）
- 验证 `vout` 在合理直流范围内（0.8V ~ 1.2V）
- 验证尾电流源正常工作

### 3.2 步骤 2：AC 测试

**改动文件**: `toffee/tests/analog/test_opamp_ac.py`（新建）

**内容**:
- 低频增益 > 40dB
- 相位裕度 > 45°
- 单位增益带宽 > 10MHz

### 3.3 步骤 3：NgSpiceSimulator 事件驱动化

**改动文件**: `toffee/toffee/analog/ngspice_simulator.py`

**改动**:
1. 移除 `step_time()` 中的 `self.tick()` 调用（避免 double-trigger）
2. 新增 `async next_event()` 覆盖，用 `run_in_executor` 包装 `threading.Event.wait()`

```python
async def next_event(self) -> str:
    if not self._bg_running:
        self._start_lazy_transient()
    target = self._current_time + 1e-9
    self._next_sync_time = target
    self._sync_event.clear()
    self._resume_event.set()

    loop = asyncio.get_running_loop()
    ok = await loop.run_in_executor(None, self._sync_event.wait, 60.0)
    if not ok:
        raise RuntimeError(...)

    self._current_time = self._spice_time
    # 不调 tick() —— 由 __event_loop 统一 set/clear

    with self._event_lock:
        if self._pending_events:
            return self._pending_events.popleft()
    return "step"
```

### 3.4 步骤 4：TRAN 阶跃测试 + Monitor

**改动文件**: `toffee/tests/analog/test_opamp_tran.py`（新建）

**内容**:
- `Agent.set_input()` → `set_vsrc("VINP", step_value)`
- `start_clock(simulator)` 启动事件循环
- `@monitor_method sample_vout()` 每 1ns 步进采样 `v(vout)`
- 验证 slew rate 和 settling time

### 3.5 步骤 5：Model 容差比较

**改动文件**: `toffee/toffee/_compare.py`、`toffee/toffee/analog/analog_agent.py`

**改动**:
- `_compare.py` 新增 `tolerance_compare(tol)` 工厂函数
- `AnalogAgent` 暴露 `compare_func` 参数

```python
# _compare.py
def tolerance_compare(tol=0.05):
    def cmp(dut, model):
        return abs(dut - model) < tol
    return cmp
```

### 3.6 步骤 6：TRAN 闭环跟随 + Model 自动比对

**改动文件**: `toffee/tests/analog/test_opamp_closed_loop.py`（新建）

**内容**:
- 运放接成单位增益缓冲器
- `Model.set_input()` 期望 `vout = vinp`
- `@driver_hook` 自动比对实际 vout 与理想值
- 扫描输入范围 0.3V ~ 1.5V

---

## 4. 测试覆盖总结

| # | 测试 | 分析方法论 | 事件循环 | 文件 |
|:--:|------|----------|:-------:|------|
| 1 | DC 工作点 | driver_method + 直接断言 | 否 | `test_opamp_dc.py` |
| 2 | AC 频率特性 | driver_method + 直接断言 | 否 | `test_opamp_ac.py` |
| 3 | NgSpice 事件驱动 | next_event 异步化 | 是 | (ngspice_simulator.py) |
| 4 | TRAN 阶跃 + Monitor | driver_method + monitor_method | 是 | `test_opamp_tran.py` |
| 5 | Model 容差比较 | driver_hook + tolerance | 是 | (_compare.py) |
| 6 | 闭环 + Model 比对 | driver_method + model_hook | 是 | `test_opamp_closed_loop.py` |

---

## 5. 不改动的文件

- `asynchronous.py` — `__event_loop` 已正确实现
- `simulator.py` — ABC 接口已正确
- `analog_bundle.py` — 无需改动
- `analog_env.py` — 无需改动
- `port_mapping.py` — 纯模拟不涉及
- `mixed_signal_orchestrator.py` / `mixed_signal/` — 纯模拟验证不直接涉及混合信号桥接模块
