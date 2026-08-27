# Roslyn Worker 当前契约

> 中文权威版本；英文对应文档见 [ROSLYN_WORKER.en.md](ROSLYN_WORKER.en.md)。

本文件描述 `CL-WP-02` 的首个可运行纵切，不表示 `CL-GATE-02` 已通过。

## 已实现

- .NET 8 控制台 Worker，通过 stdin 或 `--input` 接收本地 JSON；
- Roslyn 5.9.0 语法树、Compilation 和 SemanticModel；
- 输入源码原始字节与 snapshot SHA-256 强绑定，转码后的 Worker 文本另有传输 SHA-256，路径必须是安全的 Git 风格相对路径；
- 输出符合 `analyzer-result.schema.json`；
- 类型、方法、条件、throw、return 和状态节点；
- `DIRECT_CALL`、`BRANCHES_TO`、`THROWS_FROM`、`RETURNS_FROM`、`READS_STATE`、`WRITES_STATE`；
- Unity 生命周期、UnityEvent、`[SerializeField]` 引用；
- `SendMessage` 显式输出 `DYNAMIC_DISPATCH_UNKNOWN / UNKNOWN`；
- 节点、边、位置、来源与置信度确定性排序。
- Unity Context Builder 读取 `.asmdef`、ProjectVersion、生成的 `.csproj`、define、Compile glob、ProjectReference 与 metadata HintPath；
- 递归构建程序集依赖图，并区分 `BOUND_UNVERIFIED`、`MISSING`、`OUTSIDE_UNITY_ROOT` 与 `ANALYZER_ONLY`；
- Worker Input Assembler 只读取 `SnapshotBinding` 中的源码，在装配前后复核 snapshot 与 Unity context；
- 源码编码严格识别 UTF-8、UTF-8 BOM、UTF-16 BOM 和 GB18030，不支持的编码 fail closed；
- `Library/ScriptAssemblies` 输出没有源码来源绑定时标为 `PROJECT_UNVERIFIED`，且不会进入 Worker metadata references；
- 按 Unity 规则判定 asmdef include/exclude platform 与 Define Constraints，`EXCLUDED` 程序集不能装配为 Worker 输入；
- 从快照绑定的 `ProjectVersion.txt` 与 `Packages/packages-lock.json` 求值 Version Defines；支持区间、精确版本和裸版本下限，非法或不可解析来源显式降为 `INVALID`/`UNKNOWN`；
- 输出 Coroutine 启动、yield、await、C# event/delegate 订阅与发布、常见组件查找关系；
- metadata DLL 在进入 Worker 前后均以 SHA-256 校验，symlink/reparse point 被拒绝；
- 真实 Unity metadata 中存在 `MonoBehaviour`、`UnityEventBase` 且上下文声明完整时，Unity 框架关系才允许升级为 `CONFIRMED_STATIC`。
- Python `AnalyzerGraphDiffer` 合并 OLD/NEW Worker 结果，输出稳定符号、唯一结构和人工提示三类映射，以及节点/边的新增、删除、更新、移动和不变标签；
- `graph-diff` CLI 输出受 `analyzer-diff.schema.json` 与 canonical digest 约束，歧义结构不会按行号猜测。

## 当前强制降级

使用受控 Unity stub 或缺少真实 metadata 时：

- 即使调用方声称上下文 `COMPLETE`，只要缺少 digest-bound `UnityEngine.CoreModule.dll` 或关键 Unity 符号，输出仍强制为 `PARTIAL`；
- Unity 生命周期、UnityEvent 和序列化引用最多为 `STRUCTURAL`；
- 普通 C# 内部调用在 Roslyn 唯一解析时可以是 `CONFIRMED_STATIC`；
- `SendMessage`、Inspector 绑定和其他动态目标不能升级为静态确认。

## `CL-GATE-02` 仍缺少

- 为 `Library/ScriptAssemblies` 输出建立可验证的源码、编译选项和产物来源绑定；
- 覆盖更多平台名称与非 registry 包版本变体；
- 补充状态别名、事件移除、Inspector 绑定与组件 API 变体；
- 将 Golden Change 从当前 1 套扩展到计划的 10–20 套；
- 为真实 Git 历史版本绑定各自的 Unity 生成上下文，形成端到端双快照命令；
- 能力矩阵、性能与更多 adversarial cases。

包版本已锁定在 `worker/ChangeLens.Analyzer/packages.lock.json`。Roslyn 包的官方来源为 [NuGet Gallery](https://www.nuget.org/packages/Microsoft.CodeAnalysis.CSharp/5.9.0)。

## ET6 只读试点

在 `D:\ares\project\ET6\Unity` 的 Unity 2020.3.26f1c1 项目上，Context Builder 已读取 `Unity.Model`：140 个 define、221 个 metadata reference（其中 69 个 Unity reference）、632 个 Compile source、5 个 ProjectReference 和 48 个锁定包。递归图包含 6 个程序集和 12 条依赖，6 个程序集均判定为当前 Editor 上适用；这些程序集没有 Version Define 条目。632 个源码全部从含 9,328 个所选文件的工作树快照装配，其中 UTF-8 336、UTF-8 BOM 273、GB18030 23。

真实 metadata 合成样本中的生命周期、UnityEvent、协程启动和组件查找边达到 `CONFIRMED_STATIC`。实际 632 文件静态分析得到 22,382 个节点、18,874 条边，其中 `READS_STATE=9994`、`WRITES_STATE=251`、`AWAITS=12`、`DIRECT_CALL=1268`；由于 4 个项目程序集产物尚无来源绑定并产生 51 条诊断，结果仍正确为 `PARTIAL`。

试点只读取项目和 Unity 安装目录；未 checkout、未启动 Unity、未编译或执行 ET6 项目代码。前后 Git status 均为 203 条，规范化内容 SHA-256 均为 `7c47c6fd1bce7f21375a4c965e6bcbb92ae937e765b84b30ea6af25432389228`。

## 第一套 OLD/NEW Golden Change

`fixtures/unity-minimal` 的 base/target 已分别通过真实 Worker 在内存中分析，并与人工标注逐项核对。冻结结果为 OLD 19 节点、NEW 25 节点、11 对映射、14 个新增节点、8 个移除节点、14 条新增边、8 条移除边和 8 对不变关系，canonical digest 为 `e3d40c21b0026a0e47f0ffc8d921d4350e3c4afcd3d9f98a44f71db575454155`。

`Claim -> TryClaim`、`CalculateBonus` 跨类型移动和 `Start -> Awake` 来自明确的人工 mapping hint，均未冒充静态符号确认。两个重复状态访问组无法唯一配对，保留为新增/删除并产生 limitation。

逐项覆盖与限制见 [C#/Unity 分析能力矩阵](CAPABILITY_MATRIX.zh-CN.md)。
