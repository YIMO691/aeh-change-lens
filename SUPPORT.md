# 支持说明 / Support

## 在哪里提问

仓库当前使用 GitHub Issues 处理可复现缺陷和范围明确的功能建议；GitHub Discussions 尚未启用。请从 [Issue 页面](https://github.com/YIMO691/aeh-change-lens/issues/new/choose) 选择对应表单。

安全问题不要公开提交，请遵循 [SECURITY.md](SECURITY.md)。

## 提交前准备

请先搜索现有 Issue，并准备以下经过脱敏的信息：

- Change Lens 版本或 commit SHA；
- 操作系统、Python、.NET SDK、Git 和 Unity 版本；
- 使用 Codex Skill 还是 CLI；
- 完整命令或复现步骤；
- 预期结果、实际结果和退出状态；
- 可公开的最小证据、错误摘要或人工构造的复现 fixture。

不要上传专有游戏源码、凭据、内部仓库地址、个人信息或未经许可的完整报告。若问题只能在私有项目中复现，请先构造最小脱敏 fixture；无法脱敏时只描述症状和环境。

## 支持边界

本仓库不提供通用 Unity、C#、Roslyn、Git 或 Codex 使用支持，也不承诺开发预览阶段的响应时限。维护者会优先处理：

1. 违反只读、离线或不执行目标代码边界的问题；
2. OLD/NEW 证据混用或可信度错误提升；
3. 能由最小 fixture 稳定复现的错误；
4. 与当前工作包和能力矩阵一致的功能请求。

English support requests are welcome. Include a minimal, sanitized reproduction and never attach proprietary project source.
