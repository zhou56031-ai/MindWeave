# Q26：LangGraph 状态图、检查点与 MySQL 运行记录

## 1. 原理与本项目的使用

第 49 篇用 StateGraph 把 choose→resolve 两站排成固定流程，状态在节点之间传递。它编译时没有配置 checkpointer，所以图本身不具备跨重启恢复能力；第 50 篇用 AgentRun 表保存“待审批提案”，这只是应用级持久运行记录，不等同于 LangGraph 的完整节点检查点。LangGraph 官方将 checkpointer 用于线程级状态快照、故障恢复与人机协作；以后若用其原生 interrupt/Command 恢复，需提供可持久化 checkpointer 和稳定 thread_id。[Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api)、[持久化](https://docs.langchain.com/oss/python/langgraph/persistence)。

## 2. 同类技术路线对比

| 路线 | 适合的情况 | 代价或边界 |
|---|---|---|
| 普通 async 函数链 | 步骤少、顺序固定 | 分支和状态可视化需自行设计 |
| 本篇 StateGraph + MySQL AgentRun | 节点边界清楚，待审批状态可重启恢复 | 图内部没有完整 checkpoint |
| StateGraph + 持久 checkpointer | 原生中断、恢复、时间线 | 存储适配、版本升级和状态迁移更复杂 |
| 进程内 MemorySaver | 本地演示 | 进程重启即失去状态 |

## 3. 工程边界与面试追问

判断恢复能力时要问清恢复的究竟是“提案数据”还是“图执行指针”。本项目当前可恢复审批，但不能把 LangGraph 流运行到任意节点后从那一点继续。状态表里保存用户、会话、提案、状态，且对每次恢复重新验证归属。面试官若问为何还用 LangGraph，两站图目前的收益主要是明确节点协议和后续扩展点；若流程永久只有两步，普通函数也完全合理。

