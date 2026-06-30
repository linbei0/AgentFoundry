# Skill Marketplace v1 设计

## 背景

HaAgent 已有本地 skills v1：用户级和受信任项目级 `SKILL.md` 会被加载为本地 registry，模型只能通过 `skill_list` 读取 metadata，并在需要时通过 `skill_read` 读取单个 skill 正文。

本次接入远端 skill marketplace，范围限定为两个来源：

- `skills_sh`：`skills.sh` 生态，作为主来源。
- `skillsmp`：`skillsmp.com` 生态，作为补充搜索来源。

不接入 GenericAgent 105K search、OpenClaw、GitHub Code Search 或其他第三方目录，避免 v1 变成多源聚合系统。

## 目标

- 用户可以在 TUI 内搜索远端 skills。
- 模型可以在需要扩展能力时通过受控工具搜索 marketplace。
- 搜索结果保持紧凑，不增加默认模型输入 token。
- 安装必须由用户显式触发，不能由模型静默完成。
- 远端内容作为外部数据处理，不直接作为可信 instruction。

## 非目标

- 不实现通用 plugin/package manager。
- 不默认同步或缓存完整 marketplace。
- 不把远端搜索结果混入本地 `SkillRegistry`。
- 不支持未列入范围的 marketplace provider。
- 不为 `skillsmp` 做自动安装，除非后续确认它的完整下载、校验和安全审计接口。

## 用户体验

TUI 增加两类命令：

```text
/skills search <query>
/skills install <result-id>
```

`/skills search <query>` 同时查询 `skills_sh` 和 `skillsmp`，展示合并结果。每条结果包含：

- 临时 result id
- provider
- skill 名称
- source 或 author
- 简介
- installs 或其他质量信号
- detail URL
- 是否可安装

`/skills install <result-id>` 仅支持可安装结果。v1 中可安装结果限定为 `skills_sh`。公网可用接口目前只稳定提供搜索和详情 URL，因此安装写入用户级 skills 目录的是引用型 `SKILL.md`：包含 marketplace 来源 metadata、简介、来源 URL 和审阅提示，不把远端页面内容当作可信 instruction。

## Provider 边界

新增 `haagent.skills.marketplace` 模块，提供统一客户端接口：

```python
search_marketplace(query, providers=None, limit=10) -> MarketplaceSearchResult
```

核心类型：

- `MarketplaceProvider`：`skills_sh` 或 `skillsmp`。
- `MarketplaceSkillCard`：远端搜索结果的归一化卡片。
- `MarketplaceSearchResult`：包含 query、providers、cards、warnings。

客户端只负责 HTTP 请求、字段归一化和错误显式化，不负责安装、不负责加入本地 registry。

### skills.sh

`skills_sh` 是主来源。v1 使用公开可用的搜索 API。新版 `/api/v1` 当前需要认证时，客户端不伪造完整安装，而是保留详情 URL 并生成引用型本地 skill。

### SkillsMP

`skillsmp` 是补充来源。v1 只做搜索与展示，不安装。若接口失败，搜索结果保留 provider warning，不影响另一个 provider 的结果。

## 工具边界

新增只读工具：

```text
skill_market_search
```

参数：

- `query`: 必填字符串。
- `providers`: 可选字符串列表，只允许 `skills_sh`、`skillsmp`。
- `limit`: 可选整数，范围 1 到 10。

返回：

- `status`
- `query`
- `results`
- `warnings`

该工具是只读联网工具，必须：

- 经过 `ToolRouter`。
- 写入 `tool-calls.jsonl`。
- 不返回完整 `SKILL.md` 正文。
- 不在默认 context 中注入结果。

新增安装能力不暴露给模型作为普通工具。安装由 TUI/service 用户命令调用，走显式用户确认路径。后续如果需要模型发起安装请求，应先通过 `request_user_input` 或等价的人类确认边界。

## 安装策略

v1 只允许从 `skills_sh` 安装。

安装结果写入用户级 skills 目录，并复用现有本地 skills loader。安装前必须检查：

- result id 来自最近一次搜索结果。
- provider 是 `skills_sh`。
- skill 名称转换后的目录名安全。
- 目标目录不存在；存在时显式失败，不覆盖。
- 可安装标记来自 provider 归一化结果。

写入的引用型 `SKILL.md` 必须带来源 metadata，并明确提示远端内容仍需审阅。不得把下载失败伪装成已经安装了完整 upstream skill。

## 安全与错误处理

- 所有远端文本都按外部数据处理。
- API key、鉴权 token、错误消息中的 secret 不写入 trace。
- 单个 provider 失败不导致整个搜索失败，但必须返回 warning。
- 两个 provider 都失败时返回结构化错误。
- 不做中文自动翻译；如果 query 是中文，按原文搜索，并在 UI 文案中提示英文关键词通常更稳定。
- 不引入字符串匹配作为信任边界；信任边界来自 provider enum、用户确认、安装目录存在性和本地 loader 的显式读取。

## 测试计划

- marketplace client：
  - 正确请求 `skills_sh` 和 `skillsmp`。
  - 字段归一化稳定。
  - provider 失败时返回 warning。
  - limit 和 providers 校验有效。
- ToolRouter：
  - `skill_market_search` schema 可导出。
  - 工具调用写入 trace。
  - 返回结果不包含完整正文。
- TUI/service：
  - `/skills search` 展示合并结果。
  - `/skills install` 拒绝未搜索过的 id。
  - `/skills install` 拒绝 `skillsmp` 结果。
  - 安装不覆盖已有目录。
- 回归：
  - 本地 `skill_list` / `skill_read` 行为不变。
  - 默认 chat 没有远端 marketplace 结果注入。

## 实施顺序

1. 添加 marketplace 类型和 HTTP client。
2. 添加 `skill_market_search` 工具和 registry/router 集成。
3. 添加 service 层搜索缓存和 TUI `/skills search` 命令。
4. 添加 `skills_sh` 安装路径和 TUI `/skills install` 命令。
5. 补齐文档和相关测试。
