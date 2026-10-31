from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import render, redirect

from apps.accounts.views import (
    login_view,
    admin_login_view,
    login_redirect_view,
    select_workspace_view,
    logout_view,
    google_login_view,
    google_callback_view,
)
from apps.workspaces.admin_views import (
    platform_admin_overview,
    platform_admin_companies,
    platform_admin_company_detail,
    platform_admin_authorized_emails,
    platform_admin_company_knowledge,
    platform_admin_company_email_integration,
    platform_admin_company_toggle,
    platform_admin_users,
    platform_admin_ai_models,
    platform_admin_activity,
)
from apps.workspaces.views import (
    workspace_dashboard,
    workspace_settings_view,
)
from apps.emails.views import (
    email_inbox_view,
    email_review_queue_view,
    proposal_action_view,
    sync_now_view,
    gmail_connect_view,
    global_gmail_callback_view,
    disconnect_mailbox_view,
)
from apps.tickets.views import (
    ticket_list_view,
    my_tickets_view,
    team_queue_view,
    ticket_detail_view,
)
from apps.customers.views import (
    customer_list_view,
    customer_detail_view,
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
    knowledge_reindex_view,
)
from apps.ai_engine.views import ai_settings_view, company_ai_health_view
from apps.voice_support.views import voice_settings_view
from apps.analytics.views import (
    workspace_analytics_view,
    weekly_insights_view,
    export_weekly_csv_view,
)
from apps.customers.widget_views import (
    widget_view,
    widget_demo_view,
    widget_message_api,
    widget_voice_api,
    widget_complete_api,
)
from apps.workspaces.models import Workspace

def landing_view(request):
    """Root landing page - restrained, single-page presentation."""
    workspaces = Workspace.objects.filter(status=Workspace.Status.ACTIVE)
    shopease = Workspace.objects.filter(slug="shopease").first() or workspaces.first()
    expressbeas = Workspace.objects.filter(slug="expressbeas").first()
    return render(request, "landing.html", {
        "workspaces": workspaces,
        "shopease": shopease,
        "expressbeas": expressbeas,
    })

def company_demo_redirect_view(request, company_slug):
    """Redirects /shopease/demo/ or /expressbeas/demo/ to widget_demo."""
    from django.shortcuts import get_object_or_404
    ws = get_object_or_404(Workspace, slug=company_slug)
    return redirect("widget_demo", public_key=ws.public_key)

def inbox_redirect_view(request, company_slug):
    return redirect("email_inbox", company_slug=company_slug)

