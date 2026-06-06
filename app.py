"""
Affinity Group - Ticket Submission System
=========================================
Standalone Streamlit app for submitting data requests, bug reports,
and feature requests. Sends tickets directly to scott.phillips@affinitysales.com
via Microsoft Graph API.

Employee directory enables single-field identification (email or name lookup).
"""
import streamlit as st
import requests
import json
import base64
from datetime import datetime, date
from pathlib import Path

st.set_page_config(
    page_title="Submit a Request | Affinity Group",
    page_icon="🎫",
    layout="centered",
)

# Brand colors
ORANGE = "#F5921E"
CHARCOAL = "#2D2D2D"


# ─── Employee Directory ───
@st.cache_data
def load_employee_directory():
    """Load employee directory (email -> name mapping)."""
    dir_path = Path(__file__).parent / "employee_directory.json"
    if dir_path.exists():
        with open(dir_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_directory_options():
    """Build display options: 'Name (email)' sorted by name."""
    directory = load_employee_directory()
    # Build both lookups
    options = []
    for email, name in sorted(directory.items(), key=lambda x: x[1].lower()):
        options.append({"display": f"{name} ({email})", "name": name, "email": email})
    return options


# ─── Microsoft Graph Email ───
def get_graph_token() -> str:
    """Get OAuth2 token for Microsoft Graph API."""
    tenant_id = st.secrets["graph"]["tenant_id"]
    client_id = st.secrets["graph"]["client_id"]
    client_secret = st.secrets["graph"]["client_secret"]

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    response = requests.post(token_url, data=payload)
    response.raise_for_status()
    return response.json()["access_token"]


def send_ticket_email(ticket: dict, attachment_data: bytes = None, attachment_name: str = None) -> bool:
    """Send ticket as formatted email via Microsoft Graph."""
    token = get_graph_token()
    sender = st.secrets["graph"]["sender_email"]
    recipient = st.secrets["graph"]["recipient_email"]

    # Build HTML email body
    priority_colors = {
        "Low": "#4CAF50",
        "Medium": "#FF9800",
        "High": "#F44336",
        "Urgent": "#9C27B0",
    }
    p_color = priority_colors.get(ticket["priority"], "#666")

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {CHARCOAL}; padding: 15px 20px; border-radius: 8px 8px 0 0;">
            <span style="color: {ORANGE}; font-size: 18px; font-weight: bold;">TICKET</span>
            <span style="color: white; font-size: 18px;"> SUBMISSION</span>
        </div>
        <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="padding: 8px 0; font-weight: bold; width: 140px; color: #555;">Submitted By:</td>
                    <td style="padding: 8px 0;">{ticket['submitter_name']} ({ticket['submitter_email']})</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; font-weight: bold; color: #555;">Request Type:</td>
                    <td style="padding: 8px 0;">{ticket['request_type']}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; font-weight: bold; color: #555;">Priority:</td>
                    <td style="padding: 8px 0;">
                        <span style="background: {p_color}; color: white; padding: 3px 10px; border-radius: 12px; font-size: 13px;">
                            {ticket['priority']}
                        </span>
                    </td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; font-weight: bold; color: #555;">Due Date:</td>
                    <td style="padding: 8px 0;">{ticket.get('due_date', 'Not specified')}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; font-weight: bold; color: #555;">Submitted:</td>
                    <td style="padding: 8px 0;">{datetime.now().strftime('%B %d, %Y at %I:%M %p')}</td>
                </tr>
            </table>
            <hr style="border: none; border-top: 1px solid #eee; margin: 15px 0;">
            <p style="font-weight: bold; color: #555; margin-bottom: 5px;">Description:</p>
            <div style="background: #f9f9f9; padding: 12px; border-radius: 6px; white-space: pre-wrap;">{ticket['description']}</div>
        </div>
    </div>
    """

    # Build email message
    message = {
        "message": {
            "subject": f"[{ticket['priority']}] {ticket['request_type']} - from {ticket['submitter_name']}",
            "body": {
                "contentType": "HTML",
                "content": html_body,
            },
            "toRecipients": [{"emailAddress": {"address": recipient}}],
        },
        "saveToSentItems": "true",
    }

    # Add attachment if provided
    if attachment_data and attachment_name:
        encoded = base64.b64encode(attachment_data).decode("utf-8")
        message["message"]["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachment_name,
                "contentBytes": encoded,
            }
        ]

    # Send via Graph
    url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=message)
    return response.status_code in (200, 202)


# ─── UI ───
st.markdown(f"""
<div style="background: {CHARCOAL}; padding: 15px 25px; border-radius: 10px; margin-bottom: 25px;">
    <span style="color: {ORANGE}; font-size: 22px; font-weight: bold;">AFFINITY GROUP</span>
    <span style="color: white; font-size: 22px; font-weight: 300;"> REQUEST PORTAL</span>
</div>
""", unsafe_allow_html=True)

st.markdown("Submit a request for data additions, fixes, feature requests, or bug reports. "
            "Your ticket will be sent directly to the data engineering team.")

st.markdown("---")

# Load directory
directory_options = get_directory_options()
display_list = [""] + [opt["display"] for opt in directory_options]

# Form
with st.form("ticket_form", clear_on_submit=True):
    col1, col2 = st.columns(2)

    with col1:
        # Single identity field - searchable selectbox
        selected = st.selectbox(
            "Who are you? *",
            options=display_list,
            index=0,
            help="Start typing your name or email to search",
            placeholder="Search by name or email...",
        )

        request_type = st.selectbox(
            "Request Type *",
            options=[
                "Data Fix / Correction",
                "Feature Request",
                "Bug Report",
                "Report / Dashboard Request",
                "Order Management Update",
                "Order Management New Feature",
                "CRM Update",
                "Match File",
                "Dist Code Import",
                "Other",
            ],
        )
        priority = st.selectbox(
            "Priority *",
            options=["Low", "Medium", "High", "Urgent"],
            index=1,
        )

    with col2:
        due_date = st.date_input("Target Due Date (optional)", value=None, min_value=date.today())
        attachment = st.file_uploader(
            "Attachment (optional)",
            type=["csv", "xlsx", "pdf", "png", "jpg", "txt", "docx"],
            help="Upload a screenshot, file, or reference document",
        )

    description = st.text_area(
        "Description *",
        height=180,
        placeholder="Describe your request in detail...\n\n"
                    "For data fixes: include the client name, date range, and what looks wrong.\n"
                    "For order management: include the client and specific changes needed.\n"
                    "For features: describe what you'd like to see and why.",
    )

    submitted = st.form_submit_button("Submit Request", use_container_width=True, type="primary")

if submitted:
    # Resolve name/email from selection
    submitter_name = ""
    submitter_email = ""
    if selected:
        # Find the matching entry
        for opt in directory_options:
            if opt["display"] == selected:
                submitter_name = opt["name"]
                submitter_email = opt["email"]
                break

    # Validate required fields
    if not submitter_name or not submitter_email:
        st.error("Please select your name from the directory.")
    elif not description.strip():
        st.error("Please provide a description of your request.")
    else:
        ticket = {
            "submitter_name": submitter_name,
            "submitter_email": submitter_email,
            "request_type": request_type,
            "priority": priority,
            "due_date": due_date.strftime("%B %d, %Y") if due_date else "Not specified",
            "description": description.strip(),
        }

        # Handle attachment
        attach_bytes = None
        attach_name = None
        if attachment:
            attach_bytes = attachment.read()
            attach_name = attachment.name

        with st.spinner("Submitting your request..."):
            try:
                success = send_ticket_email(ticket, attach_bytes, attach_name)
                if success:
                    st.success("Your request has been submitted successfully! "
                               "You'll receive a response from the data team shortly.")
                    st.balloons()
                else:
                    st.error("There was an issue sending your request. Please try again or email "
                             "scott.phillips@affinitysales.com directly.")
            except Exception as e:
                st.error(f"Error submitting request: {str(e)[:200]}\n\n"
                         "Please email scott.phillips@affinitysales.com directly.")

# Footer
st.markdown("---")
st.caption("Affinity Group Data Engineering | Questions? Contact scott.phillips@affinitysales.com")
