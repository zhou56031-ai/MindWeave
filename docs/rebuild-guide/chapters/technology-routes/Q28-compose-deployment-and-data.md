# Q28：Docker Compose 单机部署、健康检查与持久数据

## 1. 原理与本项目的使用

第 53 篇让 MySQL、Redis、Neo4j、FastAPI、图 Worker 与已复制的前端一起运行。Compose 用服务名连接容器，用 healthcheck 区分“容器已经启动”和“依赖可以响应”；MySQL/Redis 数据卷、Neo4j 卷、PDF 图片卷和模型缓存卷各自保存状态。Docker 官方说明 depends_on 的 service_healthy 才会等待被依赖项的健康检查；普通 service_started 只等容器启动。[Docker Compose 启动顺序](https://docs.docker.com/compose/how-tos/startup-order/)、[持久卷](https://docs.docker.com/engine/storage/volumes/)。

## 2. 同类技术路线对比

| 路线 | 适合的情况 | 代价或边界 |
|---|---|---|
| 宿主机分别启动服务 | 调试路径短 | 环境差异和进程管理较多 |
| Docker Compose 单机 | 本项目复刻与小规模联调 | 单机故障、备份和扩容需另做 |
| Kubernetes/编排平台 | 多实例、滚动更新 | 运维与成本远超本阶段 |
| 托管数据库 + 容器应用 | 降低数据库运维 | 费用、网络和凭据管理变化 |

## 3. 工程边界与面试追问

前端 Dockerfile/NGINX 直接复用参考源码；后端镜像不内置 .env，运行时注入。数据卷不是备份：误删卷、磁盘损坏或错误迁移仍会丢数据；要定期导出 MySQL、Neo4j 和图片目录，并做恢复演练。/health/live 测进程，/health/ready 测 MySQL/Redis，图 Worker 还需独立观察任务推进。面试官若问重启后任务如何恢复，回答应同时说明 MySQL 工单持久、超时 running 回收与幂等写图。

