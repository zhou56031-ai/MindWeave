# MindWeave 复刻教程（基于 RAGNotebook）

> 2026-10-20，按最新要求重新建立教程。面向有 Python、HTTP、JSON 和异步基础的学习者。

从现有后端环境继续，逐步完成真实项目。每篇说明目录、文件职责和关键后端调用关系；新建文件给完整代码，修改既有文件只给定位、前后对照和一段生动的整体解释。前端直接复用参考项目源码，不再编写逐文件操作教程。

## 现在从这里继续

[第 65 篇：前端契约、完整回归与最终验收](chapters/65-frontend-contract-and-final-acceptance.md)是当前收束入口。第 01–65 篇对应的应用代码已经接入；第 61–65 篇补齐了抽取审计、多模态 PDF、剩余 API、限流/日志/预热和最终契约测试。后端 82 个测试、前端生产构建与 Compose 配置已通过；Embedding 已切换为 QwenCloud `text-embedding-v4` 512 维线上接口并通过真实请求，真实 MySQL/Neo4j/Redis 的关键路径也已验证。完整镜像构建和双账号浏览器人工验收仍按第 65 篇保留。

第 53 篇的 Compose 代码和配置已完成，但“从空镜像构建全部容器、重启后验证持久化”的最终运行验收仍以本机实际结果为准。教程生成不代表 Docker 构建已经成功。

正式复刻目录已代执行第 01–26 篇的应用步骤；第 23 篇解析文件在第 24 篇实施前已存在。Markdown/ZIP 导出、知识表和列表、单文件及多文件上传、详情和删除均经真实请求验证。前端源码已从参考提交复制进 `MindWeave/front`，Vite 端口为 3100、后端代理为 8100，注册页面入口已移除。前端交付状态及运行方法见[前端接入记录](frontend-integration.md)。

## 当前进度

| 内容 | 状态 |
|---|---|
| 复刻目录与学习记录 | 已准备 |
| backend/.venv、依赖、锁文件、requirements.txt | 已准备，环境检查通过 |
| 新版第 01 篇 | 已编写，验证范围见正文末尾 |
| 新版第 02–16 篇 | 已生成；第 07–16 篇已代执行并按篇验证 |
| 新版第 17–20 篇 | 已代执行；真实 MySQL 中验证统计、搜索、批量操作和账号隔离 |
| 新版第 21–26 篇后端教程 | 已代执行；第 23 篇解析文件原已存在，真实 MySQL 和 HTTP 验证通过 |
| 前端 | 直接复制参考项目完整源码并完成复刻环境接入；不要求学习者照教程编写 |
| 新版第 27–36 篇后端教程 | 已代执行；回顾、DeepSeek、会话、字面检索与聊天流已接入 |
| 新版第 37–53 篇后端教程 | 已代执行；PDF/Office、多模态图片、Neo4j、Embedding、混合检索、Agent、审批和 Compose 代码已接入 |
| 新版第 54–56 篇补齐教程 | 已代执行；语义笔记搜索、自动标签分类和 GraphRAG 已接入 |
| 新版第 57–60 篇补齐教程 | 已代执行；Web 兜底、多工具循环、checkpoint、Chunk 提及和双链已接入 |
| 新版第 61–65 篇补齐教程 | 已代执行；抽取审计、多模态、剩余 API、治理和自动验收已接入 |
| 正式复刻项目的应用代码 | 后端主线对应第 01–65 篇；自动验收通过，人工浏览器与完整镜像构建待单独记录 |

## 新版连续教程

