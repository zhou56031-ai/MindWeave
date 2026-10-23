# Q02｜为什么后端使用 FastAPI？

**对应位置：** `backend/main.py` 创建 `FastAPI`，`app/router/note_router.py` 定义接口，`app/utils/auth_utils.py` 和 `app/db/db_config.py` 提供请求依赖；首次接入见[第 01 篇](../01-backend-entry-and-health.md)。

## 请求到底怎样找到代码

后端启动时，`app.include_router(note_router)` 把笔记路由登记进主应用。浏览器请求 `/note/stats` 时，FastAPI 匹配路由，先准备 `Depends(get_current_user_id)` 和 `Depends(get_db)`，再调用处理函数。它们不是“定义时就运行”：鉴权、数据库会话都在这次请求需要它们时才取得。FastAPI 官方把这种机制称为依赖注入，并能据此生成 API 文档。[FastAPI 依赖文档](https://fastapi.tiangolo.com/tutorial/dependencies/)

想象路由是窗口号码：号码负责把人带到正确柜台，依赖负责在办事前核实身份并取出本次使用的表单夹；真正的业务规则仍写在 service。`async def` 允许路由在等待异步数据库调用时让出执行机会，但不会让 CPU 密集型解析自动变快。

## 与同类框架比较

| 路线 | 特点 | 什么时候可能更合适 | 本项目为什么没选 |
|---|---|---|---|
| FastAPI | 围绕类型标注、请求验证、依赖和 OpenAPI 组织接口 | API 为主、希望明确输入模型与异步调用链 | 当前选用 |
| Flask | 轻量的 WSGI 框架，核心小，按需要组合扩展 | 小型应用或团队希望自行选配组件 | 需另外约定输入校验、异步数据访问与接口文档的整套做法 |
| Django | 自带 ORM 等完整数据库应用能力 | 需要后台管理、模板页面及其完整生态 | 参考项目本来采用 FastAPI，整体迁移会偏离复刻目标 |

FastAPI 官方列出自动请求验证、依赖和 OpenAPI 文档能力；Flask 官方将其定位为轻量 WSGI 框架；Django 官方展示其内建 ORM。这些是框架提供的能力范围，**不是对性能或安全性的绝对排名**。[FastAPI 功能](https://fastapi.tiangolo.com/features/)、[Flask 官方文档](https://flask.palletsprojects.com/en/stable/)、[Django 概览](https://docs.djangoproject.com/en/5.2/intro/overview/)

**本项目的选型理由：** 复刻参考项目的路由、依赖与响应契约，且后端要访问异步 MySQL/Redis。换框架会使学习重点转向移植框架，而不是理解原项目的数据流。
