from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils.text import slugify
from apps.teams.models import Team, TeamMembership
from services.workspaces.access_control import require_workspace_roles

@require_workspace_roles("OWNER", "ADMIN", "MANAGER")
def team_list_view(request, company_slug):
    workspace = request.workspace
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        slug = slugify(name)
        if not name:
            messages.error(request, "Team name cannot be empty.")
            return redirect("team_list", company_slug=workspace.slug)

        if Team.objects.filter(workspace=workspace, slug=slug).exists():
            messages.error(request, f"Team with name '{name}' already exists in this workspace.")
            return redirect("team_list", company_slug=workspace.slug)

        Team.objects.create(workspace=workspace, name=name, slug=slug, description=description)
        messages.success(request, f"Team '{name}' created successfully.")
        return redirect("team_list", company_slug=workspace.slug)

    teams = Team.objects.filter(workspace=workspace).prefetch_related("memberships__user")
    return render(request, "teams/team_list.html", {
        "workspace": workspace,
        "teams": teams,
        "active_nav": "teams"
    })


@require_workspace_roles("OWNER", "ADMIN", "MANAGER")
def team_detail_view(request, company_slug, team_id):
    workspace = request.workspace
    team = get_object_or_404(Team, id=team_id, workspace=workspace)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add_member":
            user_id = request.POST.get("user_id")
            role = request.POST.get("role", "MEMBER")
            membership = workspace.memberships.filter(user_id=user_id, is_active=True).first()
            if membership:
                TeamMembership.objects.get_or_create(
                    team=team,
                    user=membership.user,
                    defaults={"role": role}
                )
                messages.success(request, f"Added {membership.user.full_name} to {team.name}.")
            return redirect("team_detail", company_slug=workspace.slug, team_id=team.id)

        elif action == "remove_member":
            membership_id = request.POST.get("membership_id")
            TeamMembership.objects.filter(id=membership_id, team=team).delete()
            messages.success(request, "Member removed from team.")
            return redirect("team_detail", company_slug=workspace.slug, team_id=team.id)

    members = team.memberships.select_related("user")
    existing_user_ids = members.values_list("user_id", flat=True)
    available_staff = workspace.memberships.filter(is_active=True).exclude(user_id__in=existing_user_ids).select_related("user")

    return render(request, "teams/team_detail.html", {
        "workspace": workspace,
        "team": team,
        "members": members,
        "available_staff": available_staff,
        "active_nav": "teams"
    })