| 篇目 | 教学文档 | 本篇完成的项目能力 |
|---|---|---|
| 01 | [创建后端入口与健康检查](chapters/01-backend-entry-and-health.md) | 已代执行，建立入口、路由和成功响应 |
| 02 | [请求模型、配置与统一错误处理](chapters/02-request-models-config-and-errors.md) | 输入模型、配置优先级、404/405/422 与业务异常 |
| 03 | [MySQL、异步会话与生命周期](chapters/03-mysql-and-async-session.md) | 独立数据库、请求会话、连接池与就绪检查 |
| 04 | [笔记模型与真实创建读取](chapters/04-note-model-and-create-read.md) | 建表、事务提交、创建、列表和详情 |
| 05 | [局部修改、删除与置顶](chapters/05-note-update-delete-and-pin.md) | 区分未传/null/False，补齐写操作 |
| 06 | [分页、筛选与排序](chapters/06-note-pagination-filter-and-sort.md) | 分类、精确标签、总量与页数据、排序白名单 |
| 07 | [用户表与注册接口](chapters/07-user-model-registration.md) | 已代执行并用真实 MySQL 验证用户持久化、密码哈希和重复账号检查 |
| 08 | [JWT 与登录](chapters/08-jwt-login.md) | 已代执行并用真实 MySQL 验证签名令牌、密码验证和登录接口 |
| 09 | [真实用户保护笔记](chapters/09-protect-notes-with-user.md) | 已代执行；从 Bearer token 识别用户并用双账号验证笔记隔离 |
| 10 | [Redis 与就绪检查](chapters/10-redis-and-readiness.md) | 已代执行；Redis 容器、连接和双依赖就绪检查，经停机与恢复验证 |
| 11 | [注销与黑名单](chapters/11-logout-blacklist.md) | 已代执行；旧令牌即时失效、TTL 和 Redis 故障关闭经实测 |
| 12 | [一次性刷新令牌](chapters/12-refresh-token-rotation.md) | 已代执行；原子消费旧令牌、并发竞争和故障恢复经实测 |
| 13 | [个人资料](chapters/13-user-profile.md) | 已代执行；读取、修改、持久化与令牌更新经实测 |
| 14 | [重置密码](chapters/14-reset-password.md) | 已代执行；旧密码校验、新哈希持久化与当前令牌撤销经实测 |
| 15 | [模板表与默认列表](chapters/15-note-template-model-and-list.md) | 已代执行；每用户六个默认模板、重复读取与隔离经实测 |
| 16 | [模板增删改与排序](chapters/16-note-template-crud-reorder.md) | 已代执行；自定义模板管理、权限与整体排序经实测 |
| 17 | [分类统计](chapters/17-note-category-stats.md) | 已代执行；个人笔记总数、各分类与未分类计数 |
| 18 | [关键词搜索](chapters/18-note-keyword-search.md) | 已代执行；当前用户标题/正文检索，语义搜索留待图谱阶段 |
| 19 | [批量删除与置顶](chapters/19-note-batch-delete-and-pin.md) | 已代执行；批量清单校验、用户隔离与一次事务提交 |
| 20 | [批量改分类与删除分类](chapters/20-note-category-batch-and-delete.md) | 已代执行；区分给笔记换分类与删除分类下全部笔记 |
| 21 | [Markdown 与 ZIP 下载](chapters/21-note-markdown-and-zip-export.md) | 单篇与批量笔记导出 |
| 22 | [知识文档表、切片表和列表](chapters/22-knowledge-tables-and-list.md) | MySQL 持久化结构与用户文档列表 |
| 23 | [文本解析与切片](chapters/23-text-parser-and-chunks.md) | UTF-8 TXT/Markdown 与确定性重叠切片 |
| 24 | [单文件导入](chapters/24-single-knowledge-upload.md) | 文件与切片同事务写入、按用户 MD5 去重 |
| 25 | [多文件 SSE 导入](chapters/25-knowledge-sse-multi-upload.md) | 对接现有前端的逐文件进度事件 |
| 26 | [知识详情与删除](chapters/26-knowledge-detail-and-delete.md) | 详情、切片、MD5、删除与清空 |
| 27 | [回顾记录与笔记事务](chapters/27-review-record-and-note-lifecycle.md) | 已代执行：创建笔记同时登记回顾记录 |
| 28 | [今日回顾列表](chapters/28-review-today-list.md) | 已代执行：读取本人到期笔记 |
| 29 | [完成回顾与间隔推进](chapters/29-review-done-and-intervals.md) | 已代执行：锁行推进回顾进度 |
| 30 | [DeepSeek 客户端](chapters/30-deepseek-client-and-configuration.md) | 已代执行：统一后端模型调用与配置 |
| 31 | [AI 回顾题](chapters/31-ai-review-question.md) | 已代执行：生成并校验四选一题 |
| 32 | [补全与自动标签](chapters/32-note-autocomplete-and-auto-tag.md) | 已代执行：笔记 AI 建议与标签写入 |
| 33 | [聊天会话与消息表](chapters/33-chat-session-message-tables.md) | 已代执行：持久化聊天数据骨架 |
| 34 | [聊天会话接口](chapters/34-chat-session-list-detail-delete.md) | 已代执行：本人会话列表、详情与删除 |
| 35 | [用户范围内的知识检索](chapters/35-user-scoped-knowledge-retrieval.md) | 已代执行：MySQL 字面候选和来源上下文 |
| 36 | [聊天流与持久化](chapters/36-chat-stream-and-persistence.md) | 已代执行：SSE 增量回答与成功轮次入库 |
| 37 | [PDF、Word、PPT 文字导入](chapters/37-pdf-office-text-ingestion.md) | 已代执行：多格式文字与页码 |
| 38 | [PDF 页面图片与视觉](chapters/38-pdf-images-and-vision.md) | 已代执行：扫描页和图片访问 |
| 39 | [Neo4j 连接与约束](chapters/39-neo4j-connection-and-schema.md) | 已代执行：独立图服务 |
| 40 | [实体关系抽取](chapters/40-entity-relation-extraction.md) | 已代执行：模型结构化候选 |
| 41 | [图谱来源持久化](chapters/41-graph-source-persistence.md) | 已代执行：来源节点与实体边 |
| 42 | [图构建队列和 Worker](chapters/42-graph-build-queue-and-worker.md) | 已代执行：异步构建与状态 |
| 43 | [图谱读取与事件](chapters/43-graph-read-api-and-events.md) | 已代执行：画布和进度接口 |
| 44 | [图谱人工编辑](chapters/44-graph-manual-editing.md) | 已代执行：实体、类型、关系与合并 |
| 45 | [Embedding 与向量索引](chapters/45-embedding-and-vector-index.md) | 已代执行：local/remote 切换，线上 QwenCloud `text-embedding-v4` 512 维 |
| 46 | [混合检索](chapters/46-hybrid-retrieval.md) | 已代执行：全文、向量与降级 |
| 47 | [Agentic RAG 证据](chapters/47-agentic-rag-evidence.md) | 已代执行：查询规划和来源卡 |
| 48 | [Agent 工具白名单](chapters/48-agent-tool-registry.md) | 已代执行：受控读工具与写提案 |
| 49 | [LangGraph 与运行记录](chapters/49-langgraph-and-agent-run.md) | 已代执行：决策流和 MySQL 状态 |
| 50 | [人工审批与恢复](chapters/50-human-approval-and-resume.md) | 已代执行：待办卡、恢复与防重 |
| 51 | [笔记补充接口与重排](chapters/51-remaining-note-and-rerank-apis.md) | 已代执行：写作、关联片段、重排 |
| 52 | [图谱恢复与一致性](chapters/52-graph-recovery-and-consistency.md) | 已代执行：重抽和超时任务 |
| 53 | [Compose 部署和验收](chapters/53-compose-deployment-and-acceptance.md) | 部分验证：配置通过，完整容器构建与重启持久化待执行 |

