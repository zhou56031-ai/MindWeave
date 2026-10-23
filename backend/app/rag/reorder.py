"""对调用方给出的少量候选做本地向量二次排序。"""

from app.rag.embedding import embed_many
from app.rag.related import cosine


async def reorder(query: str, documents: list[str]) -> list[dict]:
    if not documents:
        return []
    texts = [query, *[document[:2000] for document in documents]]
    vectors = await embed_many(texts)
    query_vector = vectors[0]
    ranked = []
    for index, (document, vector) in enumerate(zip(documents, vectors[1:])):
        score = cosine(query_vector, vector)
        ranked.append((
            index,
            {"document": document, "similarity": round(score, 4)},
        ))
    ranked.sort(key=lambda item: (-item[1]["similarity"], item[0]))
    return [item for _, item in ranked]
