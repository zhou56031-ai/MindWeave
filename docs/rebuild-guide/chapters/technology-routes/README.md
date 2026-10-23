# 技术路线 Q 文档

这里集中讲**为什么采用某种技术路线**。章节正文仍负责“建哪个文件、写什么代码、怎样运行”；Q 文档负责原理、同类方案对比、项目里的具体用法和适用边界。阅读 Q 文档不代表这项技术已由学习者掌握，也不代表待操作章节已经在正式后端实现。

文件名统一以大写 `Q` 加两位序号开头，一种可独立选择的技术路线对应一篇文档；同一技术在多章出现时复用链接，发生关键选型变化时更新原文或另写新 Q 文档。新路线首次出现在教程时，必须同时创建或链接相应 Q 文档。

| 文档 | 首次涉及的教程 | 比较对象 |
|---|---|---|
| [Q01：uv 项目环境](Q01-uv-project-environment.md) | 第 01 篇前的环境准备 | pip + venv、Poetry |
| [Q02：FastAPI 接口框架](Q02-fastapi-web-framework.md) | 第 01 篇 | Flask、Django |
| [Q03：Pydantic 输入模型](Q03-pydantic-validation.md) | 第 02 篇 | dataclass、手工校验 |
| [Q04：Docker Compose 本地服务](Q04-docker-compose-local-services.md) | 第 03 篇 | 本机安装、逐个运行容器 |
| [Q05：MySQL 持久化](Q05-mysql-relational-database.md) | 第 03 篇 | PostgreSQL、SQLite |
| [Q06：SQLAlchemy 异步 ORM](Q06-sqlalchemy-async-orm.md) | 第 03–04 篇 | 手写 SQL、同步 ORM |
| [Q07：bcrypt 密码哈希](Q07-password-hashing.md) | 第 07 篇 | Argon2id、PBKDF2、快速哈希 |
| [Q08：JWT 登录令牌](Q08-jwt-authentication.md) | 第 08 篇 | 服务端 Session、随机不透明令牌 |
| [Q09：Redis 令牌状态](Q09-redis-token-state.md) | 第 10–12 篇 | 进程内存、MySQL 状态表 |
| [Q10：笔记搜索路线](Q10-note-search-strategies.md) | 第 18 篇 | 全文索引、向量语义检索 |
| [Q11：文本切片策略](Q11-text-chunking.md) | 第 23 篇 | 固定字符、递归结构、按 token |
| [Q12：上传去重指纹](Q12-file-deduplication.md) | 第 24 篇 | 文件名、MD5、SHA-256、字节复核 |
| [Q13：SSE 上传进度](Q13-sse-progress-stream.md) | 第 25 篇 | 轮询、WebSocket |
| [Q14：固定间隔回顾](Q14-spaced-review-schedule.md) | 第 27 篇 | SM-2、FSRS、手动日程 |
| [Q15：DeepSeek 模型客户端](Q15-deepseek-model-client.md) | 第 30 篇 | 官方 SDK、兼容 SDK、框架适配 |
| [Q16：知识检索路线](Q16-knowledge-retrieval-routes.md) | 第 35 篇 | 全文索引、向量、混合与图谱检索 |
| [Q17：文档解析](Q17-document-parsing.md) | 第 37 篇 | 分格式解析、转换服务、通用解析器 |
| [Q18：PDF 视觉](Q18-pdf-vision.md) | 第 38 篇 | 文字层、OCR、多模态模型 |
| [Q19：Neo4j 图存储](Q19-neo4j-graph-store.md) | 第 39 篇 | 属性图、关系表、RDF、向量库 |
| [Q20：实体关系抽取](Q20-entity-relation-extraction.md) | 第 40 篇 | LLM、规则、专用模型、人工 |
| [Q21：持久任务队列](Q21-persistent-work-queues.md) | 第 42 篇 | MySQL 工单、进程任务、Redis、Celery |
| [Q22：Embedding 与向量](Q22-embedding-vector-index.md) | 第 45 篇 | 本地 BGE、托管 API、pgvector、专用向量库 |
| [Q23：混合检索与重排](Q23-hybrid-retrieval-and-rerank.md) | 第 46 篇 | 字面、全文、向量、RRF、重排 |
| [Q24：Agentic RAG 规划](Q24-agentic-rag-planning.md) | 第 47 篇 | 直接检索、规则拆词、多查询规划 |
| [Q25：Agent 工具权限](Q25-agent-tools-and-permissions.md) | 第 48 篇 | 工具白名单、自动调用、外部工具协议 |
| [Q26：LangGraph 与持久状态](Q26-langgraph-and-durable-state.md) | 第 49 篇 | 函数链、StateGraph、原生 checkpointer |
| [Q27：人工审批与幂等](Q27-human-approval-and-idempotency.md) | 第 50 篇 | 提案状态机、原生 interrupt、外部审批 |
| [Q28：Compose 部署](Q28-compose-deployment-and-data.md) | 第 53 篇 | 单机 Compose、宿主机、编排平台 |
| [Q29：对话记忆与上下文](Q29-conversation-context.md) | 第 66 篇 | 最近窗口、全量历史、摘要、历史检索、框架状态 |
| [Q30：Agent 循环与可恢复压缩](Q30-agent-loop-and-context-compaction.md) | 第 67 篇 | 固定检索、JSON 决策、原生工具循环、归档、摘要、长期记忆 |
| [Q31：Agent 诊断与调用追踪](Q31-agent-trace-and-contextvars.md) | 第 68 篇 | 请求日志、ContextVar、Span、OpenTelemetry、观测平台、持久事件 |
| [Q32：结构切片与证据组织](Q32-structured-rag-and-evidence-selection.md) | 第 69 篇 | 固定切片、结构切片、RRF、Bi-Encoder、Cross-Encoder、LLM 重排 |
| [Q33：分批索引与代际发布](Q33-staged-index-publication.md) | 第 69 篇 | 删后重建、内存整批、暂存发布、活跃代指针、索引别名切换 |

Q31–Q33 配套第 68–69 篇求职改进教程，当前为待实施方案；没有因此更新正式应用代码或学习者能力等级。

Q17–Q28 随第 37–53 篇待操作教程提供技术选型说明。Q 文档只说明选型，**不证明学习者已掌握该技术，也不表示复刻后端已经执行这些章节**；实际实施状态以复刻代码与验收记录核对。
