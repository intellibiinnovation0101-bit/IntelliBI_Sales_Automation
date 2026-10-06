"""
Escalation email — sent to the Active members of the escalation section
(default 'intellibiadmin') when a Website Lead is not acknowledged in time.

Reuses the project's existing Gmail SMTP credentials
(credentials/email_config.py: GMAIL_SENDER / GMAIL_APP_PASS) — the SAME account
the report scripts already send from. No new credentials are introduced.
"""
from __future__ import annotations

import sys

from config import CREDENTIALS_DIR, SETTINGS
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


def _send(recips, subject, plain, html) -> bool:
    try:
        sender, app_pass = _smtp_creds()
    except Exception as e:
        print("  [mailer] could not load email_config.py — e-mail not sent:", e)
        return False
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart
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
        return True
    except Exception as e:
        print("  [mailer] send FAILED:", e)
        return False


def send_no_online_alert(leads: list, info: dict) -> bool:
    """Website leads are waiting and NO counsellor app is online. Says whether
    the counsellors are genuinely offline or this server cannot be reached
    (network self-check), so the right person fixes the right thing."""
    from html import escape
    recips = [r["email"] for r in counsellors.escalation_recipients()]
    if not recips:
        print("  [mailer] no escalation recipients (Active) — skipping")
        return False
    net = info.get("network") or {}
    pres = info.get("presence") or {"counsellors": [], "counts": {}}
    server_problem = net.get("ok") is False
    if server_problem:
        subject = "Lead Alert SERVER NOT REACHABLE — website leads not delivered"
        headline = ("Counsellor computers cannot reach the Lead Alert server, so no "
                    "popups can be shown. This is a server/network problem, not the "
                    "counsellors.")
    else:
        subject = f"No counsellor online — {len(leads)} website lead(s) waiting"
        headline = ("Website leads are waiting and no counsellor's Lead Alert app is "
                    "online.")
    state_txt = {"offline": "offline", "stale": "connection lost",
                 "not_registered": "app not registered on this server",
                 "online": "online"}
    who = []
    for c in pres.get("counsellors", []):
        seen = ", ".join(f"{d.get('machine') or '?'} last seen {d.get('last_seen') or 'never'}"
                         for d in c.get("computers", [])) or "no registered computer"
        who.append((c.get("name") or c.get("email"), state_txt.get(c.get("state"), c.get("state")), seen))
    lead_rows = "".join(
        f"<tr><td style='padding:3px 10px'>{escape(str(l.get('received_at','')))}</td>"
        f"<td style='padding:3px 10px'>{escape(str(l.get('name','')))}</td>"
        f"<td style='padding:3px 10px'>{escape(str(l.get('mobile','')))}</td>"
        f"<td style='padding:3px 10px'>{escape(str(l.get('course','')))}</td></tr>" for l in leads)
    who_rows = "".join(f"<tr><td style='padding:3px 10px'>{escape(n)}</td>"
                       f"<td style='padding:3px 10px'><b>{escape(s)}</b></td>"
                       f"<td style='padding:3px 10px;color:#5b6b86'>{escape(d)}</td></tr>"
                       for n, s, d in who)
    fix = (f"<p><b>Fix:</b> {escape(net.get('fix',''))}</p>" if server_problem else
           "<p>Ask the counsellors to start <b>IntelliBI Lead Alert</b> (tray icon) — "
           "waiting leads pop up as soon as an app connects.</p>")
    html = f"""<html><body style="font-family:'Segoe UI',Arial,sans-serif;color:#1a2a48">
      <p style="font-size:16px"><b style="color:#b00020">{escape(headline)}</b></p>
      {f"<p>{escape(net.get('summary',''))}</p>" if server_problem else ""}
      <p><b>Waiting leads</b></p><table style="border-collapse:collapse">{lead_rows}</table>
      <p><b>Counsellors</b></p><table style="border-collapse:collapse">{who_rows}</table>
      {fix}
      <p style="color:#5b6b86;font-size:13px">Automated message from the IntelliBI
      Website Lead Alert service. Sent at most once per lead and once every
      {int(SETTINGS.no_online_alert_cooldown_min)} minutes.</p>
    </body></html>"""
    plain = (headline + "\n\n" + (net.get("summary", "") + "\n\n" if server_problem else "")
             + "Waiting leads:\n" + "\n".join(
                 f"  {l.get('received_at','')}  {l.get('name','')}  {l.get('mobile','')}  "
                 f"{l.get('course','')}" for l in leads)
             + "\n\nCounsellors:\n" + "\n".join(f"  {n}: {s} ({d})" for n, s, d in who)
             + ("\n\nFix: " + net.get("fix", "") if server_problem else ""))
    ok = _send(recips, subject, plain, html)
    if ok:
        print("  [mailer] 'no counsellor online' alert sent to", ", ".join(recips))
    return ok


