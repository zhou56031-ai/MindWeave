"""运行一个 AutoRAG trial（默认训练集）。"""
import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

from autorag import LazyInit, generator_models  # noqa: E402
from autorag.embedding.base import embedding_models  # noqa: E402
from llama_index.embeddings.openai_like import OpenAILikeEmbedding  # noqa: E402
from llama_index.llms.openai_like import OpenAILike  # noqa: E402

embedding_models["qwen"] = LazyInit(
    OpenAILikeEmbedding,
    model_name=os.environ["EMBEDDING_MODEL"],
    api_base=os.environ["EMBEDDING_BASE_URL"],
    api_key=os.environ["EMBEDDING_API_KEY"],
    dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS", "512")),
)


class DeepSeekChat(OpenAILike):
    """rankGPT 会丢掉 is_chat_model，这里在构造时强制打开。"""

    def __init__(self, model: str, api_base: str, api_key: str,
                 max_tokens: int | None = None, temperature: float = 0.1,
                 reasoning_effort: str | None = "none", **kwargs):
        super().__init__(
            model=model, api_base=api_base, api_key=api_key,
            is_chat_model=True, context_window=128000,
            max_tokens=max_tokens, temperature=temperature,
            reasoning_effort=reasoning_effort, **kwargs,
        )


generator_models["deepseek_chat"] = DeepSeekChat

from autorag.evaluator import Evaluator  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--config", required=True)
parser.add_argument("--qa", default=str(ROOT / "eval/autorag/dataset/qa.train.parquet"))
parser.add_argument("--corpus", default=str(ROOT / "eval/autorag/data/corpus.parquet"))
parser.add_argument("--project", required=True)
parser.add_argument("--full-ingest", action="store_true")
args = parser.parse_args()

Evaluator(
    qa_data_path=args.qa,
    corpus_data_path=args.corpus,
    project_dir=args.project,
).start_trial(args.config, full_ingest=args.full_ingest)