> 第 27–52 篇对应主要应用代码已接入并通过自动或真实服务验证；第 53 篇仅完成 Compose 配置校验，完整镜像构建与重启持久化仍保留为最终验收项。

### 后续补齐教程 54–65

| 篇目 | 教学文档 | 补齐目标 |
|---|---|---|
| 54 | [语义笔记搜索](chapters/54-semantic-note-search.md) | 已代执行：Neo4j 混合检索、MySQL 回填与置顶优先 |
| 55 | [自动标签与分类](chapters/55-auto-note-enrichment.md) | 已代执行：新笔记后台生成 tags/category |
| 56 | [图谱检索](chapters/56-graph-aware-retrieval.md) | 已代执行：问句抽实体、图关系和相关 Chunk |
| 57 | [可答性与 Web 兜底](chapters/57-answerability-and-web-fallback.md) | 已代执行：可答性、Tavily/Serper 和证据融合 |
| 58 | [多工具 Agent](chapters/58-multi-step-agent-tools.md) | 已代执行：工具补全和最多五步循环 |
| 59 | [Checkpoint 与审批快照](chapters/59-langgraph-checkpoint-and-approval-snapshot.md) | 已代执行：MySQL checkpoint 和 approval |
| 60 | [Chunk 提及与双链](chapters/60-chunk-mentions-and-wikilinks.md) | 已代执行：Chunk MENTIONS 和 WIKI 边 |
| 61 | [抽取审计与系统类型](chapters/61-extraction-audit-and-system-types.md) | 已代执行：哈希、payload、日志、孤儿清理和默认类型 |
| 62 | [多模态 PDF 批处理](chapters/62-multimodal-pdf-batch-and-dedup.md) | 已代执行：图片哈希去重、批处理和全部图片接口 |
| 63 | [剩余 API 与媒体](chapters/63-api-and-media-parity.md) | 已代执行：头像、MD5、非流式多上传和 export |
| 64 | [限流、日志与预热](chapters/64-rate-limit-logging-and-background-init.md) | 已代执行：Redis 限流、耗时头和 Embedding 预热 |
| 65 | [前端契约与最终验收](chapters/65-frontend-contract-and-final-acceptance.md) | 自动契约通过；Compose 配置通过，完整构建和浏览器人工验收待记录 |

