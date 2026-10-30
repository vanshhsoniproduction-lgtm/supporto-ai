from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()

class EmailOrUsernameModelBackend(ModelBackend):
    """Allows users to sign in with either their email address or username."""
    def authenticate(self, request, username=None, password=None, **kwargs):
        ident = username or kwargs.get("email")
        if not ident or not password:
            return None

        ident = ident.strip()
        user = User.objects.filter(
            Q(email__iexact=ident) | Q(username__iexact=ident)
        ).first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

