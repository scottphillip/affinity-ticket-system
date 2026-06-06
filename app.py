"""
Affinity Group - Ticket Submission System
=========================================
Standalone Streamlit app for submitting data requests, bug reports,
and feature requests. Tickets are logged to Snowflake and optionally
sent via email to scott.phillips@affinitysales.com.

Users log in with their company email + password (stored in Snowflake).
"""
import streamlit as st
import json
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
TICKETS_TABLE = "DB_PROD_TRF.SCH_TRF_UTILS.TB_TICKET_LOG"
ADMIN_EMAIL = "scott.phillips@affinitysales.com"
APP_URL = "https://affinity-ticket-system-6fphpygble6rytav26s8eb.streamlit.app"


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


# ─── Ticket Functions ───
def save_ticket(ticket: dict) -> int:
    """Save ticket to Snowflake log table. Returns the new ticket ID."""
    run_dml(
        f"""INSERT INTO {TICKETS_TABLE}
            (SUBMITTER_EMAIL, SUBMITTER_NAME, REQUEST_TYPE, PRIORITY, DUE_DATE, DESCRIPTION)
            VALUES (%s, %s, %s, %s, %s, %s)""",
        (
            ticket["submitter_email"],
            ticket["submitter_name"],
            ticket["request_type"],
            ticket["priority"],
            ticket["due_date"],
            ticket["description"],
        )
    )
    # Get the ID of the ticket we just inserted
    rows = run_query(f"SELECT MAX(TICKET_ID) FROM {TICKETS_TABLE}")
    return rows[0][0] if rows else 0


def get_user_tickets(email: str):
    """Get all tickets for a user."""
    return run_query(
        f"""SELECT TICKET_ID, REQUEST_TYPE, PRIORITY, DESCRIPTION, STATUS, CREATED_AT, DUE_DATE
            FROM {TICKETS_TABLE}
            WHERE SUBMITTER_EMAIL = %s
            ORDER BY CREATED_AT DESC""",
        (email,)
    )


def get_all_open_tickets():
    """Get all open tickets (admin view)."""
    return run_query(
        f"""SELECT TICKET_ID, SUBMITTER_NAME, SUBMITTER_EMAIL, REQUEST_TYPE, PRIORITY,
                   DESCRIPTION, CREATED_AT, DUE_DATE
            FROM {TICKETS_TABLE}
            WHERE STATUS = 'OPEN'
            ORDER BY
                CASE PRIORITY WHEN 'Urgent' THEN 1 WHEN 'High' THEN 2
                     WHEN 'Medium' THEN 3 ELSE 4 END,
                CREATED_AT ASC"""
    )


def get_completed_tickets():
    """Get completed tickets (admin view)."""
    return run_query(
        f"""SELECT TICKET_ID, SUBMITTER_NAME, REQUEST_TYPE, PRIORITY, DESCRIPTION,
                   CREATED_AT, COMPLETED_AT
            FROM {TICKETS_TABLE}
            WHERE STATUS = 'COMPLETED'
            ORDER BY COMPLETED_AT DESC
            LIMIT 50"""
    )


def mark_ticket_complete(ticket_id: int):
    """Mark a ticket as completed."""
    run_dml(
        f"UPDATE {TICKETS_TABLE} SET STATUS = 'COMPLETED', COMPLETED_AT = CURRENT_TIMESTAMP() WHERE TICKET_ID = %s",
        (ticket_id,)
    )


# ─── Email Notification (via Snowflake SYSTEM$SEND_EMAIL) ───
def try_send_email(ticket: dict, ticket_id: int) -> bool:
    """Send ticket notification via Snowflake's built-in email system."""
    try:
        complete_url = f"{APP_URL}/?complete={ticket_id}"
        subject = f"[TICKET] [{ticket['priority']}] {ticket['request_type']} - from {ticket['submitter_name']}"
        body = (
            f"New ticket submitted (#{ticket_id}):\n\n"
            f"From: {ticket['submitter_name']} ({ticket['submitter_email']})\n"
            f"Type: {ticket['request_type']}\n"
            f"Priority: {ticket['priority']}\n"
            f"Due: {ticket.get('due_date', 'Not specified')}\n"
            f"Submitted: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n\n"
            f"Description:\n{ticket['description']}\n\n"
            f"---\n"
            f"Mark Complete: {complete_url}"
        )
        # Escape single quotes for SQL
        subject_safe = subject.replace("'", "''")
        body_safe = body.replace("'", "''")

        run_query(
            f"CALL SYSTEM$SEND_EMAIL("
            f"'AFFINITY_EMAIL_NOTIFICATION_INTEGRATION', "
            f"'{ADMIN_EMAIL}', "
            f"'{subject_safe}', "
            f"'{body_safe}')"
        )
        return True
    except Exception:
        return False


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


