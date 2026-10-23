# Q06｜为什么用 SQLAlchemy 异步 ORM？

**对应位置：** `backend/app/models/` 定义映射，`app/db/db_config.py` 建立 `AsyncEngine`、会话工厂和 `get_db()`；第 03–04 篇接通读写。SQLAlchemy 是数据访问层，MySQL 是保存数据的数据库服务，它们不属于同一类替代品。

## 一次请求怎样用到会话

`get_db()` 在请求到来时从 `AsyncSessionLocal` 取得会话，路由把会话传给 service。`select(Note).where(Note.user_id == user_id)` 是 Python 中构造的 SQL 表达式；`await db.execute(...)` 才真正请求数据库。创建笔记时，`db.add` 把对象登记到会话，`await db.commit()` 提交事务；请求结束后 `async with` 关闭会话。这个过程像借一本登记簿：每个请求有自己的页，查询和修改都在这页记录，提交才盖章。SQLAlchemy 官方明确说 `AsyncSession` 是有状态的事务对象，并发任务不应共享同一个实例。[SQLAlchemy 异步会话文档](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)、[会话并发边界](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)

`create_async_engine` 持有连接池配置，不等于每次请求重新建立一个引擎。`AsyncSession` 也不等于“所有代码自动并行”：只有在等待兼容的异步 I/O 时，事件循环才有机会服务其他任务。

## 与同类数据访问路线比较

| 路线 | 优点 | 代价 | 本项目的判断 |
|---|---|---|---|
| SQLAlchemy 异步 ORM | 用 Python 类映射表，查询表达式与事务在同一体系 | 要理解会话、flush、commit、refresh 和关系加载 | 当前采用，贴合参考代码及异步接口 |
| 手写 SQL + 驱动 | SQL 行为直接可见，复杂查询可以精细控制 | 映射、参数、事务边界要自行组织 | 局部复杂查询可以使用 SQLAlchemy Core 或参数化 SQL |
| 同步 ORM | 调试与生态可能更熟悉 | 同步数据库调用不能直接当成异步 I/O 使用 | 当前请求链已采用异步 MySQL 驱动 |

SQLAlchemy 同时提供 ORM 和 Core；选 ORM 不意味着不需要理解 SQL。实际排错时仍要追踪 `WHERE user_id`、事务和生成的查询。[SQLAlchemy ORM 官方介绍](https://docs.sqlalchemy.org/en/20/orm/index.html)

**最重要的边界：** Pydantic schema 描述接口输入输出，SQLAlchemy model 描述表与行；两者名字都可能叫“模型”，但分别处在 HTTP 边界和数据库边界。
