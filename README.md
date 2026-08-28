# AEH Change Lens

[![Governed checks](https://github.com/YIMO691/aeh-change-lens/actions/workflows/contracts.yml/badge.svg)](https://github.com/YIMO691/aeh-change-lens/actions/workflows/contracts.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](pyproject.toml)
[![.NET 8](https://img.shields.io/badge/.NET-8.0-512BD4.svg)](worker/ChangeLens.Analyzer/ChangeLens.Analyzer.csproj)

中文 | [English](README.en.md) | [文档索引](docs/README.md)

AEH Change Lens 是面向 Unity/C# 游戏业务代码的只读修改解释工具。它把一次代码修改整理为：

```text
原逻辑链路 → 结构化变化 → 新逻辑链路
                  │
                  └─ 代码事实、来源证据、意图推断、影响与未知项
```

它不会读取或还原模型隐藏思维链，只展示能够被 Git、Roslyn、用户提供的任务说明和明确标注的推断所支持的结论。

> [!IMPORTANT]
> 项目目前是开发预览版，`CL-WP-02` 仍为 `IN_PROGRESS`，尚未完成正式发布评估。当前适合个人受控工作流和原型验证，不代表所有 Unity 项目都可开箱即用。

## 功能

- 对比 Git `OLD` revision 与 `NEW` revision/工作树，全程不 checkout。
- 使用 Roslyn 提取调用、分支、异常、状态读写、生命周期、协程、异步、事件和常见 Unity 关系。
- 输出确定性的新增、删除、修改、移动和上下文关系。
- 生成中文优先、无脚本、完全离线的 Change Story HTML。
- 严格分开 `CODE_FACT`、`SOURCE_EVIDENCE` 和 `INTENT_INFERENCE`。
- 对缺失、过期、越界或无法证明的输入 fail closed 或显式降级为 `PARTIAL`。
- 提供显式触发的 `$aeh-change-lens` Codex Skill，隐藏日常 CLI 参数。

详细覆盖范围见[能力矩阵](docs/CAPABILITY_MATRIX.zh-CN.md)。

## 快速开始

### 方式一：通过 Codex 使用（个人工作推荐）

安装仓库内的显式触发 Skill：

```powershell
.\integrations\codex\install_skill.ps1
```

在新的 Codex 会话中调用：

```text
$aeh-change-lens 分析我当前对 ET6 的修改
```

Skill 默认不会介入普通编码任务。它会优先使用当前 Git 仓库，否则使用个人默认项目 `D:\ares\project\ET6`，并将报告写到目标仓库之外。

### 方式二：直接使用 CLI

要求：

- Python 3.11 或更高版本；
- .NET SDK 8.0；
- Git；
- Unity 项目中可验证的生成项目或 compile-manifest 基线。

```powershell
python -m pip install -e ".[contract]"
dotnet build worker\ChangeLens.Analyzer\ChangeLens.Analyzer.csproj --configuration Release
```

生成 OLD → NEW 报告：

```powershell
change-lens explain D:\GameRepo Unity `
  --assembly Unity.Model `
  --base HEAD `
  --target WORKTREE `
  --request-id CHANGE-001 `
  --analysis-output change-analysis.json `
  --output change-story.html `
  --pretty
```

不安装 Python 包也可以从源码仓库调用：

```powershell
python .\run_change_lens.py --help
```

完整参数和意图证据格式见 [Change Story 使用说明](docs/CHANGE_STORY.zh-CN.md)。

## 编译基线

可信的历史比较要求 OLD 和 NEW 各自携带匹配版本的 Unity 生成 `.csproj`，或由 Change Lens 导出的 compile manifest。对于忽略 `.csproj` 的仓库，应在相关代码干净时建立基线：

```powershell
change-lens export-compile-manifest D:\GameRepo Unity `
  --assembly Unity.Model `
  --pretty
```

该命令会向目标仓库写入 `.aeh-change-lens/compile-manifests/<Assembly>.json`。Codex Skill 不会擅自执行；需要用户在当前会话单独授权。没有历史基线时，工具拒绝用当前编译选项冒充旧版本证据。

## 输出

Change Story 报告包含：

1. 修改摘要与变化计数；
2. 代码事实、来源证据和意图推断；
3. 原链路与新链路；
4. 符号变化与代码位置；
5. 状态、事件、类型和动态目标影响；
6. `PARTIAL` 原因及其他限制。

HTML 是 UTF-8 单文件，不包含 JavaScript、CDN、远程字体或遥测。

## 安全边界

默认分析策略：

- 网络访问：拒绝；
- checkout：拒绝；
- 编译或执行目标项目代码：拒绝；
- 修改 AEH Gate、审批或机器真值：拒绝；
- 构建仓库自有 Roslyn Worker：允许；
- 在调用者指定位置写报告：允许。

安全问题请按照 [SECURITY.md](SECURITY.md) 私下报告，不要在公开 Issue 中附带专有项目源码。

## 项目结构

```text
src/aeh_change_lens/          Python 编排、快照、Unity 上下文和报告
worker/ChangeLens.Analyzer/   .NET 8 / Roslyn 静态分析 Worker
schemas/                      JSON Schema 契约
fixtures/                     人工标注 Unity Golden Change
tests/                        契约、快照、分析、报告和集成测试
integrations/codex/           显式触发的个人 Codex Skill
governance/                   工作包、Gate 和原始验证记录
docs/                         中文权威文档与英文镜像
```

## 开发与验证

```powershell
python -m pip install -e ".[contract]"
dotnet build worker\ChangeLens.Analyzer\ChangeLens.Analyzer.csproj --configuration Release
python -m unittest discover -s tests -v
```

测试只允许构建仓库自有 Worker。真实 Unity 试点必须通过环境变量显式启用，并保持目标项目只读。

## 文档

从[文档索引](docs/README.md)开始，或直接阅读：

- [实施方案](docs/IMPLEMENTATION_PLAN.zh-CN.md)
- [Change Story 报告](docs/CHANGE_STORY.zh-CN.md)
- [C#/Unity 能力矩阵](docs/CAPABILITY_MATRIX.zh-CN.md)
- [OLD/NEW 图差异契约](docs/GRAPH_DIFF.zh-CN.md)
- [Roslyn Worker](docs/ROSLYN_WORKER.zh-CN.md)
- [快照契约](docs/SNAPSHOT_CONTRACT.zh-CN.md)

## 贡献与支持

- 贡献代码前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
- 使用问题见 [SUPPORT.md](SUPPORT.md)。
- 社区行为要求见 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
- 项目状态和剩余 Gate 条件见 [CL-GATE-02 progress](governance/gates/CL-GATE-02-progress.md)。

## 许可证

[MIT License](LICENSE)
