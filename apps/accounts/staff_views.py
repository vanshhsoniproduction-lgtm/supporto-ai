from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_POST
from apps.accounts.forms import StaffInviteForm
from apps.workspaces.models import WorkspaceMembership
from apps.teams.models import TeamMembership
from services.workspaces.access_control import require_workspace_roles

User = get_user_model()

@require_workspace_roles("OWNER", "ADMIN")
def staff_list_view(request, company_slug):
    workspace = request.workspace
    form = StaffInviteForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"].strip().lower()
        first_name = form.cleaned_data["first_name"].strip()
        last_name = form.cleaned_data["last_name"].strip()
        role = form.cleaned_data["role"]
        password = form.cleaned_data["password"] or "Supporto@123"

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": first_name,
                "last_name": last_name
            }
        )
        if created:
            user.set_password(password)
            user.save()

        membership, m_created = WorkspaceMembership.objects.get_or_create(
            workspace=workspace,
            user=user,
            defaults={"role": role, "is_active": True}
        )
        if not m_created:
            membership.role = role
            membership.is_active = True
            membership.save()
            messages.info(request, f"Updated existing membership for {email}.")
        else:
            messages.success(request, f"Staff member {email} added successfully (Default password: {password}).")

        return redirect("staff_list", company_slug=workspace.slug)

    memberships = workspace.memberships.select_related("user").order_by("role", "user__first_name")
    return render(request, "staff/staff_list.html", {
        "workspace": workspace,
        "memberships": memberships,
        "form": form,
        "active_nav": "staff"
    })


@require_workspace_roles("OWNER", "ADMIN")
@require_POST
def staff_toggle_status_view(request, company_slug, membership_id):
    workspace = request.workspace
    membership = get_object_or_404(WorkspaceMembership, id=membership_id, workspace=workspace)
    if membership.user == request.user:
        messages.error(request, "You cannot deactivate your own membership.")
        return redirect("staff_list", company_slug=workspace.slug)

    membership.is_active = not membership.is_active
    membership.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"Membership for {membership.user.email} updated.")
    return redirect("staff_list", company_slug=workspace.slug)

