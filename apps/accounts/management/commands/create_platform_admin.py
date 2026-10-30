from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()

class Command(BaseCommand):
    help = "Creates or promotes a Platform Administrator for Supporto AI"

    def add_arguments(self, parser):
        parser.add_argument("--email", type=str, default="admin@supporto.ai", help="Admin email address")
        parser.add_argument("--password", type=str, default="Supporto@Admin123", help="Admin password")
        parser.add_argument("--first-name", type=str, default="Platform", help="First name")
        parser.add_argument("--last-name", type=str, default="Admin", help="Last name")

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        first_name = options["first_name"]
        last_name = options["last_name"]

        user, created = User.objects.get_or_create(
            email=email,
            defaults={
                "username": email,
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": True,
                "is_superuser": True,
                "platform_role": User.PlatformRole.PLATFORM_ADMIN,
            }
        )

        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.platform_role = User.PlatformRole.PLATFORM_ADMIN
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"[+] Platform Administrator '{email}' created successfully!"))
        else:
            self.stdout.write(self.style.SUCCESS(f"[+] User '{email}' promoted to Platform Administrator!"))
        self.stdout.write(f"    Login URL : /login/")
        self.stdout.write(f"    Admin URL : /admin/")
        self.stdout.write(f"    Password  : {password}")

