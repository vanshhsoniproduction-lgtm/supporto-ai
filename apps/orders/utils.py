import re

def normalize_phone(phone: str | None) -> str:
    """
    Normalizes Indian phone numbers to standard 10-digit format:
    Strips '+91', '91' prefix (if 12 digits total), spaces, dashes,
    dots, parentheses, and leading '0' (if 11 digits total).
    Returns a clean 10-digit string if valid, else the extracted digits or empty string.
    """
    if not phone:
        return ""
    
    # Strip all non-digit characters
    raw = str(phone).strip()
    digits = re.sub(r"\D", "", raw)
    
    # If starts with 91 and has 12 digits, strip country code 91
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    # If starts with 0 and has 11 digits (e.g. STD/trunk prefix), strip 0
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    
    # Return 10 digits
    return digits


def is_valid_phone(phone: str | None) -> bool:
    """
    Returns True if phone normalizes to a valid 10-digit Indian mobile number
    starting with 6, 7, 8, or 9.
    """
    cleaned = normalize_phone(phone)
    return bool(len(cleaned) == 10 and cleaned[0] in "6789")


