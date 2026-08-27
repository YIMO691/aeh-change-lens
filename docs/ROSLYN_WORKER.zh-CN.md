# Roslyn Worker 当前契约

> 中文权威版本；英文对应文档见 [ROSLYN_WORKER.en.md](ROSLYN_WORKER.en.md)。

本文件描述 `CL-WP-02` 的首个可运行纵切，不表示 `CL-GATE-02` 已通过。

## 已实现

- .NET 8 控制台 Worker，通过 stdin 或 `--input` 接收本地 JSON；
- Roslyn 5.9.0 语法树、Compilation 和 SemanticModel；
- 输入源码内容与 SHA-256 强绑定，路径必须是安全的 Git 风格相对路径；
- 输出符合 `analyzer-result.schema.json`；
- 类型、方法、条件、throw、return 和状态节点；
- `DIRECT_CALL`、`BRANCHES_TO`、`THROWS_FROM`、`RETURNS_FROM`、`WRITES_STATE`；
- Unity 生命周期、UnityEvent、`[SerializeField]` 引用；
- `SendMessage` 显式输出 `DYNAMIC_DISPATCH_UNKNOWN / UNKNOWN`；
- 节点、边、位置、来源与置信度确定性排序。

## 当前强制降级

Worker 目前只加载 .NET 平台元数据和调用方提供的内存源码；测试中的 Unity 类型是受控 stub，不是 Unity 官方程序集。因此：

- 即使调用方声称上下文 `COMPLETE`，输出能力仍强制为 `PARTIAL`；
- Unity 生命周期、UnityEvent 和序列化引用最多为 `STRUCTURAL`；
- 普通 C# 内部调用在 Roslyn 唯一解析时可以是 `CONFIRMED_STATIC`；
- `SendMessage`、Inspector 绑定和其他动态目标不能升级为静态确认。

## `CL-GATE-02` 仍缺少

- 从 `.asmdef` 构建程序集边界；
- 加载真实 Unity reference assemblies，并绑定文件摘要；
- 平台/define 分支与 Assembly Definition constraints；
- Coroutine、`async/await`、delegate/C# event、组件查找的完整关系；
- OLD/NEW 两套 Golden Graph 与人工标注逐项比对；
- 能力矩阵、性能与更多 adversarial cases。

包版本已锁定在 `worker/ChangeLens.Analyzer/packages.lock.json`。Roslyn 包的官方来源为 [NuGet Gallery](https://www.nuget.org/packages/Microsoft.CodeAnalysis.CSharp/5.9.0)。

