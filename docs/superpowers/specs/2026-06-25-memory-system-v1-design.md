# HaAgent Memory System v1 Design

更新时间：2026-06-25
状态：设计草案 v1

## 目标

HaAgent 需要一个健全、可控、可审计的记忆系统，使个人助手能够在当前会话、当前 workspace 和用户跨目录偏好之间复用稳定信息，同时不增加普通用户心智负担，也不把完整 episode trace、完整工具输出或完整历史塞进模型输入。

本设计的核心原则是：长期记忆不能由模型直接写入事实源。模型可以从已验证的 episode/turn 中提出候选，但候选必须先进入队列，经过用户确认或编辑后，才由确定性服务落到长期记忆文件。

## 参考项目取舍

GenericAgent 给 HaAgent 的主要启发是分层记忆、working checkpoint、长任务续跑和 No Execution, No Memory。HaAgent 保留这些方向，但不把所有任务结束都当作长期记忆入口；短期 checkpoint 服务当前会话，长期记忆必须单独治理。

OpenHarness 给 HaAgent 的主要启发是 `MEMORY.md` 式入口、结构化 memory 文件、按任务选择相关记忆、记录 memory 使用情况，以及从 episode 中提取候选。HaAgent 采用“索引 + 结构化事实源 + 检索审计”的思路，但不采用无确认的自动落库：`auto_extract` 只能生成候选，不能直接写入 facts/sop/glossary/decisions。

## 非目标

- 不把长期记忆作为普通任务完成后的自动副作用。
- 不让模型在用户确认后再次改写要落库的内容。
- 不保存 API key、token、cookie、密码、私钥、明文凭据或其他 secret。
- 不把猜测、未验证观察、失败尝试、完整 transcript、完整 `tool-calls.jsonl` 当作长期记忆。
- 不为了兼容旧 `.runs`、旧 episode 或旧记忆格式增加复杂迁移逻辑。

## 总体结构

```text
Memory System
  ├─ Session State / Working Checkpoint   当前轮次、长任务推进、可丢弃
  ├─ Durable Memory Store
  │    ├─ Workspace Memory               项目事实、SOP、约定
  │    └─ User Memory                    偏好、跨目录习惯
  ├─ Memory Index                        入口索引/摘要视图，不是事实源
  ├─ Memory Retrieval                    按任务选择相关记忆
  ├─ Memory Candidate Extraction         从已验证事件提取候选
  ├─ Memory Review Queue                 待确认/待编辑/待拒绝
  └─ Memory Governance                   去重、过期、secret、猜测、审计、软删除
```

三条存储线必须物理分开：

- Session Memory：当前会话和长任务 checkpoint，属于短期状态。
- Workspace Memory：当前目录的稳定事实、SOP、术语和决策，属于目录级长期记忆。
- User Memory：用户偏好、跨目录工作习惯和通用约束，属于用户级长期记忆。

`Memory Index` 只是入口和摘要视图，不是真实事实源。真实内容以各自物理文件为准。

## 物理存储

建议 v1 使用可读的 JSONL 或 Markdown-with-frontmatter 文件，优先保证可审计、可 diff、可手动修复。

```text
<runs_root>/sessions/<session_id>/
  session.json
  turns.jsonl
  working_state.json
  memory_candidates.jsonl

<workspace_root>/.haagent/memory/
  index.json
  facts.jsonl
  sop.jsonl
  glossary.jsonl
  decisions.jsonl
  tombstones.jsonl
  audit.jsonl

~/.haagent/memory/
  index.json
  user_preferences.jsonl
  habits.jsonl
  constraints.jsonl
  tombstones.jsonl
  audit.jsonl
```

如果后续不希望在用户项目目录写 `.haagent/memory/`，可以把 workspace memory 放到用户级目录下的 workspace-id 子目录；但逻辑上仍必须与 User Memory 分开，不能混成一个全局文件。

## Session Memory

Session Memory 负责当前会话和长任务续跑，不是长期记忆。

当前已有能力包括：

