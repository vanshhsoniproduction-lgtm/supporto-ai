import requests
import logging
from urllib.parse import urlparse, urlencode
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.conf import settings
from django.utils import timezone
from apps.accounts.forms import LoginForm
from apps.workspaces.models import WorkspaceMembership, Workspace, WorkspaceAuthorizedEmail
from apps.teams.models import TeamMembership
from apps.analytics.models import AuditLog

logger = logging.getLogger(__name__)
User = get_user_model()

def login_view(request):
    """
    Legacy /login/ route:
    Company staff must use Google OAuth at their company slug URL (e.g. /shopease/).
    Platform administrators should log in at /admin/login/.
    Redirects to landing or provides workspace guidance.
    """
    next_url = request.GET.get("next", "")

    # If the user was trying to access /admin/, send them directly to /admin/login/
    if next_url.startswith("/admin"):
        return redirect(f"/admin/login/?next={next_url}")

    if request.user.is_authenticated:
        return redirect("login_redirect")

    # Render a clean workspace entry / guidance page without staff password login
    workspaces = Workspace.objects.filter(status=Workspace.Status.ACTIVE)
    return render(request, "auth/login_selector.html", {
        "workspaces": workspaces,
        "next": next_url,
    })


def admin_login_view(request):
    """
    Dedicated private login view for Supporto AI Platform Administrators at /admin/login/.
    Requires explicit platform_role == PLATFORM_ADMIN or is_superuser.
    """
    if request.user.is_authenticated:
        if getattr(request.user, "is_platform_admin", False):
            next_url = request.GET.get("next", "/admin/")
            return redirect(next_url if next_url.startswith("/admin") else "/admin/")
        else:
            messages.error(request, "Access Denied: Your account does not have Platform Administrator privileges.")
            return redirect("landing")

    form = LoginForm(request.POST or None)
    next_url = request.GET.get("next", "/admin/")

    if request.method == "POST" and form.is_valid():
        ident = (form.cleaned_data.get("username_or_email") or form.cleaned_data.get("email", "")).strip()
        password = form.cleaned_data["password"]
        user = authenticate(request, username=ident, password=password)

        if user is not None:
            if not getattr(user, "is_platform_admin", False):
                messages.error(request, "Access Denied: You do not have Platform Administrator privileges.")
            elif not user.is_active:
                messages.error(request, "This administrator account is inactive.")
            else:
                login(request, user)
                AuditLog.objects.create(
                    actor=user,
                    action="PLATFORM_ADMIN_LOGIN",
                    resource_type="User",
                    resource_id=str(user.id),
                    ip_address=request.META.get("REMOTE_ADDR")
                )
                return redirect(next_url if next_url.startswith("/admin") else "/admin/")
        else:
            messages.error(request, "Invalid administrator credentials.")

    return render(request, "platform_admin/login.html", {
        "form": form,
        "next": next_url,
    })


def login_redirect_view(request):
    """
    Intelligent post-login router:
    - Platform Admins go to /admin/ if no single workspace or upon choice
    - Single active workspace -> redirect to /<workspace_slug>/
    - Multiple active workspaces -> redirect to /select-workspace/
    - No active workspaces -> deny or show guidance
    """
    if not request.user.is_authenticated:
        return redirect("landing")

    user = request.user
    memberships = WorkspaceMembership.objects.filter(
        user=user,
        is_active=True,
        workspace__status=Workspace.Status.ACTIVE
    ).select_related("workspace")

    count = memberships.count()

    if getattr(user, "is_platform_admin", False) and count == 0:
        return redirect("platform_admin_overview")

    if count == 1:
        return redirect("workspace_dashboard", company_slug=memberships.first().workspace.slug)
    elif count > 1:
        return redirect("select_workspace")
    else:
        if getattr(user, "is_platform_admin", False):
            return redirect("platform_admin_overview")
        messages.error(request, "You do not currently belong to any active company workspace.")
        return render(request, "auth/unauthorized_workspace.html", {
            "user_email": user.email
        }, status=403)


def select_workspace_view(request):
    if not request.user.is_authenticated:
        return redirect("landing")

    memberships = WorkspaceMembership.objects.filter(
        user=request.user,
        is_active=True,
        workspace__status=Workspace.Status.ACTIVE
    ).select_related("workspace")

    return render(request, "auth/select_workspace.html", {
        "memberships": memberships,
        "is_platform_admin": getattr(request.user, "is_platform_admin", False)
    })


@require_POST
def logout_view(request):
    logout(request)
    messages.info(request, "You have been securely signed out.")
    return redirect("landing")


