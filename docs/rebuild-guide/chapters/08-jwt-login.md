# 第 08 篇：签发 JWT 并完成登录

> 日期：2026-10-20。新版连续复刻教程；对象是有 Python/HTTP/异步基础的学习者。
> 前置：[第 07 篇](07-user-model-registration.md)完成后再操作。
> 成果：注册成功与登录成功都能拿到有期限的签名令牌。
> 2026-10-20 正式复刻目录已完成本篇代码、依赖和本机随机签名密钥，并通过真实 MySQL 注册、登录、错误密码、邮箱校验及 JWT 验签验证。Passlib 1.7.4 与 bcrypt 4.3.0 首次运行可能打印读取版本的警告；本次密码校验成功。

> 运行附记（2026-10-20）：为用户明确指定的两个三位数本地练习密码，正式复刻目录中的 `LoginRequest.password` 最小长度现为 3。本篇以下代码保留当时实施第 08 篇的 `min_length=6`，用于理解原步骤；实际运行以复刻目录当前文件为准。普通注册与改密仍要求至少六位。练习账号由助手在本地数据库创建并经前端代理验证，没有把密码放进教程。

**技术路线原理与同类比较：** [Q08：JWT 与服务端 Session、不透明令牌](technology-routes/Q08-jwt-authentication.md)。

## 1. 目标与文件变化总览

这一篇围绕 **签名密钥、JWT 生成与解码、密码核验、最后登录时间**。先看改变了哪些文件，再按路径逐个完成；前端界面暂不参与代码讲解。

本篇核心接口：`/user/login/`。

| 标记 | 文件 | 本篇作用 |
|---|---|---|
| 【修改】 | `.env.example` | 不含真实密钥的本地环境变量样例。|
| 【修改】 | `backend/app/core/settings.py` | 从本机环境读取并验证服务配置。|
| 【修改】 | `backend/app/router/user.py` | 用户接口；把 HTTP 参数、依赖、服务和响应接起来。|
| 【修改】 | `backend/app/schemas/user_schemas.py` | HTTP 输入输出边界；验证请求，控制响应公开字段。|
| 【修改】 | `backend/app/services/user_service.py` | 用户业务动作；查询、校验、哈希、提交由这里协调。|
| 【修改】 | `backend/app/utils/auth_utils.py` | 令牌签发、解码、鉴权与撤销的集中实现。|

**阶段边界：** 这一篇笔记接口仍使用演示身份；第 09 篇切换到令牌身份。

## 2. 从哪个目录开始

本篇六处手写文件、依赖与 `.env` 签名配置已在正式复刻目录完成，下面保留操作过程供学习和复核。注册页面仍按你的要求跳过；第 09 篇应承接本篇最终文件，不能跳步。

终端执行位置：

```text
.
```

```bash
cd "."
pwd
git status --short
```

### 本篇新增依赖

下面命令在后端项目目录执行。`uv add` 同时维护 `pyproject.toml` 与 `uv.lock`；随后导出兼容 `pip` 的 `requirements.txt`。这些生成文件不要求手工抄写。

```bash
cd "./backend"
uv add 'python-jose==3.5.0'
uv export --locked --no-dev --no-emit-project --no-hashes --format requirements.txt --output-file requirements.txt
uv sync
```

运行后检查三个文件及环境：

```bash
cd "./backend"
ls -l pyproject.toml uv.lock requirements.txt .venv
uv run python -c "import fastapi, sqlalchemy; print('依赖可导入')"
```

### 同步本机 `.env`

`.env.example` 只是一份样例。已有 `.env` 不要整个覆盖；打开下列本机文件，在末尾补上本篇字段：

```text
./.env
```

```dotenv
SECRET_KEY=<用下方命令生成的随机值>
ALGORITHM=HS256
```

生成随机签名密钥的命令在后端目录执行，输出请自己复制进 `.env`，不要提交到 Git：

```bash
cd "./backend"
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`settings.py` 中的默认字样只便于教材阶段导入，真正运行请以 `.env` 中随机密钥覆盖。更换这个密钥会让以前签发的 token 失效。

## 3. 按顺序改文件

先完成依赖和父目录，再逐个编辑下面文件。修改已有文件只给前后对照和整体解释，新建文件才给完整内容；diff 的正负号只供定位，不能复制进源码。

### 步骤 1：【修改】`.env.example`

**编辑文件的完整地址：**

```text
./.env.example
```

**修改定位与前后对照：**

```diff
--- .env.example（修改前）
+++ .env.example（修改后）
@@ -6,3 +6,5 @@
 MYSQL_PASSWORD=mindweave_pass_change_me
 MYSQL_DATABASE=MindWeave
 MYSQL_ROOT_PASSWORD=mindweave_root_change_me
+SECRET_KEY=replace_with_a_random_secret
+ALGORITHM=HS256
```

**整体解释：** JWT 要签名，先要约定密钥、算法和有效期。示例文件告诉本机 .env 需要填哪些值；登录签发与后续验证读取同一套配置，就像发证处和验票处使用同一枚印章。

**保存后检查：**

```bash
test -f "./.env.example" && echo "已找到 .env.example"
```

### 步骤 2：【修改】`backend/app/core/settings.py`

**编辑文件的完整地址：**

```text
./backend/app/core/settings.py
```

**修改定位与前后对照：**

```diff
--- backend/app/core/settings.py（修改前）
+++ backend/app/core/settings.py（修改后）
@@ -24,5 +24,9 @@
     MYSQL_PASSWORD: SecretStr = SecretStr("mindweave_pass_change_me")
     MYSQL_DATABASE: str = "MindWeave"
 
+    # 【新增 C01】JWT 的签名密钥来自本机 .env。
+    SECRET_KEY: SecretStr = SecretStr("local_dev_only_change_me")
+    ALGORITHM: Literal["HS256"] = "HS256"
+
 
 settings = Settings()
```

**整体解释：** settings 把 JWT 密钥和有效期集中保管，令牌工具从这里取值签发、验证。SecretStr 避免常规调试输出直接露出密钥，配置缺失也能在启动阶段被发现，而不是登录一半才失败。

**保存后检查：**

```bash
test -f "./backend/app/core/settings.py" && echo "已找到 backend/app/core/settings.py"
```

### 步骤 3：【修改】`backend/app/router/user.py`

**编辑文件的完整地址：**

```text
./backend/app/router/user.py
```

**修改定位与前后对照：**

```diff
--- backend/app/router/user.py（修改前）
+++ backend/app/router/user.py（修改后）
@@ -2,8 +2,9 @@
 from sqlalchemy.ext.asyncio import AsyncSession
 
 from app.db.db_config import get_db
