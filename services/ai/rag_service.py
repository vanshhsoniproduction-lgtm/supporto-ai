import re
import math
from collections import Counter
from apps.knowledge_base.models import KnowledgeDocument, KnowledgeChunk

STOPWORDS = {
    "a", "about", "all", "an", "and", "any", "are", "as", "at", "be", "been", "but",
    "by", "can", "do", "does", "for", "from", "get", "has", "have", "how", "i", "if",
    "in", "is", "it", "its", "me", "much", "my", "no", "not", "of", "on", "or", "our",
    "so", "tell", "that", "the", "their", "there", "this", "to", "was", "we", "what",
    "when", "where", "which", "who", "will", "with", "would", "you", "your"
}

class RAGService:
    """
    Multi-tenant Retrieval-Augmented Generation (RAG) Service.
    Retrieves knowledge snippets strictly scoped to the requesting workspace.
    Uses tokenized TF-IDF scoring over document chunks with metadata tracking,
    stopword filtering, and minimum score gating.
    """

    MIN_SCORE_THRESHOLD = 1.5

    @classmethod
    def _tokenize(cls, text: str, filter_stops: bool = True) -> list[str]:
        tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_-]{2,}\b", text)]
        if filter_stops:
            filtered = [t for t in tokens if t not in STOPWORDS]
            return filtered if filtered else tokens
        return tokens

    @classmethod
    def retrieve_context(cls, workspace_id: int, query: str, top_k: int = 3) -> list[dict]:
        """
        Retrieves top_k relevant snippets from active knowledge documents/chunks
        of the specified workspace. Strictly scopes by workspace_id.
        Enforces MIN_SCORE_THRESHOLD to prevent hallucinated matches.
        """
        query_tokens = cls._tokenize(query)
        if not query_tokens:
            return []

        active_docs = KnowledgeDocument.objects.filter(
            workspace_id=workspace_id,
            is_active=True
        ).prefetch_related("chunks")

        scored_items = []

        for doc in active_docs:
            chunks = list(doc.chunks.all())

            if chunks:
                for chunk in chunks:
                    chunk_tokens = cls._tokenize(chunk.content, filter_stops=False)
                    if not chunk_tokens:
                        continue
                    counts = Counter(chunk_tokens)
                    score = 0.0
                    for q_term in query_tokens:
                        tf = counts.get(q_term, 0)
                        if tf > 0:
                            title_boost = 3.0 if q_term in doc.title.lower() else 1.0
                            score += (1 + math.log(tf)) * title_boost

                    if score >= cls.MIN_SCORE_THRESHOLD:
                        scored_items.append((score, doc, chunk.content))
            else:
                searchable = doc.get_searchable_text()
                doc_tokens = cls._tokenize(searchable, filter_stops=False)
                if not doc_tokens:
                    continue
                counts = Counter(doc_tokens)
                score = 0.0
                for q_term in query_tokens:
                    tf = counts.get(q_term, 0)
                    if tf > 0:
                        title_boost = 3.0 if q_term in doc.title.lower() else 1.0
                        question_boost = 2.5 if doc.question and q_term in doc.question.lower() else 1.0
                        score += (1 + math.log(tf)) * title_boost * question_boost

                if score >= cls.MIN_SCORE_THRESHOLD:
                    content = f"Q: {doc.question}\nA: {doc.answer}" if doc.doc_type == KnowledgeDocument.DocType.FAQ else doc.content
                    scored_items.append((score, doc, content))

        scored_items.sort(key=lambda x: x[0], reverse=True)

        results = []
        seen_docs = set()
        for score, doc, snippet in scored_items:
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
