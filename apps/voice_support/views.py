from django.shortcuts import render, redirect
from django.contrib import messages
from apps.voice_support.models import VoiceConfiguration, IVRMenu, IVROption
from apps.teams.models import Team
from services.workspaces.access_control import require_workspace_roles
from services.ai.model_manager import model_manager

@require_workspace_roles("OWNER", "ADMIN")
def voice_settings_view(request, company_slug):
    workspace = request.workspace
    config, _ = VoiceConfiguration.objects.get_or_create(workspace=workspace)
    menu, _ = IVRMenu.objects.get_or_create(workspace=workspace, name="Main Support Menu")

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_config":
            config.is_enabled = bool(request.POST.get("is_enabled"))
            config.voice_name = request.POST.get("voice_name", "af_sarah").strip()
            config.speed = float(request.POST.get("speed", 1.0))
            config.welcome_voice_text = request.POST.get("welcome_voice_text", config.welcome_voice_text).strip()
            config.save()
            messages.success(request, "Voice configuration saved.")
        elif action == "add_ivr_option":
            digit = int(request.POST.get("digit", 1))
            label = request.POST.get("label", "").strip()
            action_type = request.POST.get("action_type", "ROUTE_AI")
            team_id = request.POST.get("target_team")
            target_team = Team.objects.filter(id=team_id, workspace=workspace).first() if team_id else None
            IVROption.objects.update_or_create(
                menu=menu,
                digit=digit,
                defaults={
                    "label": label,
                    "action_type": action_type,
                    "target_team": target_team,
                    "response_text": request.POST.get("response_text", "").strip()
                }
            )
            messages.success(request, f"IVR Option {digit} configured.")
        return redirect("voice_settings", company_slug=workspace.slug)

    options = menu.options.select_related("target_team").order_by("digit")
    teams = Team.objects.filter(workspace=workspace, is_active=True)
    health = model_manager.get_health_status()

    return render(request, "voice_support/settings.html", {
        "workspace": workspace,
        "config": config,
        "menu": menu,
        "options": options,
        "teams": teams,
        "health": health,
        "active_nav": "voice_settings"
    })

