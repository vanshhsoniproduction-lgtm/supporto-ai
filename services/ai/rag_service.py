import re
import math
from collections import Counter
from apps.knowledge_base.models import KnowledgeDocument, KnowledgeChunk

class RAGService:
    """
    Multi-tenant Retrieval-Augmented Generation (RAG) Service.
    Retrieves documents strictly scoped to the requesting workspace.
    Uses an internal lexical/BM25-style keyword search fallback
    with pluggable interface for dense vector embeddings.
    """

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return [w.lower() for w in re.findall(r"\b\w{2,}\b", text)]

    @classmethod
    def retrieve_context(cls, workspace_id: int, query: str, top_k: int = 3) -> list[dict]:
        """
        Retrieves top_k relevant snippets from active knowledge documents of the specified workspace.
        Strictly scopes by workspace_id to guarantee tenant isolation.
        """
        query_tokens = cls._tokenize(query)
        if not query_tokens:
            return []

        docs = KnowledgeDocument.objects.filter(
            workspace_id=workspace_id,
            is_active=True
        )

        scored_docs = []
        for doc in docs:
            searchable = doc.get_searchable_text()
            doc_tokens = cls._tokenize(searchable)
            if not doc_tokens:
                continue

            doc_counts = Counter(doc_tokens)
            score = 0.0

            # Lexical BM25-inspired term overlap
            for q_term in query_tokens:
                tf = doc_counts.get(q_term, 0)
                if tf > 0:
                    # Boost exact matches in title or question
                    title_boost = 2.5 if q_term in doc.title.lower() else 1.0
                    question_boost = 3.0 if doc.question and q_term in doc.question.lower() else 1.0
                    score += (1 + math.log(tf)) * title_boost * question_boost

            if score > 0:
                scored_docs.append((score, doc))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc in scored_docs[:top_k]:
            if doc.doc_type == KnowledgeDocument.DocType.FAQ:
                content = f"Q: {doc.question}\nA: {doc.answer}"
            else:
                content = doc.content if doc.content else doc.title

            results.append({
                "id": doc.id,
                "title": doc.title,
                "doc_type": doc.doc_type,
                "content": content[:800],
                "score": round(score, 3)
            })

        return results

rag_service = RAGService()

