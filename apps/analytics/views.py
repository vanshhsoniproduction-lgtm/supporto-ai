from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from services.analytics.metrics_service import metrics_service
from services.analytics.weekly_insights import weekly_insights_service
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


@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
def weekly_insights_view(request, company_slug):
    """Weekly AI Insights report calculating real metrics and sentiment trends."""
    if request.GET.get("export") == "csv":
        return export_weekly_csv_view(request, company_slug)

    workspace = request.workspace
    report = weekly_insights_service.get_weekly_report(workspace)

    return render(request, "analytics/weekly_insights.html", {
        "workspace": workspace,
        "report": report,
        "active_nav": "analytics"
    })


@require_workspace_roles("OWNER", "ADMIN", "MANAGER", "AGENT")
def export_weekly_csv_view(request, company_slug):
    """Exports the weekly analytics report as a downloadable CSV."""
    workspace = request.workspace
    report = weekly_insights_service.get_weekly_report(workspace)
    csv_content = weekly_insights_service.export_csv(report)

    response = HttpResponse(csv_content, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{workspace.slug}_weekly_insights.csv"'
    return response