### AI 回答质量改进教程

| 篇目 | 教学文档 | 状态 |
|---|---|---|
| 66 | [对话历史、工具证据与回答策略](chapters/66-ai-conversation-quality.md) | 已代执行；正式目录 27 项相关测试通过，8100 存活与就绪正常 |
| 67 | [Agent 循环与可恢复上下文压缩](chapters/67-agent-loop-and-context-compaction.md) | 已代执行并同步第 66 篇完成后的基准；原生工具循环、可恢复压缩与会话租约已接入，本次按要求未运行测试 |
| 68 | [Agent 请求诊断与调用追踪](chapters/68-agent-run-tracing.md) | 教程已生成，尚未实施；14 个文件步骤，关联模型、工具、检索、压缩与保存过程 |
| 69 | [长文档索引与 RAG 证据优化](chapters/69-rag-evidence-quality.md) | 教程已生成，尚未实施；先完成第 68 篇，20 个文件步骤，包含结构切片、分批发布、重排与证据预算 |

配套：[Q29：对话记忆与上下文整理](chapters/technology-routes/Q29-conversation-context.md)、[Q30：Agent 循环与可恢复压缩](chapters/technology-routes/Q30-agent-loop-and-context-compaction.md)、[Q31：诊断与调用追踪](chapters/technology-routes/Q31-agent-trace-and-contextvars.md)、[Q32：结构切片与证据组织](chapters/technology-routes/Q32-structured-rag-and-evidence-selection.md)、[Q33：分批索引与代际发布](chapters/technology-routes/Q33-staged-index-publication.md)。

第 68–69 篇按求职准备中的两项优先改进编写，只含第 1、2、3 部分；新文件给完整代码，已有文件只给修改定位和 diff，并结合故障场景解释工程取舍。本次仅交付文档，没有修改应用源码或运行测试。

