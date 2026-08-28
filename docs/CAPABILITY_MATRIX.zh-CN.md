# C#/Unity 分析能力矩阵

> 中文权威版本；状态对应 `CL-WP-02`，不表示 `CL-GATE-02` 已通过。

| 能力 | 当前状态 | 最高静态置信度 | 明确限制 |
|---|---|---|---|
| 类型、方法声明 | 已实现 | `CONFIRMED_STATIC` | 仅输入程序集源码 |
| 直接调用 | 已实现 | `CONFIRMED_STATIC` | Roslyn 必须唯一解析目标符号 |
| 分支、return、throw | 已实现 | `STRUCTURAL` | 尚未构造完整控制流图 |
| 状态写入 | 部分实现 | `CONFIRMED_STATIC` | 覆盖 field/property assignment 与 `++`/`--`；不推断反射写入 |
| 状态读取 | 部分实现 | `CONFIRMED_STATIC` | 覆盖可解析 field/property；不推断别名、反射或运行时对象 |
| Unity 生命周期 | 已实现 | `CONFIRMED_STATIC` | 上下文不完整时降为 `STRUCTURAL` |
| 启动协程 | 已实现 | `CONFIRMED_STATIC` | 字符串目标保持 `UNKNOWN` |
| `yield` | 已实现 | `STRUCTURAL` | 不声称静态获知下一帧实际恢复路径 |
| `await` | 已实现 | `CONFIRMED_STATIC` | 目标或 awaitable 无法解析时降级 |
| C# event/delegate 订阅 | 部分实现 | `CONFIRMED_STATIC` | 直接方法组确认；lambda 为 `STRUCTURAL`，工厂返回 handler 为 `UNKNOWN`；尚无 `-=` |
| C# event/delegate 发布 | 部分实现 | `CONFIRMED_STATIC` | 直接符号确认；间接 delegate `Invoke` 为 `STRUCTURAL` |
| UnityEvent 调用 | 已实现 | `CONFIRMED_STATIC` | Inspector 具体监听目标仍未知 |
| 序列化引用 | 部分实现 | `CONFIRMED_STATIC` | 只确认字段到类型；具体对象未知 |
| 组件查找 | 已实现 | `CONFIRMED_STATIC` | 覆盖常见 generic/`typeof` API；运行时实例未知 |
| `SendMessage` 等动态分发 | 已实现降级 | `UNKNOWN` | 不猜测字符串对应方法 |
| asmdef 平台适用性 | 已实现 | 确定性上下文事实 | 由生成 csproj define 推导当前编译平台 |
| asmdef Define Constraints | 已实现 | 确定性上下文事实 | 支持逐行 AND、行内 `||`、`!`；非法表达式为 `UNKNOWN` |
| Version Defines | 部分实现 | 确定性上下文事实 | 绑定 Unity 版本与 `packages-lock.json`；无法解析的 Git/path 包版本为 `UNKNOWN` |
| ScriptAssemblies 来源绑定 | 部分实现 | `PROJECT_ATTESTED` | 可证明 revision 输入/输出哈希闭包；仍是外部 Unity 构建声明，不是可复现构建 |
| Inspector UnityEvent 绑定 | 未实现 | `UNKNOWN` | 需要序列化资产或运行时证据 |
| OLD/NEW 稳定符号映射 | 已实现 | `CONFIRMED_STATIC` | 仅类型/方法的同一 Roslyn 限定符号 |
| 缺编译基线时的变更 C# 子图 | 已实现（显式） | `STRUCTURAL / PARTIAL` | 需 `--allow-syntax-partial`；不含完整程序集、define、metadata 或未变更依赖 |
| OLD/NEW 结构映射 | 部分实现 | `STRUCTURAL` | 仅唯一 kind/label/path；歧义候选不猜测 |
| 重命名/跨类型移动映射 | 部分实现 | `STRUCTURAL` | 需要人工复核 mapping hint；尚无自动相似度判断 |
| Golden Change | 部分实现 | 人工标注 + 确定性摘要 | 当前 1 套，目标 10–20 套 |
| 可提交 compile manifest | 已实现 | snapshot-bound | 需在基线和源码变化后导出；不追溯猜测旧提交 |
| 历史 Git 双上下文分析 | 部分实现 | snapshot-bound | 每侧需有生成 csproj 或匹配源码的清单；引用缺失时 `PARTIAL` |
| Change Story 中文 HTML | 首个纵切已实现 | 分层继承原证据置信度 | 单文件、无脚本、离线；大型图会确定性截断并披露 |
| AI 修改原因说明 | 部分实现 | `SOURCE_EVIDENCE` / `INFERRED` | 可导入目标、计划、commit；不读取隐藏思维链，不把代码推断当真实意图 |

Define Constraints 的求值规则遵循 [Unity 2020.3 Assembly Definition properties](https://docs.unity3d.com/2020.3/Documentation/Manual/class-AssemblyDefinitionImporter.html)：所有约束行必须成立，单行可使用 `||`，符号可用 `!` 否定。

Version Defines 支持 Unity 文档定义的数学区间、`[]` 包含端点、`()` 排除端点、`[x]` 精确版本和裸版本下限；空格与通配符按无效表达式处理。包版本来自同一源码快照绑定的 `Packages/packages-lock.json`，无法可靠转为版本的来源不会被猜测。
