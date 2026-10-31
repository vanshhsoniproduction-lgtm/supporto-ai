# Supporto AI — Hackathon Presentation & Judge Defense Guide

> **Problem Statement 2.5:** AI Agent for Automated Customer Support and Ticket Triage  
> **Team:** Supporto AI  
> **Platform Stack:** Django 5.1, Qwen 8B LLM (GGUF), Whisper Small STT, Kokoro ONNX TTS, Semantic RAG, Tailwind CSS, SQLite

---

## 1. The 30-Second Elevator Pitch

> *"Judges, small e-commerce stores and SaaS startups are drowning in repetitive customer support tickets, while hiring 24/7 support agents costs thousands of dollars a month. When urgent issues like double charges or damaged deliveries happen, they get buried under FAQs.*
>
> *We built **Supporto AI** — a privacy-first, multi-tenant AI customer support and automated ticket triage platform. Supporto AI reads customer inquiries across **live web chats, incoming emails, and real-time browser phone calls**. It classifies intent and urgency, drafts grounded replies from company knowledge bases, and automatically escalates critical financial or defect cases to human teams with SLA tracking.*
>
> *And as a bonus twist, it continuously tracks customer sentiment and generates automated weekly insight reports on recurring complaints."*

---

## 2. Problem Statement Alignment Matrix

