# Supporto AI
### Intelligent Support. Faster Resolutions.
A complete, multi-tenant AI customer support & ticket management web platform built with Django, Tailwind CSS, Material Design, and local AI model integration (Qwen 8B LLM, Whisper Small STT, Kokoro TTS).

---

## Architecture Overview

- **Backend**: Python 3.12, Django 5.1, Django ORM, SQLite (`data/supporto.sqlite3`).
- **Multi-Tenancy**: Isolated workspaces, URL-safe company slugs (`/[company_slug]/`), role-based access control (Platform Admin, Owner, Admin, Manager, Agent).
- **Frontend**: Pure Django Templates, Tailwind CSS, Material Symbols, Vanilla JavaScript (No React/Node/SPA).
- **Custom Admin**: Custom platform administration at `/admin/` (Default Django admin relocated to `/django-admin/`).
- **Customer Widget**: Embeddable chat and push-to-talk browser voice widget identified by unguessable public keys (`/widget/<public_key>/`).
- **Local AI Models**:
  - LLM: `models/llm/Qwen3-8B-Q4_K_M.gguf`
  - STT: `models/stt/whisper-small/`
  - TTS: `models/tts/kokoro/`
- **Graceful Degradation**: Core web features remain fully operational even if local AI runtimes or models are unavailable.

---

## Directory Structure

```
supporto_ai/
├── manage.py
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
├── apps/
│   ├── accounts/          # Custom User, authentication, platform roles, staff
│   ├── workspaces/        # Multi-tenant workspaces, settings, custom platform admin
│   ├── teams/             # Support teams & multi-team agent memberships
│   ├── customers/         # Anonymous visitors & customer identities
│   ├── conversations/     # Chat transcripts, messages, intent & urgency
│   ├── tickets/           # Ticket lifecycle, assignments, events, comments
│   ├── knowledge_base/    # Multi-tenant RAG documents & FAQ management
│   ├── ai_engine/         # AI configuration, execution logs, prompt builder
│   ├── voice_support/     # Kokoro TTS config, browser voice sessions, IVR
│   └── analytics/         # Audit logs, live database metrics, SLA reporting
├── services/
│   ├── ai/                # Model manager, LLM inference, Whisper STT, Kokoro TTS, RAG
│   ├── tickets/           # Ticket service & intelligent routing
│   ├── conversations/     # Conversation lifecycle & ticket auto-creation
│   ├── workspaces/        # Strict tenant isolation middleware & access control
│   └── analytics/         # Real-time metrics calculations
├── templates/             # Material Design-inspired Django templates
├── static/                # CSS and JavaScript assets
├── media/                 # Uploaded files and generated voice audio
├── scripts/
│   └── copy_jarvis_models.py # Safe model copy & checksum script
├── data/
│   └── supporto.sqlite3   # Development SQLite database
├── models/
│   ├── llm/               # Qwen 8B GGUF
│   ├── stt/               # Whisper Small (CTranslate2)
│   ├── tts/               # Kokoro (ONNX + voices)
│   └── model_manifest.json# SHA-256 integrity manifest
├── tests/                 # Automated test suite
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Quickstart & Setup Guide (macOS / Linux)

### 1. Python Requirements
- Python 3.12 (e.g. `/opt/homebrew/bin/python3.12` on macOS Apple Silicon).

### 2. Create and Activate Virtual Environment
```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```
Default configuration values work immediately for local development.

### 5. Safe Model Copy from Existing JARVIS Project
To safely copy the local AI models without touching or altering the source JARVIS files:
```bash
python scripts/copy_jarvis_models.py --jarvis-root "/Users/vanshhsoni/Desktop/JARVIS"
```
The script will:
- Copy `Qwen3-8B-Q4_K_M.gguf` into `models/llm/`.
- Copy `whisper-small/` into `models/stt/whisper-small/`.
- Copy `kokoro/` into `models/tts/kokoro/` (excluding personal audio recordings).
- Verify SHA-256 hashes and generate `models/model_manifest.json`.
- Skip already verified files if re-run.

### 6. Apply Database Migrations
```bash
python manage.py migrate
```

### 7. Create Platform Administrator
Create the super administrator account for `/admin/`:
```bash
python manage.py create_platform_admin --email admin@supporto.ai --password Supporto@Admin123
```

### 8. Seed Initial Demo Data
Populate the database with the **ShopEase** company, teams, multi-team agents, sample tickets, knowledge FAQs, and voice settings:
```bash
python manage.py seed_demo
```

---

## Running the Application

Start the local Django development server:
```bash
python manage.py runserver
```
Visit the following primary URLs:

1. **Custom Platform Administration**:
   - URL: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)
   - Login: `admin@supporto.ai` / `Supporto@Admin123`
   - Features: Platform Overview, Company Approvals/Suspensions, User Roles, AI Model Health, Audit Trail.

2. **Company Portal (ShopEase)**:
   - URL: [http://127.0.0.1:8000/shopease/](http://127.0.0.1:8000/shopease/)
   - Owner Login: `owner@shopease.com` / `ShopEase@123`
   - Agent Login (Multi-team): `agent.two@shopease.com` / `ShopEase@123`
   - Features: Support Dashboard, All Tickets, Team Queue, My Tickets, Teams, Staff, Knowledge Base (RAG), AI Settings, Voice & IVR Settings, Analytics.

3. **Customer Support Widget Demo Store**:
   - URL: [http://127.0.0.1:8000/widget/205efaa9-4d66-4903-b6f6-cccb701c8668/demo/](http://127.0.0.1:8000/widget/205efaa9-4d66-4903-b6f6-cccb701c8668/demo/)
   - Interactive e-commerce store with floating AI widget.
   - Test **Chat with AI** or **Talk with AI** (push-to-talk).
   - Test **Urgent Billing Escalation**: Type *"my credit card was deducted twice for order #SE-84920"*. The AI immediately flags the issue as **CRITICAL**, auto-generates a ticket, and routes it directly to **Billing Support**.

4. **Default Django Admin** (Database debugging):
   - URL: [http://127.0.0.1:8000/django-admin/](http://127.0.0.1:8000/django-admin/)

---

## Running Automated Tests

Run the full automated test suite verifying Authentication, Multi-tenant Security, Cross-workspace Data Leakage Prevention, Teams, Ticketing, and Widget:
```bash
python manage.py test tests
```

---

## Google OAuth Configuration (Optional)

To enable Google OAuth for company owners:
1. Go to Google Cloud Console > APIs & Services > Credentials.
2. Create an OAuth 2.0 Client ID (Web Application).
3. Set the Authorized Redirect URI to:
   `http://127.0.0.1:8000/accounts/google/callback/`
4. Update `.env`:
   ```env
   GOOGLE_OAUTH_CLIENT_ID=your-google-client-id
   GOOGLE_OAUTH_CLIENT_SECRET=your-google-client-secret
   ```
If unconfigured, the application runs in development mode and provides an interactive setup page.

