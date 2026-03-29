"""Friend mode — remembers contacts and enables smart texting/messaging."""

import json
import smtplib
from pathlib import Path
from email.mime.text import MIMEText

from jarvis.config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD
from jarvis.tools.base import Tool, registry

CONTACTS_FILE = Path(__file__).parent.parent.parent / "data" / "memory" / "contacts.json"


def _load_contacts() -> dict:
    if CONTACTS_FILE.exists():
        return json.loads(CONTACTS_FILE.read_text(encoding="utf-8"))
    return {}


def _save_contacts(data: dict):
    CONTACTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# Carrier email-to-SMS gateways
CARRIERS = {
    "verizon": "vtext.com",
    "att": "txt.att.net",
    "tmobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "uscellular": "email.uscc.net",
    "cricket": "sms.cricketwireless.net",
    "boost": "sms.myboostmobile.com",
    "metro": "mymetropcs.com",
    "mint": "tmomail.net",  # Mint uses T-Mobile
    "google": "msg.fi.google.com",  # Google Fi
}


def save_contact(name: str = "", phone: str = "", carrier: str = "", email: str = "",
                 relationship: str = "", notes: str = "", **kwargs) -> str:
    """Save a contact — name, phone, carrier, email, relationship."""
    if not name:
        return "I need at least a name."

    contacts = _load_contacts()
    key = name.lower().strip()

    # Update or create
    existing = contacts.get(key, {})
    if phone:
        # Clean phone number
        phone = "".join(c for c in phone if c.isdigit())
        if len(phone) == 10:
            phone = "1" + phone
        existing["phone"] = phone
    if carrier:
        existing["carrier"] = carrier.lower().strip()
    if email:
        existing["email"] = email
    if relationship:
        existing["relationship"] = relationship
    if notes:
        existing["notes"] = notes
    existing["name"] = name

    contacts[key] = existing
    _save_contacts(contacts)

    saved = [f"name: {name}"]
    if phone: saved.append(f"phone: {phone}")
    if carrier: saved.append(f"carrier: {carrier}")
    if relationship: saved.append(f"relationship: {relationship}")
    return f"Contact saved — {', '.join(saved)}"


def get_contact(name: str = "", **kwargs) -> str:
    """Look up a contact by name."""
    contacts = _load_contacts()

    if not name:
        if not contacts:
            return "No contacts saved yet."
        lines = ["Saved contacts:"]
        for key, data in contacts.items():
            rel = data.get("relationship", "")
            lines.append(f"  {data.get('name', key)}{' (' + rel + ')' if rel else ''}")
        return "\n".join(lines)

    key = name.lower().strip()

    # Exact match
    if key in contacts:
        c = contacts[key]
        lines = [f"Contact: {c.get('name', name)}"]
        if c.get("phone"): lines.append(f"  Phone: {c['phone']}")
        if c.get("carrier"): lines.append(f"  Carrier: {c['carrier']}")
        if c.get("email"): lines.append(f"  Email: {c['email']}")
        if c.get("relationship"): lines.append(f"  Relationship: {c['relationship']}")
        if c.get("notes"): lines.append(f"  Notes: {c['notes']}")
        return "\n".join(lines)

    # Fuzzy match
    for k, data in contacts.items():
        if key in k or key in data.get("name", "").lower():
            return get_contact(data.get("name", k))

    return f"No contact found for '{name}'. Save one with: save contact [name] [phone] [carrier]"


def text_contact(name: str = "", message: str = "", **kwargs) -> str:
    """Send a text message to a saved contact via email-to-SMS."""
    if not name or not message:
        return "I need a contact name and a message."

    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Gmail not configured. Need GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env."

    contacts = _load_contacts()
    key = name.lower().strip()

    # Find contact
    contact = contacts.get(key)
    if not contact:
        for k, data in contacts.items():
            if key in k or key in data.get("name", "").lower():
                contact = data
                break

    if not contact:
        return f"No contact '{name}'. Save one first: save contact [name] [phone] [carrier]"

    phone = contact.get("phone", "")
    carrier = contact.get("carrier", "")

    if not phone:
        return f"No phone number saved for {contact.get('name', name)}."

    if not carrier:
        return f"No carrier saved for {contact.get('name', name)}. I need it to send SMS. Save with: save contact {name} carrier [verizon/att/tmobile/etc]"

    gateway = CARRIERS.get(carrier.lower())
    if not gateway:
        return f"Unknown carrier '{carrier}'. Supported: {', '.join(CARRIERS.keys())}"

    sms_email = f"{phone}@{gateway}"

    try:
        msg = MIMEText(message)
        msg["From"] = GMAIL_ADDRESS
        msg["To"] = sms_email
        msg["Subject"] = ""  # SMS doesn't need subject

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, sms_email, msg.as_string())

        return f"Text sent to {contact.get('name', name)}: \"{message}\""
    except Exception as e:
        return f"Failed to send text: {e}"


# ─── Register ───

registry.register(Tool(
    name="save_contact",
    description="Save a contact with name, phone, carrier, email, relationship. Use for 'save Jake's number', 'add mom to contacts', 'remember that Jake's number is...'.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Contact name (e.g. 'Jake', 'Mom', 'Coach')"},
            "phone": {"type": "string", "description": "Phone number"},
            "carrier": {"type": "string", "description": "Phone carrier: verizon, att, tmobile, sprint, cricket, boost, metro, mint, google"},
            "email": {"type": "string", "description": "Email address"},
            "relationship": {"type": "string", "description": "Relationship (friend, mom, dad, brother, etc.)"},
            "notes": {"type": "string", "description": "Any notes about this person"},
        },
        "required": ["name"],
    },
    handler=save_contact,
))

registry.register(Tool(
    name="get_contact",
    description="Look up a contact or list all contacts. Use for 'what's Jake's number', 'show my contacts', 'who do I have saved'.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Contact name to look up (empty to list all)"},
        },
    },
    handler=get_contact,
))

registry.register(Tool(
    name="text_contact",
    description="Send a text message to a saved contact. Use for 'text Jake about the game', 'send mom a message', 'tell Jake I'm on my way'. Requires contact to have phone + carrier saved.",
    parameters={
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Contact name"},
            "message": {"type": "string", "description": "The text message to send"},
        },
        "required": ["name", "message"],
    },
    handler=text_contact,
))