# ─── MAIN APP (after login) ───
def show_main_app():
    """Display the main app with tabs for logged-in users."""
    user_name = st.session_state.user_name
    user_email = st.session_state.user_email
    is_admin = (user_email == ADMIN_EMAIL)

    # Header
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

    # Tabs
    if is_admin:
        tab_submit, tab_my_tickets, tab_admin = st.tabs(["Submit Request", "My Tickets", "Admin - All Tickets"])
    else:
        tab_submit, tab_my_tickets = st.tabs(["Submit Request", "My Tickets"])

    # ── Submit Request Tab ──
    with tab_submit:
        st.markdown("Submit a request for data additions, fixes, feature requests, or bug reports.")

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
                    # Always save to database first
                    ticket_id = save_ticket(ticket)

                    # Try email (best-effort)
                    email_sent = try_send_email(ticket, ticket_id)

                    if email_sent:
                        st.success("Your request has been submitted and the team has been notified!")
                    else:
                        st.success("Your request has been submitted and saved! "
                                   "The team will review it shortly.")
                    st.balloons()

    # ── My Tickets Tab ──
    with tab_my_tickets:
        st.markdown("### Your Requests")
        tickets = get_user_tickets(user_email)

        if not tickets:
            st.info("You haven't submitted any requests yet.")
        else:
            open_tickets = [t for t in tickets if t[4] == "OPEN"]
            closed_tickets = [t for t in tickets if t[4] == "COMPLETED"]

            if open_tickets:
                st.markdown(f"**Open Requests ({len(open_tickets)})**")
                for t in open_tickets:
                    ticket_id, req_type, pri, desc, status, created, due = t
                    pri_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴", "Urgent": "🟣"}.get(pri, "⚪")
                    created_str = created.strftime("%b %d, %Y") if created else ""
                    with st.expander(f"{pri_emoji} **{req_type}** — {created_str}"):
                        st.markdown(f"**Priority:** {pri}  |  **Due:** {due}  |  **Status:** {status}")
                        st.markdown(f"**Description:**\n\n{desc}")

            if closed_tickets:
                st.markdown(f"**Completed ({len(closed_tickets)})**")
                for t in closed_tickets:
                    ticket_id, req_type, pri, desc, status, created, due = t
                    created_str = created.strftime("%b %d, %Y") if created else ""
                    with st.expander(f"✅ **{req_type}** — {created_str}"):
                        st.markdown(f"**Priority:** {pri}  |  **Due:** {due}  |  **Status:** {status}")
                        st.markdown(f"**Description:**\n\n{desc}")

    # ── Admin Tab (Scott only) ──
    if is_admin:
        with tab_admin:
            st.markdown("### All Open Tickets")

            open_tickets = get_all_open_tickets()

            if not open_tickets:
                st.success("No open tickets! All caught up.")
            else:
                st.markdown(f"**{len(open_tickets)} open request(s)**")
                for t in open_tickets:
                    ticket_id, name, email, req_type, pri, desc, created, due = t
                    pri_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴", "Urgent": "🟣"}.get(pri, "⚪")
                    created_str = created.strftime("%b %d, %Y %I:%M %p") if created else ""

                    with st.expander(f"{pri_emoji} **{req_type}** — {name} ({created_str})"):
                        st.markdown(f"**From:** {name} ({email})")
                        st.markdown(f"**Priority:** {pri}  |  **Due:** {due}")
                        st.markdown(f"**Description:**\n\n{desc}")
                        if st.button("✅ Mark Complete", key=f"complete_{ticket_id}", type="primary"):
                            mark_ticket_complete(ticket_id)
                            st.success(f"Ticket #{ticket_id} marked as complete!")
                            st.rerun()

            # Completed section
            st.markdown("---")
            with st.expander("View Completed Tickets"):
                completed = get_completed_tickets()
                if not completed:
                    st.info("No completed tickets yet.")
                else:
                    for t in completed:
                        ticket_id, name, req_type, pri, desc, created, completed_at = t
                        created_str = created.strftime("%b %d") if created else ""
                        completed_str = completed_at.strftime("%b %d") if completed_at else ""
                        st.markdown(f"- ✅ **{req_type}** from {name} "
                                    f"(submitted {created_str}, completed {completed_str})")

    # Footer
    st.markdown("---")
    st.caption("Affinity Group Data Engineering | Questions? Contact scott.phillips@affinitysales.com")


# ─── MAIN ───
# Handle "Mark Complete" link from email
params = st.query_params
if "complete" in params:
    ticket_id_param = params["complete"]
    if st.session_state.get("logged_in") and st.session_state.get("user_email") == ADMIN_EMAIL:
        try:
            mark_ticket_complete(int(ticket_id_param))
            st.query_params.clear()
            st.success(f"Ticket #{ticket_id_param} marked as complete!")
        except Exception:
            st.error("Could not complete ticket. Please use the Admin tab.")
    elif not st.session_state.get("logged_in"):
        st.info("Please sign in to mark this ticket complete.")
        show_login()
        st.stop()

if st.session_state.get("logged_in"):
    show_main_app()
else:
    show_login()
