# AEH Change Lens

> 状态：已授权实施；`CL-GATE-00`、`CL-GATE-01` 已通过，正在实施 `CL-WP-02`。
> Status: implementation authorized; `CL-GATE-00` and `CL-GATE-01` passed; `CL-WP-02` is active.

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

当前已实现的开发者入口：

```powershell
change-lens snapshot <repository-root> --base <commit> --target WORKTREE --pretty
```

该命令只读取 Git 对象和工作树中的受支持源码，输出原/新版本的相对路径、对象 ID、逐文件 SHA-256、清单摘要和 rename 映射；不 checkout、不编译或执行目标项目代码。

Roslyn Worker 的首个纵切已经能从内存源码提取类型、方法、调用、分支、异常、返回、状态写入、生命周期、UnityEvent、序列化引用和动态未知关系。它尚未加载真实 Unity 元数据程序集，因此会强制返回 `PARTIAL`，不构成 `CL-GATE-02` 完成声明；Viewer 也尚未实现。

当前 Gate：

```text
PLAN_READY
IMPLEMENTATION_AUTHORIZATION_GRANTED
CL-GATE-00_PASSED
CL-GATE-01_PASSED
CL-WP-02_IN_PROGRESS
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
