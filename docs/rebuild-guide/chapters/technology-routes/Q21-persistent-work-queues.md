# Q21：MySQL 持久工单与同类队列

## 1. 原理与本项目的使用

第 42、52 篇把“正文更新”和“待建图工单”放在同一个 MySQL 事务。提交成功后 Worker 才认领工单、调用模型、写 Neo4j。队列的核心不是让请求变快这么简单，而是把可能失败的跨系统步骤变成有状态、可重试、可观察的工作。行锁和 skip_locked 让多个 Worker 避免认领同一 pending 行；任务仍需要幂等，因为进程可能在写完图但未回写完成状态时崩溃。[SQLAlchemy with_for_update](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.GenerativeSelect.with_for_update)。

## 2. 同类技术路线对比

| 路线 | 适合的情况 | 代价或边界 |
|---|---|---|
| MySQL 工单表 | 与正文同事务，学习和追踪直接 | 需要轮询、回收超时和控制表压力 |
| FastAPI BackgroundTasks | 单次请求后的小型非关键操作 | 进程崩溃丢任务，不能当持久队列 |
| Redis Streams/RQ | 较低延迟、任务吞吐高 | 需处理 MySQL 与队列写入之间的可靠投递 |
| Celery/消息代理 | 复杂调度和大量 Worker | 依赖和运维成本更高 |

## 3. 工程边界与面试追问

任务状态至少区分 pending、running、completed、failed；attempts 和 run_token 帮助识别重试与过期执行者。恢复超时 running 时要设置保守租约，避免慢任务被抢；写图按来源替换，重试也不应重复累加。面试官若问“事务提交后进程立刻崩溃怎么办”，工单已经在 MySQL，重启 Worker 后仍可处理。

