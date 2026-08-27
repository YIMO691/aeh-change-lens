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
- [C#/Unity 能力矩阵](docs/CAPABILITY_MATRIX.zh-CN.md)
- [C#/Unity capability matrix](docs/CAPABILITY_MATRIX.en.md)
- [OLD/NEW 图差异契约](docs/GRAPH_DIFF.zh-CN.md)
- [OLD/NEW graph diff contract](docs/GRAPH_DIFF.en.md)
- [机器可读治理契约](governance/proposal.yaml)

当前已实现的开发者入口：

```powershell
change-lens snapshot <repository-root> --base <commit> --target WORKTREE --pretty
change-lens unity-context <unity-project-root> --assembly <name> --graph --pretty
change-lens roslyn-input <repository-root> <unity-project-root> --assembly <name> --request-id <id>
change-lens graph-diff <old-result.json> <new-result.json> --mapping-hints <hints.json> --pretty
change-lens export-compile-manifest <repository-root> <unity-project-relative-path> --assembly <name> --pretty
change-lens analyze-change <repository-root> <unity-project-relative-path> --assembly <name> --base <commit> --target WORKTREE --request-id <id> --pretty
```

该命令只读取 Git 对象和工作树中的受支持源码，输出原/新版本的相对路径、对象 ID、逐文件 SHA-256、清单摘要和 rename 映射；不 checkout、不编译或执行目标项目代码。

Roslyn Worker 的当前纵切可以提取类型、方法、调用、分支、异常、返回、状态读写、生命周期、Coroutine/yield、async/await、C# event/delegate、UnityEvent、序列化引用、组件查找和动态未知关系。Unity Context Builder 已执行 asmdef 平台、Define Constraints 与 Version Defines 判定，并将 Unity 版本、锁定包版本、依赖和 metadata 纳入摘要绑定。`graph-diff` 已能将 OLD/NEW Worker 图映射为确定性的新增、删除、更新、移动与不变链路；稳定符号可静态确认，人工重命名提示和唯一结构映射保持较低置信度，歧义候选不猜测。程序集图会递归跟随 ProjectReference，但 `Library/ScriptAssemblies` 输出在缺少源码快照来源证明时保持 `PROJECT_UNVERIFIED`。`roslyn-input` 只从已绑定的 Git/工作树快照取源码字节，并在装配前后检查 stale；ET6/Unity 2020.3 的只读试点已覆盖 UTF-8、UTF-8 BOM 和 GB18030 历史源码。

`CL-GATE-02` 尚未通过：当前只有 1 套人工标注 Golden Change，尚未达到计划的 10–20 套；`ScriptAssemblies` 输出仍需建立可验证来源，状态读取仍不覆盖别名与运行时对象，事件移除和 Inspector 绑定尚未补齐；Viewer 也尚未实现。

`analyze-change` 要求 OLD 与 NEW snapshot 各自包含生成的 `<Assembly>.csproj`，或包含由 `export-compile-manifest` 预先导出并提交的 `.aeh-change-lens/compile-manifests/<Assembly>.json`。清单绑定 define、精确源码集合及语义哈希、metadata 文件名/哈希和 ProjectReference，不保存本机绝对 DLL 路径。源码变化后未重新导出会 fail closed；当前工作树 csproj 只能按文件名与 SHA-256 定位本机 DLL，不能向历史版本注入源码或编译选项。没有建立清单基线的旧提交仍不会被追溯猜测。

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

For Unity repositories that ignore generated csproj files,
`export-compile-manifest` creates a portable, committable baseline. Historical
analysis accepts that artifact only from the matching revision, rejects stale
source semantics, and never substitutes NEW compile options for OLD.

## License

MIT. See [LICENSE](LICENSE).