urlpatterns = [
    # A. Public Landing Page
    path("", landing_view, name="landing"),
    path("<slug:company_slug>/demo/", company_demo_redirect_view, name="company_demo_redirect"),

    # Django internal admin
    path("django-admin/", admin.site.urls),

    # Authentication Access Points
    path("login/", login_view, name="login"),
    path("admin/login/", admin_login_view, name="admin_login"),
    path("login/redirect/", login_redirect_view, name="login_redirect"),
    path("select-workspace/", select_workspace_view, name="select_workspace"),
    path("logout/", logout_view, name="logout"),
    path("accounts/google/login/", google_login_view, name="google_login"),
    path("accounts/google/callback/", google_callback_view, name="google_callback"),
    path("integrations/gmail/callback/", global_gmail_callback_view, name="global_gmail_callback"),

    # B. Custom Platform Administration at /admin/
    path("admin/", platform_admin_overview, name="platform_admin_overview"),
    path("admin/companies/", platform_admin_companies, name="platform_admin_companies"),
    path("admin/companies/<slug:slug>/", platform_admin_company_detail, name="platform_admin_company_detail"),
    path("admin/companies/<slug:slug>/authorized-emails/", platform_admin_authorized_emails, name="platform_admin_authorized_emails"),
    path("admin/companies/<slug:slug>/knowledge-base/", platform_admin_company_knowledge, name="platform_admin_company_knowledge"),
    path("admin/companies/<slug:slug>/email-integration/", platform_admin_company_email_integration, name="platform_admin_company_email_integration"),
    path("admin/companies/<slug:slug>/integrations/email/", platform_admin_company_email_integration, name="platform_admin_company_email_integration_alias"),
    path("admin/companies/<int:workspace_id>/toggle/", platform_admin_company_toggle, name="platform_admin_company_toggle"),
    path("admin/users/", platform_admin_users, name="platform_admin_users"),
    path("admin/ai-models/", platform_admin_ai_models, name="platform_admin_ai_models"),
    path("admin/activity/", platform_admin_activity, name="platform_admin_activity"),

    # Customer Support Widget (Public routes identified by secure public_key UUID)
    path("widget/<uuid:public_key>/", widget_view, name="widget_embed"),
    path("widget/<uuid:public_key>/demo/", widget_demo_view, name="widget_demo"),
    path("widget/<uuid:public_key>/message/", widget_message_api, name="widget_message_api"),
    path("widget/<uuid:public_key>/voice/", widget_voice_api, name="widget_voice_api"),
    path("widget/<uuid:public_key>/complete/", widget_complete_api, name="widget_complete_api"),

    # C. Company-Specific Portal at /<company_slug>/
    path("<slug:company_slug>/", workspace_dashboard, name="workspace_dashboard"),
    path("<slug:company_slug>/inbox/", inbox_redirect_view, name="workspace_inbox_redirect"),
    path("<slug:company_slug>/emails/", email_inbox_view, name="email_inbox"),
    path("<slug:company_slug>/emails/sync/", sync_now_view, name="email_sync_now"),
    path("<slug:company_slug>/emails/review/", email_review_queue_view, name="email_review_queue"),
    path("<slug:company_slug>/emails/proposals/<int:proposal_id>/action/", proposal_action_view, name="proposal_action"),
    path("<slug:company_slug>/settings/integrations/email/", gmail_connect_view, name="gmail_connect"),
    path("<slug:company_slug>/settings/integrations/email/<int:connection_id>/disconnect/", disconnect_mailbox_view, name="disconnect_mailbox"),

    # Tickets
    path("<slug:company_slug>/tickets/", ticket_list_view, name="ticket_list"),
    path("<slug:company_slug>/tickets/my/", my_tickets_view, name="my_tickets"),
    path("<slug:company_slug>/tickets/queue/", team_queue_view, name="team_queue"),
    path("<slug:company_slug>/tickets/<str:ticket_number>/", ticket_detail_view, name="ticket_detail"),

    # Customers
    path("<slug:company_slug>/customers/", customer_list_view, name="customer_list"),
    path("<slug:company_slug>/customers/<int:customer_id>/", customer_detail_view, name="customer_detail"),

    # Teams & Staff
    path("<slug:company_slug>/teams/", team_list_view, name="team_list"),
    path("<slug:company_slug>/teams/<int:team_id>/", team_detail_view, name="team_detail"),
    path("<slug:company_slug>/staff/", staff_list_view, name="staff_list"),
    path("<slug:company_slug>/staff/<int:membership_id>/toggle/", staff_toggle_status_view, name="staff_toggle_status"),

    # Shared Knowledge Base
    path("<slug:company_slug>/knowledge-base/", knowledge_base_view, name="knowledge_base"),
    path("<slug:company_slug>/knowledge/", knowledge_base_view, name="knowledge_base_alias"),
    path("<slug:company_slug>/knowledge/<int:doc_id>/delete/", knowledge_delete_view, name="knowledge_delete"),
    path("<slug:company_slug>/knowledge/<int:doc_id>/reindex/", knowledge_reindex_view, name="knowledge_reindex"),

    # AI & Voice Configurations
    path("<slug:company_slug>/ai-settings/", ai_settings_view, name="ai_settings"),
    path("<slug:company_slug>/ai-health/", company_ai_health_view, name="company_ai_health"),
    path("<slug:company_slug>/voice-settings/", voice_settings_view, name="voice_settings"),

    # Analytics & Weekly Insights
    path("<slug:company_slug>/analytics/", workspace_analytics_view, name="workspace_analytics"),
    path("<slug:company_slug>/analytics/weekly/", weekly_insights_view, name="weekly_insights"),
    path("<slug:company_slug>/analytics/weekly/export-csv/", export_weekly_csv_view, name="export_weekly_csv"),

    # Workspace Settings
    path("<slug:company_slug>/settings/", workspace_settings_view, name="workspace_settings"),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
