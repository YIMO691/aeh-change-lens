# 贡献指南 / Contributing

感谢你改进 AEH Change Lens。项目当前以中文文档为语义权威版本，英文文档用于协作和交叉检查。

Thank you for improving AEH Change Lens. Chinese documentation is authoritative; English mirrors are provided for collaboration and cross-checking.

## 开始之前 / Before you start

1. 搜索现有 Issue 和 Pull Request，避免重复工作。
2. 缺陷和功能建议请使用仓库的结构化 Issue Forms。
3. 每个 Pull Request 只绑定一个主工作包；不要顺带引入后续工作包能力。
4. 不要提交专有项目源码、凭据、个人数据、Unity Library 产物或未经许可的日志。
5. 不得把推断写成已确认事实，也不得弱化 fail-closed、证据绑定或可信度语义。

## 本地环境 / Local setup

要求 Python 3.11+、.NET SDK 8.0 和 Git。

```powershell
python -m pip install -e ".[contract]"
dotnet restore worker\ChangeLens.Analyzer\ChangeLens.Analyzer.csproj --locked-mode
dotnet build worker\ChangeLens.Analyzer\ChangeLens.Analyzer.csproj --configuration Release --no-restore
python -m unittest discover -s tests -v
```

测试工作流只允许构建仓库自有 Roslyn Worker。不得编译或执行被分析的 Unity 项目。

## 修改要求 / Change requirements

| 修改类型 | 最低要求 |
|---|---|
| Python 或 Roslyn 行为 | 添加或更新对应单元测试；说明可信边界是否变化 |
| Schema 或机器可读契约 | 更新示例、契约测试和受影响文档 |
| Change Story UI | 验证无 JavaScript、无远程资源、HTML 可离线打开 |
| Codex Skill | 更新 Skill 契约测试；保持显式触发和目标只读 |
| 文档 | 中文先行；同步英文镜像或明确记录差异 |

格式化或生成器产生的大规模改动应与行为修改分开提交，便于审查。

## Pull Request 标准

请完整填写仓库的 Pull Request 模板，包括：

- 为什么需要修改，以及用户可见结果；
- 主工作包、验收条件、不变量、风险和退出 Gate；
- 精确的验证命令与结果；
- 目标仓库是否保持只读；
- 未验证项、`PARTIAL` 原因和后续工作。

Gate 未满足时应使用 Draft Pull Request，且不得宣称工作包已完成。

## 安全与隐私 / Security and privacy

- 默认离线，不新增遥测或外部数据流。
- 不 checkout、不修改、不编译、不运行目标项目。
- 报告默认写到目标仓库之外；只有显式授权的 fixture 或 compile manifest 操作可以写入目标。
- 安全漏洞请遵循 [SECURITY.md](SECURITY.md)，不要在公开 Issue 中披露漏洞细节。

提交贡献即表示你同意遵守 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。
