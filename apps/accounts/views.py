import requests
from urllib.parse import urlparse
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.conf import settings
from apps.accounts.forms import LoginForm
from apps.workspaces.models import WorkspaceMembership, Workspace

User = get_user_model()

def login_view(request):
    if request.user.is_authenticated:
        return redirect("login_redirect")

    form = LoginForm(request.POST or None)
    next_url = request.GET.get("next", "")

    if request.method == "POST" and form.is_valid():
        ident = (form.cleaned_data.get("username_or_email") or form.cleaned_data.get("email", "")).strip()
        password = form.cleaned_data["password"]
        user = authenticate(request, username=ident, password=password)

        if user is not None:
            if not user.is_active:
                messages.error(request, "This account is inactive. Please contact your administrator.")
            else:
                login(request, user)
                if next_url:
                    parsed = urlparse(next_url)
                    if not parsed.netloc and next_url.startswith("/"):
                        return redirect(next_url)
                return redirect("login_redirect")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, "auth/login.html", {
        "form": form,
        "next": next_url,
        "google_enabled": bool(settings.GOOGLE_OAUTH_CLIENT_ID),
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
        return redirect("login")

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
        return render(request, "auth/no_workspace.html")


def select_workspace_view(request):
    if not request.user.is_authenticated:
        return redirect("login")

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
    return redirect("login")


def google_login_view(request):
    """Initiates Google OAuth or shows friendly setup guide in dev mode."""
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        return render(request, "auth/google_oauth_setup.html", {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        })

    # Google OAuth flow URL
    google_auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"response_type=code&client_id={settings.GOOGLE_OAUTH_CLIENT_ID}&"
        f"redirect_uri={settings.GOOGLE_OAUTH_REDIRECT_URI}&"
        f"scope=openid%20email%20profile&access_type=offline&prompt=select_account"
    )
    return redirect(google_auth_url)


def google_callback_view(request):
    """Handles OAuth callback, exchanges authorization code, verifies email, and logs user in."""
    error = request.GET.get("error")
    if error:
        messages.error(request, f"Google OAuth failed: {error}")
        return redirect("login")

    code = request.GET.get("code")
    if not code:
        return render(request, "auth/google_oauth_setup.html", {
            "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        })

    # Exchange authorization code for access token
    token_url = "https://oauth2.googleapis.com/token"
    token_payload = {
        "code": code,
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    try:
        token_resp = requests.post(token_url, data=token_payload, timeout=10)
        token_data = token_resp.json()
        access_token = token_data.get("access_token")

        if not access_token:
            messages.error(request, f"Could not obtain access token from Google: {token_data.get('error_description', 'Unknown error')}")
            return redirect("login")

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
            messages.error(request, "Google email is unverified or unavailable.")
            return redirect("login")

        # Check existing user
        user = User.objects.filter(email=email).first()
        if not user:
            # Create user on first Google sign-in
            user = User.objects.create_user(
                email=email,
                username=email,
                first_name=userinfo.get("given_name", "Google"),
                last_name=userinfo.get("family_name", "User"),
            )
            # In development mode, auto-associate with active demo workspace as AGENT
            demo_ws = Workspace.objects.filter(status=Workspace.Status.ACTIVE).first()
            if demo_ws:
                WorkspaceMembership.objects.create(
                    workspace=demo_ws,
                    user=user,
                    role=WorkspaceMembership.Role.AGENT,
                    is_active=True
                )

        if not user.is_active:
            messages.error(request, "Your account is currently inactive. Contact your administrator.")
            return redirect("login")

        # Check membership or platform role
        has_active_workspace = WorkspaceMembership.objects.filter(
            user=user,
            is_active=True,
            workspace__status=Workspace.Status.ACTIVE
        ).exists()

        if not has_active_workspace and not getattr(user, "is_platform_admin", False):
            messages.error(request, f"User {email} has no active assigned workspaces.")
            return redirect("login")

        # Successful authentication
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Signed in with Google as {email}!")
        return redirect("login_redirect")

    except Exception as e:
        messages.error(request, f"Google OAuth exchange failed: {e}")
        return redirect("login")
