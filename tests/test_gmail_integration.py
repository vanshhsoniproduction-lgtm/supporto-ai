from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.db import IntegrityError
from apps.workspaces.models import Workspace
from apps.emails.models import MailboxConnection, InboundEmail
from apps.emails.services.token_crypto import encrypt_token, decrypt_token
from apps.emails.services.gmail_service import GmailService, strip_html_tags, parse_email_address

class GmailIntegrationTests(TestCase):
    def setUp(self):
        self.workspace = Workspace.objects.create(name="ShopEase", slug="shopease")

    def test_token_encryption_and_decryption(self):
        raw_secret = "ya29.a0ARrdaM_SAMPLE_OAUTH_ACCESS_TOKEN_12345"
        ciphertext = encrypt_token(raw_secret)
        self.assertNotEqual(ciphertext, raw_secret)
        self.assertNotIn("SAMPLE_OAUTH", ciphertext)

        plaintext = decrypt_token(ciphertext)
        self.assertEqual(plaintext, raw_secret)

    def test_empty_and_corrupt_tokens(self):
        self.assertEqual(encrypt_token(""), "")
        self.assertEqual(decrypt_token(""), "")
        self.assertEqual(decrypt_token("invalid_base64_or_bad_fernet_token"), "")

    def test_html_stripping_and_header_parsing(self):
        html_input = "<html><body><style>body { color: red; }</style><p>Hello <b>ShopEase</b> support team!</p></body></html>"
        cleaned = strip_html_tags(html_input)
        self.assertEqual(cleaned, "Hello ShopEase support team!")

        name, email = parse_email_address('Alice Smith <alice@example.com>')
        self.assertEqual(name, "Alice Smith")
        self.assertEqual(email, "alice@example.com")

        name2, email2 = parse_email_address('support@shopease.com')
        self.assertEqual(name2, "")
        self.assertEqual(email2, "support@shopease.com")

    def test_inbound_email_deduplication(self):
        # Create first inbound email
        InboundEmail.objects.create(
            workspace=self.workspace,
            provider_message_id="msg_gmail_unique_001",
            sender_email="customer@example.com",
            sender_name="Customer",
            subject="Order Help",
            original_text_body="Need help with order",
            normalized_text_body="Need help with order",
        )
        self.assertEqual(InboundEmail.objects.filter(workspace=self.workspace).count(), 1)

        # Attempt to insert identical provider_message_id for same workspace should raise IntegrityError
        with self.assertRaises(IntegrityError):
            InboundEmail.objects.create(
                workspace=self.workspace,
                provider_message_id="msg_gmail_unique_001",
                sender_email="customer@example.com",
                subject="Duplicate Order Help",
                original_text_body="Duplicate message",
            )

    def test_mailbox_connection_and_sync_cursor(self):
        connection = MailboxConnection.objects.create(
            workspace=self.workspace,
            email_address="support@shopease.com",
            provider=MailboxConnection.Provider.GMAIL,
            encrypted_access_token=encrypt_token("mock_access_token"),
            encrypted_refresh_token=encrypt_token("mock_refresh_token"),
            status=MailboxConnection.Status.ACTIVE,
        )
        self.assertIsNone(connection.last_sync_at)

        # Mock Gmail API client to return empty messages list
        with patch.object(GmailService, "get_authenticated_service") as mock_get_service:
            mock_service = MagicMock()
            mock_get_service.return_value = mock_service
            mock_list = MagicMock()
            mock_list.execute.return_value = {"messages": []}
            mock_service.users().messages().list.return_value = mock_list

            synced = GmailService.sync_mailbox(connection)
            self.assertEqual(synced, 0)

            connection.refresh_from_db()
            self.assertIsNotNone(connection.last_sync_at)

    def test_disconnected_mailbox_skipped(self):
        connection = MailboxConnection.objects.create(
            workspace=self.workspace,
            email_address="support@shopease.com",
            provider=MailboxConnection.Provider.GMAIL,
            encrypted_access_token=encrypt_token("mock_access_token"),
            status=MailboxConnection.Status.DISCONNECTED,
        )
        with patch.object(GmailService, "get_authenticated_service") as mock_get_service:
            synced = GmailService.sync_mailbox(connection)
            self.assertEqual(synced, 0)
            mock_get_service.assert_not_called()

    def test_sync_mailboxes_management_command(self):
        MailboxConnection.objects.create(
            workspace=self.workspace,
            email_address="support@shopease.com",
            provider=MailboxConnection.Provider.GMAIL,
            encrypted_access_token=encrypt_token("mock_access_token"),
            status=MailboxConnection.Status.ACTIVE,
        )
        with patch.object(GmailService, "sync_mailbox", return_value=0) as mock_sync:
            call_command("sync_mailboxes", once=True)
            mock_sync.assert_called_once()

