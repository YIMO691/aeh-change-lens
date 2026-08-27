# C#/Unity 分析能力矩阵

> 中文权威版本；状态对应 `CL-WP-02`，不表示 `CL-GATE-02` 已通过。

| 能力 | 当前状态 | 最高静态置信度 | 明确限制 |
|---|---|---|---|
| 类型、方法声明 | 已实现 | `CONFIRMED_STATIC` | 仅输入程序集源码 |
| 直接调用 | 已实现 | `CONFIRMED_STATIC` | Roslyn 必须唯一解析目标符号 |
| 分支、return、throw | 已实现 | `STRUCTURAL` | 尚未构造完整控制流图 |
| 状态写入 | 部分实现 | `CONFIRMED_STATIC` | 当前覆盖 field/property assignment |
| 状态读取 | 未实现 | — | `READS_STATE` 暂不输出 |
| Unity 生命周期 | 已实现 | `CONFIRMED_STATIC` | 上下文不完整时降为 `STRUCTURAL` |
| 启动协程 | 已实现 | `CONFIRMED_STATIC` | 字符串目标保持 `UNKNOWN` |
| `yield` | 已实现 | `STRUCTURAL` | 不声称静态获知下一帧实际恢复路径 |
| `await` | 已实现 | `CONFIRMED_STATIC` | 目标或 awaitable 无法解析时降级 |
| C# event/delegate 订阅 | 已实现 | `CONFIRMED_STATIC` | 当前覆盖 `+=` 方法组 |
| C# event/delegate 发布 | 已实现 | `CONFIRMED_STATIC` | 当前覆盖可解析的 `Invoke` |
| UnityEvent 调用 | 已实现 | `CONFIRMED_STATIC` | Inspector 具体监听目标仍未知 |
| 序列化引用 | 部分实现 | `CONFIRMED_STATIC` | 只确认字段到类型；具体对象未知 |
| 组件查找 | 已实现 | `CONFIRMED_STATIC` | 覆盖常见 generic/`typeof` API；运行时实例未知 |
| `SendMessage` 等动态分发 | 已实现降级 | `UNKNOWN` | 不猜测字符串对应方法 |
| asmdef 平台适用性 | 已实现 | 确定性上下文事实 | 由生成 csproj define 推导当前编译平台 |
| asmdef Define Constraints | 已实现 | 确定性上下文事实 | 支持逐行 AND、行内 `||`、`!`；非法表达式为 `UNKNOWN` |
| Version Defines | 未实现 | — | 尚未读取 package/module version 进行表达式求值 |
| ScriptAssemblies 来源绑定 | 部分实现 | `PROJECT_UNVERIFIED` | 找到产物但未证明其源码/选项/输出闭包 |
| Inspector UnityEvent 绑定 | 未实现 | `UNKNOWN` | 需要序列化资产或运行时证据 |

Define Constraints 的求值规则遵循 [Unity 2020.3 Assembly Definition properties](https://docs.unity3d.com/2020.3/Documentation/Manual/class-AssemblyDefinitionImporter.html)：所有约束行必须成立，单行可使用 `||`，符号可用 `!` 否定。

