from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.views.decorators.http import require_POST
from apps.knowledge_base.models import KnowledgeDocument
from services.ai.rag_service import rag_service
from services.workspaces.access_control import require_workspace_roles

def knowledge_base_view(request, company_slug):
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
                KnowledgeDocument.objects.create(
                    workspace=workspace,
                    title=title or question[:50],
                    doc_type=KnowledgeDocument.DocType.FAQ,
                    question=question,
                    answer=answer,
                    content=f"Q: {question}\nA: {answer}",
                    is_active=True
                )
                messages.success(request, "FAQ added successfully.")
            return redirect("knowledge_base", company_slug=workspace.slug)

        elif action == "upload_doc":
            title = request.POST.get("title", "").strip()
            content = request.POST.get("content", "").strip()
            uploaded_file = request.FILES.get("file")

            if uploaded_file and not content:
                try:
                    content = uploaded_file.read().decode("utf-8", errors="ignore")
                except Exception as e:
                    content = f"Uploaded file: {uploaded_file.name}"

            if not title:
                title = uploaded_file.name if uploaded_file else "Uploaded Document"

            KnowledgeDocument.objects.create(
                workspace=workspace,
                title=title,
                doc_type=KnowledgeDocument.DocType.ARTICLE,
                content=content,
                file=uploaded_file,
                is_active=True
            )
            messages.success(request, f"Document '{title}' added to Knowledge Base.")
            return redirect("knowledge_base", company_slug=workspace.slug)

    search_query = request.GET.get("q", "").strip()
    search_results = []
    if search_query:
        search_results = rag_service.retrieve_context(workspace.id, search_query, top_k=5)

    documents = KnowledgeDocument.objects.filter(workspace=workspace).order_by("-created_at")

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
    workspace = request.workspace
    doc = get_object_or_404(KnowledgeDocument, id=doc_id, workspace=workspace)
    doc.delete()
    messages.success(request, f"Document '{doc.title}' deleted.")
    return redirect("knowledge_base", company_slug=workspace.slug)