def send_offline_hour_alert(info: dict) -> bool:
    """All counsellors offline for a full hour inside the monitoring window.

    info: offline_since, now (datetime), presence (ops.presence_report()),
    network (netcheck.LAST), leads (website leads received since offline_since),
    server_urls, window ("Mon-Sat 10:00-19:00"), after_minutes.
    """
    from html import escape
    recips = [r["email"] for r in counsellors.section_recipients(SETTINGS.offline_alert_section)]
    if not recips:
        print(f"  [mailer] offline alert: no Active recipients in section "
              f"'{SETTINGS.offline_alert_section}' — not sent")
        return False
    since, now = info["offline_since"], info["now"]
    mins = int((now - since).total_seconds() // 60)
    dur = f"{mins // 60} h {mins % 60:02d} min" if mins >= 60 else f"{mins} min"
    net = info.get("network") or {}
    server_problem = net.get("ok") is False
    pres = info.get("presence") or {"counsellors": []}
    leads = info.get("leads") or []
    waiting = [l for l in leads if l.get("status") == "RECEIVED"]

    if server_problem:
        subject = (f"ALERT: Lead Alert server not reachable — no counsellor connected "
                   f"for {dur} (since {since:%H:%M})")
        headline = ("No counsellor has been connected to the Website Lead Alert for "
                    f"{dur}. The server's own check says counsellor computers CANNOT "
                    "reach it, so this is a server/network problem — the counsellors "
                    "may be working but cannot receive popups.")
    else:
        subject = (f"ALERT: All counsellors offline for {dur} — Website Lead Alert "
                   f"(since {since:%H:%M}, {since:%a %d-%b})")
        headline = (f"No counsellor has had the IntelliBI Lead Alert app online for {dur} "
                    f"(since {since:%H:%M}). New website leads cannot pop up for anyone.")

    state_txt = {"offline": "Offline", "stale": "Connection lost",
                 "not_registered": "App not registered on this server", "online": "Online"}
    rows, plain_rows = [], []
    for c in pres.get("counsellors", []):
        comps = c.get("computers") or []
        last = max((d.get("last_seen") or "" for d in comps), default="") or "never"
        machines = ", ".join(d.get("machine") or "?" for d in comps) or "—"
        reason = next((d.get("last_disconnect_reason") for d in comps
                       if d.get("last_disconnect_reason")), "") or ""
        st = state_txt.get(c.get("state"), c.get("state"))
        rows.append(f"<tr><td style='padding:4px 10px'>{escape(c.get('name') or '')}</td>"
                    f"<td style='padding:4px 10px'>{escape(c.get('email') or '')}</td>"
                    f"<td style='padding:4px 10px'><b>{escape(st)}</b></td>"
                    f"<td style='padding:4px 10px'>{escape(machines)}</td>"
                    f"<td style='padding:4px 10px'>{escape(last)}</td>"
                    f"<td style='padding:4px 10px;color:#5b6b86'>{escape(reason)}</td></tr>")
        plain_rows.append(f"  {c.get('name')} <{c.get('email')}>: {st}; computer(s): {machines}; "
                          f"last seen {last}{'; ' + reason if reason else ''}")
    status_txt = {"RECEIVED": "waiting", "ASSIGNED": "assigned",
                  "UNACKNOWLEDGED": "expired (nobody accepted)"}
    lead_rows = "".join(
        f"<tr><td style='padding:3px 10px'>{escape(str(l.get('received_at','')))}</td>"
        f"<td style='padding:3px 10px'>{escape(str(l.get('name','')))}</td>"
        f"<td style='padding:3px 10px'>{escape(str(l.get('course','')))}</td>"
        f"<td style='padding:3px 10px'>{escape(status_txt.get(l.get('status'), str(l.get('status'))))}</td></tr>"
        for l in leads) or "<tr><td style='padding:3px 10px;color:#5b6b86'>none</td></tr>"
    urls = ", ".join(info.get("server_urls") or []) or "(no network)"
    net_line = (net.get("summary") or "not checked") + (
        f" — Fix: {net.get('fix')}" if server_problem and net.get("fix") else "")
    todo = ("<li>On the office PC run <b>lead_alert\\deploy\\Fix-Firewall.bat</b> as "
            "administrator (or restart the Lead Alert service, which repairs it "
            "automatically), then check that counsellors show as online.</li>"
            if server_problem else
            "<li>Ask the counsellors to start <b>IntelliBI Lead Alert</b>; the tray icon "
            "must be <b>green</b> (Connected).</li>"
            "<li>If an app shows <b>red</b> (cannot reach server / not registered), check the "
            "office PC is on and connected, or re-register that computer.</li>")
    html = f"""<html><body style="font-family:'Segoe UI',Arial,sans-serif;color:#1a2a48">
      <p style="font-size:16px"><b style="color:#b00020">{escape(headline)}</b></p>
      <table style="border-collapse:collapse;font-size:14px">
        <tr><td style="padding:3px 10px;color:#555">All offline since</td><td><b>{since:%a %d-%b-%Y %H:%M}</b></td></tr>
        <tr><td style="padding:3px 10px;color:#555">Alert time</td><td>{now:%H:%M}</td></tr>
        <tr><td style="padding:3px 10px;color:#555">Website leads since then</td><td>{len(leads)} ({len(waiting)} still waiting)</td></tr>
        <tr><td style="padding:3px 10px;color:#555">Server check</td><td>{escape(net_line)}</td></tr>
        <tr><td style="padding:3px 10px;color:#555">Server address</td><td>{escape(urls)} (status: /health)</td></tr>
      </table>
      <p style="margin-top:16px"><b>Counsellors</b></p>
      <table style="border-collapse:collapse;font-size:13px">
        <tr style="background:#eef2f8"><th style="padding:4px 10px;text-align:left">Name</th><th style="padding:4px 10px;text-align:left">Email</th><th style="padding:4px 10px;text-align:left">Status</th><th style="padding:4px 10px;text-align:left">Computer</th><th style="padding:4px 10px;text-align:left">Last seen</th><th style="padding:4px 10px;text-align:left">Last disconnect</th></tr>
        {''.join(rows)}
      </table>
      <p style="margin-top:16px"><b>Website leads received while everyone was offline</b></p>
      <table style="border-collapse:collapse;font-size:13px">{lead_rows}</table>
      <p style="margin-top:16px"><b>What to do</b></p><ul>{todo}</ul>
      <p style="color:#5b6b86;font-size:12px">Monitoring: {escape(info.get('window',''))}.
      One e-mail per offline period: the next alert is sent only after a counsellor
      comes online and all are offline again for {int(info.get('after_minutes', 60))}
      minutes. Automated message from the IntelliBI Website Lead Alert service.</p>
    </body></html>"""
    plain = (headline + "\n\n"
             f"All offline since: {since:%a %d-%b-%Y %H:%M}\nAlert time: {now:%H:%M}\n"
             f"Website leads since then: {len(leads)} ({len(waiting)} still waiting)\n"
             f"Server check: {net_line}\nServer address: {urls}\n\nCounsellors:\n"
             + "\n".join(plain_rows) + "\n\nLeads:\n"
             + ("\n".join(f"  {l.get('received_at','')}  {l.get('name','')}  {l.get('course','')}  "
                          f"{status_txt.get(l.get('status'), l.get('status'))}" for l in leads)
                or "  none")
             + f"\n\nMonitoring: {info.get('window','')}. One e-mail per offline period.\n")
    ok = _send(recips, subject, plain, html)
    if ok:
        print("  [mailer] 1-hour offline alert sent to", ", ".join(recips))
    return ok