-from app.schemas.user_schemas import RegisterRequest, UserResponse
+from app.schemas.user_schemas import LoginRequest, RegisterRequest, UserResponse
 from app.services.user_service import user_service
+from app.utils.auth_utils import generate_token
 
 user_router = APIRouter(prefix="/user", tags=["user"])
 
@@ -14,9 +15,27 @@
     db: AsyncSession = Depends(get_db),
 ) -> dict:
     user = await user_service.register(db, payload)
+    token, _expires_at = generate_token(user.uuid, user.username, user.email)
     return {
         "status": 201,
         "message": f"{user.username} 注册成功",
         "user": UserResponse.model_validate(user).model_dump(mode="json"),
-        "token": None,  # 第 08 篇颁发 JWT；当前先验证账户落库。
+        "token": token,
     }
+
+
+@user_router.post("/login/")
+async def login(
+    payload: LoginRequest,
+    db: AsyncSession = Depends(get_db),
+) -> dict:
+    user = await user_service.authenticate(
+        db, payload.username, str(payload.email) if payload.email else None,
+        payload.password,
+    )
+    token, _expires_at = generate_token(user.uuid, user.username, user.email)
+    return {
+        "message": f"{user.username} 登录成功",
+        "user": UserResponse.model_validate(user).model_dump(mode="json"),
+        "token": token,
+    }
```

**整体解释：** 登录流程先让服务查账户、核密码，再让令牌工具发 JWT；像核对身份后才发通行证。注册成功后也可按同一方式签发，客户端凭令牌访问受保护接口，不能只凭请求中写了用户名就领证。

**保存后检查：**

```bash
test -f "./backend/app/router/user.py" && echo "已找到 backend/app/router/user.py"
```

### 步骤 4：【修改】`backend/app/schemas/user_schemas.py`

**编辑文件的完整地址：**

```text
./backend/app/schemas/user_schemas.py
```

**修改定位与前后对照：**

```diff
--- backend/app/schemas/user_schemas.py（修改前）
+++ backend/app/schemas/user_schemas.py（修改后）
@@ -9,6 +9,12 @@
     password: str = Field(min_length=6, max_length=72)
     confirm_password: str
     telephone: str | None = Field(default=None, max_length=11)
+
+
+class LoginRequest(BaseModel):
+    username: str | None = None
+    email: EmailStr | None = None
+    password: str = Field(min_length=6, max_length=72)
 
 
 class UserResponse(BaseModel):
```

**整体解释：** LoginRequest 是入口的材料清单，FastAPI 先检查字段形状，再把合格数据交给服务。账号是否存在、密码是否匹配不在这张清单上判断；两层接起来才是完整的登录核验。

**保存后检查：**

```bash
test -f "./backend/app/schemas/user_schemas.py" && echo "已找到 backend/app/schemas/user_schemas.py"
```

### 步骤 5：【修改】`backend/app/services/user_service.py`

**编辑文件的完整地址：**

```text
./backend/app/services/user_service.py
```

**修改定位与前后对照：**

```diff
--- backend/app/services/user_service.py（修改前）
+++ backend/app/services/user_service.py（修改后）
@@ -1,3 +1,5 @@
+from datetime import UTC, datetime
+
 from passlib.context import CryptContext
 from sqlalchemy import or_, select
 from sqlalchemy.ext.asyncio import AsyncSession
@@ -41,5 +43,23 @@
         await db.refresh(user)
         return user
 
+    async def authenticate(self, db: AsyncSession, username: str | None,
+                           email: str | None, password: str) -> User:
+        identity = username or email
+        if not identity:
+            raise BusinessException(code=4001, message="请输入用户名或邮箱")
+        result = await db.execute(
+            select(User).where(or_(User.username == identity, User.email == identity))
+        )
+        user = result.scalars().first()
+        if user is None or not verify_password(password, user.password):
+            raise BusinessException(code=4002, message="用户名或密码错误")
+        if user.status != UserStatusChoice.ACTIVE or not user.is_active:
+            raise BusinessException(code=4003, message="用户不可登录")
+        user.last_login = datetime.now(UTC).replace(tzinfo=None)
+        await db.commit()
+        await db.refresh(user)
+        return user
+
 
 user_service = UserService()
```

**整体解释：** 认证服务用用户名或邮箱找用户，校验密码哈希和账户状态，全部通过后才更新最近登录时间并提交。路由拿到被确认的用户再签令牌；任何一关失败都不会发出通行证。

**保存后检查：**

```bash
test -f "./backend/app/services/user_service.py" && echo "已找到 backend/app/services/user_service.py"
```

### 步骤 6：【修改】`backend/app/utils/auth_utils.py`

**编辑文件的完整地址：**

```text
./backend/app/utils/auth_utils.py
```

**修改定位与前后对照：**

```diff
--- backend/app/utils/auth_utils.py（修改前）
+++ backend/app/utils/auth_utils.py（修改后）
@@ -1,6 +1,36 @@
+import time
+from uuid import uuid4
+
+from jose import JWTError, jwt
+
+from app.core.settings import settings
+
 DEMO_USER_ID = "learning-user"
 
 
 async def get_current_user_id() -> str:
-    # 【新增】仅限当前本机学习阶段；后续换成 JWT 验证后取得真实用户编号。
+    # 第 09 篇将这里替换为验证 Bearer token 的依赖。
     return DEMO_USER_ID
