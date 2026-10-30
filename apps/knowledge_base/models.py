from django.db import models
from apps.workspaces.models import Workspace

class KnowledgeDocument(models.Model):
    class DocType(models.TextChoices):
        FAQ = "FAQ", "Frequently Asked Question"
        ARTICLE = "ARTICLE", "Knowledge Article"
        POLICY = "POLICY", "Company Policy"
        MANUAL = "MANUAL", "Product Manual"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="knowledge_documents")
    title = models.CharField(max_length=255)
    doc_type = models.CharField(max_length=30, choices=DocType.choices, default=DocType.FAQ)
    question = models.TextField(blank=True, help_text="Specific question for FAQ items")
    answer = models.TextField(blank=True, help_text="Specific answer for FAQ items")
    content = models.TextField(blank=True, help_text="Full text content for articles or extracted documents")
    file = models.FileField(upload_to="documents/", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.workspace.name} - [{self.doc_type}] {self.title}"

    def get_searchable_text(self) -> str:
        parts = [self.title]
        if self.question:
            parts.append(self.question)
        if self.answer:
            parts.append(self.answer)
        if self.content:
            parts.append(self.content)
        return "\n".join(parts)


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    chunk_index = models.PositiveIntegerField(default=0)
    content = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["document", "chunk_index"]

    def __str__(self):
        return f"Chunk #{self.chunk_index} for Doc #{self.document_id}"