第 37–65 篇新教程只保留编号 1、2、3 的三个主要部分。新引入的技术另见 [Q17–Q28](chapters/technology-routes/README.md)；教程编写完成、代码已经接入、运行验收通过是三件不同的事。

第 09–26 篇沿用你确认的格式：新建文件完整代码只在编辑步骤展示一次；修改文件只给 diff 和连贯的整体解释，不做逐行表格或阶段末代码副本。后端注册接口保留，注册页面按你的要求跳过。此前旧版第 17–22 篇前端教程已撤下；现在第 17–26 篇全部是**后端**教程。

**验证边界：** 第 07–16 篇已在正式复刻目录接入；真实 MySQL 上的注册、登录、JWT 签名、双账号笔记隔离、资料修改、密码重置和模板全流程均通过验证。Redis 就绪、注销黑名单 TTL、一次性刷新（包括四请求并发仅一请求成功）及变更后的当前令牌撤销均已验证；Redis 故障时鉴权和刷新返回 503。第 13–16 篇使用的临时测试账号及模板记录已清理。模板默认初始化的并发竞争、数据库提交与 Redis 撤销之间的故障窗口及 Redis 卷重建后的持久化尚未解决或单独验证。Passlib 1.7.4 与 bcrypt 4.3.0 首次散列时会打印版本读取警告，但本次哈希和验证成功。

第 17–20 篇已在正式后端完成。账号 123、456 的临时笔记验证了统计、搜索、批量操作和跨账号隔离。第 21–26 篇已接入正式后端：真实请求验证了 Markdown/ZIP 下载、知识列表、文本上传、SSE 事件、去重、详情、切片、按名/MD5 删除、清空和账号隔离；数据库确认删除后测试切片为 0。第 61–65 篇完成后的自动验收包含 82 个测试，前端生产构建和 Compose 配置通过；真实 Redis 固定窗口、Neo4j 系统类型/孤儿清理、MySQL 多页 PDF 视觉流水线及 QwenCloud Embedding 已单独验证。现有 Neo4j Chunk 数量为 0，因此切换模型时没有旧向量残留。临时验证数据已清理。浏览器双账号全路径与完整 Docker 镜像构建仍未标记通过。

固定复刻根目录：

```text
.
```

上一级源码作为参考。教材、问答与学习画像仍放在这里的 docs/rebuild-guide；应用代码和个人运行记录写进 MindWeave。

## 保留的文档

- [文档、大模型与 Neo4j 的关系](concepts/01-documents-neo4j-llm-relationships.md)：用完整案例解释原文、MySQL、大模型、任务队列和知识图谱的职责边界。
- [参考项目与复刻项目差异审计](concepts/02-reference-vs-rebuild-gap-audit.md)：逐项对比架构、数据模型、API、Agent、GraphRAG、前端和部署缺口。
- [教程编写指导](tutorial-writing-guide.md)：后续教程统一遵守，包含变更标记示范。
- [技术路线 Q 文档](chapters/technology-routes/README.md)：按技术原理、同类路线对比和本项目选型阅读；文件名均以 Q 开头。
- [复刻路线](roadmap.md)：1:1 目标与后续项目阶段。
- [前端接入记录](frontend-integration.md)：已完成的源码复制、运行验证，以及前后端调用关系。
- [知识问答册](03-knowledge-q-and-a.md)：保留实际提问和解释。
- [学习画像](learner-profile/README.md)：保留已知基础和讲解偏好。
- [已完成的环境操作记录](../../MindWeave/环境搭建记录（未随仓库发布）)：沿用已有环境，不重新初始化。

## 旧材料清理说明

原 10 篇教程、早期样章、旧总规划与旧验证报告已删除。最新编写指导从 02-writing-standard.md 改名为 tutorial-writing-guide.md，只保留这一份。新版章节从第 01 篇重新编号。

知识画像中的“旧第 02–04 章”等文字是历史自评范围，不是当前章节编号；相应知识记录保留。正式复刻目录中的虚拟环境、依赖、Git 历史和个人学习日志均保留。
