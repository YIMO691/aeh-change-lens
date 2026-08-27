# OLD/NEW 图差异契约

> 中文权威版本；这是 `CL-WP-02` 的确定性中间产物，不表示 `CL-GATE-02` 已通过。

`graph-diff` 将两个已经通过 Roslyn Worker 生成的 `analyzer-result` 合并为同一张双版本图。节点和边保留 `OLD`/`NEW` 身份，并使用 `ADDED`、`REMOVED`、`UPDATED`、`MOVED`、`UNCHANGED_CONTEXT` 标记变化。输出符合 `schemas/analyzer-diff.schema.json`，可直接作为后续 Viewer 和 Explain Bundle 的输入。

```powershell
change-lens graph-diff old-result.json new-result.json `
  --renames renames.json `
  --mapping-hints mapping-hints.json `
  --pretty
```

## 映射规则

1. Roslyn 限定符号身份相同的类型和方法自动映射为 `SAME_SYMBOL / CONFIRMED_STATIC`。
2. 同一结构种类、标签和归一化路径在两侧各只出现一次时，可以映射为 `HEURISTIC / STRUCTURAL`。
3. 重复结构签名不按行号或出现顺序猜测；两侧节点保留为新增/删除，并输出 limitation。
4. 重命名、跨类型移动或生命周期替换必须由人工复核的 mapping hint 提供；提示本身不会被冒充为 Roslyn 静态确认。
5. 只有映射后的起点、终点和 relation 都一致，OLD/NEW 边才成为一对 `UNCHANGED_CONTEXT`；其余边明确为 `REMOVED` 或 `ADDED`。
6. 新增/删除关系会把对应的已映射上下文节点标记为 `UPDATED`，使方法级链路变化可见。

mapping hint 是 JSON 数组：

```json
[
  {
    "old_label": "Game.RewardController.Claim(int)",
    "new_label": "Game.RewardController.TryClaim(int)",
    "kind": "RENAMED",
    "basis": ["human_review", "CHANGE-001"]
  }
]
```

支持的 hint kind 为 `RENAMED`、`MOVED`、`RENAMED_AND_MOVED` 和 `HEURISTIC`。标签必须在对应侧唯一解析，否则命令 fail closed。

## Golden Change

`fixtures/unity-minimal` 是第一套人工标注 Golden Change。测试在内存中分别分析 base/target 源码，不执行项目代码，再与 `expected-change.yaml` 和 `expected-graph-diff.yaml` 比对。

当前冻结投影：OLD 19 节点、NEW 25 节点、11 对映射、14 个新增节点、8 个移除节点、14 条新增边、8 条移除边、8 对不变关系。两组重复状态访问由于无法唯一对应而保持未映射；这是预期的不确定性，不是漏报掩盖。

`canonical_digest` 覆盖状态、双版本图、映射、摘要和限制。相同输入与配置必须产生相同摘要。

## 一键历史分析

当两个 Git lane 都包含可审计的 Unity 生成工程文件时，可以直接执行：

```powershell
change-lens analyze-change D:\game-repo Unity `
  --assembly Game.Runtime `
  --base <commit> `
  --target WORKTREE `
  --request-id CHANGE-001 `
  --mapping-hints mapping-hints.json `
  --pretty
```

命令依次绑定 OLD/NEW snapshot、将每一侧的 `*.cs`、`*.asmdef`、生成 csproj 或 compile manifest、ProjectVersion 和 package lock 验哈希后物化到独立临时目录、分别构建 Unity Context、运行仓库自带静态 Worker，再生成 Graph Diff。输出同时包含两个 revision manifest、Context digest、编译输入 provenance、rename、policy 与最终 canonical digest。

若仓库忽略 Unity 生成 csproj，应在基线状态先运行并提交：

```powershell
change-lens export-compile-manifest D:\game-repo Unity --assembly Game.Runtime --pretty
git add Unity/.aeh-change-lens/compile-manifests/Game.Runtime.json
```

每次源码集合或内容变化后重新导出。清单对源码使用换行归一化后的语义 SHA-256，同时 revision snapshot 仍绑定原始字节 SHA-256；因此 Git 的 CRLF/LF 转换不会制造伪 stale，其他源码变化仍会拒绝。metadata 只记录文件名、种类和 SHA-256，不泄露本机绝对路径；分析时当前 csproj 仅作为同哈希 DLL 的 locator。若某个 revision 同时缺少 csproj 与清单、清单摘要被改写或源码语义哈希不匹配，命令在 Worker 前 fail closed。工具不会用 NEW 编译选项代替 OLD，也不会启动 Unity。没有预先建立清单基线的旧提交不能事后猜测恢复。
