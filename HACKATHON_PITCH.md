# Supporto AI — Hackathon Presentation & Judge Defense Guide

> **Problem Statement 2.5:** AI Agent for Automated Customer Support and Ticket Triage  
> **Team:** Supporto AI  
> **Platform Stack:** Django 5.1, Real SQL Data Layer (`apps/orders`), Local Qwen 8B LLM (GGUF), Whisper Small STT, Kokoro ONNX TTS, Semantic RAG, Tailwind CSS, SQLite

---

## 1. The 30-Second Elevator Pitch

> *"Judges, small e-commerce stores and logistics companies are drowning in repetitive customer support tickets, while hiring 24/7 human support teams costs thousands of dollars a month. When urgent issues like double charges, damaged parcels, or delays happen, they get buried under FAQs.
>
> We built **Supporto AI** — a privacy-first, multi-tenant AI customer support and automated ticket triage platform backed by a **real SQL relational database**. Supporto AI serves customers across **live web chats, incoming emails, and real-time browser phone calls**. It verifies customer identity via 10-digit mobile phone numbers with zero-leak privacy protection, provides granular order and consignment tracking, and automatically escalates critical financial or defect cases to human teams with SLA tracking.
>
> And as our bonus twist, it continuously tracks customer sentiment and generates automated weekly insight reports on recurring complaints."*

---

## 2. Platform Architecture & Data Layer

Unlike systems with mocked or hardcoded order data, Supporto AI features a production-grade relational database:

- **E-Commerce Data Model (`ShopEase`):** Real relational `Order`, `OrderItem`, and `ReturnRequest` tables tracking items, pricing, payment methods (UPI, Card, COD), delivery estimates, and return windows.
- **Logistics & Carrier Network (`ExpressBeas`):** Dedicated `Shipment` and `ShipmentEvent` tables tracking 15-digit AWBs across multi-hub sorting scans (Pickup -> Inward -> In Transit -> Out for Delivery -> Delivered with OTP).
- **Phone-Verified Customer Identity:** Customers are authenticated by name and 10-digit Indian mobile number (`6367743066` / `9571538144`). If a phone number does not match the order or consignment record, the AI enforces a strict zero-leak policy.
- **Audited Tool Sandbox:** The AI interacts through typed, audited tool executions (`list_customer_orders`, `get_order_details`, `get_shipment_tracking`, `get_return_refund_status`, `cancel_order`, `escalate_to_human`).

---

## 3. Demo Credentials & Portals

| Portal / Role | URL | Email / Phone | Password |
| :--- | :--- | :--- | :--- |
| **Platform Superuser** | `http://127.0.0.1:8000/admin/` | `admin@admin.com` | `admin` |
| **ShopEase Owner** | `http://127.0.0.1:8000/shopease/dashboard/` | `owner@shopease.com` | `ShopEase@123` |
| **ShopEase Agent** | `http://127.0.0.1:8000/shopease/dashboard/` | `agent@shopease.com` | `Agent@123` |
| **ExpressBeas Owner** | `http://127.0.0.1:8000/expressbeas/dashboard/` | `owner@expressbeas.in` | `ExpressBeas@123` |
| **ExpressBeas Agent** | `http://127.0.0.1:8000/expressbeas/dashboard/` | `agent@expressbeas.in` | `Agent@123` |
| **ShopEase Demo Store** | `http://127.0.0.1:8000/shopease/demo/` | Pre-filled: Vansh (`6367743066`) | — |
| **ExpressBeas Tracking** | `http://127.0.0.1:8000/expressbeas/demo/` | Pre-filled: Vansh (`6367743066`) | — |

---

## 4. The 3-Minute Live Demo Script (Step-by-Step)

### Minute 1: The Customer Experience & Phone Identity (ShopEase)
1. Open the **ShopEase Demo Store**: `http://127.0.0.1:8000/shopease/demo/`
2. Click the floating chat bubble. Choose quick-fill **Customer A (Vansh Soni — 6367743066)**.
3. Test Query 1: *"What are my orders?"*  
   -> AI lists real SQL orders (`SE-84920`, `SE-84922`) with items, prices, and status.