- `AgentSession` 维护 session id、workspace root、turn count 和 session package。
- `turns.jsonl` 记录每轮请求摘要、结果状态、episode 路径和 verification 状态。
- `working_state.json` 保存当前目标、关键发现、已做动作、下一步和最近更新 turn。
- `summary_text()` 只把有界 turn 摘要带入下一轮。

v1 需要保持这些边界：

- Session Memory 可以自动更新，因为它只服务当前会话恢复。
- Session Memory 不能自动晋升为 Workspace/User Memory。
- 长任务 checkpoint 可以来自 runtime 的确定性摘要，但不得保存完整 trace。
- 用户结束会话或任务完成后，只有经过候选队列和用户确认的内容才能进入长期记忆。

## Workspace Memory

Workspace Memory 记录当前目录内稳定、可复用、可审计的信息，分为四类。

```
workspace-memory/
  facts/
    写入：被文件、配置、命令、测试、用户确认过的稳定项目事实
    禁止：猜测、临时状态、一次性输出、未验证推断

  sop/
    写入：重复使用的项目流程，且忘记后会增加明显成本
    禁止：普通命令清单、一次性操作步骤、还没跑通的计划

  glossary/
    写入：项目内术语、缩写、领域词、组件名含义
    禁止：通用编程概念、能从名字直接看懂的词

  decisions/
    写入：明确做出的架构/产品/流程决策，带原因和影响范围
    禁止：临时想法、未确认方案、个人猜测
```

### facts

`facts` 是关于当前 workspace 的稳定事实。

适合写入：

- 项目主要语言、包管理器、测试命令和默认入口。
- 目录结构中稳定的职责边界。
- 本项目明确采用的配置位置、运行约束和安全边界。

不适合写入：

- 单次任务的临时状态。
- 模型推测出来但没有证据的判断。
- 失败尝试、完整命令输出或完整日志。

### sop

`sop` 是在当前 workspace 做事的标准流程。

适合写入：

- 修改 CLI 行为前必须阅读哪些文档。
- 改动 runtime 合同时应跑哪些测试。
- 发布、检查、评测、文档更新的固定步骤。

不适合写入：

- 只发生一次的操作记录。
- 模糊建议，例如“注意测试”。
- 与项目规范冲突的个人习惯。

### glossary

`glossary` 是当前 workspace 的术语表，帮助模型稳定理解项目语言。

适合写入：

- `episode`、`session package`、`workspace root`、`TaskSpec` 等项目术语。
- 容易混淆的内部概念之间的差异。
- 用户或项目文档明确使用的缩写和别名。

不适合写入：

- 普通常识词。
- 没有项目特定含义的技术名词。
- 尚未确认的命名偏好。

### decisions

`decisions` 是当前 workspace 的架构或产品决策记录，应该包含背景、结论和后果。

适合写入：

- “长期记忆必须先进入候选队列，用户确认后才落库”。
- “`Memory Index` 不是事实源”。
- “普通用户路径是直接运行 `haagent` 进入 TUI，并通过 `/model` 配置模型”。

不适合写入：

- 没有明确选择的讨论过程。
- 与用户最终确认相反的中间方案。
- 未来可能尝试但尚未接受的想法。

## User Memory

User Memory 记录跨 workspace 可复用的用户偏好和习惯。

适合写入：

- 用户希望回复使用简体中文。
- 用户不接受为了最小化实现而忽略已确认的目标架构。
- 用户偏好先讨论目标架构，再按确认后的架构最大努力实现。

不适合写入：

- 只对单个项目成立的 SOP。
- 用户临时情绪或一次性指令。
- 任何凭据、密钥、隐私敏感内容或未经确认的个人属性。

User Memory 的检索优先级低于当前任务显式指令和 workspace 文档。它只能补充行为偏好，不能覆盖用户在当前 turn 的明确要求。

## Memory Index

`index.json` 是 token 控制入口，不是事实源。

建议字段：

