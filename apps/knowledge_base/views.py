import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from apps.knowledge_base.models import KnowledgeDocument, KnowledgeChunk
from apps.knowledge_base.services.document_processor import document_processor
from services.ai.rag_service import rag_service
from services.workspaces.access_control import require_workspace_roles

logger = logging.getLogger(__name__)

@require_workspace_roles("OWNER", "ADMIN", "MANAGER")
def knowledge_base_view(request, company_slug):
    """
    Company Knowledge Base management:
    - Multiple file batch upload (TXT, MD, PDF, DOCX, CSV)
    - Add/Edit FAQ
    - Document chunks visualization
    - Search & preview
    """
    workspace = request.workspace

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "add_faq":
            title = request.POST.get("title", "").strip()
            question = request.POST.get("question", "").strip()
            answer = request.POST.get("answer", "").strip()

            if not question or not answer:
                messages.error(request, "Question and Answer are required for FAQ.")
            else:
                doc = KnowledgeDocument.objects.create(
                    workspace=workspace,
                    title=title or question[:60],
                    doc_type=KnowledgeDocument.DocType.FAQ,
                    question=question,
                    answer=answer,
                    content=f"Q: {question}\nA: {answer}",
                    is_active=True
                )
                document_processor.chunk_and_index(doc)
                messages.success(request, f"FAQ '{doc.title}' added and indexed successfully.")
            return redirect("knowledge_base", company_slug=workspace.slug)

        elif action == "upload_batch":
            uploaded_files = request.FILES.getlist("files")
            if not uploaded_files:
                single_file = request.FILES.get("file")
                if single_file:
                    uploaded_files = [single_file]

            if not uploaded_files:
                messages.error(request, "Please select at least one document to upload.")
                return redirect("knowledge_base", company_slug=workspace.slug)

            success_count = 0
            errors = []
            for f in uploaded_files:
                doc, err = document_processor.process_uploaded_document(workspace, f)
                if doc:
                    success_count += 1
                else:
                    errors.append(f"{f.name}: {err}")

            if success_count > 0:
                messages.success(request, f"Successfully uploaded and indexed {success_count} document(s).")
            if errors:
                messages.warning(request, f"Some files could not be processed: {'; '.join(errors)}")

            return redirect("knowledge_base", company_slug=workspace.slug)

    search_query = request.GET.get("q", "").strip()
    search_results = []
    if search_query:
        search_results = rag_service.retrieve_context(workspace.id, search_query, top_k=5)

    documents = KnowledgeDocument.objects.filter(workspace=workspace).prefetch_related("chunks").order_by("-updated_at")

    return render(request, "knowledge_base/index.html", {
        "workspace": workspace,
        "documents": documents,
        "search_query": search_query,
        "search_results": search_results,
        "active_nav": "knowledge"
    })


@require_workspace_roles("OWNER", "ADMIN", "MANAGER")
@require_POST
def knowledge_delete_view(request, company_slug, doc_id):
    """Deletes a document and cascades to its chunks."""
    workspace = request.workspace
    doc = get_object_or_404(KnowledgeDocument, id=doc_id, workspace=workspace)
    title = doc.title
    doc.delete()
    messages.success(request, f"Document '{title}' deleted from Knowledge Base.")
    return redirect("knowledge_base", company_slug=workspace.slug)


@require_workspace_roles("OWNER", "ADMIN", "MANAGER")
@require_POST
def knowledge_reindex_view(request, company_slug, doc_id):
    """Rechunks and re-indexes a document."""
    workspace = request.workspace
    doc = get_object_or_404(KnowledgeDocument, id=doc_id, workspace=workspace)
    chunk_count = document_processor.chunk_and_index(doc)
    messages.success(request, f"Document '{doc.title}' re-indexed ({chunk_count} chunks generated).")
    return redirect("knowledge_base", company_slug=workspace.slug)
