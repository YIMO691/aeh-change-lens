# 安全策略 / Security policy

## 支持范围 / Supported versions

AEH Change Lens 当前是开发预览版，尚未发布稳定版本。安全修复只面向 `main` 分支的最新代码；历史提交和未合并分支不承诺维护。

AEH Change Lens is a development preview with no stable release. Security fixes target the latest code on `main`; historical commits and unmerged branches are not supported.

## 安全边界 / Security boundary

下列问题属于本项目的安全范围：

- 路径穿越、符号链接或 Windows reparse point 导致读取/写入越过授权根目录；
- 意外 checkout、修改、编译或执行被分析项目；
- 未经授权的网络访问、遥测或源码外传；
- 利用 stale/hash 校验缺陷混用 OLD 与 NEW 证据；
- 把推断或不完整证据错误提升为已确认事实；
- Change Story 中可执行脚本、远程资源或未转义内容造成的注入。

一般使用问题、能力缺口和不含安全影响的解析错误请按照 [SUPPORT.md](SUPPORT.md) 提交。

## 报告漏洞 / Reporting a vulnerability

请勿在公开 Issue、Pull Request、日志或截图中发布漏洞细节、利用代码、凭据或专有项目源码。

仓库目前没有公开的专用安全邮箱，也未启用 GitHub Private Vulnerability Reporting。请先通过维护者 GitHub 个人资料中提供的私密联系方式建立联系。如果没有可用私密渠道，可以创建标题为 `[Security contact request]` 的最小公开 Issue；只请求私密联系方式，不要包含任何漏洞细节。

收到私密报告后，维护者会尽力确认影响、协商披露时间，并在修复可用时更新报告者。开发预览阶段不承诺固定响应时限。

Do not disclose vulnerability details publicly. Contact the maintainer through a private channel listed on their GitHub profile. If no private channel is available, open a minimal `[Security contact request]` issue with no vulnerability details or proprietary source.
