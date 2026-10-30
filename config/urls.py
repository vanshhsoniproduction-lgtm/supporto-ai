from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect

from apps.accounts.views import (
    login_view,
    login_redirect_view,
    select_workspace_view,
    logout_view,
    google_login_view,
    google_callback_view,
)
from apps.workspaces.admin_views import (
    platform_admin_overview,
    platform_admin_companies,
    platform_admin_company_toggle,
    platform_admin_users,
    platform_admin_ai_models,
    platform_admin_activity,
)
from apps.workspaces.views import (
    workspace_dashboard,
    workspace_settings_view,
)
from apps.tickets.views import (
    ticket_list_view,
    my_tickets_view,
    team_queue_view,
    ticket_detail_view,
)
from apps.teams.views import (
    team_list_view,
    team_detail_view,
)
from apps.accounts.staff_views import (
    staff_list_view,
    staff_toggle_status_view,
)
from apps.knowledge_base.views import (
    knowledge_base_view,
    knowledge_delete_view,
)
from apps.ai_engine.views import ai_settings_view
from apps.voice_support.views import voice_settings_view
from apps.analytics.views import workspace_analytics_view
from apps.customers.widget_views import (
    widget_view,
    widget_demo_view,
    widget_message_api,
    widget_voice_api,
    widget_complete_api,
)

from django.shortcuts import render, redirect
from apps.workspaces.models import Workspace

def landing_view(request):
    workspaces = Workspace.objects.filter(status=Workspace.Status.ACTIVE)
    demo_ws = workspaces.first()
    demo_widget_url = f"/widget/{demo_ws.public_key}/demo/" if demo_ws else ""
    return render(request, "landing.html", {
        "workspaces": workspaces,
        "demo_widget_url": demo_widget_url
    })

urlpatterns = [
    # Root Landing Page
    path("", landing_view, name="landing"),

    # Default Django admin for developer / database inspection
    path("django-admin/", admin.site.urls),

    # Authentication
    path("login/", login_view, name="login"),
    path("login/redirect/", login_redirect_view, name="login_redirect"),
    path("select-workspace/", select_workspace_view, name="select_workspace"),
    path("logout/", logout_view, name="logout"),
    path("accounts/google/login/", google_login_view, name="google_login"),
    path("accounts/google/callback/", google_callback_view, name="google_callback"),

    # Custom Platform Administration at /admin/
    path("admin/", platform_admin_overview, name="platform_admin_overview"),
    path("admin/companies/", platform_admin_companies, name="platform_admin_companies"),
    path("admin/companies/<int:workspace_id>/toggle/", platform_admin_company_toggle, name="platform_admin_company_toggle"),
    path("admin/users/", platform_admin_users, name="platform_admin_users"),
    path("admin/ai-models/", platform_admin_ai_models, name="platform_admin_ai_models"),
    path("admin/activity/", platform_admin_activity, name="platform_admin_activity"),

    # Customer Support Widget (Public routes identified by public_key UUID)
    path("widget/<uuid:public_key>/", widget_view, name="widget_embed"),
    path("widget/<uuid:public_key>/demo/", widget_demo_view, name="widget_demo"),
    path("widget/<uuid:public_key>/message/", widget_message_api, name="widget_message_api"),
    path("widget/<uuid:public_key>/voice/", widget_voice_api, name="widget_voice_api"),
    path("widget/<uuid:public_key>/complete/", widget_complete_api, name="widget_complete_api"),

    # Company Portal at /[company_slug]/
    path("<slug:company_slug>/", workspace_dashboard, name="workspace_dashboard"),
    path("<slug:company_slug>/settings/", workspace_settings_view, name="workspace_settings"),
    path("<slug:company_slug>/tickets/", ticket_list_view, name="ticket_list"),
    path("<slug:company_slug>/tickets/my/", my_tickets_view, name="my_tickets"),
    path("<slug:company_slug>/tickets/queue/", team_queue_view, name="team_queue"),
    path("<slug:company_slug>/tickets/<str:ticket_number>/", ticket_detail_view, name="ticket_detail"),
    path("<slug:company_slug>/teams/", team_list_view, name="team_list"),
    path("<slug:company_slug>/teams/<int:team_id>/", team_detail_view, name="team_detail"),
    path("<slug:company_slug>/staff/", staff_list_view, name="staff_list"),
    path("<slug:company_slug>/staff/<int:membership_id>/toggle/", staff_toggle_status_view, name="staff_toggle_status"),
    path("<slug:company_slug>/knowledge/", knowledge_base_view, name="knowledge_base"),
    path("<slug:company_slug>/knowledge/<int:doc_id>/delete/", knowledge_delete_view, name="knowledge_delete"),
    path("<slug:company_slug>/ai-settings/", ai_settings_view, name="ai_settings"),
    path("<slug:company_slug>/voice-settings/", voice_settings_view, name="voice_settings"),
    path("<slug:company_slug>/analytics/", workspace_analytics_view, name="workspace_analytics"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

