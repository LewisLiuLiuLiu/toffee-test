# Toffee 模拟 & 混合信号 — 项目追踪文档

> 最后更新: 2026-06-18
> 状态: Phase A/B/C 核心架构已完成；正在进行 E2E 清理与文档同步。Orchestrator 单元测试 32/32 PASS，Orchestrator E2E 4/4 PASS。
> 本文档是工作区唯一项目追踪文档，所有进展、问题、计划均记录于此。

---

## 目录

1. [项目背景与目标](#1-项目背景与目标)
2. [当前代码状态](#2-当前代码状态)
3. [架构分析](#3-架构分析)
4. [已识别问题清单](#4-已识别问题清单)
5. [开发路线图](#5-开发路线图)
6. [附录：已完成工作总结](#6-附录已完成工作总结)

---

## 1. 项目背景与目标

### 1.1 Toffee 核心理念

Toffee 是一个用**软件工程方法论做芯片验证**的框架。

- 数字电路 RTL 通过 Picker 编译成二进制 `.so` 文件
- Toffee 调用 `.so`，提供 Agent/Bundle/Monitor/Model 等类似 UVM 的验证抽象
- 核心优势：复用软件生态（AI、程序员、测试框架）到芯片验证

### 1.2 当前目标

将 Toffee 从**纯数字验证**拓展到**纯模拟验证**和**混合信号验证**。

**纯模拟验证**：模拟电路是 SPICE 网表，无法编译成 `.so`。直接以 ngspice / Xyce 为后端，套用 Toffee 的 Agent/Bundle/Monitor/Model 方法论。

**混合信号验证**：核心挑战是数模交互：
- D2A（数字→模拟）：数字输出 = 模拟输入，需要自动桥接。Xyce 用 YDAC/updateTimeVoltagePairs，ngspice 用 lazy sync。
- A2D（模拟→数字）：**模拟对数字是异步的**。ngspice 的 async trigger 可在任意时间点检测阈值穿越，这是事件驱动的关键。

---

## 2. 当前代码状态

### 2.1 已完成的模块

| 模块 | 文件 | 状态 | 说明 |
|------|------|:----:|------|
| Simulator ABC `events` + `next_event()` | `simulator.py` | OK | 事件驱动骨架已就位 |
| `__event_loop` | `asynchronous.py` | OK | 替代 `__clock_loop`，支持多事件，已连线到 `start_clock()` |
| PortMapping d2a/a2d | `port_mapping.py` | OK | `D2ASpec`, `D2AParamSpec`, `A2DSpec`，含 YADC 支持 + `has_a2d()` |
| MixedSignalOrchestrator | `mixed_signal_orchestrator.py` | **OK** | 事件驱动混合信号协调器。自动 A2D trigger 注册 + clock boundary 跟踪 + RefreshComb/Step 分发。同步 `advance_to()` / `step_time()` 保留作为 lockstep 后备 |
| MixedSignalBridge | `mixed_signal/bridge.py` | **OK** | 统一 D2A/A2D 桥接，支持 `set_source` / `set_source_waveform` 自适应 |
| NgSpiceSimulator 事件驱动化 | `ngspice_simulator.py` | **OK** | `async next_event(target_time=...)` 支持可变步长；async trigger 机制完整 |
| XyceSimulator 事件驱动化 | `xyce_simulator.py` | **OK** | `events` + `current_time` + `next_event()` 全部实现；`port_mapping` 参数支持 YDAC/YADC 自动注入；`read()` 透明返回 YADC 量化电压 |
| AnalogBackend ABC | `analog/analog_backend.py` | **OK** | 统一后端数据接口，替代原有 `hasattr` 探测 |
| AnalogAgent event 配置 | `analog_agent.py` | OK | 支持 `event_name` + `compare_func` 参数 |
| AnalogBundle / AnalogEnv | `analog_bundle.py`, `analog_env.py` | OK | 已实现和验证，TRAN 事件循环 + Monitor 链路跑通 |
| Model 容差比较 | `_compare.py` | **OK** | `tolerance_compare(tol)` 工厂函数已添加 |
| Bundle 混合信号集成 | `bundle.py` | OK | `bind()` 自动检测 `loop.global_clock_event`，支持 orchestrator |
| `toffee/analog/__init__.py` | `analog/__init__.py` | OK | 完整导出 |
| `toffee/mixed_signal/__init__.py` | `mixed_signal/__init__.py` | OK | 导出 `MixedSignalOrchestrator` + `PortMapping` + `MixedSignalEnv` |
| 纯模拟运放测试套件 | `tests/analog/test_opamp_*.py` | **OK** | 4 文件：DC + AC + TRAN + 闭环 |
| Orchestrator 单元测试 | `toffee-test/tests/mixed_signal/` | **OK** | 32 tests with mock analog/DUT + real ngspice |
| XyceSimulator 单元测试 | `tests/analog/test_xyce_*.py` | **OK** | events + next_event + portmapping (18 tests) |
| NgSpiceSimulator 单元测试 | `tests/analog/test_ngspice_*.py` | **OK** | async events + target_time + lazy sync |
| E2E orchestrator 测试 | `toffee-test/tests/e2e/test_orchestrator_e2e.py` | **OK** | RC + 运放比较器，ngspice + Xyce 双后端，事件驱动验证 |

### 2.2 正在清理 / 阻塞项

| 项目 | 说明 |
|------|------|
| `toffee-test/tests/e2e/` 旧 E2E 迁移 | **已完成** — `test_smoke.py`、`test_tt03_tempsensor.py`、`test_tt05_dac.py`、`test_sar_adc.py`、`sar_ctrl_dut.py` 已迁移到 `MixedSignalOrchestrator`；非 SKY130 E2E 全部 PASS |
| `toffee/tests/test_bundle.py` 回归 | **已解决** — 采用严格行为：缺失 signal 始终抛异常；docstring、文档、测试用例已同步 |
| Git working tree 整理 | `toffee/` 和 `toffee-test/` 均有大量未提交改动 |
| Xyce subprocess 隔离 (D1) | Xyce `abort()` 杀死 Python 进程，需进程隔离。设计未澄清。 |
| SKY130 精简模型库验证 (D2) | `sky130.lib.spice.tt.red` 未找到（`fixtures.reduced_model_lib()` 报错）；Xyce 解析 SKY130 `.lib` 仍触发 abort()。属于外部依赖问题。 |
| Xyce `setCircuitParameter` (P3-3) | Xyce 引擎限制：不重标记电导矩阵，D2A param 测试永久 XFAIL。 |

### 2.3 E2E 测试状态

| 层级 | 测试 | 状态 |
|:----:|------|:----:|
| Layer 0 | Orches. RC bidirectional | **PASS** (xyce + ngspice) |
| Layer 0 | Orches. opamp comparator | **PASS** (xyce + ngspice) |
| Layer 0 | RC smoke (D2A voltage, bidirectional, A2D inverter) | **PASS** (xyce + ngspice) |
| Layer 0 | D2A param gain | **XFAIL** (Xyce engine limitation) |
| Layer 1 | SAR ADC (full, midscale, picker) | **XFAIL/ABORT** (SKY130 .lib 解析导致 Xyce abort) |
| Layer 2 | TT05 DAC 3-bit monotonic | **XFAIL/ABORT** (SKY130 .lib 解析导致 Xyce abort) |
| Layer 3 | TT03 temp sensor (load only) | **FAIL** (缺少 `sky130.lib.spice.tt.red`) |

---

## 3. 架构分析

### 3.1 事件驱动架构 — 已落地

```
start_clock(orchestrator)
  └─► __event_loop ──► await orchestrator.next_event()
        ├── has_a2d() → analog leads (event-driven)
        │     ├── await analog.next_event(target_time=clock_boundary)
        │     │     ├── ngspice: async trigger 在穿越瞬间截停
        │     │     └── xyce: PAUSE breakpoint + YADC 检测穿越
        │     ├── "threshold_crossed" → A2D → RefreshComb → boundary 不变
        │     └── "step"/"clock_edge" → A2D → Step(1) → D2A → boundary += 1ns
        └── no a2d → digital leads (Step → D2A → step_time → A2D)
              └── events["step"].set()
```

### 3.2 Lockstep / 同步后备 — 通过 MixedSignalOrchestrator 提供

`MixedSignalSimulator` 已合并进 `MixedSignalOrchestrator` 并从代码库删除。需要同步 lockstep 推进的测试可直接使用：

```python
orch = MixedSignalOrchestrator(dut, analog, mapping, step_strategy=StepExactStrategy(max_step=1e-9))
orch.advance_to(5e-9)
```

`advance_to()` 内部会调用 `step_time()`，在有 A2D 时使用 `StepExactStrategy` 子步进 + `RefreshComb()`；无 A2D 时使用 `Step(1)`。

### 3.3 关键架构决策

| ADR | 内容 |
|-----|------|
| 0001 | 集中同步——bridge 在 `next_event()` 内部完成，event fire 时系统已同步 |
| 0002 | YADC 注入属于 XyceSimulator，不属于 Orchestrator。`read()` 是唯一抽象点 |
| 0003 | 三种执行模式：`start_clock()` 用于数字/混合信号，`start_callback_executor()` 用于纯模拟 |

---

## 4. 已识别问题清单

### P0 — 架构阻塞

| # | 问题 | 状态 |
|---|------|:----:|
| P0-1 | MixedSignalSimulator 锁步架构 | **已解决** — `MixedSignalOrchestrator` 提供事件驱动 + lockstep 双模式，`MixedSignalSimulator` 已删除 |
| P0-2 | 缺少 MixedSignalOrchestrator | **已解决** — `mixed_signal_orchestrator.py` 已实现 |

### P1 — 技术债务

| # | 问题 | 状态 |
|---|------|:----:|
| P1-1 | ~~Double-trigger 缺陷~~ | **已修复** — `NgSpiceSimulator.step_time()` 不再调用 `tick()` |
| P1-2 | ~~NgSpiceSimulator 未覆盖 `next_event()`~~ | **已修复** |
| P1-3 | XyceSimulator 缺少 `events` 属性 | **已修复** |
| P1-4 | Bundle 未集成到混合信号 | **已修复** |
| P1-5 | ~~Model 比较无容差~~ | **已修复** |
| P1-6 | `toffee-test` E2E 仍引用已删除的 `MixedSignalSimulator` | **已完成** |

### P2 — 代码质量

| # | 问题 | 状态 |
|---|------|:----:|
| P2-1 | ~~`MixedSignalSimulator` 访问私有 `_xyce`~~ | **已修复** — 通过 `AnalogBackend.read_adc_states()` 抽象 |
| P2-2 | `DigitalSimulator` 未显式声明 `events` | **已修复** |
| P2-3 | ~~无纯模拟 E2E 测试~~ | **已修复** |
| P2-4 | `bundle.py` 缺失 signal 改抛异常导致旧测试失败 | **已解决** — 采用严格行为，测试与文档已同步 |

### P3 — 外部依赖

| # | 问题 | 影响 |
|---|------|------|
| P3-1 | SKY130 `.lib` 解析导致 Xyce `abort()` | SAR ADC/TT05 测试 XFAIL |
| P3-2 | TT03 PEX 网表 DC >120s | 无法用于步进式 co-simulation |
| P3-3 | Xyce `setCircuitParameter` 不重标记电导矩阵 | D2A param 测试永久 XFAIL |

---

## 5. 开发路线图

### Phase A: 架构阻塞 ✅

- [x] **A1** — NgSpiceSimulator `async next_event()`
- [x] **A2** — MixedSignalOrchestrator 实现
- [x] **A3** — `MixedSignalSimulator` 合并进 Orchestrator 并删除旧文件
- [x] **A4** — XyceSimulator `events` 属性

### Phase B: 混合信号完善 ✅

- [x] **B1** — Orchestrator 集成 async trigger + PAUSE breakpoint
- [x] **B2** — Bundle 集成（`bind()` 自动 clock_event）
- [x] **B3** — 混合信号 E2E（RC + 运放，ngspice + Xyce 双后端）

### Phase C: 纯模拟验证 ✅

- [x] **C1** — 运放 DC + AC + TRAN + 闭环
- [x] **C2** — Model `tolerance_compare()`
- [x] **C3** — AnalogAgent + Monitor + AnalogBundle 链路

### Phase D: 外部依赖 / 清理

- [ ] **D1** — Xyce subprocess 隔离（方案已确定：自定义 report handler + try/catch）
- [x] ~~**D2**~~ — SKY130 精简模型库验证 — **BLOCKED**：BSIM4 binning 格式与 ngspice 42 不兼容，非 toffee 问题
- [x] **D3** — DigitalSimulator `events`
- [x] **D4** — `toffee-test` 旧 E2E 全面迁移到 `MixedSignalOrchestrator`（非 SKY130 测试全部 PASS）
- [x] **D5** — `bundle.py` 缺失 signal 行为与测试对齐（严格抛异常）
- [ ] **D6** — 整理并提交 `toffee/` 和 `toffee-test/` working tree

---

## 6. 附录：已完成工作总结

### 6.1 核心改动 (Phase A-C 早期)

| Commit | 文件 | 改动 |
|--------|------|------|
| c6ebbc1 | `test_opamp_ngspice.py` | 增强 DC 测试（M1 电流、vout 范围、vdsat） |
| 5892075 | `test_opamp_ac.py` | 新建 AC 测试（增益 / 相位裕度） |
| 8db15c6 | `ngspice_simulator.py` | **核心修复**：移除 `step_time()` 的 `tick()` + 新增 `async next_event()` |
| a333d31 | `test_opamp_tran.py` | 新建 TRAN 测试（阶跃响应 + Monitor 采样） |
| e8fe6dc | `_compare.py`, `analog_agent.py` | 新增 `tolerance_compare()` + `compare_func` 参数 |
| ad37d83 | `test_opamp_closed_loop.py` | 新建闭环缓冲器测试（feedback + 容差断言） |

### 6.2 2026-05-22 Session — Phase A/B 完成 + 混合信号事件驱动

| 变更 | 文件 | 说明 |
|------|------|------|
| Orchestrator 实现 | `mixed_signal_orchestrator.py` | A2D trigger 注册 + clock boundary 跟踪 + RefreshComb/Step 分发 + `_finished` 守卫 |
| MixedSignalBridge 提取 | `mixed_signal/bridge.py` | 统一 D2A/A2D 桥接逻辑，供 Orchestrator 复用 |
| MixedSignalSimulator 合并/删除 | `mixed_signal_simulator.py` | 功能并入 Orchestrator，旧文件删除 |
| Xyce D2A 波形修复 | `mixed_signal_orchestrator.py` + `bridge.py` | 同步 `advance_to()` 使用完整剩余时间窗口做 D2A，避免 Xyce `updateTimeVoltagePairs` 在短连续窗口间无法拼接值跳变 |
| DigitalSimulator 修复 | `digital_simulator.py` | 显式 `events` 属性 |
| Bundle 混合信号集成 | `bundle.py` | `bind()` 自动检测 `loop.global_clock_event` |
| NgSpiceSimulator | `ngspice_simulator.py` | `next_event()` 支持 `target_time` 参数；`current_time` 属性 |
| XyceSimulator 事件驱动 | `xyce_simulator.py` | `events` + `current_time` + `next_event()`；`port_mapping` YDAC/YADC 注入；`read()` 透明返回 YADC 量化电压 |
| Xyce C++ PAUSE breakpoint | `N_DEV_ADC.C` | ADC 状态变化时 push PAUSE breakpoint 到 `breakPointTimes` |
| Xyce C++ setPauseTime | `N_CIR_XyceCInterface.C/.h` | 新增 `xyce_setPauseTime` C API |
| 领域文档 | `CONTEXT.md`, `docs/adr/0001`, `docs/adr/0002` | Bridge read() 透明抽象；集中同步 ADR；YADC 注入 ADR |
| 单元测试 | `toffee-test/tests/mixed_signal/`, `toffee/tests/analog/` | Orchestrator 32 tests + XyceSimulator 18 tests + NgSpice 30 tests |
| E2E 测试 | `toffee-test/tests/e2e/test_orchestrator_e2e.py` | Orchestrator RC + 运放比较器，ngspice + Xyce 双后端（4 passed） |
| PRD + Issues | `.scratch/mixed-signal-event-driven/` | 3 PRDs + 8 issues |

### 6.3 E2E 测试文件清单

| 文件 | 说明 |
|------|------|
| `tests/e2e/conftest.py` | 环境检测，自动 skip |
| `tests/e2e/fixtures.py` | `analog_sim` fixture |
| `tests/e2e/sar_ctrl_dut.py` | Python FSM DUT 模型 |
| `tests/e2e/test_smoke.py` | RC D2A + bidirectional + inverter（已迁移到 Orchestrator，6 PASS / 1 XFAIL） |
| `tests/e2e/test_orchestrator_e2e.py` | Orchestrator RC + 运放比较器，ngspice + Xyce (4 PASS) |
| `tests/e2e/test_sar_adc.py` | SAR ADC（全部 XFAIL，SKY130；迁移到 Orchestrator 中） |
| `tests/e2e/test_tt05_dac.py` | TT05 DAC（XFAIL，SKY130；迁移到 Orchestrator 中） |
| `tests/e2e/test_tt03_tempsensor.py` | TT03 温度传感器（load only；迁移到 Orchestrator 中） |
| `tests/e2e/netlists/` | SPICE 网表 + SKY130 精简模型库 |

### 6.4 已知外部依赖版本

| 组件 | 版本/路径 |
|------|----------|
| Xyce | 7.11.0 DEVELOPMENT-202604201454 |
| ngspice | v36 (`/usr/bin/ngspice`，`libngspice.so`) |
| SKY130 PDK | `/mnt/d/ongoingProjects/layoutProjects/skywater-pdk/` |
| Picker | v0.9.0 |
| Verilator | `/usr/local/bin/verilator` |

---

> 本文档取代此前所有分散的文档。项目状态和计划以此为准。
