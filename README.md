# AEH Change Lens

> 状态：方案已冻结，尚未授权开始实现。
> Status: plan frozen; implementation has not been authorized.

## 中文

AEH Change Lens 是一个只读的代码变更解释工具。它把一次 AI 辅助修改展示为：

```text
原逻辑链路 -> 结构化变化 -> 新逻辑链路
                 |
                 +-> 需求、证据、测试、验证与不确定性
```

它不尝试读取或还原模型隐藏的思维链，而是展示能够被代码、Git、AEH 工件和测试结果支持的修改依据。

首个版本的已确认默认项：

- 文档和界面双语，中文优先；
- 独立于 AEH 的仓库和 Python 包；
- 首发语言为 Python；
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
IMPLEMENTATION_AUTHORIZATION_NOT_GRANTED
RELEASE_NOT_ASSESSED
```

## English

AEH Change Lens is a read-only code-change explanation tool. It presents an AI-assisted modification as an evidence-linked transition from the old logic path to the new logic path.

It does not claim to expose hidden model chain of thought. It explains only rationale supported by source, Git history, AEH artifacts, tests, runtime observations, or clearly labeled inference.

Confirmed defaults for the first version:

- bilingual product and documentation, Chinese first;
- a repository and Python package separate from AEH;
- Python as the first analyzed language;
- deterministic offline analysis by default;
- optional LLM explanation only after explicit enablement;
- change authors and reviewers as the primary users;
- a pilot corpus of 10–20 manually annotated Changes;
- no mutation of AEH Gates, approvals, or normative machine truth.

This repository currently contains a plan, not an implementation or release claim.

## License

MIT. See [LICENSE](LICENSE).
