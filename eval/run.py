"""跑完整评测并生成 eval/results/report.md。"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"


def run(script: str) -> None:
    result = subprocess.run([str(PYTHON), str(ROOT / "eval" / script)], cwd=ROOT)
    if result.returncode != 0:
        raise SystemExit(f"{script} 失败")


def main() -> None:
    run("validate.py")
    run("retrieval.py")
    run("e2e.py")

    retrieval = json.loads((ROOT / "eval/results/retrieval.json").read_text(encoding="utf-8"))
    e2e = json.loads((ROOT / "eval/results/e2e.json").read_text(encoding="utf-8"))
    lines = [
        "# 仓库内评测报告", "",
        "数据：demo-docs + 设计系统 + 功能全景，共 80 个切片；60 条问题（50 可答 + 10 不可答）。", "",
        "## 检索", "",
        "| 指标 | 值 |", "|---|---|",
        f"| Recall@3 | {retrieval['recall@3']} |",
        f"| Recall@5 | {retrieval['recall@5']} |",
        f"| MRR@5 | {retrieval['mrr@5']} |", "",
        "| 来源 | 条数 | Recall@3 | Recall@5 |", "|---|---|---|---|",
    ]
    for name, value in retrieval["per_file"].items():
        lines.append(f"| {name} | {value['n']} | {value['recall@3']} | {value['recall@5']} |")
    lines += [
        "", "## 端到端", "",
        "| 指标 | 值 |", "|---|---|",
        f"| 可答样本 | {e2e['answerable']} |",
        f"| 不可答样本 | {e2e['negative']} |",
        f"| 引用捏造 | {e2e['fabricated_citations']} |",
        f"| 拒答正确率 | {e2e['refusal_accuracy']} |", "",
        "> 局限：题库由模型生成后按引文回查，未逐条人工改写；60 条只用于回归，不用于宣称绝对水平。",
    ]
    (ROOT / "eval/results/report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("report -> eval/results/report.md")


if __name__ == "__main__":
    main()
