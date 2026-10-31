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
from apps.orders.utils import normalize_phone
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
    customer_name = request.GET.get("name", "").strip()
    customer_email = request.GET.get("email", "").strip()
    customer_phone = request.GET.get("phone", "").strip() or request.session.get("customer_phone", "").strip()
    initial_query = request.GET.get("q", "").strip()

    return render(request, "widget/widget_frame.html", {
        "workspace": workspace,
        "settings": settings_obj,
        "voice_config": voice_config,
        "public_key": str(public_key),
        "customer_name": customer_name,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
        "initial_query": initial_query,
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
    customer_phone = data.get("customer_phone", "").strip() or request.session.get("customer_phone", "").strip()

    if customer_phone:
        request.session["customer_phone"] = customer_phone

    if not message_text:
        return JsonResponse({"error": "Message text is required."}, status=400)

    customer = conversation_service.get_or_create_customer(
        workspace=workspace,
        session_token=session_token,
        name=customer_name,
        email=customer_email,
        phone=customer_phone
    )
    conv_id = data.get("conversation_id")
    conversation = None
    if conv_id:
        conversation = Conversation.objects.filter(workspace=workspace, id=conv_id).first()
    if not conversation:
        conversation = conversation_service.start_conversation(
            workspace=workspace,
            customer=customer,
            channel=Conversation.Channel.WEB_CHAT
        )

    if customer_phone and customer and not customer.normalized_phone:
        customer.phone = customer_phone
        customer.clean()
        customer.save(update_fields=["phone", "normalized_phone", "updated_at"])

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
    customer_name = request.POST.get("customer_name", "Visitor").strip()
    customer_email = request.POST.get("customer_email", "").strip()
    customer_phone = request.POST.get("customer_phone", "").strip() or request.session.get("customer_phone", "").strip()

    if customer_phone:
        request.session["customer_phone"] = customer_phone

    if not audio_file:
        return JsonResponse({"error": "No audio file received."}, status=400)

    # Save audio temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as temp_audio:
        for chunk in audio_file.chunks():
            temp_audio.write(chunk)
        temp_audio_path = temp_audio.name

    try:
        # 1. High-speed speech pipeline: Use browser real-time transcript if available (<100ms),
        # otherwise run local Whisper Small STT
        browser_transcript = request.POST.get("browser_transcript", "").strip()
        transcribed_text = browser_transcript

        if not transcribed_text:
            stt_result = stt_service.transcribe_audio(temp_audio_path)
            transcribed_text = stt_result.get("text", "").strip()

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
            session_token=session_token,
            name=customer_name,
            email=customer_email,
            phone=customer_phone
        )
        conversation = conversation_service.start_conversation(
            workspace=workspace,
            customer=customer,
            channel=Conversation.Channel.BROWSER_VOICE
        )

        if customer_phone and conversation:
            if not conversation.metadata:
                conversation.metadata = {}
            if conversation.metadata.get("customer_phone") != customer_phone:
                conversation.metadata["customer_phone"] = customer_phone
                conversation.save(update_fields=["metadata", "updated_at"])

        # 3. Handle message with AI
        ai_result = agent_runner.handle_customer_message(conversation, transcribed_text)
        reply_text = ai_result["ai_message"]

        # 4. Generate TTS audio with Kokoro (optimized for low-latency conversational speech)
        voice_config = getattr(workspace, "voice_config", None)
        voice_name = voice_config.voice_name if voice_config else "af_sarah"
        speed = voice_config.speed if voice_config else 1.05

        # Limit voice synthesis to first 2 concise sentences for instant audio streaming
        import re
        tts_sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', reply_text) if s.strip()]
        spoken_text = " ".join(tts_sentences[:2]) if tts_sentences else reply_text

        tts_result = tts_service.generate_speech(spoken_text, voice=voice_name, speed=speed)

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


@csrf_exempt
@require_POST
def widget_customer_check_api(request, public_key):
    try:
        workspace = Workspace.objects.get(public_key=public_key, status=Workspace.Status.ACTIVE)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Invalid workspace key."}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = request.POST

    raw_phone = data.get("phone", "").strip()
    norm_phone = normalize_phone(raw_phone)
    if not norm_phone or len(norm_phone) != 10 or norm_phone[0] not in "6789":
        return JsonResponse({"error": "Please enter a valid 10-digit Indian mobile number."}, status=400)

    # 1. Check existing Customer
    customer = Customer.objects.filter(workspace=workspace, normalized_phone=norm_phone).first()
    found_name = customer.name if customer and customer.name else ""

    # 2. Check Orders on file
    if not found_name:
        from apps.orders.models import Order
        order = Order.objects.filter(workspace=workspace, customer_phone=norm_phone).exclude(customer_name="").first()
        if order and order.customer_name:
            found_name = order.customer_name

    # 3. Check Shipments on file
    if not found_name:
        from apps.orders.models import Shipment
        shipment = Shipment.objects.filter(workspace=workspace, receiver_phone=norm_phone).exclude(receiver_name="").first()
        if shipment and shipment.receiver_name:
            found_name = shipment.receiver_name

    if found_name:
        if not customer:
            customer = Customer.objects.create(
                workspace=workspace,
                name=found_name,
                phone=norm_phone,
                normalized_phone=norm_phone
            )
        request.session["customer_phone"] = norm_phone
        request.session["customer_name"] = found_name
        return JsonResponse({
            "exists": True,
            "name": found_name,
            "phone": norm_phone
        })

    return JsonResponse({
        "exists": False,
        "phone": norm_phone
    })


@csrf_exempt
@require_POST
def widget_customer_register_api(request, public_key):
    try:
        workspace = Workspace.objects.get(public_key=public_key, status=Workspace.Status.ACTIVE)
    except Workspace.DoesNotExist:
        return JsonResponse({"error": "Invalid workspace key."}, status=404)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        data = request.POST

    raw_phone = data.get("phone", "").strip()
    norm_phone = normalize_phone(raw_phone)
    if not norm_phone or len(norm_phone) != 10 or norm_phone[0] not in "6789":
        return JsonResponse({"error": "Please enter a valid 10-digit Indian mobile number."}, status=400)

    name = data.get("name", "").strip() or "Valued Customer"

    customer = Customer.objects.filter(workspace=workspace, normalized_phone=norm_phone).first()
    if customer:
        customer.name = name
        customer.phone = norm_phone
        customer.save(update_fields=["name", "phone", "updated_at"])
    else:
        customer = Customer.objects.create(
            workspace=workspace,
            name=name,
            phone=norm_phone,
            normalized_phone=norm_phone
        )

    request.session["customer_phone"] = norm_phone
    request.session["customer_name"] = name
    return JsonResponse({
        "success": True,
        "name": customer.name,
        "phone": norm_phone
    })


@csrf_exempt
@require_POST
def widget_customer_logout_api(request, public_key):
    request.session.pop("customer_phone", None)
    request.session.pop("customer_name", None)
    return JsonResponse({"success": True})
