# Q10｜为什么第 18 篇先做关键词搜索？

**对应位置：** `backend/app/services/note_service.py` 的 `search_notes()`；第 18 篇接通 `GET /note/search`。参考项目后续涉及图谱/语义检索，这一阶段只保证笔记页面能按字面文字搜索。

## 当前查询实际匹配什么

`Note.user_id == user_id` 先圈定当前用户，标题或正文只要 `contains(keyword, autoescape=True)` 命中就进入结果。`autoescape=True` 让 `%`、`_` 等 SQL `LIKE` 特殊字符按普通输入文字处理。服务分别查询总量与当前页，因此 `total_count` 是匹配总数，不是本页长度。输入“RAG”能找到含这三个字母的笔记；输入近义词不保证找到。它更像在自己的文件柜里逐页找相同字形，不会自动理解概念。[SQLAlchemy `contains` 文档](https://docs.sqlalchemy.org/en/20/core/sqlelement.html#sqlalchemy.sql.expression.ColumnOperators.contains)

## 与同类检索路线比较

| 路线 | 依据什么匹配 | 优点 | 限制 |
|---|---|---|---|
| `LIKE`/`contains` | 字面子串 | 实现简单，适合先核对接口与用户隔离 | 数据多时性能需实测；不理解同义词 |
| 数据库全文索引 | 分词后的词项和索引 | 可为文本检索设计索引与排序 | 分词、语言与索引更新规则需要配置和评估 |
| 向量语义检索 | 文本经过 Embedding 后的向量相似度 | 可能召回不同措辞的相关内容 | 需要模型、索引、阈值、来源和质量评测；相似不等于正确 |

MySQL 8.0 支持 `FULLTEXT` 索引和对应搜索函数；这说明“以后性能不够”不必立即跳到向量库，但全文索引的词项匹配也不等同于语义理解。[MySQL 全文搜索官方文档](https://dev.mysql.com/doc/refman/8.0/en/fulltext-search.html)、[FULLTEXT 索引约束](https://dev.mysql.com/doc/refman/8.0/en/create-index.html)

**本项目为什么分阶段：** 第 18 篇先固定 URL、响应形状和用户隔离，让页面真正可用；后续 Embedding/Neo4j 阶段再替换 service 内部的候选生成，并用固定材料比较召回结果。能返回一页笔记，只证明接口和字面搜索工作，不能证明 RAG 检索质量合格。
