# Change Story 中文 HTML 报告

> 中文权威版本。当前实现属于 `CL-WP-02` 的用户可见纵切，不表示 `CL-GATE-02` 已通过，也不提前激活依赖该 Gate 的后续工作包。

## 目标

Change Story 将已有的、证据绑定的 OLD/NEW Roslyn 图差异转换为一个可离线打开的单文件 HTML：

```text
完整 OLD/NEW 分析
        |
业务聚焦、主题相关性与生成代码降噪
        |----------------------|
        v                      v
快速理解（默认）          详细思路拆解
        \______________________/
                   |
             完整技术证据
```

报告用于回答五个问题：到底改了什么、原来怎样、现在怎样、为什么可能这样实现、哪些结论仍不确定。详细拆解是依据代码证据重建的工程实现结构，不是模型隐藏思维链。

## 一键生成

```powershell
change-lens explain D:\GameRepo Unity `
  --assembly Unity.Model `
  --base <old-commit> `
  --target WORKTREE `
  --request-id CHANGE-001 `
  --intent-evidence intent-evidence.json `
  --analysis-output change-analysis.json `
  --story-output change-story.json `
  --output change-story.html `
  --pretty
```

`explain` 依次完成 revision-bound 静态分析、确定性 OLD/NEW 图差异、Change Story 投影和 HTML 渲染。它仍遵守原分析策略：默认无网络、不 checkout、不编译或执行目标项目代码。

已有 `change-analysis.json` 时可只重渲染报告，不重新运行 Roslyn：

```powershell
change-lens render-report change-analysis.json `
  --intent-evidence intent-evidence.json `
  --source-root D:\GameRepo `
  --story-output change-story.json `
  --output change-story.html `
  --pretty
```

### 缺少历史编译基线

严格模式会先检查 OLD/NEW 是否各自拥有 revision-bound `.csproj` 或 compile manifest，缺失时立即拒绝，不再先扫描整个源码闭包。若当前目标只是理解已有改动，可显式添加：

```text
--allow-syntax-partial --progress
```

此时报告固定标记为 `PARTIAL`，只包含仓库内已变更 C# 文件的 Roslyn syntax/局部符号子图。它不会使用当前工作树的编译选项解释 OLD，也不会把结构调用、跨程序集或 Unity 动态关系标成完整静态事实。

`--source-root` 指向 Git 仓库根目录，只用于为 NEW 工作树位置生成本地文件链接。OLD 位置保持为 revision/path/line 文本；当 NEW 也是不可变 Git revision 时也不生成本地链接，避免把当前工作树文件冒充历史源码。

## 来源证据

可选的 `intent-evidence.json` 只接受以下契约：

```json
{
  "schema_version": "1.0.0",
  "source": "reviewed Codex session",
  "user_goal": "购买数量必须大于零。",
  "ai_plan": [
    "在状态写入前增加参数校验。",
    "将奖励计算移动到独立策略类型。"
  ],
  "commit_message": "guard invalid rewards and extract policy"
}
```

字段以陈述原文进入报告，不会因为来自 AI 对话或 commit message 而自动升级为代码事实。未知字段和空陈述 fail closed。

## 三层解释语义

| 层 | 含义 | 允许的表述 |
|---|---|---|
| `CODE_FACT` | Git/Roslyn/确定性 Diff 支持的事实 | “新增条件分支”“方法被人工复核为重命名” |
| `SOURCE_EVIDENCE` | 用户需求、AI 计划或提交说明中的原始陈述 | “AI 计划：在写入前校验” |
| `INTENT_INFERENCE` | 根据代码模式形成的保守假设 | “可能增加前置校验”“可能重新划分职责” |

没有来源证据时，报告明确显示“未提供”，不会生成伪造的 AI 计划。所有意图推断都使用“可能”，置信度为 `INFERRED`，并关联触发该推断的 edge 或 mapping ID。

## 双层阅读模式

### 快速理解

默认页控制在一屏到数屏内，优先展示：

- 一句话结论和明确标注的帮助理解比喻；
- 最多 5 张业务变化卡片；
- OLD/NEW 各最多 8 个重点步骤；
- 影响范围和最多 4 个优先风险。

方法参数、重复条件、生成代码数量和完整关系不会占据首页。快速流程是按主题相关性与业务层组织的“重点流程”，不是声称完整运行时调用栈。

### 详细思路拆解

详细页按配置、服务端、协议、Unity 编辑器工具、客户端、运行逻辑和测试阶段组织代表对象、关键关系与新增决策点。每一项保留源码位置或节点/关系证据。完整事实层、原始链路、符号表和全部限制继续保留，但默认折叠。

可选 `--story-output` 保存同一份聚焦后的 `change-story.json`。Codex 应优先读取它，而不是遍历体积更大的 `change-analysis.json`。

## 聚焦与降噪

每个版本只选择以下关系进入用户可见链路：

- 关系本身新增或删除；或
- 关系连接了新增、删除、修改、移动的节点。

完全不变且不连接变化节点的背景关系不会占满报告。快速层进一步按照变化类型、业务入口、主题词重合和跨层作用加权；普通生成代码和测试代码不会抢占主业务流程。协议字段未形成独立 Roslyn 节点时，只能用文件内容变化上下文提示，不会伪造字段级语义。

技术证据中的每个 lane 仍最多展示 80 条聚焦关系、16 条链、每条链 8 个 hop；发生截断时会写入限制项，完整分析仍可通过 `--analysis-output` 保存。

## 报告安全与可移植性

- HTML 不加载 JavaScript、字体、CDN 或远程资源；
- 标题、符号、路径和来源陈述全部 HTML 转义；
- 报告是 UTF-8 单文件，可离线复制和审阅；
- Change Story 和原 analysis 都有独立 canonical digest；
- 只有 NEW 工作树位置可选择性链接当前本地文件；
- 报告生成不会修改被分析仓库，输出路径由调用者显式指定。

## 当前限制

- 链路是“变化节点加受限关系”的解释视图，不是完整运行时调用栈或完整 CFG；
- 仅凭代码不能证明 AI 的真实修改意图；
- 多入口、大型分叉图会被确定性截断并披露；
- 当前 Viewer 使用无脚本双页签与折叠面板，尚无搜索、缩放或 IDE 插件；
- Golden Change 仍为 1 套，未达到 `CL-GATE-02` 计划的 10–20 套。
