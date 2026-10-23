# Q09｜为什么令牌状态放在 Redis？

**对应位置：** `backend/app/db/redis_config.py` 管连接；`app/utils/auth_utils.py` 使用 `blacklist:{jti}`；第 10 篇接入服务，第 11–12 篇接入注销和一次性刷新。

## TTL 与原子操作怎样协作

JWT 中的 `jti` 是单枚令牌的编号。注销时，代码执行 `SET blacklist:{jti} 1 EX <剩余秒数>`；之后鉴权看到该键就拒绝请求。令牌原本也会在 `exp` 到期，所以黑名单键只需要活到那时。Redis 的 `SET` 支持同时设置值和过期时间，TTL 到期后键会失效。[Redis SET 命令](https://redis.io/docs/latest/commands/set/)、[Redis EXPIRE 命令](https://redis.io/docs/latest/commands/expire/)

刷新令牌时使用 `SET ... NX`：只有键还不存在的第一位请求者能创建它。想象只有一张可领取的新票，多个窗口同时伸手，Redis 原子地决定谁先拿到；若先用 `EXISTS` 再用普通 `SET`，两个并发请求都可能在间隙里认为票还在。本项目把 Redis 不可用时的鉴权返回设计为 503，避免“查不了黑名单就放行”。

## 与同类状态存储比较

| 路线 | 优点 | 局限 | 本项目的判断 |
|---|---|---|---|
| Redis | 键值查询、带 TTL 的临时状态和条件写入很直接 | 增加服务依赖；持久性要配置和验证 | 用于短期令牌状态 |
| Python 进程内字典 | 写法简单，无额外服务 | 多进程不共享，重启丢失，过期清理需自写 | 不适合真实注销状态 |
| MySQL 状态表 | 与用户数据共用持久数据库 | 高频短期状态需清理和索引策略 | 可作为另一种设计，当前参考实现未选 |

Compose 中的 Redis 配置了数据卷与 AOF；Redis 官方说明 AOF 通过记录写入来恢复数据。**这不等于已经验证所有重启或卷重建场景**，相关边界仍按教程验证记录表述。[Redis 持久化说明](https://redis.io/docs/latest/management/persistence/)

**职责边界：** MySQL 保存用户和笔记的长期业务数据；Redis 在这里保存短期、可过期的令牌状态。不要因为两个服务都能存数据就随意互换它们的角色。