```json
{
  "version": "1.0",
  "updated_at": "2026-06-25T00:00:00Z",
  "source": "workspace",
  "items": [
    {
      "id": "mem_...",
      "category": "facts",
      "title": "Default quality gate",
      "summary": "Run uv run haagent check for runtime-facing handoff.",
      "tags": ["verification", "runtime"],
      "updated_at": "2026-06-25T00:00:00Z",
      "status": "active"
    }
  ]
}
```

索引只包含标题、摘要、标签、分类、状态和更新时间。检索命中后，再读取对应事实源条目；不能把索引摘要当作最终事实。

## Memory Retrieval

检索必须按当前任务选择相关记忆，而不是把所有记忆注入模型。

推荐优先级：

1. 当前 turn 的用户明确指令。
2. 当前 workspace 的 `AGENTS.md` 和相关项目文档。
3. Session Memory 的 bounded summary 与 working_state。
4. Workspace Memory 中与当前任务匹配的 facts/sop/glossary/decisions。
5. User Memory 中与当前任务匹配的偏好和跨目录习惯。

检索预算必须显式、可测：

- 每类记忆有最大条数和最大字符数。
- 默认只注入摘要和必要字段。
- 对可能冲突的记忆，优先暴露冲突状态，而不是静默选择一个。
- 被检索并进入模型输入的记忆 id 必须写入 context manifest，便于审计。

## Memory Extraction

Memory Extraction 从已验证 episode/turn 中提取候选，不直接写长期记忆。

提取不能在每个任务完成后无条件运行。v1 只允许以下触发方式：

- 用户显式要求“记住这个”“以后按这个做”“把这个沉淀为项目约定”。
- 当前 turn 产生了用户确认的偏好、术语、SOP 或架构决策。
- runtime 检测到高置信的重复稳定事实，但只能生成 pending 候选，不能自动确认。
- 用户打开候选审查流程时，对最近 session 或指定 episode 做离线提取。

默认不提取的情况：

- 只是读文件、总结资料、修复一次问题或跑一次命令。
- 任务成功但没有可复用的稳定事实、SOP、术语或决策。
- 用户没有确认结论，或结论只对当前 turn 有意义。
- 内容会增加 token 噪音，未来任务很难复用。

允许提取候选的来源：

- 成功完成的 turn。
- 用户明确确认过的回答、决策或偏好。
- verification 成功或已由用户接受的执行结果。
- 当前 session 中反复出现且有证据支持的稳定模式。

禁止提取候选的来源：

- 失败 turn 中未经复盘确认的内容。
- 模型猜测、可能、也许、看起来之类不确定判断。
- 完整 transcript、完整工具输出、完整错误日志。
- secret、个人隐私敏感内容、外部账号信息。

候选建议字段：

```json
{
  "candidate_id": "cand_...",
  "scope": "workspace",
  "category": "decisions",
  "title": "Long-term memory write path",
  "body": "长期记忆必须先进入候选队列，用户确认后由确定性服务落库。",
  "evidence": {
    "session_id": "session-...",
    "turn_index": 8,
    "episode_path": ".runs/...",
    "evidence_summary": "User confirmed the candidate queue requirement."
  },
  "risk_flags": [],
  "status": "pending",
  "created_at": "2026-06-25T00:00:00Z"
}
```

候选必须能被用户查看、编辑、确认、拒绝或延后。

## 用户确认与确定性落库

长期记忆写入流程必须是：

```text
已验证 episode/turn
  -> Memory Extraction 生成候选
  -> Candidate Queue
  -> 用户查看、编辑、确认或拒绝
  -> Deterministic Commit Service
  -> facts/sop/glossary/decisions 或 user memory
  -> audit.jsonl
  -> index.json 更新
```

确认后不再调用 AI 改写内容。确定性落库服务只做：

- 校验 schema。
- 校验 scope/category 合法。
- 运行 secret 扫描。
- 计算 id 和内容 hash。
- 检查重复和冲突。
- 写入目标事实源。
- 追加 audit 记录。
- 重建或更新 index。

如果用户在确认界面编辑候选，编辑后的文本就是落库文本；AI 不再参与二次润色。

## Memory Governance