+
+
+def generate_token(user_id: str, username: str, email: str) -> tuple[str, int]:
+    now = int(time.time())
+    expires_at = now + 24 * 60 * 60
+    token = jwt.encode(
+        {"user_id": user_id, "username": username, "email": email,
+         "iat": now, "exp": expires_at, "jti": str(uuid4())},
+        settings.SECRET_KEY.get_secret_value(),
+        algorithm=settings.ALGORITHM,
+    )
+    return token, expires_at
+
+
+def decode_token(token: str) -> dict | None:
+    try:
+        return jwt.decode(
+            token,
+            settings.SECRET_KEY.get_secret_value(),
+            algorithms=[settings.ALGORITHM],
+        )
+    except JWTError:
+        return None
```

**整体解释：** 令牌工具把用户身份、签发时间、过期时间和唯一编号装进 JWT 并签名。后续请求带回它时，验证工具检查签名和时效再取用户 ID；载荷虽然可读，却不能随意改动而不破坏签名。

**保存后检查：**

```bash
test -f "./backend/app/utils/auth_utils.py" && echo "已找到 backend/app/utils/auth_utils.py"
```

## 4. 把这些文件连成一次真实执行

本次例子：用邮箱和密码登录。先记住接口 `/user/login/`。下面每一站都写清谁把什么交给谁。

### 先用一个形象场景理解核心机制

JWT 像一张盖有服务器印章的临时通行证。载荷中写了用户编号、签发时间 `iat`、到期时间 `exp` 和通行证编号 `jti`；签名让服务器发现内容被篡改。它不是加密保密袋，载荷里的信息可以被读到，所以不要把密码或密钥放进载荷。`SECRET_KEY` 是盖章用的印模，应该只在本机 `.env` 保存。
登录时 `authenticate` 先按用户名或邮箱找用户，再用密码验证函数比对输入和数据库哈希。只有账号可用且密码正确，服务才更新 `last_login` 并提交。路由随后拿到完整 User 对象，把 `uuid` 交给 `generate_token`。登录响应中的 token 不是另存一份会话记录；第 09 篇会在每次请求重新验签并查当前用户状态。
如果把 `SECRET_KEY` 换掉，先前签发的 token 即使还没过期也会验签失败。开发阶段很容易因为 `.env` 路径写错而出现这种现象；先检查配置从哪个目录加载，再考虑代码逻辑。

### 第 1 站：客户端提交邮箱、密码。

这一站的输入来自上一层：客户端提交邮箱、密码。可在本篇对应的 diff 或新建文件代码中找到相关函数。

观察时分清三种时刻：导入模块时只创建声明；收到 HTTP 请求后才执行路由和依赖；数据库 `commit` 后数据才作为事务结果保存。

### 第 2 站：LoginRequest 负责字段形状和基本长度。

这一站的输入来自上一层：LoginRequest 负责字段形状和基本长度。可在本篇对应的 diff 或新建文件代码中找到相关函数。

观察时分清三种时刻：导入模块时只创建声明；收到 HTTP 请求后才执行路由和依赖；数据库 `commit` 后数据才作为事务结果保存。

### 第 3 站：authenticate 用用户名或邮箱查记录，再用 verify_password 比对哈希。

这一站的输入来自上一层：authenticate 用用户名或邮箱查记录，再用 verify_password 比对哈希。可在本篇对应的 diff 或新建文件代码中找到相关函数。

观察时分清三种时刻：导入模块时只创建声明；收到 HTTP 请求后才执行路由和依赖；数据库 `commit` 后数据才作为事务结果保存。

### 第 4 站：登录时间写入数据库并提交。

这一站的输入来自上一层：登录时间写入数据库并提交。可在本篇对应的 diff 或新建文件代码中找到相关函数。

观察时分清三种时刻：导入模块时只创建声明；收到 HTTP 请求后才执行路由和依赖；数据库 `commit` 后数据才作为事务结果保存。

### 第 5 站：generate_token 将 user_id、iat、exp、jti 写进 JWT 载荷，再用 SECRET_KEY 签名。

这一站的输入来自上一层：generate_token 将 user_id、iat、exp、jti 写进 JWT 载荷，再用 SECRET_KEY 签名。可在本篇对应的 diff 或新建文件代码中找到相关函数。

观察时分清三种时刻：导入模块时只创建声明；收到 HTTP 请求后才执行路由和依赖；数据库 `commit` 后数据才作为事务结果保存。

### 第 6 站：浏览器或 curl 保存 token；随后请求放进 Authorization: Bearer 头。

这一站的输入来自上一层：浏览器或 curl 保存 token；随后请求放进 Authorization: Bearer 头。可在本篇对应的 diff 或新建文件代码中找到相关函数。

观察时分清三种时刻：导入模块时只创建声明；收到 HTTP 请求后才执行路由和依赖；数据库 `commit` 后数据才作为事务结果保存。

### 请求到状态变化的路线图

```mermaid
sequenceDiagram
    participant C as 客户端
    participant R as FastAPI 路由
    participant D as 身份与依赖
    participant S as 业务服务
    participant DB as MySQL
    participant K as Redis
    C->>R: HTTP 请求
    R->>D: 解析和校验依赖
    D-->>R: user_id / db session
    R->>S: 调用业务动作
    S->>DB: 查询或提交
    DB-->>S: ORM 对象
    S-->>R: 返回结果
    R-->>C: JSON 响应
