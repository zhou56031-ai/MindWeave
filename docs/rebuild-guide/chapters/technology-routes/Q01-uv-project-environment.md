# Q01｜为什么用 uv 管理这个 Python 项目？

**对应位置：** 复刻项目 `backend/pyproject.toml`、`backend/uv.lock`、`backend/.venv` 和第 01 篇的 `uv run` 命令。本篇讲依赖与解释器选择，不讲 Python 变量或函数语法。

## 它实际解决的问题

写下 `fastapi==0.123.0` 只说明项目需要这个包；真正运行时还要决定它的传递依赖版本、安装到哪个 Python 环境，以及另一台机器怎样装出相同的一组包。可以把 `pyproject.toml` 看成采购要求，`uv.lock` 看成已确定的采购清单，`.venv` 是本项目专用的仓库。`uv run uvicorn main:app ...` 从这个仓库拿解释器和依赖来运行服务。官方文档说明，`uv run` 会检查锁文件与环境是否同步；`--locked` 可以要求锁文件必须已与项目声明一致。[uv 项目与锁文件说明](https://docs.astral.sh/uv/guides/projects/)、[锁定与同步](https://docs.astral.sh/uv/concepts/projects/sync/)

本项目还保留 `requirements.txt`，用于需要传统依赖列表的场合。它由 `uv export --locked ...` 从锁文件生成；平时增加依赖应先运行 `uv add`，不能只手改导出结果。此前出现的 `VIRTUAL_ENV` 路径警告，意思是当前 Shell 激活了另一个项目的虚拟环境；默认项目命令仍会选当前 `backend/.venv`，除非明确使用 `--active`。[uv 项目环境配置](https://docs.astral.sh/uv/concepts/projects/config/)

## 同类方案怎么比

| 路线 | 工作方式 | 更合适的场景 | 在此项目的代价 |
|---|---|---|---|
| `uv` 项目模式 | 项目声明、锁文件、虚拟环境和运行命令放在一条工作流里 | 希望按教程在多台机器复现环境 | 需要学会区分 `pyproject.toml`、`uv.lock` 和导出的 `requirements.txt` |
| `python -m venv` + `pip` | 先建环境，再用 pip 安装依赖 | 很小的脚本、已有 pip 工作流 | 锁定、更新、导出与运行纪律要自行组织 |
| Poetry | 也提供项目声明、锁定和虚拟环境管理 | 团队已有 Poetry 规范 | 本项目已有 uv 锁文件，切换会带来另一套命令和锁文件 |

这不是速度排行榜，也不表示其他工具做不到锁定。这里沿用 uv，是因为复刻目录已有完整的 uv 环境；换工具不会让笔记业务更正确，反而会让教材中的命令与当前工程脱节。

**自己判断时看这三件事：** 新增依赖应改哪里？运行命令最终用哪个解释器？把工程交给别人后能否重建相同环境？如果其中一个答案不清楚，先查环境链路，再排查业务代码。
