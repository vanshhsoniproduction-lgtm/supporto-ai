from django.shortcuts import render, redirect
from django.contrib import messages
from apps.ai_engine.models import AgentConfiguration, AgentRun
from services.workspaces.access_control import require_workspace_roles
from services.ai.model_manager import model_manager

@require_workspace_roles("OWNER", "ADMIN")
def ai_settings_view(request, company_slug):
    workspace = request.workspace
    config, _ = AgentConfiguration.objects.get_or_create(workspace=workspace)

    if request.method == "POST":
        config.system_prompt = request.POST.get("system_prompt", config.system_prompt).strip()
        config.temperature = float(request.POST.get("temperature", 0.2))
        config.max_tokens = int(request.POST.get("max_tokens", 512))
        config.confidence_threshold = float(request.POST.get("confidence_threshold", 0.7))
        config.auto_escalate_urgent = bool(request.POST.get("auto_escalate_urgent"))
        config.save()
        messages.success(request, "AI Agent configuration saved.")
        return redirect("ai_settings", company_slug=workspace.slug)

    recent_runs = AgentRun.objects.filter(workspace=workspace).order_by("-created_at")[:20]
    health = model_manager.get_health_status()

    return render(request, "ai_engine/settings.html", {
        "workspace": workspace,
        "config": config,
        "recent_runs": recent_runs,
        "health": health,
        "active_nav": "ai_settings"
    })

