# Q22：中文 Embedding、向量索引与迁移

## 1. 原理与本项目的使用

第 45 篇提供 `local` 与 `remote` 两种 provider。`local` 使用 BAAI/bge-small-zh-v1.5；当前复刻项目采用 QwenCloud `text-embedding-v4` 的 OpenAI 兼容接口，输出 512 维向量，再由应用统一做 L2 归一化。相似文字通常在向量空间里更近。Neo4j 向量索引保存每个 Chunk 的向量，查询时必须用同一个模型编码问题，再取近邻候选。向量只表达模型学到的相似性，不是事实正确性，也不自带用户权限。[QwenCloud 文本向量接口](https://platform.qianwenai.com/docs/api-reference/text-embedding/openai-embedding)、[Neo4j 向量索引](https://neo4j.com/docs/cypher-manual/5/indexes/search-indexes/vector-indexes/)。

## 2. 同类技术路线对比

| 路线 | 适合的情况 | 代价或边界 |
|---|---|---|
| 本地 BGE + Neo4j | 无需逐次向量 API 费用，图与向量同处一库 | 下载/内存/CPU 耗时，模型升级需重建 |
| 托管 Embedding API | 部署轻、模型能力可升级 | 外部调用成本、隐私与服务依赖 |
| pgvector/PostgreSQL | 关系数据与向量可统一 | 本项目现用 MySQL，迁移代价较大 |
| 专用向量库 | 大规模向量功能与性能 | 再增加一个存储同步边界 |

## 3. 工程边界与面试追问

索引维度必须与模型输出维度一致；更换模型即使维度相同，也不能把旧向量和新向量混用。当前实现记录模型名和 provider，按 10 条一批请求，检查返回数量与维度并归一化。生产切换应记录模型版本，后台重算全部 Chunk，全部成功后再让查询使用新配置；失败时可切回 `local`。多用户系统不能先取全局 topK 再以用户过滤就认为召回无损，其他用户候选可能挤掉本用户；数据量增加时要评估分区或前置过滤策略。

