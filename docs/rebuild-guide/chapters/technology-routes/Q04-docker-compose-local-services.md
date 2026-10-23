# Q04｜为什么用 Docker Compose 启动 MySQL 和 Redis？

**对应位置：** 复刻根目录 `docker-compose.yml`；MySQL 首次接入见[第 03 篇](../03-mysql-and-async-session.md)，Redis 接入见[第 10 篇](../10-redis-and-readiness.md)。当前 Python 后端仍由本机 `uv run uvicorn` 启动，Compose 主要管理依赖服务。

## 从一份 YAML 到两个可连接的服务

Compose 文件声明 `mysql`、`redis` 两个服务、镜像、环境变量、端口、健康检查和数据卷。执行 `docker compose up -d --wait` 时，**Docker daemon** 实际创建容器、网络和卷；Compose CLI 负责按这份定义发命令。所以“找不到 Docker daemon”是容器引擎未可用，与 Python 代码无关。`${MYSQL_PASSWORD:?...}` 则在启动前由 Compose 读取根目录 `.env` 并插值；变量缺失会在创建容器前失败。Docker 官方把 Compose 定义为通过 YAML 管理多容器应用和生命周期的工具。[Docker Compose 概览](https://docs.docker.com/compose/)、[应用模型](https://docs.docker.com/compose/intro/compose-application-model/)

`127.0.0.1:13306:3306` 的左侧是宿主机地址与端口，右侧是 MySQL 容器端口；`mysql_data:/var/lib/mysql` 让数据库文件不随容器进程停止而立即消失。卷也不是自动备份，删除卷或损坏数据仍会造成损失。

## 与其他本地路线比较

| 路线 | 好处 | 需要承担的事 | 适用情况 |
|---|---|---|---|
| Compose | 一份配置同时描述 MySQL、Redis、端口和卷 | 需要 Docker daemon、镜像与磁盘空间 | 本复刻项目的本地依赖服务 |
| 本机直接安装 | 少一层容器映射 | 自行管理版本、服务启动、端口和数据目录 | 机器上已有稳定数据库服务 |
| 逐个 `docker run` | 能精确控制单个容器命令 | 多服务配置、网络和卷参数容易分散 | 只做单容器短实验 |

**本项目选择 Compose 的原因：** 参考项目要同时依赖多个服务，复刻还需避开参考实例的端口和数据。把这些配置集中到一份文件，读者能看到“应用究竟连哪里”。遇到 503 时，先分辨是 Compose 未启动、服务未健康、端口映射错误，还是后端自身连接设置错误。