4. Test Query 2: *"Where is order SE-84920?"*  
   -> AI details: Delivered 3 days ago, FedEx Express (FX-94001118), return window open.
5. Test Query 3: *"What is the status of my return?"*  
   -> AI reveals: Pickup scheduled for Wireless Headphones, refund of ₹4,999.00 to original card ending 4242.
6. Test Query 4: *"Cancel order SE-84922"*  
   -> Order is PLACED. AI cancels it in the database and automatically creates a high-priority ticket (#TK-xxxx) for Order Support!

### Minute 2: Carrier Network & Multi-Tenant Security (ExpressBeas)
1. Open **ExpressBeas Tracking Demo**: `http://127.0.0.1:8000/expressbeas/demo/`
2. Test Query: *"Where is my consignment 152785863851740?"*  
   -> AI returns the real 6-event timeline: Booked at Ghaziabad Hub -> Delhi Main Sort Hub -> Delhi Highway Dispatch -> Jaipur Mother Hub -> Delivered with OTP.
3. **Show Zero-Leak Privacy to Judges:**  
   Ask for Riya's parcel (`152785863852001`) while logged in as Vansh (`6367743066`).  
   -> AI securely rejects: *"I couldn't verify that order against your phone number."* Zero data leaked.
4. **Show Cross-Tenant Isolation:**  
   Ask ExpressBeas for ShopEase order `SE-84920`.  
   -> AI immediately reports order not found. Complete multi-tenant database separation.

### Minute 3: Sensitive Case Escalation & Bonus Weekly Insights
1. In chat, send:  
   *"My credit card was charged twice ($199) for order SE-84920! Cancel it and refund my money immediately!"*
2. AI detects **Intent: BILLING**, **Urgency: CRITICAL**, **Sentiment: ANGRY**, and responds authoritatively:  
   *"I have marked this as urgent and immediately routed it to our Billing Support team. Your support ticket is #TK-xxxx. A dedicated human specialist will review your case and respond within 15 minutes."*
3. Switch to Staff Portal (`/shopease/tickets/`):  
   Show the new ticket with **CRITICAL** badge, linked directly to `related_order=SE-84920` with a 15-minute SLA timer.
4. Switch to **Weekly Insights** (`/shopease/analytics/weekly-insights/`):  
   Show recurring customer complaint analytics, percentage breakdowns summing to 100%, and 1-click CSV report export.

---

## 5. Judge Q&A Cheat Sheet (Defense Answers)

### Q1: "Where does the order and tracking data come from?"
> *"Our platform uses a real SQL relational database layer (`apps/orders`) with foreign key workspace scoping. ShopEase manages Orders, OrderItems, and ReturnRequests. ExpressBeas manages Shipments with granular ShipmentEvents. In addition, workspace owners can optionally configure an external authenticated webhook if they want to integrate a live external Shopify or custom ERP store."*

### Q2: "How do you protect customer data and privacy?"
> *"We enforce phone number verification on all order and consignment queries. When a customer enters their 10-digit mobile number, the AI normalizes it (`+91`, `0`, dashes, spaces) and verifies it against the order's `customer_phone` or shipment's `receiver_phone`/`sender_phone`. If there is a mismatch, the system reveals zero order details and advises the user to contact verified support."*

### Q3: "Can the AI hallucinate or issue false refunds?"
> *"No. The AI's tool registry has strict operational boundaries. The AI can read order status, tracking timelines, and return status, but financial actions like issuing refunds are gated. For cancellations, the AI updates the order status in the database and automatically creates a linked support ticket for human agents to process the payment gateway reversal."*

### Q4: "How does the bonus twist (Weekly Insights) work?"
> *"Our analytics engine continuously monitors conversations, email triage outcomes, and ticket resolutions over a rolling 7-day window. It aggregates recurring complaint categories, computes SLA compliance rates, and tracks sentiment shifts from ANGRY to POSITIVE. Workspace managers can review this on their dashboard or export a formal CSV report with a single click."*
