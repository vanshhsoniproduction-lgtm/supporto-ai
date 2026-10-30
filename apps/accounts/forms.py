from django import forms
from django.contrib.auth import get_user_model

User = get_user_model()

class LoginForm(forms.Form):
    username_or_email = forms.CharField(
        label="Username or Email",
        required=False,
        widget=forms.TextInput(attrs={
            "class": "w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-orange-500 focus:border-transparent outline-none transition",
            "placeholder": "admin or name@company.com",
            "autocomplete": "username"
        })
    )
    email = forms.CharField(required=False, widget=forms.HiddenInput())
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-orange-500 focus:border-transparent outline-none transition",
            "placeholder": "••••••••",
            "autocomplete": "current-password"
        })
    )

    def clean(self):
        cleaned_data = super().clean()
        ident = (cleaned_data.get("username_or_email") or cleaned_data.get("email") or "").strip()
        if not ident:
            raise forms.ValidationError("Please enter your username or email address.")
        cleaned_data["username_or_email"] = ident
        return cleaned_data


class StaffInviteForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            "class": "w-full px-4 py-2 border rounded-md focus:ring-2 focus:ring-orange-500",
            "placeholder": "agent@company.com"
        })
    )
    first_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={"class": "w-full px-4 py-2 border rounded-md"})
    )
    last_name = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={"class": "w-full px-4 py-2 border rounded-md"})
    )
    role = forms.ChoiceField(
        choices=[
            ("AGENT", "Support Agent"),
            ("MANAGER", "Support Manager"),
            ("ADMIN", "Administrator")
        ],
        widget=forms.Select(attrs={"class": "w-full px-4 py-2 border rounded-md"})
    )
    password = forms.CharField(
        required=False,
        help_text="Optional temporary password. If left blank, random password will be set.",
        widget=forms.PasswordInput(attrs={"class": "w-full px-4 py-2 border rounded-md"})
    )
