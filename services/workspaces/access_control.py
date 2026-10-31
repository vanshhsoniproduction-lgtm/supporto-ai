from functools import wraps
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from apps.workspaces.models import Workspace, WorkspaceMembership

RESERVED_ROOT_PATHS = {
    "admin",
    "django-admin",
    "login",
    "logout",
    "widget",
    "static",
    "media",
    "select-workspace",
    "accounts",
    "integrations",
    "api",
    "favicon.ico",
}

class TenantContextMiddleware:
    """
    Resolves the active Workspace from URL prefix /<company_slug>/ and attaches it
    to request.workspace and request.membership. Enforces strict multi-tenant isolation.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path_parts = [p for p in request.path.strip("/").split("/") if p]
        request.workspace = None
        request.membership = None

        if path_parts:
            first_part = path_parts[0]
            if first_part not in RESERVED_ROOT_PATHS and not request.path.startswith("/api/public"):
                try:
                    workspace = Workspace.objects.get(slug=first_part)
                    request.workspace = workspace
                except Workspace.DoesNotExist:
                    raise Http404(f"Workspace '{first_part}' not found.")

                # If this is a company portal route (e.g. /<slug>/...)
                # Check user authentication and workspace membership
                if not request.user.is_authenticated:
                    if len(path_parts) == 1:
                        # Allow company landing / Google login view to render
                        return self.get_response(request)
                    return redirect(f"/{first_part}/")

                if workspace.status != Workspace.Status.ACTIVE and not getattr(request.user, "is_platform_admin", False):
                    return HttpResponseForbidden("This workspace is currently suspended or pending approval.")

                membership = WorkspaceMembership.objects.filter(
                    workspace=workspace,
                    user=request.user,
                    is_active=True
                ).first()

                is_platform_admin = getattr(request.user, "is_platform_admin", False)

                if not membership and not is_platform_admin:
                    if len(path_parts) == 1:
                        # Allow company landing to render so unauthorized template displays
                        return self.get_response(request)
                    return HttpResponseForbidden(f"Access Denied: You are not an authorized member of {workspace.name}.")

                request.membership = membership

        response = self.get_response(request)
        return response


def require_platform_admin(view_func):
    """
    Decorator ensuring only explicit platform administrators can access view.
    Redirects unauthenticated requests to dedicated /admin/login/ route.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/admin/login/?next={request.path}")
        if not getattr(request.user, "is_platform_admin", False):
            raise PermissionDenied("Platform administrator access required.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def require_workspace_roles(*allowed_roles):
    """
    Decorator ensuring current user has one of the specified roles in request.workspace.
    Platform admins always bypass role restriction.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                workspace_slug = kwargs.get("company_slug", "")
                return redirect(f"/{workspace_slug}/" if workspace_slug else "/landing")
            if getattr(request.user, "is_platform_admin", False):
                return view_func(request, *args, **kwargs)

            membership = getattr(request, "membership", None)
            if not membership or membership.role not in allowed_roles:
                raise PermissionDenied("You do not have the required role to access this resource.")
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def workspace_context_processor(request):
    """Context processor making workspace and user membership available to templates."""
    return {
        "current_workspace": getattr(request, "workspace", None),
        "current_membership": getattr(request, "membership", None),
        "is_platform_admin": getattr(request.user, "is_platform_admin", False) if request.user.is_authenticated else False,
    }
