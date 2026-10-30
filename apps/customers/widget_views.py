import json
import uuid
import tempfile
from pathlib import Path
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.decorators.clickjacking import xframe_options_exempt
from apps.workspaces.models import Workspace, WorkspaceSettings
from apps.conversations.models import Conversation
from apps.customers.models import Customer
from services.conversations.conversation_service import conversation_service
from services.ai.agent_runner import agent_runner
from services.ai.stt_service import stt_service
from services.ai.tts_service import tts_service
from services.ai.model_manager import model_manager

@xframe_options_exempt
def widget_view(request, public_key):
    workspace = get_object_or_404(Workspace, public_key=public_key, status=Workspace.Status.ACTIVE)
    settings_obj = getattr(workspace, "settings", None)
    voice_config = getattr(workspace, "voice_config", None)

    return render(request, "widget/widget_frame.html", {
        "workspace": workspace,
        "settings": settings_obj,
        "voice_config": voice_config,
        "public_key": str(public_key),
    })


def widget_demo_view(request, public_key):
    workspace = get_object_or_404(Workspace, public_key=public_key, status=Workspace.Status.ACTIVE)
    return render(request, "widget/demo_store.html", {
        "workspace": workspace,
        "public_key": str(public_key),
    })


@csrf_exempt
@require_POST
def widget_message_api(request, public_key):
    try:
        workspace = Workspace.objects.get(public_key=public_key, status=Workspace.Status.ACTIVE)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Invalid or inactive workspace key."}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = request.POST

    message_text = data.get("message", "").strip()
    session_token = data.get("session_token", "").strip() or str(uuid.uuid4())
    customer_name = data.get("customer_name", "Visitor").strip()
    customer_email = data.get("customer_email", "").strip()

    if not message_text:
        return JsonResponse({"error": "Message text is required."}, status=400)

    customer = conversation_service.get_or_create_customer(
        workspace=workspace,
        session_token=session_token,
        name=customer_name,
        email=customer_email
    )
    conversation = conversation_service.start_conversation(
        workspace=workspace,
        customer=customer,
        channel=Conversation.Channel.WEB_CHAT
    )

    result = agent_runner.handle_customer_message(conversation, message_text)
    result["session_token"] = session_token

    return JsonResponse(result)


@csrf_exempt
@require_POST
def widget_voice_api(request, public_key):
    """
    Accepts audio blob from browser microphone.
    1. Transcribes via Whisper Small.
    2. Runs AI Agent evaluation.
    3. Synthesizes voice audio via Kokoro TTS.
    4. Returns transcript, reply text, and playback audio URL.
    """
    try:
        workspace = Workspace.objects.get(public_key=public_key, status=Workspace.Status.ACTIVE)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Invalid or inactive workspace key."}, status=404)

    audio_file = request.FILES.get("audio")
    session_token = request.POST.get("session_token", "").strip() or str(uuid.uuid4())

    if not audio_file:
        return JsonResponse({"error": "No audio file received."}, status=400)

    # Save audio temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
        for chunk in audio_file.chunks():
            temp_audio.write(chunk)
        temp_audio_path = temp_audio.name

    try:
        # 1. Transcribe with Whisper, with graceful WebSpeech fallback from client
        stt_result = stt_service.transcribe_audio(temp_audio_path)
        transcribed_text = stt_result.get("text", "").strip()
        browser_transcript = request.POST.get("browser_transcript", "").strip()

        if not transcribed_text and browser_transcript:
            transcribed_text = browser_transcript

        if not transcribed_text:
            return JsonResponse({
                "transcription": "",
                "ai_message": "Sorry, I could not hear or transcribe any speech. Please try speaking again.",
                "audio_url": "",
                "session_token": session_token
            })

        # 2. Get customer & conversation
        customer = conversation_service.get_or_create_customer(
            workspace=workspace,
            session_token=session_token
        )
        conversation = conversation_service.start_conversation(
            workspace=workspace,
            customer=customer,
            channel=Conversation.Channel.BROWSER_VOICE
        )

        # 3. Handle message with AI
        ai_result = agent_runner.handle_customer_message(conversation, transcribed_text)
        reply_text = ai_result["ai_message"]

        # 4. Generate TTS audio with Kokoro
        voice_config = getattr(workspace, "voice_config", None)
        voice_name = voice_config.voice_name if voice_config else "af_sarah"
        speed = voice_config.speed if voice_config else 1.0

        tts_result = tts_service.generate_speech(reply_text, voice=voice_name, speed=speed)

        return JsonResponse({
            "transcription": transcribed_text,
            "ai_message": reply_text,
            "audio_url": tts_result.get("audio_url", ""),
            "conversation_id": conversation.id,
            "is_escalated": ai_result.get("is_escalated", False),
            "session_token": session_token
        })
    finally:
        # Clean up temporary file
        try:
            Path(temp_audio_path).unlink(missing_ok=True)
        except Exception:
            pass


@csrf_exempt
@require_POST
def widget_complete_api(request, public_key):
    try:
        workspace = Workspace.objects.get(public_key=public_key, status=Workspace.Status.ACTIVE)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Invalid workspace."}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = request.POST

    session_token = data.get("session_token", "").strip()
    customer = Customer.objects.filter(workspace=workspace, session_token=session_token).first()
    if not customer:
        return JsonResponse({"error": "Session not found."}, status=404)

    active_conv = Conversation.objects.filter(workspace=workspace, customer=customer, status=Conversation.Status.ACTIVE).first()
    if not active_conv:
        return JsonResponse({"message": "No active conversation to complete."})

    res = conversation_service.finalize_conversation(active_conv)
    return JsonResponse(res)