```

这张图只表示典型路径。注册尚无当前用户依赖；第 10 篇以后令牌状态检查还会访问 Redis；并非每个请求都会写数据库。

## 5. 运行与验收

先在一个终端启动依赖并等待容器健康，再在另一个终端启动后端；已有服务正在运行时不要重复占用 8100。

```bash
cd "."
docker compose up -d --wait
docker compose ps
```

第二个终端执行：

```bash
cd "./backend"
uv run uvicorn main:app --host 127.0.0.1 --port 8100 --reload
```

一次可复制请求：第 07 篇代执行时已在本机复刻数据库创建下列练习账号；若你已换过该账号密码，请改用自己的账号。

```bash
curl -i -X POST http://127.0.0.1:8100/user/login/ -H "Content-Type: application/json" -d '{"email":"lesson07_check_20261020@example.com","password":"sample123"}'
```

### 验收时看三层结果

1. **HTTP 状态**：成功请求通常是 200；参数无效、身份无效和依赖故障分别观察对应错误。
2. **响应 JSON**：看公开字段、业务消息和返回的 token/模板列表；密码哈希不应出现在用户响应里。
3. **持久化状态**：注册、修改、密码重置、模板增删改排序要在重启后仍存在；令牌黑名单要遵守 TTL 语义。

如果某一步报错，先读终端堆栈的第一处项目文件路径，再按本文文件步骤检查导入、配置与先后顺序。

### 已代执行的真实验收（2026-10-20）

- `python-jose==3.5.0` 已在复刻项目依赖和虚拟环境中；`SECRET_KEY` 已随机生成并只写入权限为 `0600` 的本机 `.env`，未放入教程或输出日志。
- 六处手写文件与本篇最终代码一致；重新启动的 8100 后端已注册 `/user/login/`，`/health/ready` 继续返回 HTTP 200。
- 新用户注册和登录均返回可验签的 JWT；登录签发的新令牌含不同的 `jti`，`last_login` 非空，用户响应不含密码。测试账号 `lesson08_check_1792481918@example.com` 保留在复刻 MySQL 供后续练习。
- 错误密码得到当前项目约定的 **HTTP 200、JSON `code=4002`**；非法邮箱在请求模型处被拒绝，返回 HTTP 422。篡改令牌无法通过 `decode_token` 验证。
- 本篇仍保持笔记接口的演示身份 `learning-user`；第 09 篇才让笔记请求真正使用 JWT 中的用户编号。

## 6. 逐案推演：输入、经过、结果

下列是读代码与手工验证结合的练习卡。每张卡都让你先预测、再请求、最后回到具体函数解释。某些卡要求用第二个测试账号或临时停服务，请只操作复刻项目容器。

### 案例 01：正确登录

- **准备**：使用刚注册的邮箱与正确密码。
- **预期**：返回非空 token。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 01.1 变体：缺省字段

把“正确登录”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“返回非空 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 01.2 变体：边界长度

把“正确登录”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“返回非空 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 01.3 变体：重复提交

把“正确登录”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“返回非空 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 01.4 变体：并发请求

把“正确登录”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“返回非空 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 01.5 变体：服务重启

把“正确登录”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“返回非空 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

### 案例 02：密码错误

- **准备**：邮箱正确但密码不对。
- **预期**：业务错误，不签发 token。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 02.1 变体：缺省字段

把“密码错误”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误，不签发 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 02.2 变体：边界长度

把“密码错误”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误，不签发 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 02.3 变体：重复提交

把“密码错误”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误，不签发 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 02.4 变体：并发请求

把“密码错误”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误，不签发 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 02.5 变体：服务重启

把“密码错误”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误，不签发 token”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

### 案例 03：账号不存在

- **准备**：使用未知邮箱。
- **预期**：业务错误。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 03.1 变体：缺省字段

把“账号不存在”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 03.2 变体：边界长度

把“账号不存在”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 03.3 变体：重复提交

把“账号不存在”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 03.4 变体：并发请求

把“账号不存在”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 03.5 变体：服务重启

把“账号不存在”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

### 案例 04：用户名登录

- **准备**：提交 username 而不提交 email。
- **预期**：按用户名找到用户。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 04.1 变体：缺省字段

把“用户名登录”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“按用户名找到用户”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 04.2 变体：边界长度

把“用户名登录”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“按用户名找到用户”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 04.3 变体：重复提交

把“用户名登录”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“按用户名找到用户”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 04.4 变体：并发请求

把“用户名登录”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“按用户名找到用户”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 04.5 变体：服务重启

把“用户名登录”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“按用户名找到用户”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

### 案例 05：两种身份都缺

- **准备**：只提交 password。
- **预期**：业务错误。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 05.1 变体：缺省字段

把“两种身份都缺”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 05.2 变体：边界长度

把“两种身份都缺”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 05.3 变体：重复提交

把“两种身份都缺”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 05.4 变体：并发请求

把“两种身份都缺”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 05.5 变体：服务重启

把“两种身份都缺”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“业务错误”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

### 案例 06：签名篡改

- **准备**：修改 token 中任意字符。
- **预期**：decode_token 失败。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 06.1 变体：缺省字段

把“签名篡改”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 06.2 变体：边界长度

把“签名篡改”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 06.3 变体：重复提交

把“签名篡改”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 06.4 变体：并发请求

把“签名篡改”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 06.5 变体：服务重启

把“签名篡改”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

### 案例 07：过期令牌

- **准备**：exp 早于当前时间。
- **预期**：decode_token 失败。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 07.1 变体：缺省字段

把“过期令牌”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 07.2 变体：边界长度

把“过期令牌”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 07.3 变体：重复提交

把“过期令牌”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 07.4 变体：并发请求

把“过期令牌”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 07.5 变体：服务重启

把“过期令牌”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“decode_token 失败”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

### 案例 08：密钥改变

- **准备**：服务更换 SECRET_KEY。
- **预期**：旧 token 无法解码。
- **先预测**：客户端会先经过哪个路由？哪些 Pydantic 字段会提前阻断？
- **依赖追踪**：如果路由用了 `Depends`，把每个依赖的输入值来源写下来。
- **服务追踪**：指出服务查询时的用户范围；若有状态变化，指出哪行 `commit` 让它持久化。
- **异常追踪**：本案例如果失败，错误由请求验证、业务异常、HTTP 异常还是依赖网络错误产生？
- **验证动作**：执行对应请求后，先读 HTTP 状态，再读 JSON 字段，必要时查询数据库或 Redis。
- **回滚观察**：失败后检查是否发生了本不该发生的数据库改动。
- **复盘**：用一句话解释为什么输出符合预期，再对照上面的完整代码。

#### 08.1 变体：缺省字段

把“密钥改变”这一案例与“缺省字段”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“旧 token 无法解码”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 08.2 变体：边界长度

把“密钥改变”这一案例与“边界长度”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“旧 token 无法解码”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 08.3 变体：重复提交

把“密钥改变”这一案例与“重复提交”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“旧 token 无法解码”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 08.4 变体：并发请求

把“密钥改变”这一案例与“并发请求”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“旧 token 无法解码”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

#### 08.5 变体：服务重启

把“密钥改变”这一案例与“服务重启”组合，先判断输入验证、路由、服务与存储哪一层会改变结果。
原始预期是“旧 token 无法解码”。若变体不改变本案例实际输入，就保持原预期；若改变，写出发生变化的那一行代码。
不要凭“通常会这样”作答：在文件里定位 `Field`、`Depends`、`where`、`commit` 或 Redis 操作。

## 7. 阶段末完整代码核对册

这一节是本阶段的**核对副本**：按路径展开关键后端文件，方便你逐文件确认最终状态。实际编辑仍以上面“按顺序改文件”的步骤为准；相同代码无需重复粘贴。复刻目录里的 `.env` 含本机秘密，不在这里展示。

### 核对文件：`backend/app/__init__.py`

完整地址：

```text
./backend/app/__init__.py
```

职责：本阶段应用组成部分。

```python
"""RAGNotebook 复刻项目的后端应用模块。"""
```

### 核对文件：`backend/app/core/__init__.py`

完整地址：

```text
./backend/app/core/__init__.py
```

职责：本阶段应用组成部分。

```python
"""供业务模块复用的基础工具。"""
```

### 核对文件：`backend/app/core/failed_response.py`

完整地址：

```text
./backend/app/core/failed_response.py
```

职责：本阶段应用组成部分。

```python
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class BusinessException(Exception):
    def __init__(self, code: int = 4001, message: str = "业务处理失败"):
        self.code = code
        self.message = message
        super().__init__(message)


