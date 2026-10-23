# Q08｜为什么登录返回 JWT？

**对应位置：** `backend/app/utils/auth_utils.py` 的 `generate_token()`、`decode_token()`、`get_current_user_id()`；登录接入见[第 08 篇](../08-jwt-login.md)，路由保护见[第 09 篇](../09-protect-notes-with-user.md)。

## 一枚令牌怎样变成当前用户

登录先用密码哈希验证用户，成功后生成带 `user_id`、`iat`、`exp`、`jti` 等声明的 JWT。后续浏览器在 `Authorization: Bearer ...` 中提交令牌。服务端验证签名、限定算法并检查过期时间，然后取 `user_id`；本项目还查 Redis 黑名单和 MySQL 用户状态，最后把真正可用的用户编号交给笔记路由。路由再用这个编号限制数据库查询。

JWT 可以理解为一张带防伪签章的通行证：读到证上写着某个名字不够，还要核验签章、有效期和注销状态。**常见的签名 JWT 不是加密保险箱**；其载荷可被解码，不应写入密码或密钥。JWT 标准定义了用于传递声明的紧凑表示，签名/完整性保护与加密是不同形式。[RFC 7519：JWT](https://www.rfc-editor.org/rfc/rfc7519.html)

## 与其他登录状态路线比较

| 路线 | 每次请求怎样确认身份 | 优势 | 需要处理的问题 |
|---|---|---|---|
| 签名 JWT | 验签并检查声明；本项目还查 Redis 和用户表 | 各服务可验证已签名声明 | 立即注销和状态变更需要额外设计 |
| 服务端 Session | 客户端只持随机会话 ID，服务端查会话记录 | 服务端易集中撤销 | 依赖会话存储及其可用性 |
| 不透明随机令牌 | 客户端只持随机 token，服务端查映射 | 客户端不携带可读声明 | 每次验证通常需要服务端查询 |

OWASP 对服务端 Session 的说明强调，会话 ID 的业务含义应保存在服务端；会话 ID 或令牌本身被窃取后都可能被冒用。[OWASP Session 管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

**为什么本项目还用 Redis？** 单靠 JWT 的签名和 `exp`，一个已签发且未过期的令牌通常仍可通过离线验签；第 11–12 篇为“注销立即失效”和“一次性刷新”增加服务端状态。因此本项目的实际鉴权已经不是完全无状态的 JWT。
