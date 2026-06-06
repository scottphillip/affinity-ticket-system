"""
Affinity Group - Ticket Submission System
=========================================
Standalone Streamlit app for submitting data requests, bug reports,
and feature requests. Sends tickets directly to scott.phillips@affinitysales.com
via Microsoft Graph API.

Users log in with their company email + password (stored in Snowflake).
"""
import streamlit as st
import requests
import json
import base64
import hashlib
import snowflake.connector
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

USERS_TABLE = "DB_PROD_TRF.SCH_TRF_UTILS.TB_TICKET_APP_USERS"


# ─── Snowflake Connection ───
@st.cache_resource
def get_snowflake_conn():
    """Get Snowflake connection for user auth."""
    return snowflake.connector.connect(
        account=st.secrets["snowflake"]["account"],
        user=st.secrets["snowflake"]["user"],
        password=st.secrets["snowflake"]["password"],
        warehouse=st.secrets["snowflake"]["warehouse"],
        role=st.secrets["snowflake"]["role"],
    )


def run_query(sql: str, params: tuple = None):
    """Execute a query and return results as list of tuples."""
    conn = get_snowflake_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    except Exception:
        # Reconnect on stale connection
        st.cache_resource.clear()
        conn = get_snowflake_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()


def run_dml(sql: str, params: tuple = None):
    """Execute DML (INSERT/UPDATE) statement."""
    conn = get_snowflake_conn()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
    except Exception:
        st.cache_resource.clear()
        conn = get_snowflake_conn()
        cur = conn.cursor()
        cur.execute(sql, params)
    finally:
        cur.close()


# ─── Employee Directory ───
@st.cache_data
def load_employee_directory():
    """Load employee directory (email -> name mapping)."""
    dir_path = Path(__file__).parent / "employee_directory.json"
    if dir_path.exists():
        with open(dir_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


# ─── Auth Functions ───
def hash_password(password: str) -> str:
    """SHA-256 hash for password storage."""
    return hashlib.sha256(password.encode()).hexdigest()


def check_user_exists(email: str) -> bool:
    """Check if user has an account in Snowflake."""
    rows = run_query(
        f"SELECT 1 FROM {USERS_TABLE} WHERE EMAIL = %s",
        (email,)
    )
    return len(rows) > 0


def verify_password(email: str, password: str) -> bool:
    """Verify password against stored hash."""
    rows = run_query(
        f"SELECT PASSWORD_HASH FROM {USERS_TABLE} WHERE EMAIL = %s",
        (email,)
    )
    if not rows:
        return False
    return rows[0][0] == hash_password(password)


def create_user(email: str, display_name: str, password: str):
    """Create a new user account."""
    run_dml(
        f"INSERT INTO {USERS_TABLE} (EMAIL, DISPLAY_NAME, PASSWORD_HASH) VALUES (%s, %s, %s)",
        (email, display_name, hash_password(password))
    )


def update_last_login(email: str):
    """Update last login timestamp."""
    run_dml(
        f"UPDATE {USERS_TABLE} SET LAST_LOGIN = CURRENT_TIMESTAMP() WHERE EMAIL = %s",
        (email,)
    )


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

    if attachment_data and attachment_name:
        encoded = base64.b64encode(attachment_data).decode("utf-8")
        message["message"]["attachments"] = [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": attachment_name,
                "contentBytes": encoded,
            }
        ]

    url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = requests.post(url, headers=headers, json=message)
    return response.status_code in (200, 202)


