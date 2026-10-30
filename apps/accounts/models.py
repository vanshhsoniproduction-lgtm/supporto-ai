from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _

class CustomUserManager(BaseUserManager):
    """Custom user manager where email is the unique identifier for authentication."""
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_("The Email field must be set"))
        email = self.normalize_email(email).lower()
        extra_fields.setdefault("username", email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("platform_role", User.PlatformRole.PLATFORM_ADMIN)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    class PlatformRole(models.TextChoices):
        PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform Administrator"
        PLATFORM_SUPPORT = "PLATFORM_SUPPORT", "Platform Support"
        NONE = "NONE", "Standard User"

    username = models.CharField(max_length=150, unique=True, blank=True)
    email = models.EmailField(_("email address"), unique=True, db_index=True)
    platform_role = models.CharField(
        max_length=30,
        choices=PlatformRole.choices,
        default=PlatformRole.NONE,
        help_text="Explicit platform-level role. Only PLATFORM_ADMIN can access platform /admin/.",
    )
    avatar = models.FileField(upload_to="avatars/", null=True, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = CustomUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def clean(self):
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()
            if not self.username:
                self.username = self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
            if not self.username:
                self.username = self.email
        super().save(*args, **kwargs)

    @property
    def is_platform_admin(self) -> bool:
        return self.platform_role == self.PlatformRole.PLATFORM_ADMIN or self.is_superuser

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name if name else self.email

    def __str__(self):
        return self.full_name
