from django.shortcuts import render
from services.analytics.metrics_service import metrics_service
from services.workspaces.access_control import require_workspace_roles

@require_workspace_roles("OWNER", "ADMIN", "MANAGER")
def workspace_analytics_view(request, company_slug):
    workspace = request.workspace
    metrics = metrics_service.get_workspace_metrics(workspace)

    return render(request, "analytics/workspace_analytics.html", {
        "workspace": workspace,
        "metrics": metrics,
        "active_nav": "analytics"
    })

