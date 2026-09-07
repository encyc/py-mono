# pi-agent-core 移植注记

对应上游：[`@earendil-works/pi-agent-core`](https://github.com/earendil-works/pi/tree/main/packages/agent)（v0.85.1）

## 有意偏离上游

| 上游 | 本包 | 原因 |
|---|---|---|
| typebox 类型 | Pydantic v2 | 详见 pi-ai/PORTING.md |
| Promise / ReadableStream | asyncio + AsyncGenerator | 同上 |
| 标准日志 | stdlib `logging` | 不引入私有日志包 |
| storage 直接耦合 | 通过抽象接口，storage 为可选后端 | 保持 agent-core 与存储解耦 |

## cherry-pick

（暂无）

## v0.85.1 同步说明

- **``prepare_next_turn`` 时机对齐**（本端原已声明该钩子但从未接入）：移至
  turn_end 之后、**下一轮 turn_start 之前**执行，且仅当循环继续时调用；可返回
  ``{"context", "model", "thinkingLevel"}`` 替换下一轮状态（``"off"`` 清除
  reasoning）。准备期间（如压缩）排队的 steering 消息在下一轮注入前补拉。
- ``should_stop_after_turn`` 先于 ``prepare_next_turn`` 看到已完成轮次上下文。
- ``agent_loop_continue`` 路径补发首个 ``turn_start``（对齐上游两个入口均在
  runLoop 外发首个 turn_start）。
- 工具准备阶段（参数校验 + before 钩子）完成后若已取消，不再执行工具，产出
  ``"Operation aborted"`` 错误结果（覆盖并行批次内尚未轮到的调用）。
- skills：根目录普通 ``.md`` 文件必须带非空 ``description`` frontmatter 才算
  技能，否则静默跳过（不产生诊断）；``SKILL.md`` 照常报诊断。
- **未移植**（裁剪范围）：上游本轮 agent 包重写为 harness v3 / durable drive
  （storage-backed sessions、branches/lanes/values、runtime2、invocation context
  贯穿、``AgentTool.replay``、``BranchSummaryMessage.fromId`` 可空化、conformance/
  benchmark 测试设施、session JSONL v4 与 legacy v3 导入）——与本端精简树结构
  session/harness 不同构，继续维持既有偏离。
- 本包同步版本、上游引用与对 ``pi-ai>=0.85.1,<0.86`` 的依赖约束。

## v0.84.1 同步说明（破例同步 patch）

- ``should_stop_after_turn`` 钩子接入 ``_run_loop``（每轮 ``TurnEnd`` 后询问，返回真则终止），并在 ``Agent`` / ``AgentOptions`` 上公开。
- ``before_tool_call`` 返回 ``block + terminate`` 时，被 block 的工具调用可终止后续轮次。
- ``Agent.reset()`` 在活跃运行期间拒绝并抛错。
- 上游 harness v2（reducer / telemetry / JSONL codec / session 仓库化 / conformance）仍属裁剪范围，未追逐。
- 本包同步版本、上游引用与对 ``pi-ai>=0.84.1,<0.85`` 的依赖约束。

## v0.83.0 同步说明

- 上游 agent 包在本轮没有落入当前精简 Python runtime 的行为变更。
- 本包仅同步版本、上游引用和对 `pi-ai>=0.83.0,<0.84` 的依赖约束。

## v0.82.1 同步说明

- Compaction/summary 请求使用独立 routing session，并强制
  `cache_retention="none"`，避免污染主会话缓存。
- Agent tools 会将 `constrained_sampling` 透传到 pi-ai。
- 上游新增的 Harness execution tools 与本仓库 `pi-coding-agent` 工具集职责重叠；
  当前精简 Harness 尚未公开 `ExecutionEnv`/`toolContext`，因此未引入不完整兼容层。

## 待办

- [ ] agent-loop.ts（无状态循环引擎）
- [ ] agent.ts（有状态 Agent 封装）
- [ ] harness/（skills / session / compaction / system-prompt）
- [ ] proxy（修复旧版导入位置错误）