治理层是长期记忆的安全边界，必须先于自动化扩展。

### 去重

- 内容 hash 完全相同：拒绝重复写入。
- 标题或语义近似：进入冲突检查，不自动覆盖。
- 同一 scope/category 下同一主题有新版本：保留旧条目，追加 supersedes/superseded_by。

### 过期

- 每条长期记忆可选 `expires_at` 或 `review_after`。
- 过期条目默认不进入检索，但仍保留审计记录。
- 过期不是删除；需要软删除或更新版本来改变事实源。

### 禁写 secret

必须在候选生成和确定性落库两处都做 secret scan。

发现疑似 secret 时：

- 候选标记 `risk_flags=["possible_secret"]`。
- 默认禁止确认落库。
- 用户只能选择删除候选或手动改写为非敏感描述。

### 禁写猜测

候选必须有 evidence。没有 evidence 的候选不能进入长期记忆。

如果 body 带有明显不确定措辞，候选应标记 `risk_flags=["unverified_claim"]`，默认不能直接确认。

### 软删除

删除长期记忆时不直接物理删除事实源行。

推荐做法：

- 在 `tombstones.jsonl` 记录被删除 id、删除时间、原因和操作者。
- index 将该条目标记为 `deleted`。
- 检索层默认过滤 deleted。

### 审计

所有长期记忆状态变化必须写 `audit.jsonl`：

- candidate_created
- candidate_confirmed
- memory_committed
- memory_rejected
- memory_updated
- memory_soft_deleted
- memory_expired
- index_rebuilt

审计记录不写 secret，不复制完整 episode trace，只写来源 id、摘要和状态变化。

## 与现有 HaAgent 架构的关系

本设计的历史版本曾以 CLI setup 为普通用户主路径。当前主路径已更新为直接运行 `haagent` 进入 TUI，并在 TUI 内通过 `/model` 配置模型：

```powershell
cd E:\some-folder
uv run haagent
```

本设计也不绕过现有 runtime 边界：

- 模型调用仍必须经过 `ModelGateway`。
- 工具调用仍必须经过 `ToolRouter`。
- 文件和命令工具仍受 workspace root 限制。
- episode、transcript 和 tool trace 仍用于 inspect/eval。
- session resume 仍使用 bounded summary 和 `working_state`，不读取完整 trace 注入模型。

Memory Retrieval 属于 context 构建的一部分，但必须以有界、可审计的 compact records 进入模型输入。Memory Extraction 可以由模型辅助生成候选，但候选写入必须经过用户确认和确定性落库。

## v1 实施顺序

1. 定义 memory schema 和文件布局。
2. 实现候选队列的读写、列表、确认、拒绝和审计。
3. 实现 Workspace Memory 的 facts/sop/glossary/decisions 落库。
4. 实现 User Memory 的偏好和习惯落库。
5. 实现 deterministic commit service，包括 schema 校验、secret scan、去重、软删除和 index 更新。
6. 实现 Retrieval，先只按关键词、scope、category 和 tag 选择少量相关条目。
7. 把检索到的 memory ids 写入 context manifest。
8. 再接入 Extraction，从成功 turn 中生成候选，但默认只进入 pending 队列。

v1 不需要语义向量库。只有在简单索引不足以支撑真实使用后，再考虑向量检索或嵌入模型。

## 自检

- 与 `docs/harness-requirements.md` 一致：不增加普通用户心智负担，不把 harness/eval 变成用户主线，不把完整 trace 注入模型输入。
- 与 `docs/unresolved-risks-and-roadmap.md` 一致：长期记忆必须可控、可审计，并避免完整 episode trace 进入模型输入。
- 与 `docs/code-governance.md` 一致：不绕过 `ModelGateway`、`ToolRouter`、workspace root、episode trace 和 bounded session state。
- 与当前 `AgentSession` 一致：`working_state` 和 bounded summary 仍是 Session Memory，不被误认为长期记忆。
- 与用户确认的目标架构一致：长期记忆必须先进入候选队列，用户确认后由确定性服务直接落库。
