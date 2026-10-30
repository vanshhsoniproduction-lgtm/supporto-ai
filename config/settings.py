import os
from pathlib import Path
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-supporto-ai-dev-secret-key-change-in-prod-xyz123")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")

allowed_hosts_raw = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
ALLOWED_HOSTS = [h.strip() for h in allowed_hosts_raw.split(",") if h.strip()]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Supporto AI Apps
    "apps.accounts.apps.AccountsConfig",
    "apps.workspaces.apps.WorkspacesConfig",
    "apps.teams.apps.TeamsConfig",
    "apps.customers.apps.CustomersConfig",
    "apps.conversations.apps.ConversationsConfig",
    "apps.tickets.apps.TicketsConfig",
    "apps.knowledge_base.apps.KnowledgeBaseConfig",
    "apps.ai_engine.apps.AiEngineConfig",
    "apps.voice_support.apps.VoiceSupportConfig",
    "apps.analytics.apps.AnalyticsConfig",
    "apps.emails.apps.EmailsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "services.workspaces.access_control.TenantContextMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "services.workspaces.access_control.workspace_context_processor",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Database
db_path = BASE_DIR / os.getenv("DATABASE_PATH", "data/supporto.sqlite3")
db_path.parent.mkdir(parents=True, exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(db_path),
    }
}

# Custom User Model
AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "apps.accounts.auth_backend.EmailOrUsernameModelBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
(MEDIA_ROOT / "uploads").mkdir(parents=True, exist_ok=True)
(MEDIA_ROOT / "audio").mkdir(parents=True, exist_ok=True)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Auth Redirects
LOGIN_URL = "/admin/login/"
LOGIN_REDIRECT_URL = "/login/redirect/"
LOGOUT_REDIRECT_URL = "/"

# AI Settings
AI_ENABLED = os.getenv("AI_ENABLED", "True").lower() in ("true", "1", "yes")
MODEL_LLM_PATH = BASE_DIR / os.getenv("MODEL_LLM_PATH", "models/llm/Qwen3-8B-Q4_K_M.gguf")
MODEL_STT_PATH = BASE_DIR / os.getenv("MODEL_STT_PATH", "models/stt/whisper-small")
MODEL_TTS_PATH = BASE_DIR / os.getenv("MODEL_TTS_PATH", "models/tts/kokoro")

# Google OAuth Configuration
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/accounts/google/callback/")
GMAIL_OAUTH_REDIRECT_URI = os.getenv("GMAIL_OAUTH_REDIRECT_URI", "http://127.0.0.1:8000/integrations/gmail/callback/")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
