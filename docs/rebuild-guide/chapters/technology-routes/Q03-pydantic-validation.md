# Q03｜为什么 HTTP 输入用 Pydantic？

**对应位置：** `backend/app/schemas/models.py` 中的 `NoteCreate`、`BatchIdsRequest`；首次出现见[第 02 篇](../02-request-models-config-and-errors.md)。`models/` 描述数据库表，`schemas/` 描述接口收发的数据，两者不能因为都叫“模型”就混为一层。

## 原理：先把请求变成合格的业务材料

例如请求传入 `{"title":"  学习 RAG  "}`：FastAPI 接收 JSON 后用 `NoteCreate` 构造输入对象；`field_validator(..., mode="before")` 先去掉标题首尾空格，`Field(min_length=1, max_length=200)` 再检查处理后的长度。失败时请求停在输入边界，service 不会收到这份不合格的材料。批量 ID 模型则把“至少 1 个、最多 100 个、不能重复”集中成同一入口规则。Pydantic 的模型构造会验证输入，并能生成 JSON Schema；普通 Python 类型注释本身没有这些运行时效果。[Pydantic 模型文档](https://docs.pydantic.dev/latest/concepts/models/)

但输入模型只知道**数据形状**，不知道 ID 属于哪个用户。`BatchIdsRequest(ids=[...])` 即使通过，service 仍必须把 `Note.user_id == user_id` 放进数据库查询。把 Pydantic 当作“自动授权”会留下越权漏洞。

## 与相似路线比较

| 路线 | 负责什么 | 适合哪里 | 本项目的选择 |
|---|---|---|---|
| Pydantic `BaseModel` | 从外部输入构造、验证并序列化有字段约束的对象 | HTTP 请求、响应、配置 | 放在 `schemas/`，由 FastAPI 接入 |
| 标准库 `dataclass` | 生成初始化、表示等方法；普通标注不自动检查输入类型 | 已在程序内部可信的数据对象 | 不单独承担 HTTP 边界验证 |
| 手写 `if` 校验 | 可精确实现特殊业务规则 | 少量、难以用声明表达的检查 | 放在 validator 或 service，但不为每个字段重写样板代码 |

Python 官方说明，标准 `dataclass` 主要生成方法，通常不检查注释指定的类型；这是它与 Pydantic 的关键边界。[Python dataclasses 文档](https://docs.python.org/3/library/dataclasses.html)

**判断规则：** 问“输入格式是否合法”去看 schema；问“这篇笔记归谁、能否删除、何时提交”去看 service 与数据库。两类问题可以在同一请求出现，却不能只靠一层解决。
