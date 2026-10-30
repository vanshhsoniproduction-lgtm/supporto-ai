import re
import html
import base64
import logging
from datetime import datetime, timezone as dt_timezone
from urllib.parse import urlencode
from django.conf import settings
from django.utils import timezone
from apps.emails.models import MailboxConnection, InboundEmail
from apps.emails.services.token_crypto import encrypt_token, decrypt_token

logger = logging.getLogger(__name__)

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/userinfo.email",
    "openid",
]

def strip_html_tags(text: str) -> str:
    """Removes HTML tags and normalizes whitespace safely."""
    if not text:
        return ""
    clean = re.sub(r"<style.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<script.*?</script>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = html.unescape(clean)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean

def parse_email_address(raw_header: str) -> tuple[str, str]:
    """Extracts (name, email) from headers like 'Support Team <support@example.com>'."""
    if not raw_header:
        return ("", "")
    match = re.search(r"^(.*?)\s*<([^>]+)>$", raw_header.strip())
    if match:
        name = match.group(1).strip().strip('"\'')
        email = match.group(2).strip().lower()
        return (name, email)
    return ("", raw_header.strip().lower())

class GmailService:
    @staticmethod
    def get_oauth_authorization_url(workspace_slug: str, redirect_uri: str = None) -> str:
        """Constructs Google OAuth authorization URL for Gmail mailbox connection."""
        client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
        if not redirect_uri:
            redirect_uri = getattr(settings, "GMAIL_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/integrations/gmail/callback/")

        state_payload = f"gmail_sync:{workspace_slug}"
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent", # Forces refresh_token return
            "state": state_payload,
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    @staticmethod
    def handle_oauth_callback(code: str, workspace, redirect_uri: str = None) -> MailboxConnection:
        """Exchanges auth code for tokens and creates or updates a MailboxConnection."""
        import requests
        client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
        client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
        if not redirect_uri:
            redirect_uri = getattr(settings, "GMAIL_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/integrations/gmail/callback/")

        token_url = "https://oauth2.googleapis.com/token"
        payload = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }

        resp = requests.post(token_url, data=payload, timeout=12)
        if resp.status_code != 200:
            raise ValueError(f"Failed to obtain tokens from Google: {resp.text}")

        token_data = resp.json()
        access_token = token_data.get("access_token", "")
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)
        token_expiry = timezone.now() + timezone.timedelta(seconds=expires_in)
        scope = token_data.get("scope", "")

        # Fetch mailbox user identity
        userinfo_resp = requests.get(
            "https://www.googleapis.com/oauth2/v3/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10
        )
        userinfo = userinfo_resp.json()
        email_address = userinfo.get("email", "").strip().lower()
        if not email_address:
            raise ValueError("Could not determine email address for Gmail connection.")

        connection, created = MailboxConnection.objects.get_or_create(
            workspace=workspace,
            email_address=email_address,
            defaults={
                "provider": MailboxConnection.Provider.GMAIL,
                "provider_account_id": userinfo.get("sub", ""),
                "encrypted_access_token": encrypt_token(access_token),
                "encrypted_refresh_token": encrypt_token(refresh_token) if refresh_token else "",
                "token_expiry": token_expiry,
                "granted_scopes": scope,
                "status": MailboxConnection.Status.ACTIVE,
                "error_message": "",
            }
        )

        if not created:
            connection.encrypted_access_token = encrypt_token(access_token)
            if refresh_token:
                connection.encrypted_refresh_token = encrypt_token(refresh_token)
            connection.token_expiry = token_expiry
            connection.granted_scopes = scope
            connection.status = MailboxConnection.Status.ACTIVE
            connection.error_message = ""
            connection.save()

        return connection

    @classmethod
    def get_authenticated_service(cls, connection: MailboxConnection):
        """Constructs authenticated Gmail API client from MailboxConnection with automatic refresh."""
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "")
        client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "")
        access_token = decrypt_token(connection.encrypted_access_token)
        refresh_token = decrypt_token(connection.encrypted_refresh_token)

        credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=GMAIL_SCOPES,
        )

        if credentials.expired or not credentials.valid:
            try:
                credentials.refresh(Request())
                connection.encrypted_access_token = encrypt_token(credentials.token)
                if credentials.expiry:
                    connection.token_expiry = timezone.make_aware(credentials.expiry) if timezone.is_naive(credentials.expiry) else credentials.expiry
                connection.save(update_fields=["encrypted_access_token", "token_expiry"])
            except Exception as e:
                connection.status = MailboxConnection.Status.ERROR
                connection.error_message = f"Token refresh failed: {str(e)[:200]}"
                connection.save(update_fields=["status", "error_message"])
                raise

        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    @classmethod
    def sync_mailbox(cls, connection: MailboxConnection, max_messages: int = 25) -> int:
        """
        Synchronizes new incoming emails for the connected mailbox.
        Strictly prevents duplicates, extracts payload, safely strips HTML,
        and hands off each email to the AI triage pipeline.
        """
        from apps.emails.services.email_triage import email_triage_service

        connection.last_sync_at = timezone.now()
        connection.save(update_fields=["last_sync_at"])

        if connection.status == MailboxConnection.Status.DISCONNECTED:
            logger.info(f"Skipping disconnected mailbox {connection.email_address}")
            return 0

        try:
            service = cls.get_authenticated_service(connection)
        except Exception as e:
            logger.error(f"Cannot initialize Gmail client for {connection.email_address}: {e}")
            return 0

        synced_count = 0
        try:
            # Query messages in inbox
            query = "is:inbox -label:SPAM -label:TRASH"
            list_res = service.users().messages().list(
                userId="me",
                q=query,
                maxResults=max_messages
            ).execute()

            messages = list_res.get("messages", [])
            for msg_summary in messages:
                msg_id = msg_summary["id"]

                # Deduplication check
                if InboundEmail.objects.filter(workspace=connection.workspace, provider_message_id=msg_id).exists():
                    continue

                # Fetch full message
                msg_data = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="full"
                ).execute()

                thread_id = msg_data.get("threadId", "")
                internal_date_ms = int(msg_data.get("internalDate", 0))
                received_dt = datetime.fromtimestamp(internal_date_ms / 1000.0, tz=dt_timezone.utc) if internal_date_ms else timezone.now()

                headers = {h["name"].lower(): h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
                raw_from = headers.get("from", "")
                sender_name, sender_email = parse_email_address(raw_from)
                recipient = headers.get("to", connection.email_address)
                cc = headers.get("cc", "")
                subject = headers.get("subject", "(No Subject)")

                # Extract bodies and attachments
                text_body, html_body, attachments = cls._extract_body_and_attachments(msg_data.get("payload", {}))
                normalized_text = strip_html_tags(text_body if text_body else html_body)

                inbound_email = InboundEmail.objects.create(
                    workspace=connection.workspace,
                    mailbox_connection=connection,
                    provider_message_id=msg_id,
                    provider_thread_id=thread_id,
                    sender_email=sender_email,
                    sender_name=sender_name,
                    recipient=recipient,
                    cc=cc,
                    subject=subject,
                    original_text_body=text_body,
                    normalized_text_body=normalized_text,
                    html_body=html_body,
                    received_at=received_dt,
                    attachments_metadata=attachments,
                    processing_status=InboundEmail.ProcessingStatus.NEW,
                )

                # Process via AI Email Triage
                email_triage_service.process_inbound_email(inbound_email)
                synced_count += 1

            connection.last_successful_sync_at = timezone.now()
            connection.status = MailboxConnection.Status.ACTIVE
            connection.error_message = ""
            connection.save(update_fields=["last_successful_sync_at", "status", "error_message"])

        except Exception as e:
            logger.error(f"Gmail sync failed for {connection.email_address}: {e}")
            connection.status = MailboxConnection.Status.ERROR
            connection.error_message = f"Sync error: {str(e)[:250]}"
            connection.save(update_fields=["status", "error_message"])

        return synced_count

    @classmethod
    def _extract_body_and_attachments(cls, payload: dict) -> tuple[str, str, list]:
        """Recursively parses MIME payload to extract plain text, HTML, and attachment metadata."""
        text_body = ""
        html_body = ""
        attachments = []

        def _walk(part):
            nonlocal text_body, html_body
            mime_type = part.get("mimeType", "")
            filename = part.get("filename", "")
            body = part.get("body", {})

            if filename:
                attachments.append({
                    "filename": filename,
                    "mime_type": mime_type,
                    "size": body.get("size", 0),
                    "attachment_id": body.get("attachmentId", ""),
                })

            data = body.get("data")
            if data:
                try:
                    decoded = base64.urlsafe_b64decode(data.encode("ASCII")).decode("utf-8", errors="replace")
                    if mime_type == "text/plain" and not text_body:
                        text_body = decoded
                    elif mime_type == "text/html" and not html_body:
                        html_body = decoded
                except Exception:
                    pass

            for subpart in part.get("parts", []):
                _walk(subpart)

        _walk(payload)
        return (text_body, html_body, attachments)

gmail_service = GmailService()

