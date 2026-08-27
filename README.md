# AEH Change Lens

> 状态：已授权实施；`CL-GATE-00` 已通过，`CL-WP-01` 可以开始。
> Status: implementation authorized; `CL-GATE-00` passed and `CL-WP-01` is ready.

## 中文

AEH Change Lens 是一个只读的代码变更解释工具。它把一次 AI 辅助修改展示为：

```text
原逻辑链路 -> 结构化变化 -> 新逻辑链路
                 |
                 +-> 需求、证据、测试、验证与不确定性
```

它不尝试读取或还原模型隐藏的思维链，而是展示能够被代码、Git、AEH 工件和测试结果支持的修改依据。

首个版本的已确认默认项：

- 首发产品语言和界面为中文，保留英文方案文档；
- 独立于 AEH 的仓库，采用 Python 编排层 + .NET/Roslyn 分析 Worker；
- 首发分析语言为 C#，主要面向 Unity/游戏业务代码；
- 默认完全离线、确定性分析；
- LLM 解释仅在用户显式启用时使用；
- 目标用户为代码修改者和 Reviewer；
- 使用 10–20 个人工标注 Change 做试点；
- Change Lens 永远不修改 AEH 的 Gate、审批或机器真值。

详细方案：

- [中文实施方案](docs/IMPLEMENTATION_PLAN.zh-CN.md)
- [English implementation plan](docs/IMPLEMENTATION_PLAN.en.md)
- [机器可读治理契约](governance/proposal.yaml)

当前 Gate：

```text
PLAN_READY
IMPLEMENTATION_AUTHORIZATION_GRANTED
CL-GATE-00_PASSED
CL-WP-01_READY
RELEASE_NOT_ASSESSED
```

## English

AEH Change Lens is a read-only code-change explanation tool. It presents an AI-assisted modification as an evidence-linked transition from the old logic path to the new logic path.

It does not claim to expose hidden model chain of thought. It explains only rationale supported by source, Git history, AEH artifacts, tests, runtime observations, or clearly labeled inference.

Confirmed defaults for the first version:

- Chinese as the launch product/UI language, with English plan documentation;
- a repository separate from AEH, with Python orchestration and a .NET/Roslyn analyzer worker;
- C# as the first analyzed language, focused on Unity/gameplay code;
- deterministic offline analysis by default;
- optional LLM explanation only after explicit enablement;
- change authors and reviewers as the primary users;
- a pilot corpus of 10–20 manually annotated Changes;
- no mutation of AEH Gates, approvals, or normative machine truth.

Implementation was explicitly authorized on 2026-08-27. Work proceeds one governed
work package at a time; no release claim has been made.

## License

MIT. See [LICENSE](LICENSE).