# ─── LOGIN PAGE ───
def show_login():
    """Display the login/register form."""
    st.markdown(f"""
    <div style="background: {CHARCOAL}; padding: 15px 25px; border-radius: 10px; margin-bottom: 25px;">
        <span style="color: {ORANGE}; font-size: 22px; font-weight: bold;">AFFINITY GROUP</span>
        <span style="color: white; font-size: 22px; font-weight: 300;"> REQUEST PORTAL</span>
    </div>
    """, unsafe_allow_html=True)

    tab_login, tab_register = st.tabs(["Sign In", "Create Account"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", placeholder="yourname@affinitysales.com", key="login_email")
            password = st.text_input("Password", type="password", key="login_pw")
            login_btn = st.form_submit_button("Sign In", use_container_width=True, type="primary")

        if login_btn:
            if not email or not password:
                st.error("Please enter both email and password.")
            else:
                email_lower = email.strip().lower()
                directory = load_employee_directory()

                if email_lower not in directory:
                    st.error("Email not found in the Affinity Group directory.")
                elif not check_user_exists(email_lower):
                    st.warning("No account found for this email. Please create an account first.")
                elif not verify_password(email_lower, password):
                    st.error("Incorrect password.")
                else:
                    update_last_login(email_lower)
                    st.session_state.logged_in = True
                    st.session_state.user_email = email_lower
                    st.session_state.user_name = directory[email_lower]
                    st.rerun()

    with tab_register:
        with st.form("register_form"):
            reg_email = st.text_input("Email", placeholder="yourname@affinitysales.com", key="reg_email")
            reg_pw = st.text_input("Create Password", type="password", key="reg_pw")
            reg_pw2 = st.text_input("Confirm Password", type="password", key="reg_pw2")
            register_btn = st.form_submit_button("Create Account", use_container_width=True, type="primary")

        if register_btn:
            if not reg_email or not reg_pw:
                st.error("Please fill in all fields.")
            elif reg_pw != reg_pw2:
                st.error("Passwords do not match.")
            elif len(reg_pw) < 4:
                st.error("Password must be at least 4 characters.")
            else:
                email_lower = reg_email.strip().lower()
                directory = load_employee_directory()

                if email_lower not in directory:
                    st.error("Email not found in the Affinity Group directory. "
                             "Only Affinity Group employees can create accounts.")
                elif check_user_exists(email_lower):
                    st.warning("An account already exists for this email. Please sign in instead.")
                else:
                    create_user(email_lower, directory[email_lower], reg_pw)
                    update_last_login(email_lower)
                    st.session_state.logged_in = True
                    st.session_state.user_email = email_lower
                    st.session_state.user_name = directory[email_lower]
                    st.success(f"Account created! Welcome, {directory[email_lower]}.")
                    st.rerun()


# ─── TICKET FORM (after login) ───
def show_ticket_form():
    """Display the ticket submission form for logged-in users."""
    user_name = st.session_state.user_name
    user_email = st.session_state.user_email

    st.markdown(f"""
    <div style="background: {CHARCOAL}; padding: 15px 25px; border-radius: 10px; margin-bottom: 25px;">
        <span style="color: {ORANGE}; font-size: 22px; font-weight: bold;">AFFINITY GROUP</span>
        <span style="color: white; font-size: 22px; font-weight: 300;"> REQUEST PORTAL</span>
    </div>
    """, unsafe_allow_html=True)

    # User info bar
    col_user, col_logout = st.columns([4, 1])
    with col_user:
        st.markdown(f"Logged in as **{user_name}** ({user_email})")
    with col_logout:
        if st.button("Sign Out", type="secondary"):
            st.session_state.logged_in = False
            st.session_state.user_email = None
            st.session_state.user_name = None
            st.rerun()

    st.markdown("---")
    st.markdown("Submit a request for data additions, fixes, feature requests, or bug reports. "
                "Your ticket will be sent directly to the data engineering team.")

    # Form
    with st.form("ticket_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
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
        if not description.strip():
            st.error("Please provide a description of your request.")
        else:
            ticket = {
                "submitter_name": user_name,
                "submitter_email": user_email,
                "request_type": request_type,
                "priority": priority,
                "due_date": due_date.strftime("%B %d, %Y") if due_date else "Not specified",
                "description": description.strip(),
            }

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


# ─── MAIN ───
if st.session_state.get("logged_in"):
    show_ticket_form()
else:
    show_login()