| Problem Statement Requirement | Supporto AI Implementation | Live Demo Verification |
| :--- | :--- | :--- |
| **Target Users: Startups, E-commerce, SaaS** | Multi-tenant workspaces with isolated configurations, staff, and policies. | `/shopease/` vs Platform Admin at `/admin/` |
| **Reads incoming emails or chats** | 1. Official Gmail API sync + Centralized 3-panel Email Inbox.<br>2. Real-time web chat widget + Full-screen phone calling screen. | `/shopease/emails/inbox/`<br>`/widget/<public_key>/demo/` |
| **Classifies intent & urgency** | Identifies 10+ intents (`ORDER_STATUS`, `BILLING`, `REFUND`, etc.) and urgency levels (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`). | Customer chat auto-tags intent & urgency in real-time. |
| **Drafts replies from company KB (RAG)** | Grounded RAG retrieval over FAQs, return policies, and product documentation with anti-hallucination prompts. | `/shopease/knowledge-base/` & email proposed replies |
| **Escalates sensitive cases to a human** | Urgent billing, duplicate charges, or refund requests automatically generate Open Tickets assigned to specialized human teams (`Billing Support`, `Order Support`). | Instant ticket creation on urgent query with SLA timer |
| **Stack: LLM with Tool Calling, RAG, Ticket Dashboard** | Local Qwen 8B LLM with tool calling (`lookup_order`, `escalate_to_human`, `search_knowledge_base`, `create_ticket`), faster-whisper, Kokoro TTS, Django ticket dashboard. | `/shopease/tickets/` |
| **Bonus Twist 1: Sentiment Tracking** | Tracks sentiment across every interaction (`ANGRY`, `FRUSTRATED`, `NEUTRAL`, `POSITIVE`). | Sentiment logs in conversation and email audits |
| **Bonus Twist 2: Weekly Insights Report on Recurring Complaints** | Calculates top recurring complaints, resolution rates, average response time, and provides 1-click CSV download. | `/shopease/analytics/weekly/` |

---

## 3. The 3-Minute Live Demo Script (Step-by-Step)

### Minute 1: The Customer Experience (Chat & Phone Call)
1. Open the Customer Widget Demo Store:  
   `http://127.0.0.1:8000/widget/205efaa9-4d66-4903-b6f6-cccb701c8668/demo/`
2. Click the floating chat bubble. Enter name: `Vansh` and email: `vansh@example.com`.
3. Click **"Open Full Experience"**.
4. In the full chat tab, click **"Call Support AI"** in the header.
   - Show the judges the **mobile-style calling interface**: live ticking timer (`00:05`...), animated sound waves, and live transcript.
   - Say: *"Where is my order SE-84920?"*
   - Show how the AI executes the **`lookup_order` tool**, fetches the live tracking data, and speaks back naturally: *"Your order SE-84920 for Wireless Headphones is in transit via FedEx, estimated delivery tomorrow by 5 PM."*

### Minute 2: Action Boundaries & Sensitive Case Escalation
1. Now type or speak a sensitive complaint:  
   *"My credit card was charged twice ($199) for order SE-84920! Cancel it and refund my money immediately!"*
2. Point out to judges:
   - AI detects: **Intent: BILLING**, **Urgency: CRITICAL**, **Sentiment: ANGRY**.
   - AI does **NOT** hallucinate or blindly execute a refund on the company's bank account.
   - Instead, AI immediately responds: *"I understand this is urgent. I have created a Critical Priority Ticket (#TICK-...) and escalated your case directly to our Billing Support team."*
3. Switch to the Staff Portal at `http://127.0.0.1:8000/shopease/tickets/`:
   - Show the newly generated ticket with **CRITICAL** badge, assigned to **Billing Support**, with a strict **15-Minute SLA timer**!

### Minute 3: Email Triage & Weekly Insights (The Bonus Twist)
1. Navigate to **Email Review Queue** (`/shopease/emails/review/`):
   - Show how inbound customer emails are automatically triaged by the AI.
   - The AI drafts a grounded response using the Knowledge Base.
   - The human staff reviews, edits if needed, selects the assigned team, and clicks **"Approve & Dispatch"**.
2. Navigate to **Weekly Insights** (`/shopease/analytics/weekly/`):
   - Show the automated recurring complaint breakdown:  
     *42% Shipping Delays, 28% Screen Damage, 15% Billing Disputes*.
   - Click **"Download CSV Report"** to show instant export for company management.

---

## 4. Key Technical Differentiators (Why We Stand Out)

1. **Enterprise Federated Webhook Architecture (Safe Private Data):**  
   We do **not** couple the AI directly to client SQL databases. Supporto AI uses an authenticated Tool-Calling Webhook pattern. The store (Shopify, Meesho, SaaS) provides an authenticated endpoint. Supporto AI queries live customer order status over HTTPS and grounds the LLM response.
2. **Zero-Latency Think Tag Bypass:**  
   Reasoning models (like Qwen 2.5/3 or DeepSeek) waste 15-20 seconds computing internal chain-of-thought `<think>` tags on CPU. We inject a pre-closed `<think></think>` prefix into the prompt, forcing the model into instant generation mode (< 1.5s latency).
3. **Dual Voice Architecture:**  
   Browser WebSpeech STT + Web SpeechSynthesis provides zero-latency client feedback, backed by local Whisper Small STT and Kokoro ONNX TTS for offline, high-fidelity speech synthesis.
4. **Human-in-the-Loop Safeguards:**  
   Financial writes and refunds are strictly gated. AI handles high-volume read queries autonomously, and routes write/refund queries into the staff triage queue with SLA tracking.

---

## 5. Judge Q&A Cheat Sheet (Defense Answers)

### Q1: "How does the AI access private customer data across 3 different websites (A, B, C) with different databases?"
> *"Judges, connecting an external AI directly to a company's internal SQL database is an anti-pattern and a major violation of PCI-DSS and GDPR. In Supporto AI, each client store configures an authenticated Store API / Webhook endpoint in their workspace settings. When a verified customer asks 'Where is my order?', the LLM executes the registered `lookup_order` tool, queries the store's endpoint in real time over HTTPS, and speaks the live status back. The client store retains full ownership and security of their database."*

### Q2: "Can the AI hallucinate or refund customer money by mistake?"
> *"No. We enforce strict Action Boundaries. The AI is only authorized for read-only lookups (order status, shipping carrier, return policy eligibility). Transactional and financial mutations—such as order cancellations or charge refunds—trigger automated ticket triage. The AI classifies urgency as CRITICAL, tags sentiment, and creates a prioritized ticket on the human agent dashboard with an SLA countdown."*

### Q3: "What if local AI models are not available or running on low-resource machines?"
> *"Supporto AI is architected with graceful degradation. If local model runtimes are unavailable, our intelligent RAG fallback engine activates in < 15ms. In addition, our voice layer supports browser-native WebSpeech recognition and speech synthesis so users experience zero downtime."*

### Q4: "How does the bonus twist (Weekly Insights) work?"
> *"Our analytics engine continuously monitors conversations, email triage outcomes, and ticket resolutions over a rolling 7-day window. It aggregates recurring complaint categories, computes SLA compliance rates, and tracks sentiment shifts from ANGRY to POSITIVE. Workspace managers can review this on their dashboard or export a formal CSV report with a single click."*

