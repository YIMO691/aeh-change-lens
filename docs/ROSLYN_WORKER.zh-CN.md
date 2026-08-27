# Roslyn Worker 当前契约

> 中文权威版本；英文对应文档见 [ROSLYN_WORKER.en.md](ROSLYN_WORKER.en.md)。

本文件描述 `CL-WP-02` 的首个可运行纵切，不表示 `CL-GATE-02` 已通过。

## 已实现

- .NET 8 控制台 Worker，通过 stdin 或 `--input` 接收本地 JSON；
- Roslyn 5.9.0 语法树、Compilation 和 SemanticModel；
- 输入源码原始字节与 snapshot SHA-256 强绑定，转码后的 Worker 文本另有传输 SHA-256，路径必须是安全的 Git 风格相对路径；
- 输出符合 `analyzer-result.schema.json`；
- 类型、方法、条件、throw、return 和状态节点；
- `DIRECT_CALL`、`BRANCHES_TO`、`THROWS_FROM`、`RETURNS_FROM`、`WRITES_STATE`；
- Unity 生命周期、UnityEvent、`[SerializeField]` 引用；
- `SendMessage` 显式输出 `DYNAMIC_DISPATCH_UNKNOWN / UNKNOWN`；
- 节点、边、位置、来源与置信度确定性排序。
- Unity Context Builder 读取 `.asmdef`、ProjectVersion、生成的 `.csproj`、define、Compile glob、ProjectReference 与 metadata HintPath；
- 递归构建程序集依赖图，并区分 `BOUND_UNVERIFIED`、`MISSING`、`OUTSIDE_UNITY_ROOT` 与 `ANALYZER_ONLY`；
- Worker Input Assembler 只读取 `SnapshotBinding` 中的源码，在装配前后复核 snapshot 与 Unity context；
- 源码编码严格识别 UTF-8、UTF-8 BOM、UTF-16 BOM 和 GB18030，不支持的编码 fail closed；
- `Library/ScriptAssemblies` 输出没有源码来源绑定时标为 `PROJECT_UNVERIFIED`，且不会进入 Worker metadata references；
- metadata DLL 在进入 Worker 前后均以 SHA-256 校验，symlink/reparse point 被拒绝；
- 真实 Unity metadata 中存在 `MonoBehaviour`、`UnityEventBase` 且上下文声明完整时，Unity 框架关系才允许升级为 `CONFIRMED_STATIC`。

## 当前强制降级

使用受控 Unity stub 或缺少真实 metadata 时：

- 即使调用方声称上下文 `COMPLETE`，只要缺少 digest-bound `UnityEngine.CoreModule.dll` 或关键 Unity 符号，输出仍强制为 `PARTIAL`；
- Unity 生命周期、UnityEvent 和序列化引用最多为 `STRUCTURAL`；
- 普通 C# 内部调用在 Roslyn 唯一解析时可以是 `CONFIRMED_STATIC`；
- `SendMessage`、Inspector 绑定和其他动态目标不能升级为静态确认。

## `CL-GATE-02` 仍缺少

- 为 `Library/ScriptAssemblies` 输出建立可验证的源码、编译选项和产物来源绑定；
- 执行平台/define 与 Assembly Definition constraints 的适用性判定；
- Coroutine、`async/await`、delegate/C# event、组件查找的完整关系；
- OLD/NEW 两套 Golden Graph 与人工标注逐项比对；
- 能力矩阵、性能与更多 adversarial cases。

包版本已锁定在 `worker/ChangeLens.Analyzer/packages.lock.json`。Roslyn 包的官方来源为 [NuGet Gallery](https://www.nuget.org/packages/Microsoft.CodeAnalysis.CSharp/5.9.0)。

## ET6 只读试点

在 `D:\ares\project\ET6\Unity` 的 Unity 2020.3.26f1c1 项目上，Context Builder 已读取 `Unity.Model`：140 个 define、221 个 metadata reference（其中 69 个 Unity reference）、632 个 Compile source 和 5 个 ProjectReference。递归图包含 6 个程序集和 12 条依赖；632 个源码全部从含 9,325 个所选文件的工作树快照装配，其中 UTF-8 336、UTF-8 BOM 273、GB18030 23。真实 `MonoBehaviour`/`UnityEvent` 合成样本通过 Worker，生命周期与 UnityEvent 边为 `CONFIRMED_STATIC`。4 个项目程序集产物存在但尚无来源绑定，因此实际上下文和图仍正确标记为 `PARTIAL`。

试点只读取项目和 Unity 安装目录；未 checkout、未启动 Unity、未编译或执行 ET6 项目代码，前后 Git status 指纹一致。