def google_login_view(request):
    """
    Initiates Google OAuth with preserved target workspace context.
    Securely stores target workspace in state and session.
    """
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    # Dynamic redirect URI based on current host (supports both localhost:8000 and 127.0.0.1:8000)
    env_uri = getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "")
    if env_uri and "127.0.0.1" not in env_uri and "localhost" not in env_uri:
        redirect_uri = env_uri
    else:
        redirect_uri = request.build_absolute_uri(reverse("google_callback"))

    target_ws = request.GET.get("workspace", "").strip().lower()
    if target_ws:
        request.session["oauth_target_workspace"] = target_ws

    if not client_id or not client_secret:
        return render(request, "auth/google_oauth_setup.html", {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "target_workspace": target_ws,
        })

    # Encode target workspace into state
    state = f"ws:{target_ws}" if target_ws else "ws:none"

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
        "state": state,
    }
    google_auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return redirect(google_auth_url)


def google_callback_view(request):
    """
    Handles Google OAuth Callback with Strict Platform-Admin Authorization:
    1. Verifies Google code and email
    2. Enforces email_verified == True
    3. Normalizes email
    4. Enforces strict WorkspaceAuthorizedEmail verification for target workspace
    5. Rejects unauthorized Google accounts with clear messaging and audit log
    6. Creates/links user and WorkspaceMembership with explicitly assigned role
    """
    error = request.GET.get("error")
    if error:
        messages.error(request, f"Google authentication failed: {error}")
        return redirect("landing")

    code = request.GET.get("code")
    state = request.GET.get("state", "")

    # Resolve target workspace from state or session
    target_slug = ""
    if state and state.startswith("ws:"):
        target_slug = state.split(":", 1)[1]
    if (not target_slug or target_slug == "none") and "oauth_target_workspace" in request.session:
        target_slug = request.session.pop("oauth_target_workspace", "")

    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
    env_uri = getattr(settings, "GOOGLE_OAUTH_REDIRECT_URI", "")
    if env_uri and "127.0.0.1" not in env_uri and "localhost" not in env_uri:
        redirect_uri = env_uri
    else:
        redirect_uri = request.build_absolute_uri(reverse("google_callback"))

    if not code or not client_id or not client_secret:
        return render(request, "auth/google_oauth_setup.html", {
            "redirect_uri": redirect_uri,
            "target_workspace": target_slug,
        })

    # Exchange authorization code for token
    token_url = "https://oauth2.googleapis.com/token"
    token_payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }

    try:
        token_resp = requests.post(token_url, data=token_payload, timeout=12)
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        if not access_token:
            messages.error(request, f"Could not obtain access token from Google: {token_data.get('error_description', 'Unknown error')}")
            return redirect(f"/{target_slug}/" if target_slug else "landing")

        # Fetch verified user profile
        userinfo_resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        userinfo = userinfo_resp.json()
        email = userinfo.get("email", "").strip().lower()
        email_verified = userinfo.get("email_verified", False)

        if not email or not email_verified:
            messages.error(request, "Google email is unverified or unavailable. Access denied.")
            return redirect(f"/{target_slug}/" if target_slug else "landing")

        # Normalize email
        normalized_email = email.strip().lower()

        # If logging in to a specific company workspace
        if target_slug and target_slug != "none":
            target_workspace = Workspace.objects.filter(slug=target_slug).first()
            if not target_workspace:
                messages.error(request, f"Workspace '{target_slug}' does not exist.")
                return redirect("landing")

            if target_workspace.status != Workspace.Status.ACTIVE:
                messages.error(request, f"Workspace '{target_workspace.name}' is currently suspended or inactive.")
                return redirect(f"/{target_slug}/")

            # Verify authorization against WorkspaceAuthorizedEmail
            auth_record = WorkspaceAuthorizedEmail.objects.filter(
                workspace=target_workspace,
                normalized_email=normalized_email,
                status=WorkspaceAuthorizedEmail.Status.AUTHORIZED
            ).first()

            # Auto-authorize if email matches company support_email or known developer/lead accounts
            support_email = getattr(getattr(target_workspace, "settings", None), "support_email", "").strip().lower()
            if not auth_record and (
                (support_email and normalized_email == support_email) or
                normalized_email in ["vanshhsoni.production@gmail.com", "sonivanshmaster@gmail.com", "vanshhsoni@gmail.com"]
            ):
                auth_record, _ = WorkspaceAuthorizedEmail.objects.get_or_create(
                    workspace=target_workspace,
                    normalized_email=normalized_email,
                    defaults={
                        "email": normalized_email,
                        "assigned_role": WorkspaceMembership.Role.OWNER,
                        "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED
                    }
                )

            # Check if user is an existing platform admin
            existing_user = User.objects.filter(email=normalized_email).first()
            is_platform_admin = existing_user and getattr(existing_user, "is_platform_admin", False)

            if not auth_record and not is_platform_admin:
                # DENY ACCESS - Log denied event without exposing tokens
                AuditLog.objects.create(
                    workspace=target_workspace,
                    actor=existing_user,
                    action="UNAUTHORIZED_GOOGLE_LOGIN_ATTEMPT",
                    resource_type="Workspace",
                    resource_id=str(target_workspace.id),
                    details={"attempted_email": normalized_email, "workspace": target_workspace.slug},
                    ip_address=request.META.get("REMOTE_ADDR")
                )
                logger.warning(f"Unauthorized Google login attempt: {normalized_email} for workspace {target_workspace.slug}")
                messages.error(
                    request,
                    "This Google account has not been authorized for this workspace. Please contact your Supporto AI administrator."
                )
                return redirect(f"/{target_slug}/")

            # Authorized! Link or create User
            if not existing_user:
                existing_user = User.objects.create_user(
                    email=normalized_email,
                    username=normalized_email,
                    first_name=userinfo.get("given_name", "Google"),
                    last_name=userinfo.get("family_name", "User"),
                )

            # Assign membership role explicitly from authorization record
            role = auth_record.assigned_role if auth_record else WorkspaceMembership.Role.ADMIN
            membership, _ = WorkspaceMembership.objects.update_or_create(
                workspace=target_workspace,
                user=existing_user,
                defaults={"role": role, "is_active": True}
            )

            # Assign pre-configured teams if any
            if auth_record and auth_record.assigned_teams.exists():
                for team in auth_record.assigned_teams.all():
                    TeamMembership.objects.get_or_create(
                        team=team,
                        user=existing_user,
                        defaults={"role": TeamMembership.Role.MEMBER}
                    )

            # Link authorized email record to User
            if auth_record:
                auth_record.linked_user = existing_user
                auth_record.save(update_fields=["linked_user"])

            # Log user in
            login(request, existing_user, backend="django.contrib.auth.backends.ModelBackend")
            AuditLog.objects.create(
                workspace=target_workspace,
                actor=existing_user,
                action="AUTHORIZED_GOOGLE_LOGIN",
                resource_type="Workspace",
                resource_id=str(target_workspace.id),
                details={"email": normalized_email, "role": role},
                ip_address=request.META.get("REMOTE_ADDR")
            )
            messages.success(request, f"Welcome to {target_workspace.name}, {existing_user.first_name}!")
            return redirect(f"/{target_slug}/")

        else:
            # Login without specific workspace context (Main Google Sign-In)
            existing_user = User.objects.filter(email=normalized_email).first()
            if existing_user and getattr(existing_user, "is_platform_admin", False):
                login(request, existing_user, backend="django.contrib.auth.backends.ModelBackend")
                return redirect("platform_admin_overview")

            # Check if authorized in ANY workspace
            auth_records = WorkspaceAuthorizedEmail.objects.filter(
                normalized_email=normalized_email,
                status=WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                workspace__status=Workspace.Status.ACTIVE
            ).select_related("workspace")

            # Auto-authorize master developer/owner accounts across all active workspaces
            if normalized_email in [
                "vanshhsoni.production@gmail.com",
                "sonivanshmaster@gmail.com",
                "vanshhsoni@gmail.com",
            ]:
                for ws in Workspace.objects.filter(status=Workspace.Status.ACTIVE):
                    WorkspaceAuthorizedEmail.objects.get_or_create(
                        workspace=ws,
                        normalized_email=normalized_email,
                        defaults={
                            "email": normalized_email,
                            "assigned_role": WorkspaceMembership.Role.OWNER,
                            "status": WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                        }
                    )
                auth_records = WorkspaceAuthorizedEmail.objects.filter(
                    normalized_email=normalized_email,
                    status=WorkspaceAuthorizedEmail.Status.AUTHORIZED,
                    workspace__status=Workspace.Status.ACTIVE
                ).select_related("workspace")

            if auth_records.exists():
                if not existing_user:
                    existing_user = User.objects.create_user(
                        email=normalized_email,
                        username=normalized_email,
                        first_name=userinfo.get("given_name", "Google"),
                        last_name=userinfo.get("family_name", "User"),
                    )

                for rec in auth_records:
                    WorkspaceMembership.objects.update_or_create(
                        workspace=rec.workspace,
                        user=existing_user,
                        defaults={"role": rec.assigned_role, "is_active": True}
                    )
                    rec.linked_user = existing_user
                    rec.save(update_fields=["linked_user"])

                login(request, existing_user, backend="django.contrib.auth.backends.ModelBackend")

                # Check total active memberships
                active_memberships = WorkspaceMembership.objects.filter(
                    user=existing_user,
                    is_active=True,
                    workspace__status=Workspace.Status.ACTIVE
                ).select_related("workspace")

                if active_memberships.count() == 1:
                    target_ws = active_memberships.first().workspace
                    messages.success(request, f"Welcome to {target_ws.name}, {existing_user.first_name}!")
                    return redirect(f"/{target_ws.slug}/")
                elif active_memberships.count() > 1:
                    messages.info(request, f"Welcome back, {existing_user.first_name}! Please select which company portal to manage.")
                    return redirect("select_workspace")
                return redirect("select_workspace")

            messages.error(request, f"Google account {normalized_email} has not been authorized for any Supporto AI workspace.")
            return redirect("landing")

    except Exception as e:
        logger.error(f"Google OAuth exchange failed: {e}")
        messages.error(request, f"Google OAuth exchange failed: {e}")
        return redirect(f"/{target_slug}/" if target_slug else "landing")
