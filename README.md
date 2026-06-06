# Affinity Group - Request Portal

A standalone Streamlit app for submitting data requests, bug reports, and feature requests to the data engineering team.

## Setup

1. Create a new GitHub repo (e.g., `scottphillip/affinity-ticket-system`)
2. Push this code
3. Deploy on Streamlit Community Cloud
4. Add secrets in Streamlit Cloud dashboard (Settings > Secrets):

```toml
[graph]
tenant_id = "b48813ec-319a-44de-a585-22f2088d3c9e"
client_id = "your-app-registration-client-id"
client_secret = "your-client-secret"
sender_email = "service-account@affinitysales.com"
recipient_email = "scott.phillips@affinitysales.com"
```

## Graph API Permissions

The app registration needs these Microsoft Graph API **application** permissions:
- `Mail.Send`

## Features
- Request Type (New Client, Data Fix, Feature Request, Bug Report, etc.)
- Priority level (Low/Medium/High/Urgent)
- Due date picker
- File attachment support
- Formatted HTML email sent via Graph API