async def business_exception_handler(request: Request, exc: BusinessException):
    # 【新增】参考项目约定：业务失败由正文 code 区分，HTTP 仍为 200。
    return JSONResponse(
        status_code=200,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=jsonable_encoder({
            "code": exc.status_code,
            "message": exc.detail,
            "data": None,
        }),
        headers=exc.headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # 【新增】不回传原始输入和校验上下文，保留字段位置、错误类型和提示。
    errors = [
        {"loc": list(error["loc"]), "type": error["type"], "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"code": 422, "message": "请求参数校验失败", "data": errors},
    )
```

### 核对文件：`backend/app/core/failed_response_register.py`

完整地址：

```text
./backend/app/core/failed_response_register.py
```

职责：本阶段应用组成部分。

```python
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.failed_response import (
    BusinessException,
    business_exception_handler,
    http_exception_handler,
    validation_exception_handler,
)


def register_exception_handlers(app: FastAPI) -> None:
    # 【新增】登记错误类型与处理函数的对应关系；这里不调用处理函数。
    app.add_exception_handler(BusinessException, business_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
```

### 核对文件：`backend/app/core/lifespan.py`

完整地址：

```text
./backend/app/core/lifespan.py
```

职责：启动检查与关闭时的资源释放。

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.db.db_config import async_engine, init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # 【新增】启动时先验证本项目账户可以连接目标数据库。
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        # 【新增 C01】开始接收请求前，保证本阶段的表已经存在。
        await init_db()
        yield
    finally:
        # 【新增】启动失败或应用正常关闭时，都释放连接池资源。
        await async_engine.dispose()
```

### 核对文件：`backend/app/core/settings.py`

完整地址：

```text
./backend/app/core/settings.py
```

职责：从本机环境读取并验证服务配置。

```python
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REBUILD_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REBUILD_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "RAGNotebook Rebuild"
    ENV: Literal["dev", "test", "prod"] = "dev"

    # 【新增 C01】这里是宿主机访问复刻 MySQL 的配置。
    MYSQL_HOST: str = "127.0.0.1"
    MYSQL_PORT: int = Field(default=13306, ge=1, le=65535)
    MYSQL_USER: str = "rag_learner"
    MYSQL_PASSWORD: SecretStr = SecretStr("mindweave_pass_change_me")
    MYSQL_DATABASE: str = "MindWeave"

    # 【新增 C01】JWT 的签名密钥来自本机 .env。
    SECRET_KEY: SecretStr = SecretStr("local_dev_only_change_me")
    ALGORITHM: Literal["HS256"] = "HS256"


settings = Settings()
```

### 核对文件：`backend/app/core/success_response.py`

完整地址：

```text
./backend/app/core/success_response.py
```

职责：本阶段应用组成部分。

```python
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse


def success_response(message: str = "success", data=None) -> JSONResponse:
    # 【新增】把不同业务的结果装进同一种响应结构。
    response = {
        "code": 200,
        "message": message,
        "data": data,
    }
    # 【新增】先整理为可编码的数据，再构造实际 HTTP 响应。
    return JSONResponse(content=jsonable_encoder(response))
```

### 核对文件：`backend/app/db/__init__.py`

完整地址：

```text
./backend/app/db/__init__.py
```

职责：本阶段应用组成部分。

```python
"""数据库连接与请求级会话依赖。"""
```

### 核对文件：`backend/app/db/db_config.py`

完整地址：

```text
./backend/app/db/db_config.py
```

职责：MySQL 引擎、请求级会话和建表入口。

```python
from collections.abc import AsyncIterator

from sqlalchemy import URL, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.settings import settings
from app.models.base import Base

# 【新增】用结构化 URL 处理密码中的 @、: 等字符。
database_url = URL.create(
    drivername="mysql+aiomysql",
    username=settings.MYSQL_USER,
    password=settings.MYSQL_PASSWORD.get_secret_value(),
    host=settings.MYSQL_HOST,
    port=settings.MYSQL_PORT,
    database=settings.MYSQL_DATABASE,
    query={"charset": "utf8mb4"},
)

async_engine = create_async_engine(
    database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    # 【新增】每个请求拿独立会话；写入提交由服务层明确执行。
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_mysql_connection() -> bool:
    try:
        async with async_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def init_db() -> None:
    # 【新增 C01】导入模型完成注册后，统一检查并创建缺失表。
    from app.models.note import Note  # noqa: F401
    from app.models.user_model import User  # noqa: F401

    async with async_engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
```

### 核对文件：`backend/app/models/__init__.py`

完整地址：

```text
./backend/app/models/__init__.py
```

职责：本阶段应用组成部分。

```python
"""数据库表映射与统一元数据。"""
```

### 核对文件：`backend/app/models/base.py`

完整地址：

```text
./backend/app/models/base.py
```

职责：本阶段应用组成部分。

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """全部数据库模型共享同一份 metadata。"""
```

### 核对文件：`backend/app/models/note.py`

完整地址：

```text
./backend/app/models/note.py
```

职责：本阶段应用组成部分。

```python
from sqlalchemy import JSON, Boolean, Column, DateTime, String, Text, func

from app.models.base import Base


class Note(Base):
    __tablename__ = "notes"

    # 【新增】字段与参考 Note 的核心结构对齐。
    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    tags = Column(JSON, nullable=True)
    category = Column(String(50), nullable=True)
    is_pinned = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
```

### 核对文件：`backend/app/models/user_model.py`

完整地址：

```text
./backend/app/models/user_model.py
```

职责：数据库用户表映射；约束账号字段并保存密码哈希。

```python
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func

from app.models.base import Base


class UserStatusChoice:
    DISABLED = 0
    ACTIVE = 1
    LOCKED = 2


class User(Base):
    __tablename__ = "user_service"

    uuid = Column(String(36), primary_key=True, default=lambda: uuid4().hex[:24])
    username = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    telephone = Column(String(11), unique=True, nullable=True)
    password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    status = Column(Integer, default=UserStatusChoice.ACTIVE, nullable=False)
    gender = Column(Integer, nullable=True)
    bio = Column(Text, nullable=True)
    avatar = Column(String(255), nullable=True)
    date_joined = Column(DateTime(), server_default=func.now(), nullable=False)
    last_login = Column(DateTime(), nullable=True)
```

### 核对文件：`backend/app/router/__init__.py`

完整地址：

```text
./backend/app/router/__init__.py
```

职责：本阶段应用组成部分。

```python
"""按业务划分的 HTTP 路由。"""
```

### 核对文件：`backend/app/router/health.py`

完整地址：

```text
./backend/app/router/health.py
```

职责：存活和就绪接口。

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.core.success_response import success_response
from app.db.db_config import check_mysql_connection

health_router = APIRouter(prefix="/health")


@health_router.get("/live", tags=["健康检查"], summary="健康检查")
async def get_health_application_status() -> JSONResponse:
    return success_response(
        message="health application status",
        data={"status": "ok"},
    )


@health_router.get("/ready", tags=["健康检查"], summary="数据库就绪检查")
async def get_health_readiness() -> JSONResponse:
    # 【新增 C01】能接请求与能连接业务依赖，是两种不同状态。
    if not await check_mysql_connection():
        raise HTTPException(status_code=503, detail="MySQL连接失败")
    return success_response(
        message="health readiness status",
        data={"status": "ok"},
    )
```

### 核对文件：`backend/app/router/note_router.py`

完整地址：

```text
./backend/app/router/note_router.py
```

职责：本阶段应用组成部分。

```python
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.success_response import success_response
from app.db.db_config import get_db
from app.schemas.models import NoteCreate, NoteListResponse, NoteResponse, NoteUpdate
from app.services.note_service import note_service
from app.utils.auth_utils import get_current_user_id

note_router = APIRouter(prefix="/note", tags=["note"])


@note_router.post("/create")
async def create_note(
    payload: NoteCreate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.create_note(db, user_id, payload)
    return success_response(message="笔记创建成功", data=NoteResponse.model_validate(note))


@note_router.get("/list")
async def list_notes(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    category: str | None = Query(default=None, max_length=50),
    tag: str | None = Query(default=None, min_length=1, max_length=50),
    sort_by: Literal["updated_at", "created_at", "title"] = "updated_at",
) -> JSONResponse:
    # 【修改 C02】接收服务返回的当前页和筛选总数，二者不要混淆。
    notes, total_count = await note_service.list_notes(
        db, user_id, page, page_size, category, tag, sort_by
    )
    data = NoteListResponse(
        notes=[NoteResponse.model_validate(note) for note in notes],
        total_count=total_count,
    )
    return success_response(data=data)


@note_router.get("/{note_id}")
async def get_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.get_note(db, note_id, user_id)
    if note is None:
        return success_response(message="笔记不存在")
    return success_response(data=NoteResponse.model_validate(note))


@note_router.put("/{note_id}")
async def update_note(
    note_id: str,
    payload: NoteUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # 【新增 C03】HTTP 参数与依赖准备好后，交给服务完成修改。
    note = await note_service.update_note(db, note_id, user_id, payload)
    if note is None:
        return success_response(message="笔记不存在")
    return success_response(message="笔记更新成功", data=NoteResponse.model_validate(note))


@note_router.put("/{note_id}/pin")
async def toggle_pin(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    note = await note_service.toggle_pin(db, note_id, user_id)
    if note is None:
        return success_response(message="笔记不存在")
    return success_response(message="置顶已更新", data=NoteResponse.model_validate(note))


@note_router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    deleted = await note_service.delete_note(db, note_id, user_id)
    if not deleted:
        return success_response(message="笔记不存在")
    return success_response(message="笔记删除成功")
```

### 核对文件：`backend/app/router/user.py`

完整地址：

```text
./backend/app/router/user.py
```

职责：用户接口；把 HTTP 参数、依赖、服务和响应接起来。

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.db_config import get_db
from app.schemas.user_schemas import LoginRequest, RegisterRequest, UserResponse
from app.services.user_service import user_service
from app.utils.auth_utils import generate_token

user_router = APIRouter(prefix="/user", tags=["user"])


@user_router.post("/register/")
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await user_service.register(db, payload)
    token, _expires_at = generate_token(user.uuid, user.username, user.email)
    return {
        "status": 201,
        "message": f"{user.username} 注册成功",
        "user": UserResponse.model_validate(user).model_dump(mode="json"),
        "token": token,
    }


@user_router.post("/login/")
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    user = await user_service.authenticate(
        db, payload.username, str(payload.email) if payload.email else None,
        payload.password,
    )
    token, _expires_at = generate_token(user.uuid, user.username, user.email)
    return {
        "message": f"{user.username} 登录成功",
        "user": UserResponse.model_validate(user).model_dump(mode="json"),
        "token": token,
    }
```

### 核对文件：`backend/app/schemas/__init__.py`

完整地址：

```text
./backend/app/schemas/__init__.py
```

职责：本阶段应用组成部分。

```python
"""HTTP 输入与输出的数据模型。"""
```

### 核对文件：`backend/app/schemas/models.py`

完整地址：

```text
./backend/app/schemas/models.py
```

职责：笔记和模板请求/响应字段校验。

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NoteCreate(BaseModel):
    # 【新增】先处理首尾空白，再检查标题长度。
    title: str = Field(min_length=1, max_length=200)
    content: str
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        return value.strip() if isinstance(value, str) else value
class NoteResponse(BaseModel):
    # 【新增 C01】允许从 ORM 对象属性读取响应字段。
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    content: str
    tags: list[str] | None = None
    category: str | None = None
    is_pinned: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NoteListResponse(BaseModel):
    notes: list[NoteResponse]
    total_count: int


class NoteUpdate(BaseModel):
    # 【新增 C01】所有字段可省略，但明确传 null 有单独约定。
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = None
    category: str | None = Field(default=None, max_length=50)
    tags: list[str] | None = None
    is_pinned: bool | None = None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def reject_null_for_required_columns(self):
        for name in ("title", "content", "is_pinned"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} 不能显式设为 null")
        return self
```

### 核对文件：`backend/app/schemas/user_schemas.py`

完整地址：

```text
./backend/app/schemas/user_schemas.py
```

职责：HTTP 输入输出边界；验证请求，控制响应公开字段。

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
    confirm_password: str
    telephone: str | None = Field(default=None, max_length=11)


class LoginRequest(BaseModel):
    username: str | None = None
    email: EmailStr | None = None
    password: str = Field(min_length=6, max_length=72)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    uuid: str
    username: str
    email: EmailStr
    telephone: str | None = None
    gender: int | None = None
    bio: str | None = None
    avatar: str | None = None
    status: int
    date_joined: datetime | None = None
    last_login: datetime | None = None
    is_active: bool
```

### 核对文件：`backend/app/services/__init__.py`

完整地址：

```text
./backend/app/services/__init__.py
```

职责：本阶段应用组成部分。

```python
"""笔记等业务处理逻辑。"""
```

### 核对文件：`backend/app/services/note_service.py`

完整地址：

```text
./backend/app/services/note_service.py
```

职责：本阶段应用组成部分。

```python
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failed_response import BusinessException
from app.models.note import Note
from app.schemas.models import NoteCreate, NoteUpdate


class NoteService:
    async def create_note(
        self, db: AsyncSession, user_id: str, payload: NoteCreate
    ) -> Note:
        # 【新增】字段来源明确，归属取服务端依赖，不信任客户端 user_id。
        note = Note(
            id=str(uuid4()),
            user_id=user_id,
            title=payload.title,
            content=payload.content,
            tags=payload.tags,
            category=payload.category,
        )
        db.add(note)
        await db.commit()
        await db.refresh(note)
        return note

    async def get_note(
        self, db: AsyncSession, note_id: str, user_id: str
    ) -> Note | None:
        statement = select(Note).where(Note.id == note_id, Note.user_id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def list_notes(
        self,
        db: AsyncSession,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
        category: str | None = None,
        tag: str | None = None,
        sort_by: str = "updated_at",
    ) -> tuple[list[Note], int]:
        # 【修改 C01】先建立用户范围，任何后续分支都不能丢掉它。
        conditions = [Note.user_id == user_id]
        if category is not None:
            conditions.append(Note.category == category)

        sort_columns = {
            "updated_at": Note.updated_at,
            "created_at": Note.created_at,
            "title": Note.title,
        }
        if sort_by not in sort_columns:
            raise BusinessException(code=4002, message="不支持的排序字段")
        column = sort_columns[sort_by]
        primary_order = column.asc() if sort_by == "title" else column.desc()
        statement = select(Note).where(*conditions).order_by(primary_order, Note.id.desc())
        offset = (page - 1) * page_size

        if tag is not None:
            # 【新增】先在当前用户/分类候选中精确匹配标签，再计算总数和切页。
            result = await db.execute(statement)
            candidates = list(result.scalars().all())
            matched = [note for note in candidates if tag in (note.tags or [])]
            total_count = len(matched)
            return matched[offset:offset + page_size], total_count

        # 【新增】无标签筛选时，在数据库完成 COUNT、LIMIT 和 OFFSET。
        count_statement = select(func.count(Note.id)).where(*conditions)
        total_count = int((await db.execute(count_statement)).scalar_one())
        result = await db.execute(statement.offset(offset).limit(page_size))
        return list(result.scalars().all()), total_count

    async def update_note(
        self, db: AsyncSession, note_id: str, user_id: str, payload: NoteUpdate
    ) -> Note | None:
        note = await self.get_note(db, note_id, user_id)
        if note is None:
            return None
        # 【新增 C02】只更新请求中明确给出的字段，保留其他值。
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            raise BusinessException(code=4001, message="没有提交可修改字段")
        for name, value in changes.items():
            setattr(note, name, value)
        await db.commit()
        await db.refresh(note)
        return note

    async def delete_note(
        self, db: AsyncSession, note_id: str, user_id: str
    ) -> bool:
        note = await self.get_note(db, note_id, user_id)
        if note is None:
            return False
        await db.delete(note)
        await db.commit()
        return True

    async def toggle_pin(
        self, db: AsyncSession, note_id: str, user_id: str
    ) -> Note | None:
        note = await self.get_note(db, note_id, user_id)
        if note is None:
            return None
        note.is_pinned = not note.is_pinned
        await db.commit()
        await db.refresh(note)
        return note


note_service = NoteService()
```

### 核对文件：`backend/app/services/user_service.py`

完整地址：

```text
./backend/app/services/user_service.py
```

职责：用户业务动作；查询、校验、哈希、提交由这里协调。

```python
from datetime import UTC, datetime

from passlib.context import CryptContext
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.failed_response import BusinessException
from app.models.user_model import User, UserStatusChoice
from app.schemas.user_schemas import RegisterRequest

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return pwd_context.verify(password, hashed_password)


class UserService:
    async def register(self, db: AsyncSession, payload: RegisterRequest) -> User:
        if payload.password != payload.confirm_password:
            raise BusinessException(code=4001, message="两次密码不一致")
        conditions = [User.email == str(payload.email)]
        if payload.telephone:
            conditions.append(User.telephone == payload.telephone)
        existing = await db.execute(select(User).where(or_(*conditions)))
        if existing.scalars().first() is not None:
            raise BusinessException(code=4002, message="邮箱或手机号已被注册")

        user = User(
            username=payload.username,
            email=str(payload.email),
            telephone=payload.telephone,
            password=hash_password(payload.password),
            status=UserStatusChoice.ACTIVE,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user

    async def authenticate(self, db: AsyncSession, username: str | None,
                           email: str | None, password: str) -> User:
        identity = username or email
        if not identity:
            raise BusinessException(code=4001, message="请输入用户名或邮箱")
        result = await db.execute(
            select(User).where(or_(User.username == identity, User.email == identity))
        )
        user = result.scalars().first()
        if user is None or not verify_password(password, user.password):
            raise BusinessException(code=4002, message="用户名或密码错误")
        if user.status != UserStatusChoice.ACTIVE or not user.is_active:
            raise BusinessException(code=4003, message="用户不可登录")
        user.last_login = datetime.now(UTC).replace(tzinfo=None)
        await db.commit()
        await db.refresh(user)
        return user


user_service = UserService()
```

### 核对文件：`backend/app/utils/__init__.py`

完整地址：

```text
./backend/app/utils/__init__.py
```

职责：本阶段应用组成部分。

```python
"""可复用的依赖与小工具。"""
```

### 核对文件：`backend/app/utils/auth_utils.py`

完整地址：

```text
./backend/app/utils/auth_utils.py
```

职责：令牌签发、解码、鉴权与撤销的集中实现。

```python
import time
from uuid import uuid4

from jose import JWTError, jwt

from app.core.settings import settings

DEMO_USER_ID = "learning-user"


async def get_current_user_id() -> str:
    # 第 09 篇将这里替换为验证 Bearer token 的依赖。
    return DEMO_USER_ID


def generate_token(user_id: str, username: str, email: str) -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + 24 * 60 * 60
    token = jwt.encode(
        {"user_id": user_id, "username": username, "email": email,
         "iat": now, "exp": expires_at, "jti": str(uuid4())},
        settings.SECRET_KEY.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
    return token, expires_at


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY.get_secret_value(),
            algorithms=[settings.ALGORITHM],
        )
    except JWTError:
        return None
```

### 核对文件：`backend/main.py`

完整地址：

```text
./backend/main.py
```

职责：FastAPI 实例与路由总装入口。

```python
from fastapi import FastAPI

from app.core.failed_response_register import register_exception_handlers
from app.core.lifespan import lifespan
from app.core.settings import settings
from app.router.health import health_router
from app.router.note_router import note_router
from app.router.user import user_router

# 【修改 C01】应用启动检查和关闭清理由 lifespan 管理。
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.include_router(health_router)
# 【新增 C01】把笔记接口组注册到同一个应用。
app.include_router(note_router)
# 【新增 C01】注册用户相关接口。
app.include_router(user_router)
register_exception_handlers(app)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Hello World"}


@app.get("/hello/{name}")
async def say_hello(name: str) -> dict[str, str]:
    return {"message": f"Hello {name}"}


@app.get("/health")
async def health_check() -> dict[str, str]:
    return {"message": "The service is healthy"}
```

## 8. 函数调用索引：从定义跳回执行链

下面用本阶段最终代码生成索引。查某个动作时，先定位定义，再沿着 `Depends` 或显式调用寻找上一层。这里的行号以本篇核对册源码为准。

### `backend/app/core/failed_response.py:15` → `business_exception_handler`

- **输入**：request, exc。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `business_exception_handler(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/core/failed_response.py:23` → `http_exception_handler`

- **输入**：request, exc。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `http_exception_handler(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/core/failed_response.py:35` → `validation_exception_handler`

- **输入**：request, exc。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `validation_exception_handler(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/core/failed_response_register.py:13` → `register_exception_handlers`

- **输入**：app。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `register_exception_handlers(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/core/lifespan.py:10` → `lifespan`

- **输入**：app。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `lifespan(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/core/success_response.py:5` → `success_response`

- **输入**：message, data。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `success_response(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/db/db_config.py:35` → `get_db`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `get_db(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/db/db_config.py:45` → `check_mysql_connection`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `check_mysql_connection(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/db/db_config.py:54` → `init_db`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `init_db(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/health.py:11` → `get_health_application_status`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `get_health_application_status(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/health.py:19` → `get_health_readiness`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `get_health_readiness(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/note_router.py:17` → `create_note`

- **输入**：payload, user_id, db。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `create_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/note_router.py:27` → `list_notes`

- **输入**：user_id, db, page, page_size, category, tag, sort_by。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `list_notes(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/note_router.py:48` → `get_note`

- **输入**：note_id, user_id, db。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `get_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/note_router.py:60` → `update_note`

- **输入**：note_id, payload, user_id, db。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `update_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/note_router.py:74` → `toggle_pin`

- **输入**：note_id, user_id, db。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `toggle_pin(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/note_router.py:86` → `delete_note`

- **输入**：note_id, user_id, db。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `delete_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/user.py:13` → `register`

- **输入**：payload, db。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：有；检查 JWT 或 Redis 访问。
- **找调用方**：搜索 `register(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/router/user.py:28` → `login`

- **输入**：payload, db。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：有；检查 JWT 或 Redis 访问。
- **找调用方**：搜索 `login(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/schemas/models.py:15` → `normalize_title`

- **输入**：value。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `normalize_title(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/schemas/models.py:47` → `normalize_title`

- **输入**：value。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `normalize_title(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/schemas/models.py:51` → `reject_null_for_required_columns`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `reject_null_for_required_columns(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/note_service.py:12` → `create_note`

- **输入**：db, user_id, payload。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `create_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/note_service.py:29` → `get_note`

- **输入**：db, note_id, user_id。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `get_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/note_service.py:36` → `list_notes`

- **输入**：db, user_id, page, page_size, category, tag, sort_by。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `list_notes(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/note_service.py:77` → `update_note`

- **输入**：db, note_id, user_id, payload。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `update_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/note_service.py:93` → `delete_note`

- **输入**：db, note_id, user_id。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `delete_note(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/note_service.py:103` → `toggle_pin`

- **输入**：db, note_id, user_id。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `toggle_pin(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/user_service.py:14` → `hash_password`

- **输入**：password。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `hash_password(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/user_service.py:18` → `verify_password`

- **输入**：password, hashed_password。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `verify_password(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/user_service.py:23` → `register`

- **输入**：db, payload。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `register(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/services/user_service.py:46` → `authenticate`

- **输入**：db, username, email, password。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：有；检查查询范围和提交时刻。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `authenticate(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/utils/auth_utils.py:11` → `get_current_user_id`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：有；检查 JWT 或 Redis 访问。
- **找调用方**：搜索 `get_current_user_id(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/utils/auth_utils.py:16` → `generate_token`

- **输入**：user_id, username, email。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：有；检查 JWT 或 Redis 访问。
- **找调用方**：搜索 `generate_token(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/app/utils/auth_utils.py:28` → `decode_token`

- **输入**：token。
- **执行性质**：同步，调用后在当前调用栈执行。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：有；检查 JWT 或 Redis 访问。
- **找调用方**：搜索 `decode_token(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/main.py:22` → `root`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `root(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/main.py:27` → `say_hello`

- **输入**：name。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `say_hello(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

### `backend/main.py:32` → `health_check`

- **输入**：无显式参数；可能读取模块配置或被框架调用。
- **执行性质**：异步，需要 await 或框架调度。
- **数据库参与**：本函数体没有直接操作请求级会话。
- **缓存/令牌参与**：本函数体没有直接管理令牌或 Redis。
- **找调用方**：搜索 `health_check(`，若由路由装饰器或 `Depends` 注册，检查同文件上方声明。

## 9. 故障定位与完成核对

| 现象 | 先查哪里 | 为什么 |
|---|---|---|
| `ModuleNotFoundError` | 本篇依赖安装命令、`backend/.venv` | Python 可能用了另一个虚拟环境。|
| 422 | 请求模型、JSON 字段名、`Content-Type` | 输入在进入业务服务前就被拦截。|
| 401 | Authorization 头、签名密钥、用户状态、黑名单 | 鉴权依赖先于业务函数执行。|
| 503 | `/ready`、MySQL/Redis 容器和日志 | 下游依赖不可用或策略选择拒绝继续。|
| 500 | 后端终端 traceback 首个项目路径 | 文件导入、表结构或事务操作可能不匹配。|
| Docker daemon 未启动 | Docker Desktop 状态、`docker info` | Compose 需要 Docker 引擎运行。|

本篇实际新增能力：注册成功与登录成功都能拿到有期限的签名令牌。
这一步与参考实现的阶段差异：这一篇笔记接口仍使用演示身份；第 09 篇切换到令牌身份。
核对每个文件的绝对路径、新建文件的完整代码、修改文件的 diff 与本篇接口；确认上一阶段行为仍可用。
本套教材只写入上一级 docs；除非你按本文操作，正式复刻项目不会自动进入本阶段。

