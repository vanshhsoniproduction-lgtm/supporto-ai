"""
apps/orders/demo_customers.py

Centralized configuration for demo customers, phone numbers, and identities.
All demo seed scripts, widget tests, and tool callers reference these constants.
"""
from apps.orders.utils import normalize_phone

CUSTOMER_A = {
    "name": "Vansh Soni",
    "phone": "6367743066",
    "normalized_phone": normalize_phone("6367743066"),
    "email": "vansh.soni@example.com",
    "city": "Jaipur",
    "address": "42, Shanti Nagar, Tonk Road, Jaipur, Rajasthan",
    "pincode": "302018",
}

CUSTOMER_B = {
    "name": "Riya Sharma",
    "phone": "9571538144",
    "normalized_phone": normalize_phone("9571538144"),
    "email": "riya.sharma@example.com",
    "city": "Jaipur",
    "address": "104, Malviya Nagar, Sector 3, Jaipur, Rajasthan",
    "pincode": "302017",
}

ALL_DEMO_CUSTOMERS = [CUSTOMER_A, CUSTOMER_B]

