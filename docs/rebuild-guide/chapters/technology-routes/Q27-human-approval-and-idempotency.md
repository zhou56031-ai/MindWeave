# Q27：人工审批、幂等与崩溃窗口

## 1. 原理与本项目的使用

第 50 篇的写工具运行有 pending→executing→completed/rejected 状态。用户看到 interrupt 卡片后，服务端把提案留在 MySQL；resume 请求只携带会话与 approve/reject，工具名和参数来自服务器保存的快照。对 ChatSession/AgentRun 加行锁认领，可让并发重复点击只有一次获得执行权。这种实现是应用自己的审批状态机，不是 LangGraph 原生 interrupt；原生机制需 checkpointer 与 Command 恢复。[LangGraph interrupt](https://docs.langchain.com/oss/python/langgraph/interrupts/)、[SQLAlchemy 行锁](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.GenerativeSelect.with_for_update)。

## 2. 同类技术路线对比

| 路线 | 适合的情况 | 代价或边界 |
|---|---|---|
| 立即执行模型建议 | 只读、可撤销动作 | 写入会失去用户确认 |
| MySQL 提案 + 人工审批 | 跨刷新保存、可审计、同一运行只认领一次 | 业务提交与状态提交仍有故障窗口 |
| LangGraph 原生 interrupt | 图内暂停和恢复一致 | 要配持久 checkpointer，副作用仍需幂等 |
| 外部审批平台 | 多角色/流程复杂 | 系统与权限集成成本 |

## 3. 工程边界与面试追问

数据库锁能防两个同时请求都认领 pending，但不能让“执行另一个业务表提交”和“标记 completed”自动成为同一个跨服务事务。若刚写入成功就崩溃，状态可能停在 executing；系统必须停自动重试，按 run_id 人工核对，或给业务写入增加唯一幂等键。拒绝分支不能执行工具。前端断线也不代表后端写入没发生，刷新要读取状态与目标业务记录。

