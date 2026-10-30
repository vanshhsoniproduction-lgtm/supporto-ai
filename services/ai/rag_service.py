import re
import math
from collections import Counter
from apps.knowledge_base.models import KnowledgeDocument, KnowledgeChunk

class RAGService:
    """
    Multi-tenant Retrieval-Augmented Generation (RAG) Service.
    Retrieves knowledge snippets strictly scoped to the requesting workspace.
    Uses an internal lexical/BM25-style keyword search fallback
    over document chunks with metadata tracking.
    """

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [w.lower() for w in re.findall(r"\b\w{2,}\b", text)]

    @classmethod
    def retrieve_context(cls, workspace_id: int, query: str, top_k: int = 3) -> list[dict]:
        """
        Retrieves top_k relevant snippets from active knowledge documents/chunks
        of the specified workspace. Strictly scopes by workspace_id.
        """
        query_tokens = cls._tokenize(query)
        if not query_tokens:
            return []

        # Find active documents for this workspace
        active_docs = KnowledgeDocument.objects.filter(
            workspace_id=workspace_id,
            is_active=True
        ).prefetch_related("chunks")

        scored_items = []

        for doc in active_docs:
            chunks = list(doc.chunks.all())

            # If document has chunks, score individual chunks
            if chunks:
                for chunk in chunks:
                    chunk_tokens = cls._tokenize(chunk.content)
                    if not chunk_tokens:
                        continue
                    counts = Counter(chunk_tokens)
                    score = 0.0
                    for q_term in query_tokens:
                        tf = counts.get(q_term, 0)
                        if tf > 0:
                            title_boost = 2.5 if q_term in doc.title.lower() else 1.0
                            score += (1 + math.log(tf)) * title_boost

                    if score > 0:
                        scored_items.append((score, doc, chunk.content))
            else:
                # Score unchunked or FAQ document directly
                searchable = doc.get_searchable_text()
                doc_tokens = cls._tokenize(searchable)
                if not doc_tokens:
                    continue
                counts = Counter(doc_tokens)
                score = 0.0
                for q_term in query_tokens:
                    tf = counts.get(q_term, 0)
                    if tf > 0:
                        title_boost = 2.5 if q_term in doc.title.lower() else 1.0
                        question_boost = 3.0 if doc.question and q_term in doc.question.lower() else 1.0
                        score += (1 + math.log(tf)) * title_boost * question_boost

                if score > 0:
                    content = f"Q: {doc.question}\nA: {doc.answer}" if doc.doc_type == KnowledgeDocument.DocType.FAQ else doc.content
                    scored_items.append((score, doc, content))

        scored_items.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen_docs = set()
        for score, doc, snippet in scored_items:
            # Prefer diverse docs in top results
            if doc.id in seen_docs and len(results) >= 2:
                continue
            seen_docs.add(doc.id)

            results.append({
                "id": doc.id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "content": snippet[:800],
                "score": round(score, 3)
            })
            if len(results) >= top_k:
                break

        return results

rag_service = RAGService()
