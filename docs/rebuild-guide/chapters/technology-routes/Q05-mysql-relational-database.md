# Q05｜为什么笔记和用户存进 MySQL？

**对应位置：** `backend/app/models/note.py`、`app/models/user_model.py`、`app/db/db_config.py`；数据库接入见[第 03 篇](../03-mysql-and-async-session.md)，实际笔记写入见[第 04 篇](../04-note-model-and-create-read.md)。

## 它保存的是什么

Python 进程里的列表像工作台上的纸：程序停了就不能靠它找回。MySQL 是另一个长期运行的数据库服务，`notes` 表的一行保存一篇笔记，`user_id` 指明归属；用户、模板也各有结构化表。`db.add(note)` 只是把对象放进当前会话的待处理集合，服务中的 `await db.commit()` 才把本次事务的写入提交。InnoDB 文档建议将相关写操作放进事务并以 `COMMIT` 结束；本项目也用事务避免一次业务操作只完成一半。[MySQL InnoDB 实践](https://dev.mysql.com/doc/refman/8.4/en/innodb-best-practices.html)

`Base.metadata.create_all` 在启动时检查并创建缺失表，但不会自动把已有表改成最新列结构。后续改表要考虑迁移和已有数据，不能把“Python 模型改了”理解为“线上表自动升级”。

## 与其他关系数据库比较

| 路线 | 强项 | 需要考虑的代价 | 在复刻项目里 |
|---|---|---|---|
| MySQL | 独立服务承接多请求、事务与表约束 | 要管理容器、账号、连接和迁移 | 参考项目选用，复刻沿用 |
| PostgreSQL | 同样是客户端/服务器数据库，提供丰富 SQL 与全文搜索等能力 | 方言、驱动、DDL 和运维配置要调整 | 新项目可单独评估，当前切换不帮助 1:1 对齐 |
| SQLite | 进程内、单文件、无需单独数据库服务 | 多写入并发和网络共享场景需特别评估 | 纯函数或小型本地实验可以用，正式复刻仍接 MySQL |

SQLite 官方明确区分单机嵌入式存储与多客户端共享数据服务；PostgreSQL 官方提供自己的并发控制与全文搜索功能。这里比较的是工作方式，不是声称 MySQL 总比其他数据库强。[SQLite 适用场景](https://www.sqlite.org/whentouse.html)、[PostgreSQL 并发控制](https://www.postgresql.org/docs/current/mvcc-intro.html)

**做选型时先问：** 数据要被谁共享？同时会有多少写入？是否需要与参考项目完全相同的 SQL、字段和运行方式？本教程的首要目标是复刻，因此沿用 MySQL；高并发或全文检索需求需要另外测量，不能只根据名称决定。
