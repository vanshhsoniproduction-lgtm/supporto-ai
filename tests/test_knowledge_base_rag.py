import io
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.workspaces.models import Workspace
from apps.knowledge_base.models import KnowledgeDocument, KnowledgeChunk
from apps.knowledge_base.services.document_processor import DocumentProcessor
from services.ai.rag_service import rag_service

class KnowledgeBaseRAGTests(TestCase):
    def setUp(self):
        self.workspace1 = Workspace.objects.create(name="ShopEase", slug="shopease")
        self.workspace2 = Workspace.objects.create(name="OtherCorp", slug="othercorp")

    def test_extract_text_txt(self):
        content = b"This is a standard return policy. Returns accepted within 30 days."
        file_obj = io.BytesIO(content)
        text, err = DocumentProcessor.extract_text(file_obj, "policy.txt")
        self.assertEqual(err, "")
        self.assertIn("Returns accepted within 30 days", text)

    def test_extract_text_md(self):
        content = b"# Shipping FAQ\n\nStandard shipping takes 3-5 business days."
        file_obj = io.BytesIO(content)
        text, err = DocumentProcessor.extract_text(file_obj, "shipping.md")
        self.assertEqual(err, "")
        self.assertIn("Standard shipping takes 3-5 business days", text)

    def test_extract_text_csv(self):
        content = b"Question,Answer\nHow to track order?,Visit shopease.com/track\nWhat payment methods?,Visa MasterCard"
        file_obj = io.BytesIO(content)
        text, err = DocumentProcessor.extract_text(file_obj, "faq.csv")
        self.assertEqual(err, "")
        self.assertIn("How to track order?", text)
        self.assertIn("shopease.com/track", text)

    def test_extract_unsupported_extension(self):
        content = b"Binary data"
        file_obj = io.BytesIO(content)
        text, err = DocumentProcessor.extract_text(file_obj, "archive.zip")
        self.assertIn("Unsupported file type", err)
        self.assertEqual(text, "")

    def test_scanned_pdf_ocr_error_reporting(self):
        # A mock PDF stream with empty extracted text
        # DocumentProcessor handles empty pdf extract by raising scanned doc OCR message
        import pypdf
        writer = pypdf.PdfWriter()
        # Add a blank page
        writer.add_blank_page(width=100, height=100)
        pdf_bytes = io.BytesIO()
        writer.write(pdf_bytes)
        pdf_bytes.seek(0)

        text, err = DocumentProcessor.extract_text(pdf_bytes, "scanned.pdf")
        self.assertIn("Scanned document requires OCR", err)
        self.assertEqual(text, "")

    def test_chunking_creates_knowledge_chunks(self):
        long_content = "Paragraph 1 about refunds. " * 50
        doc = KnowledgeDocument.objects.create(
            workspace=self.workspace1,
            title="Refund Guidelines",
            doc_type=KnowledgeDocument.DocType.ARTICLE,
            content=long_content,
            is_active=True,
        )
        chunk_count = DocumentProcessor.chunk_and_index(doc, chunk_size=200, overlap=50)
        self.assertGreater(chunk_count, 1)
        self.assertEqual(doc.chunks.count(), chunk_count)
        first_chunk = doc.chunks.first()
        self.assertEqual(first_chunk.document.workspace, self.workspace1)
        self.assertIn("refunds", first_chunk.content.lower())

    def test_rag_service_workspace_tenant_isolation(self):
        # Create knowledge doc for workspace 1
        doc1 = KnowledgeDocument.objects.create(
            workspace=self.workspace1,
            title="ShopEase Warranty Guide",
            doc_type=KnowledgeDocument.DocType.ARTICLE,
            content="ShopEase offers a full 2-year warranty on all electronics and premium hardware.",
            is_active=True,
        )
        DocumentProcessor.chunk_and_index(doc1)

        # Create knowledge doc for workspace 2
        doc2 = KnowledgeDocument.objects.create(
            workspace=self.workspace2,
            title="OtherCorp Secret Manual",
            doc_type=KnowledgeDocument.DocType.ARTICLE,
            content="OtherCorp confidential warranty details. Proprietary internal info.",
            is_active=True,
        )
        DocumentProcessor.chunk_and_index(doc2)

        # Query workspace 1
        w1_results = rag_service.retrieve_context(workspace_id=self.workspace1.id, query="warranty electronics")
        self.assertTrue(len(w1_results) > 0)
        self.assertEqual(w1_results[0]["title"], "ShopEase Warranty Guide")
        self.assertIn("2-year warranty", w1_results[0]["content"])

        # Ensure workspace 1 NEVER gets results from workspace 2
        w1_leak_query = rag_service.retrieve_context(workspace_id=self.workspace1.id, query="OtherCorp Secret Manual confidential")
        for res in w1_leak_query:
            self.assertNotEqual(res["title"], "OtherCorp Secret Manual")
            self.assertNotIn("Proprietary internal info", res["content"])

        # Query workspace 2
        w2_results = rag_service.retrieve_context(workspace_id=self.workspace2.id, query="confidential warranty")
        self.assertTrue(len(w2_results) > 0)
        self.assertEqual(w2_results[0]["title"], "OtherCorp Secret Manual")
