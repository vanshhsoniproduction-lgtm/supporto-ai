import os
import io
import csv
import logging
from pathlib import Path
from django.core.files.uploadedfile import UploadedFile
from apps.knowledge_base.models import KnowledgeDocument, KnowledgeChunk

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".csv"}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB

class DocumentProcessor:
    @classmethod
    def extract_text(cls, file_obj, filename: str) -> tuple[str, str]:
        """
        Extracts plain text from TXT, MD, PDF, DOCX, CSV.
        Returns: (extracted_text, error_message)
        """
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return ("", f"Unsupported file type '{ext}'. Allowed: TXT, MD, PDF, DOCX, CSV.")

        try:
            # Rewind file buffer if applicable
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)
            content_bytes = file_obj.read() if hasattr(file_obj, "read") else bytes(file_obj)

            if len(content_bytes) > MAX_FILE_SIZE_BYTES:
                return ("", f"File exceeds maximum allowed size of {MAX_FILE_SIZE_BYTES // (1024*1024)} MB.")

            if ext in (".txt", ".md"):
                try:
                    return (content_bytes.decode("utf-8"), "")
                except UnicodeDecodeError:
                    return (content_bytes.decode("latin-1", errors="replace"), "")

            elif ext == ".pdf":
                try:
                    import pypdf
                    reader = pypdf.PdfReader(io.BytesIO(content_bytes))
                    extracted = []
                    for i, page in enumerate(reader.pages):
                        page_text = page.extract_text() or ""
                        if page_text.strip():
                            extracted.append(page_text.strip())
                    full_text = "\n\n".join(extracted)
                    if not full_text.strip():
                        return ("", "PDF contains no extractable text. Scanned document requires OCR which is not supported locally.")
                    return (full_text, "")
                except Exception as e:
                    return ("", f"PDF extraction failed: {str(e)}")

            elif ext == ".docx":
                try:
                    import docx
                    doc = docx.Document(io.BytesIO(content_bytes))
                    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                    full_text = "\n\n".join(paragraphs)
                    return (full_text, "")
                except Exception as e:
                    return ("", f"DOCX extraction failed: {str(e)}")

            elif ext == ".csv":
                try:
                    text_str = content_bytes.decode("utf-8", errors="replace")
                    reader = csv.reader(io.StringIO(text_str))
                    rows = []
                    for row in reader:
                        if any(cell.strip() for cell in row):
                            rows.append(" | ".join(row))
                    return ("\n".join(rows), "")
                except Exception as e:
                    return ("", f"CSV parsing failed: {str(e)}")

        except Exception as e:
            return ("", f"Unexpected error reading file: {str(e)}")

        return ("", "Unknown processing error")

    @classmethod
    def chunk_and_index(cls, document: KnowledgeDocument, chunk_size: int = 500, overlap: int = 100) -> int:
        """Splits document content into indexed KnowledgeChunk records."""
        # Clear existing chunks
        document.chunks.all().delete()

        text = document.content or document.get_searchable_text()
        if not text.strip():
            return 0

        chunks = []
        start = 0
        text_len = len(text)
        idx = 0

        while start < text_len:
            end = min(start + chunk_size, text_len)
            chunk_content = text[start:end].strip()
            if chunk_content:
                chunks.append(
                    KnowledgeChunk(
                        document=document,
                        chunk_index=idx,
                        content=chunk_content,
                        metadata={
                            "start_char": start,
                            "end_char": end,
                            "doc_type": document.doc_type,
                            "title": document.title
                        }
                    )
                )
                idx += 1
            if end >= text_len:
                break
            start += (chunk_size - overlap)

        KnowledgeChunk.objects.bulk_create(chunks)
        return len(chunks)

    @classmethod
    def process_uploaded_document(cls, workspace, file_obj, title: str = None) -> tuple[KnowledgeDocument | None, str]:
        """Validates, extracts, saves, and chunks an uploaded document."""
        filename = getattr(file_obj, "name", "uploaded_document")
        doc_title = title.strip() if title else filename

        text, error = cls.extract_text(file_obj, filename)
        if error:
            return (None, error)

        ext = Path(filename).suffix.lower()
        doc_type = KnowledgeDocument.DocType.POLICY if "policy" in filename.lower() else KnowledgeDocument.DocType.ARTICLE

        doc = KnowledgeDocument.objects.create(
            workspace=workspace,
            title=doc_title,
            doc_type=doc_type,
            content=text,
            file=file_obj,
            is_active=True
        )

        cls.chunk_and_index(doc)
        return (doc, "")

document_processor = DocumentProcessor()

