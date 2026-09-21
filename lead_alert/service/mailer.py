"""
Escalation email — sent to the Active members of the escalation section
(default 'intellibiadmin') when a Website Lead is not acknowledged in time.

Reuses the project's existing Gmail SMTP credentials
(credentials/email_config.py: GMAIL_SENDER / GMAIL_APP_PASS) — the SAME account
the report scripts already send from. No new credentials are introduced.
"""
from __future__ import annotations

import sys

from config import CREDENTIALS_DIR
import counsellors


def _smtp_creds():
    sys.path.insert(0, str(CREDENTIALS_DIR))
    import email_config as ec  # type: ignore
    return ec.GMAIL_SENDER, ec.GMAIL_APP_PASS


def send_escalation(lead: dict) -> None:
    """Notify the escalation section that a lead is still unacknowledged."""
    recips = [r["email"] for r in counsellors.escalation_recipients()]
    if not recips:
        print("  [mailer] no escalation recipients (Active) — skipping")
        return
    try:
        sender, app_pass = _smtp_creds()
    except Exception as e:
        print("  [mailer] could not load email_config.py — escalation not sent:", e)
        return

    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    subject = "UNACKNOWLEDGED Website Lead — action needed"
    html = f"""<html><body style="font-family:'Segoe UI',Arial,sans-serif;
      color:#1a2a48">
      <p style="font-size:16px"><b style="color:#b00020">A Website Lead has not
      been acknowledged by any counsellor.</b></p>
      <table style="border-collapse:collapse">
        <tr><td style="padding:4px 12px;color:#555">Received</td><td style="padding:4px 12px"><b>{lead.get('received_at','')}</b></td></tr>
        <tr><td style="padding:4px 12px;color:#555">Name</td><td style="padding:4px 12px">{lead.get('name','')}</td></tr>
        <tr><td style="padding:4px 12px;color:#555">Mobile</td><td style="padding:4px 12px">{lead.get('mobile','')}</td></tr>
        <tr><td style="padding:4px 12px;color:#555">Email</td><td style="padding:4px 12px">{lead.get('email','')}</td></tr>
        <tr><td style="padding:4px 12px;color:#555">Course</td><td style="padding:4px 12px">{lead.get('course','')}</td></tr>
        <tr><td style="padding:4px 12px;color:#555">Form</td><td style="padding:4px 12px">{lead.get('form_type','')}</td></tr>
      </table>
      <p style="color:#5b6b86;font-size:13px">Please follow up or reassign this
      lead. (Automated escalation from the IntelliBI Website Lead Alert service.)</p>
    </body></html>"""
    plain = (f"UNACKNOWLEDGED Website Lead\n\nReceived: {lead.get('received_at','')}\n"
             f"Name: {lead.get('name','')}\nMobile: {lead.get('mobile','')}\n"
             f"Email: {lead.get('email','')}\nCourse: {lead.get('course','')}\n"
             f"Form: {lead.get('form_type','')}\n")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recips)
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html, "html"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(sender, app_pass)
            srv.sendmail(sender, recips, msg.as_string())
        print("  [mailer] escalation sent to", ", ".join(recips))
    except Exception as e:
        print("  [mailer] escalation FAILED:", e)
