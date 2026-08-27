# AEH Change Lens 实施方案

> 文档语言：中文（权威版本）
> 状态：`PLAN_READY / IMPLEMENTATION_AUTHORIZATION_NOT_GRANTED`
> 对应英文版：[IMPLEMENTATION_PLAN.en.md](IMPLEMENTATION_PLAN.en.md)
> 机器契约：[proposal.yaml](../governance/proposal.yaml)

## 1. 产品结果

对于一个明确的 AEH Change，Reviewer 不阅读完整 Diff 也应能回答：

1. 修改前的关键逻辑链路是什么；
2. 修改后的关键逻辑链路是什么；
3. 哪些节点或关系被新增、删除、移动、替换；
4. 每项关键修改由什么需求或证据支持；
5. 哪些测试验证了新链路，还有哪些未知项。

产品表达式：

```text
Git 前后版本
  + 语法/符号关系
  + AEH REQ -> AC -> EV -> TEST -> CODE -> VER
  + 可选运行时观测
  = 有来源、有置信度的原链路 -> 新链路解释
```

## 2. 已确认的 Owner 决策

| ID | 决策 |
|---|---|
| CL-DEC-001 | 首发分析语言为 C#，主要场景为 Unity/游戏业务代码 |
| CL-DEC-002 | 使用独立仓库；Python 负责 CLI/编排，.NET/Roslyn Worker 负责 C# 语义分析 |
| CL-DEC-003 | 默认离线确定性分析，LLM 解释只能显式启用 |
| CL-DEC-004 | 主要用户为代码修改者与 Reviewer |
| CL-DEC-005 | 使用 10–20 个人工标注 Change 作为试点 |
| CL-DEC-006 | 首发产品和 UI 为中文；中文方案权威，英文方案作为对应文档保留 |

这些决策使计划具备可执行性，但不等于已经授权修改代码或发布产品。

## 3. MVP 边界

### 3.1 包含

- 单个本地 Git 仓库；
- 单个显式 `CHG-*`；
- base commit 与 worktree/目标 commit 对比；
- Unity 项目中的 C# 文件、`.asmdef` 和可读取的项目编译上下文；
- 变更符号及最多一层调用上下游；
- 函数、方法、关键条件、return/raise 和已配置副作用；
- AST 级新增、删除、更新、移动映射；
- AEH 需求、证据、测试、代码和验证引用；
- 确定性 `explain-bundle.json`；
- 本地只读 Web UI 与静态 HTML 导出；
- 首发中文 UI；英文方案文档保留，英文 UI 不作为 MVP Gate；
- 明确的来源、置信度、未知项和失效状态。

### 3.2 不包含

- 全仓库知识图谱；
- 多语言首发；
- 隐藏思维链采集或还原；
- 自动批准或修改 AEH Gate；
- 默认联网、遥测或源代码上传；
- 完整处理反射、动态注入、生成代码和任意跨服务链路；
- 多 Agent 编排；
- 自动宣称推断出的业务关系为事实。

## 4. 信任模型

Change Lens 是投影层，不是新的事实所有者。

| 数据 | 权威来源 | 展示等级 |
|---|---|---|
| Revision 和源码字节 | Git/工作树 | `SOURCE_BOUND` |
| AEH 状态和 Gate | AEH 工件 | `AEH_BOUND` |
| 编译器/索引器符号关系 | Roslyn C# 语义分析 | `CONFIRMED_STATIC` |
| AST 结构 | Tree-sitter/Python AST | `STRUCTURAL` |
| 实际运行路径 | 获授权的运行时证据 | `OBSERVED_RUNTIME` |
| 规则或 LLM 解释 | 派生结果 | `INFERRED` |
| 无法确定 | 无 | `UNKNOWN` |

基本原则：较弱证据可以降级已有结论；没有更强来源时不能升级置信度。

## 5. 系统结构

```text
Snapshot Resolver
  读取 Git 对象，不 checkout，不执行项目代码
        |
C#/Unity Language Adapter
  Roslyn AST/符号/调用 + Unity 程序集与生命周期关系
        |
Semantic Differ
  old/new 节点映射与图变化
        |
AEH Evidence Linker
  REQ/AC/EV/TEST/CODE/VER + digest
        |
Explain Bundle Builder
  确定性 JSON + provenance + confidence
        |
Local Viewer / Static Export
  原链路 | 新链路 | 修改依据 | 验证 | 未知项
```

建议目录：

```text
src/aeh_change_lens/
  snapshot/
  languages/csharp/
  semantic_diff/
  evidence/
  explain/
  bundle/
  server/
ui/
schemas/
tests/
  contract/
  golden/
  adversarial/
  e2e/
```

