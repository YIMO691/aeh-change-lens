## 修改摘要 / Summary

<!-- 说明为什么修改，以及用户能观察到什么结果。Explain why this change is needed and the user-visible outcome. -->

## 修改类型 / Change type

- [ ] 缺陷修复 / Bug fix
- [ ] 新能力 / Feature
- [ ] 重构 / Refactor
- [ ] 文档或协作流程 / Documentation or workflow
- [ ] 契约、测试或治理 / Contract, test, or governance

## 治理绑定 / Governance binding

- 主工作包 / Primary work package: `CL-WP-__`
- 验收条件 / Acceptance IDs: `CL-AC-__`
- 不变量 / Invariant IDs: `CL-INV-__`
- 风险 / Risk IDs: `CL-RISK-__`
- 退出 Gate / Exit Gate: `CL-GATE-__`

## 范围与可信边界 / Scope and trust boundary

```text
Scope:
Out of scope:
Trust boundary:
External data flow:
Dependencies/licenses:
Confidence semantics:
Language/i18n semantics:
Known unknowns or PARTIAL reasons:
```

- [ ] 本 PR 只有一个主工作包 / This PR has one primary work package.
- [ ] 未引入后续工作包能力 / No later-work-package capability is included.
- [ ] 未修改 AEH normative truth；如有修改，已链接 Owner 决策记录 / AEH normative truth is unchanged, or an Owner decision is linked.
- [ ] 未把推断标记为 confirmed / No inference is labeled as confirmed.
- [ ] 默认离线且没有新增未记录的外部数据流 / Offline default is preserved and any external data flow is documented.

## 验证证据 / Verification evidence

<!-- 列出可重复执行的精确命令、结果、原始证据和不可变引用。List exact reproducible commands, results, raw evidence, and immutable references. -->

```text
Command:
Result:
Evidence:
```

## 目标完整性 / Target integrity

- [ ] 未 checkout、修改、编译或执行被分析项目 / The analyzed project was not checked out, modified, compiled, or executed.
- [ ] 测试仅写入 fixture、临时目录或明确授权的位置 / Tests wrote only to fixtures, temporary directories, or explicitly authorized paths.
- [ ] 提交内容不含专有源码、凭据、个人信息或内部地址 / No proprietary source, credentials, personal data, or internal URLs are included.

## 文档与契约 / Documentation and contracts

- [ ] 已更新受影响的中文权威文档 / Affected authoritative Chinese documentation is updated.
- [ ] 已同步英文镜像，或明确记录暂未同步原因 / English mirrors are synchronized or the gap is documented.
- [ ] Schema、示例和契约测试保持一致 / Schemas, examples, and contract tests remain synchronized.
- [ ] Gate 未通过时，本 PR 保持 Draft 且未宣称完成 / The PR remains draft and does not claim completion while its Gate is open.
