# AutoRAG 离线对比（股票课程语料）

这组实验用于回答一个具体问题：**在这套中文课程语料上，BM25、向量、混合与重排应该怎么选。**
它和仓库根目录的 `eval/` 是两套东西：

| | 本目录 | `eval/` |
|---|---|---|
| 目的 | 选配置、比较模块组合 | 防回归、改代码后快速验证 |
| 数据 | 24 份课程 PDF 的 OCR 文本 | 项目文档（3 份 Markdown） |
| 规模 | 190 切片 / 120 题（80 调参 + 40 测试） | 80 切片 / 60 题 |
| 运行 | AutoRAG 0.3.27 | 仓库内 Python 脚本 |

## 数据

| 项 | 值 |
|---|---|
| 原始 PDF | 24 份，扫描件，共 132 MB |
| OCR | macOS Vision，368 页、123,834 字 |
| 切片 | 复用 `split_structured`，190 片，平均 655 字 |
| 题目 | 120 条：50 可答 + 10 不可答 + 60 条补充（最终 80/40 分层） |

> 原始 PDF 体积大且有版权，**没有提交到 Git**；如果本地存在，会放在仓库的 `data/stock-pdfs/`（已忽略）。
> 复现不需要 PDF：`corpus/` 里是 OCR 后的 24 份 Markdown。

题目构造：

1. 模型从切片出题，`quote` 必须是切片中的连续原文；
2. 脚本回查引文；
3. 人工剔除 14 条“涨幅 / 换手 / 收盘价”等行情数值题，以及 9 条界面字段、指标参数类低质量题；
4. 补入 23 条条件 / 流程 / 对比题，最终 120 条。

`dataset/qa.jsonl` 保留完整字段；`qa.train.parquet` / `qa.test.parquet` 是 AutoRAG 直接可读的 80/40 划分。

## 环境

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install "AutoRAG==0.3.27" python-dotenv pandas pyarrow \
  llama-index-llms-openai-like llama-index-embeddings-openai-like
```

根目录 `.env` 至少需要：

```dotenv
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
EMBEDDING_API_KEY=sk-xxx
EMBEDDING_BASE_URL=https://your-endpoint/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSIONS=512
```

## 复现

```bash
cd /path/to/MindWeave

# 1) 生成 corpus.parquet
python eval/autorag/scripts/build_corpus.py

# 2) 训练集：检索 / 重排 / 生成
python eval/autorag/scripts/run_eval.py \
  --config eval/autorag/configs/eval-a.yaml \
  --project /tmp/autorag-a --full-ingest

python eval/autorag/scripts/run_eval.py \
  --config eval/autorag/configs/eval-b.yaml \
  --project /tmp/autorag-b

python eval/autorag/scripts/run_eval.py \
  --config eval/autorag/configs/eval-c.yaml \
  --project /tmp/autorag-c

# 3) 测试集：每个项目先删掉训练集 qa，否则 AutoRAG 会继续用旧文件
rm -f /tmp/autorag-a/data/qa.parquet
python eval/autorag/scripts/run_eval.py \
  --config eval/autorag/configs/eval-a-test.yaml \
  --qa eval/autorag/dataset/qa.test.parquet \
  --project /tmp/autorag-a
```

结果在每个 trial 的 `summary.csv`，例如 `/tmp/autorag-a/0/retrieve_node_line/semantic_retrieval/summary.csv`。

## 结果（测试集 40 条）

| 配置 | Recall@3 | Recall@5 | nDCG@3 | nDCG@5 |
|---|---|---|---|---|
| BM25（Qwen tokenizer） | 0.900 | 0.950 | 0.860 | 0.879 |
| 向量（text-embedding-v4） | 0.825 | 0.900 | 0.779 | 0.809 |
| 混合 RRF（w=30） | — | **0.975** | — | 0.877 |
| 向量 top8（重排前） | — | 0.950 | — | 0.835 |
| RankGPT top3（重排后） | **0.950** | — | **0.928** | — |

训练集趋势一致：混合 Recall@5 0.938（向量 0.825），重排把 nDCG@3 从 0.716 提到 0.825。

## 踩过的坑

AutoRAG 0.3.27 有几处和文档不一致，配置里已经绕开：

- prompt maker 的模块名是 `chat_fstring`，不是 `chatfstring` / `chat_f_string`；
- `prompt` 必须写成“列表的列表”（外层候选、内层消息），否则会被拆成多个组合；
- prompt_maker 用 BLEU/ROUGE 时必须显式给 `generator_modules`，否则会去调默认的 GPT-3.5；
- `hybrid_retrieval.top_k` 必须是整数，不能写列表；
- 生成器偶发 `content=None`，需要把 `max_tokens` 提到 4096，或在本地把 `content or ""`；
- 复用 project 目录跑测试集时，先删 `data/qa.parquet`。

## 局限

- 40 条测试集，1 条 = 2.5 个点，置信区间约 ±9 点；
- OCR 对图表、公式有噪声；
- 题目由模型生成、人工只做剔除，没有逐条改写；
- AutoRAG 是逐节点择优，不保证全局最优；
- RankGPT 是 listwise 重排，与线上 pointwise 0–3 打分不等价。