技术依据：Roslyn 同时提供语法树、符号表和 SemanticModel，适合作为 C# confirmed-static 关系的权威分析层；Unity 的 `.asmdef`、平台 define、编译引用和 `CompilationPipeline` 决定实际程序集边界；MonoBehaviour 事件函数属于 Unity 框架调度，不能伪装成源码中的普通直接调用。参考 [Roslyn Compiler API Model](https://learn.microsoft.com/en-us/dotnet/csharp/roslyn-sdk/compiler-api-model)、[Unity Assembly Definitions](https://docs.unity3d.com/Manual/assembly-definitions.html) 和 [Unity Event Function Execution Order](https://docs.unity3d.com/Manual/execution-order.html)。

## 6. 核心数据契约

每个图节点至少包含：

```yaml
node_id: csharp:RewardService.cs:RewardService.Claim
kind: method
change: UPDATED
old_location:
  path: Assets/Scripts/RewardService.cs
  start_line: 40
  end_line: 66
  content_hash: sha256...
new_location:
  path: Assets/Scripts/RewardService.cs
  start_line: 42
  end_line: 73
  content_hash: sha256...
provenance:
  origin: roslyn_unity_adapter
  confidence: CONFIRMED_STATIC
links:
  requirements: [REQ-002]
  evidence: [EV-004]
  tests: [TEST-004]
```

每条边至少包含来源、关系、变化类型和置信度。每项解释必须引用已有 ID，或者标记为 `INFERRED/UNLINKED`。

Bundle 必须记录：

- base/target revision；
- dirty worktree manifest；
- AEH 工件 SHA-256；
- analyzer 及配置版本；
- 节点、边、old/new 映射；
- 限制和未知项；
- canonical bundle digest；
- UI 语言不影响的语义内容。

## 7. 工作包和退出 Gate

### CL-WP-00 契约与试点冻结

产出：Bundle Schema、Python Adapter Contract、人工标注样本、隐私/导出策略。

`CL-GATE-00`：所有 P0 都有测试 Oracle；样本覆盖增删改移、改名、分支、异常、副作用、动态调用和 stale；依赖许可证已审查。

### CL-WP-01 Snapshot Resolver

产出：Git 对象读取、worktree manifest、rename 映射、digest、路径安全和 stale 判定。

`CL-GATE-01`：不 checkout、不执行项目代码；路径穿越和 symlink/reparse escape 阻断；输入变化必定 stale。

### CL-WP-02 C#/Unity Language Adapter

产出：程序集、类型、方法、调用、分支、异常和副作用节点；解析 `.asmdef`、平台/define 条件和 Unity 编译引用；识别 MonoBehaviour 生命周期、Coroutine、`async/await`、delegate/event/UnityEvent、序列化引用及常见组件访问关系；提供能力矩阵和限制。

`CL-GATE-02`：Golden Graph 与人工标注一致；Roslyn SemanticModel 可用时才把跨文件符号关系标为 confirmed；缺少 Unity 程序集、条件编译分支或工程上下文时返回显式 partial；反射、字符串消息、UnityEvent Inspector 绑定和动态调用不冒充 confirmed。

### CL-WP-03 Semantic Differ

产出：`ADDED/REMOVED/UPDATED/MOVED/UNCHANGED_CONTEXT`；歧义记录。

`CL-GATE-03`：人工样本测量映射准确性；可识别的移动/改名不退化成误导性删除新增；歧义不静默选择。

### CL-WP-04 AEH Evidence Linker 与 Bundle

产出：只读 AEH 适配器、ID 关联、Schema 校验、canonical serialization。

`CL-GATE-04`：重复生成一致；伪造、缺失、stale 引用 fail closed；AEH 受保护文件前后 digest 不变。

### CL-WP-05 Evidence-constrained Explanation

产出：确定性模板解释、可选 LLM Adapter、引用校验和 unsupported-claim 检查。

`CL-GATE-05`：每项关键陈述可引用或标记推断；源码注释的 prompt injection 不能改变权限和置信度；禁用 LLM 仍可完整使用。

### CL-WP-06 中文 Viewer 与导出

产出：同步 old/new lane、证据详情、中文首发界面和静态导出；英文 UI 保留为后续能力，不阻塞 MVP。

`CL-GATE-06`：不用颜色也能区分变化；键盘可用；离线模式无网络请求；中文术语与事实 Bundle 一致。

### CL-WP-07 Pilot 决策

产出：节点/边/映射准确性、Reviewer 任务成功率与耗时、性能和隐私报告。

`CL-GATE-07`：给出 `CONTINUE/REPOSITION/STOP`，不得只凭“图已画出”宣称成功。

## 8. P0 验收条件

