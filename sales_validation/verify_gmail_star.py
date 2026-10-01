"""
Verification of Gmail "Starred" for the Sales report e-mails
(run from the project root:  python sales_validation\\verify_gmail_star.py).

No network: Gmail SMTP and Gmail IMAP are replaced by an in-memory mailbox that
behaves like Gmail (sent message lands in a LOCALISED "All Mail" found by its
\\All flag, may take a few look-ups to appear; IMAP \\Flagged = Starred).
For pyConsolidatedLeadPerformanceReport and pyLeadFollowUpAnalysisReport it
calls the REAL send_email() and checks:
  * the e-mail is sent exactly as before and then Starred (that message only)
  * subject / sender / recipients / body identical with starring on and off
  * STAR_EMAIL_IN_GMAIL = False → no IMAP; an IMAP failure never changes the
    send result (True) and later e-mails of the run skip starring at once
  * the run summary still recognises the send line ("[email] sent to")
"""
import email
import imaplib
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ec = types.ModuleType("email_config")
ec.GMAIL_SENDER = "info@intellibiinnovationstechnologies.in"
ec.GMAIL_APP_PASS = "test-only"
sys.modules["email_config"] = ec                     # never the real credentials
for p in ("common", "sales_reports"):
    sys.path.insert(0, os.path.join(ROOT, p))

import smtplib                                        # noqa: E402
import gmail_star as GS                               # noqa: E402

FAIL = []


def check(label, got, want):
    ok = got == want
    print(f"[{'pass' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f"  (expected {want!r})"))
    if not ok:
        FAIL.append(label)


class Box:
    msgs, sessions, searches, visible_after, login_error = [], 0, 0, 0, None

    @classmethod
    def reset(cls, visible_after=0, login_error=None):
        GS._GIVE_UP.clear()
        cls.msgs, cls.sessions, cls.searches = [], 0, 0
        cls.visible_after, cls.login_error = visible_after, login_error


SENT = []


class FakeSMTP:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        pass

    def sendmail(self, sender, rcpts, msg):
        SENT.append({"from": sender, "to": list(rcpts), "msg": msg})
        m = email.message_from_string(msg)
        Box.msgs.append({"uid": str(100 + len(Box.msgs)).encode(),
                         "msgid": m.get("Message-ID") or f"<gmail-{len(Box.msgs)}@mail.gmail.com>",
                         "subject": m["Subject"], "flags": set(), "after": Box.visible_after})


class FakeIMAP:
    def __init__(self, *a, **k):
        Box.sessions += 1

    def login(self, u, p):
        if Box.login_error:
            raise imaplib.IMAP4.error(Box.login_error)
        assert (u, p) == (ec.GMAIL_SENDER, ec.GMAIL_APP_PASS)

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren \\All) "/" "[Gmail]/Todos"']

    def select(self, box, readonly=False):
        assert box == '"[Gmail]/Todos"' and not readonly
        return "OK", [b"1"]

    def noop(self):
        return "OK", [b""]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            Box.searches += 1
            vis = [m for m in Box.msgs if Box.searches > m["after"]]
            if args[0] == "X-GM-RAW":
                m = re.match(r'"rfc822msgid:(\S+)"$', args[1])
                hit = [x["uid"] for x in vis if m and x["msgid"].strip("<>") == m.group(1)]
            else:
                hit = [x["uid"] for x in vis if x["msgid"] == args[3].strip('"')]
            return "OK", [b" ".join(hit)]
        if cmd == "STORE":
            for x in Box.msgs:
                if x["uid"] == args[0]:
                    x["flags"].add(args[2].strip("()"))
            return "OK", [b""]
        raise AssertionError(cmd)

    def logout(self):
        pass


smtplib.SMTP_SSL = FakeSMTP
imaplib.IMAP4_SSL = FakeIMAP
GS.FIND_DELAYS = (0, 0, 0, 0)


def starred():
    return [x["subject"] for x in Box.msgs if "\\Flagged" in x["flags"]]


def content(rows):
    out = []
    for s in rows:
        m = email.message_from_string(s["msg"])
        out.append((s["from"], s["to"], m["Subject"], m["From"], m["To"],
                    [p.get_payload(decode=True) for p in m.walk() if p.get_content_maintype() == "text"]))
    return out


import io                                             # noqa: E402
import contextlib                                     # noqa: E402
import pyConsolidatedLeadPerformanceReport as C      # noqa: E402
import pyLeadFollowUpAnalysisReport as L             # noqa: E402

RCPT = "info@intellibiinnovationstechnologies.in"
for mod, subj in ((C, "Daily Lead Report - 01-Oct-2026"),
                  (L, "Daily Lead Follow-Up Analysis Report - 01-Oct-2026")):
    name = mod.__name__
    print(f"\n== {name} ==")
    check(f"{name}: STAR_EMAIL_IN_GMAIL default True", mod.STAR_EMAIL_IN_GMAIL, True)
    Box.reset(visible_after=2)
    SENT.clear()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        ok = mod.send_email(subj, "<p>report body</p>", [RCPT])
    log = out.getvalue()
    print(log.rstrip())
    check(f"{name}: sent (True) and Starred in Gmail", (ok, starred()), (True, [subj]))
    check(f"{name}: the starred message is exactly the one sent",
          Box.msgs[0]["msgid"] == email.message_from_string(SENT[0]["msg"])["Message-ID"], True)
    check(f"{name}: run summary still sees the send line",
          bool(re.search(r"\[email\] sent to", log)), True)
    with_star = content(SENT)
    mod.STAR_EMAIL_IN_GMAIL = False
    Box.reset()
    SENT.clear()
    ok2 = mod.send_email(subj, "<p>report body</p>", [RCPT])
    check(f"{name}: STAR_EMAIL_IN_GMAIL = False → sent, no IMAP, not starred",
          (ok2, Box.sessions, starred()), (True, 0, []))
    check(f"{name}: sender / recipients / subject / body identical with starring on and off",
          with_star, content(SENT))
    mod.STAR_EMAIL_IN_GMAIL = True
    Box.reset(login_error="[ALERT] IMAP access is disabled")
    SENT.clear()
    r = [mod.send_email(subj, "<p>x</p>", [RCPT]) for _ in range(3)]
    check(f"{name}: IMAP refused → every e-mail still sent (True); only ONE IMAP attempt per run",
          (r, len(SENT), Box.sessions), ([True, True, True], 3, 1))

print("\nALL CHECKS PASSED" if not FAIL else f"\n{len(FAIL)} CHECK(S) FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
