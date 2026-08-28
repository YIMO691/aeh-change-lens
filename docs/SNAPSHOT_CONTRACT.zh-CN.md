# Snapshot Resolver 契约

> 中文权威版本；英文对应文档见 [SNAPSHOT_CONTRACT.en.md](SNAPSHOT_CONTRACT.en.md)。

`CL-WP-01` 负责把“原版本”和“新版本”的源码字节绑定成可复核输入，且不执行目标项目代码。

## 输入模式

- Git revision：先解析成不可变 commit OID，再用 `git ls-tree` 与 `git cat-file` 读取对象；
- `WORKTREE`：读取 tracked 与未忽略的 untracked 文件，不修改 index；
- 当前选择器：`*.cs`、`*.asmdef`、`*.csproj`、固定目录 `.aeh-change-lens/compile-manifests/*.json` 与 `.aeh-change-lens/build-manifests/*.json`、`ProjectSettings/ProjectVersion.txt`、`Packages/manifest.json` 与 `Packages/packages-lock.json`。

## 摘要语义

- `git_blob_oid`：Git 存储对象 ID；worktree 文件为 `null`；
- `sha256`：实际文件字节的 SHA-256；
- `source_manifest_hash`：按相对路径排序后，对路径、大小、Git OID 和 SHA-256 的 canonical JSON 计算 SHA-256；
- revision 的 `tree_hash`：Git 根 tree 对象原始字节的 SHA-256，根 tree 通过子 tree OID 递归绑定整棵树；
- worktree 的 `tree_hash`：当前受支持源码清单摘要；它不冒充 Git tree OID；
- `tree_oid`：真实 Git tree OID；worktree 为 `null`。

## 安全边界

- 必须显式传入精确仓库根目录；
- 拒绝绝对路径、`..`、NUL、symlink、Git symlink blob 与 Windows reparse point；
- 设置 `GIT_OPTIONAL_LOCKS=0`，只调用读取或比较型 Git 命令；
- 不 checkout、不运行 Hook、不启动 Unity、不编译或执行仓库脚本；
- 输出不含绝对仓库路径或源码正文。

## Stale 判定

已有 binding 只有在 `tree_hash` 和 `source_manifest_hash` 与重新解析结果都相同时才为 current。受绑定源码的任一字节变化、增加、删除或路径变化都会导致 stale。未进入选择器的文件不属于当前分析输入，其变化不会改变源码清单摘要。

## 当前限制

- 未进行 Git LFS 内容展开；绑定的是仓库/工作树中实际读到的字节；
- worktree 的精确 rename 补充检测只确认唯一、字节完全相同的移动；修改后移动由 Git 自身 rename 检测或后续语义映射处理；
- 文件名必须是 UTF-8；无法解码时 fail closed；
- ignored 且未跟踪的 Unity 生成 csproj 不进入 worktree binding；历史分析只允许使用同一 revision 已绑定的 compile manifest，不会绕过该边界；
- 本工作包不解析 C# 语义。