- `CL-AC-001`：输入、版本、工具和配置完整绑定，确定性输出。
- `CL-AC-002`：任一绑定输入变化后旧报告显示 `STALE`。
- `CL-AC-003`：old/new 位置和变化类型绝不混淆。
- `CL-AC-004`：关键节点、边、解释和验证均有来源与置信度。
- `CL-AC-005`：不能写 AEH 机器真值、审批或 Gate。
- `CL-AC-006`：不声称展示隐藏思维链。
- `CL-AC-007`：默认图限定为 Change 子图。
- `CL-AC-008`：关键修改必须证据关联或明确 `UNLINKED`。
- `CL-AC-009`：缺失、非法、越界、不支持和无法解析均显式阻断或 partial。
- `CL-AC-010`：试点 Reviewer 能回答五个产品问题。
- `CL-AC-011`：首发 UI 为中文；英文方案文档与中文权威方案不产生事实冲突，未来英文 UI 必须复用同一 Bundle。
- `CL-AC-012`：Unity 程序集、生命周期和平台条件进入分析来源；上下文不完整时不得输出完整可信链路。

## 9. 不变量

- `CL-INV-001`：Projection 永远不成为 AEH normative truth。
- `CL-INV-002`：old/new revision 永远分离。
- `CL-INV-003`：没有更强来源不能提高置信度。
- `CL-INV-004`：未分析到不等于关系不存在。
- `CL-INV-005`：LLM 不能创建 confirmed fact 或 approval。
- `CL-INV-006`：源码位置必须绑定 revision 和 digest。
- `CL-INV-007`：静态 MVP 不执行项目代码。
- `CL-INV-008`：运行时观测必须显式授权并与静态推断分层。
- `CL-INV-009`：本地读取拒绝 path/symlink/reparse escape。
- `CL-INV-010`：导出遵循明确的源码披露策略。
- `CL-INV-011`：翻译层不能增加、删除或改变事实结论。
- `CL-INV-012`：Unity 生命周期约定不能被当作普通直接调用；必须标记为框架调度关系。
- `CL-INV-013`：缺失 `.asmdef`、define、Unity 引用或生成工程上下文时，语义分析必须降级并披露限制。

## 10. 主要风险

| ID | 风险 | 缓解 |
|---|---|---|
| CL-RISK-001 | 推断被用户当成事实 | 边级 provenance/confidence，未知优先展示 |
| CL-RISK-002 | 图爆炸 | Change slice、hop budget、折叠上下文 |
| CL-RISK-003 | 报告过期 | digest 与强制 STALE |
| CL-RISK-004 | 扩大 AEH TCB | 独立包、只读接口、受保护文件 manifest |
| CL-RISK-005 | 源码泄露 | 离线默认、显式导出、限制片段 |
| CL-RISK-006 | Prompt injection | 仓库文本一律视为数据，输出 Schema 和引用校验 |
| CL-RISK-007 | Unity 动态绑定和框架调度误判 | Roslyn + Unity 规则层、partial/unknown、可选运行时证据 |
| CL-RISK-008 | 第三方许可证冲突 | WP-00 许可证审查、外部 Adapter 隔离 |
| CL-RISK-009 | 图正确但没有产品价值 | 对照试点和停止 Gate |
| CL-RISK-010 | 中英文事实漂移 | 单一 Bundle、术语表、双语一致性测试 |
| CL-RISK-011 | Unity 编译上下文不完整 | 读取 `.asmdef`、define 和引用清单；缺失时禁止完整结论 |
| CL-RISK-012 | 生命周期/Coroutine/事件链被画成普通调用 | 使用专用边类型和框架调度 provenance |

## 11. 防偏移规则

每个实现 PR 必须：

1. 只声明一个主 `CL-WP-*`；
2. 列出涉及的 `CL-AC-*`、`CL-INV-*` 和 `CL-RISK-*`；
3. 提供退出 Gate 的原始证据；
4. 声明是否改变范围、信任边界、外部数据流、依赖或置信度；
5. 不把后续工作包能力顺手带入；
6. 改变治理字段时同步修改中英文方案和 YAML；
7. 新增超范围能力前取得 Owner 决策；
8. Gate 未通过时不得宣称完成。

以下变化必须新增决策记录：目标用户、范围、写入权限、置信度语义、P0、不变量、工作包顺序、隐私默认、首发语言和交付拓扑。

## 12. 开工条件

当前状态：

```text
PLAN_READY
IMPLEMENTATION_AUTHORIZATION_NOT_GRANTED
RELEASE_NOT_ASSESSED
```

只有 Owner 明确授权开始实现后才能进入 `CL-WP-00`。实现授权不自动允许执行目标项目代码、上传源码、运行非隔离测试或修改 AEH 仓库。
