# 未解决风险与路线图

## 当前优先级：个人助手启动体验

- `haagent setup` 配置用户级默认 profile。
- 无子命令 `haagent` 直接进入个人助手聊天模式。
- 默认 workspace root 是当前目录。
- 交互式多轮对话由 `AgentSession` 管理。
- `haagent sessions` 和 `haagent --continue` 服务目录相关会话恢复。

## 中期路线

- 长期记忆与用户偏好，按 `docs/superpowers/specs/2026-06-25-memory-system-v1-design.md` 推进：Session/Workspace/User Memory 物理分开，长期记忆先进入候选队列，用户确认后由确定性服务落库，不把完整 episode trace 注入模型输入。
- 更好的文件整理能力和文档处理能力。
- 更自然的任务恢复体验，包括跨目录提示和更清晰的 session 摘要。
- 更丰富的个人助手任务模板，例如 CSV 分析、资料整理、草稿润色和脚本结果解释。

## 风险

- 配置体验必须避免把 API key 写入本地 profile、项目配置或 trace；系统凭据库是默认存储，明文用户文件只能显式 opt-in。
- 会话恢复必须继续使用 bounded summary，不能复制完整历史、完整 episode 或完整工具输出进模型输入。
- Harness/eval/dogfood 仍要可用，但不能重新变成普通用户路径的中心。
