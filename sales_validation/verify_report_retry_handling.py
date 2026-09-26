"""
Verification of the production-failure handling in the Sales report layer:
transient Google/SMTP errors are retried, a retry never duplicates a Drive file
or an e-mail, one failed report never aborts the others, and the pipeline runner
re-runs a script only when nothing was delivered yet.

Run from the project root (no extra packages needed):
    python sales_validation\\verify_report_retry_handling.py
"""
import os
import sys
import tempfile
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "common"))

import api_retry                                   # noqa: E402

api_retry._sleep = lambda s: None                  # no real waiting in tests


# ── fakes ────────────────────────────────────────────────────────────────────
class FakeResp:
    def __init__(self, status): self.status = status


class HttpError(Exception):
    """Shape-compatible with googleapiclient.errors.HttpError."""
    def __init__(self, status, msg):
        super().__init__(f'<HttpError {status} returned "{msg}">')
        self.resp = FakeResp(status)


class Flaky:
    """Callable that fails `fails` times with `exc`, then returns `value`."""
    def __init__(self, fails, exc, value="ok"):
        self.fails, self.exc, self.value, self.calls = fails, exc, value, 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.fails:
            raise self.exc
        return self.value


# ── 1. classification ─────────────────────────────────────────────────────────
import smtplib                                      # noqa: E402
assert api_retry.is_transient(HttpError(500, "Internal Error"))                 # the 23/25/26-Sep failure
assert api_retry.is_transient(HttpError(503, "The service is currently unavailable."))  # the enrolled-sheet 503
assert api_retry.is_transient(HttpError(429, "Quota exceeded"))
assert api_retry.is_transient(HttpError(403, "userRateLimitExceeded"))
assert api_retry.is_transient(ConnectionResetError(104, "reset"))
assert api_retry.is_transient(TimeoutError("timed out"))
assert api_retry.is_transient(smtplib.SMTPServerDisconnected("closed"))
assert api_retry.is_transient(smtplib.SMTPResponseException(421, b"try later"))
assert not api_retry.is_transient(HttpError(404, "File not found"))
assert not api_retry.is_transient(HttpError(403, "The caller does not have permission"))
assert not api_retry.is_transient(HttpError(401, "Invalid Credentials"))
assert not api_retry.is_transient(HttpError(403, "storageQuotaExceeded"))
assert not api_retry.is_transient(smtplib.SMTPAuthenticationError(535, b"BadCredentials"))  # 17-Sep e-mail case
assert not api_retry.is_transient(KeyError("Mobile Number"))
print("[pass] transient vs permanent classification")

# ── 2. call_with_retry: retries transient, fails fast on permanent ───────────
logs = []
f = Flaky(2, HttpError(500, "Internal Error"))
assert api_retry.call_with_retry(f, "Drive: upload", attempts=5, base_wait=1, log=logs.append) == "ok"
assert f.calls == 3 and len(logs) == 2 and "retry 1/4" in logs[0]
f = Flaky(9, HttpError(503, "unavailable"))
try:
    api_retry.call_with_retry(f, "x", attempts=4, base_wait=1, log=logs.append); raise AssertionError
except HttpError:
    assert f.calls == 4                            # gave up after the configured attempts
f = Flaky(1, HttpError(404, "not found"))
try:
    api_retry.call_with_retry(f, "x", attempts=5, base_wait=1, log=logs.append); raise AssertionError
except HttpError:
    assert f.calls == 1                            # permanent error: no retry at all
print("[pass] call_with_retry back-off / fail-fast")

# ── 3. Drive upload: a 500 AFTER the file was stored must not duplicate it ───
class FakeDrive:
    """Minimal drive.files() emulation: create() may fail after storing the file."""
    def __init__(self, fail_after_store=0):
        self.store, self.fail_after_store, self.creates = [], fail_after_store, 0

    def create(self, name):
        self.creates += 1
        self.store.append({"id": f"id{self.creates}", "name": name, "webViewLink": f"https://x/{self.creates}"})
        if self.creates <= self.fail_after_store:
            raise HttpError(500, "Internal Error")          # stored, but the response was a 500
        return self.store[-1]

    def find(self, name):
        return [x for x in self.store if x["name"] == name]

drive = FakeDrive(fail_after_store=1)
name = "Lead Performance - Daily - 26-Sep-2026 _06.46.54 PM (Masked)"
res = api_retry.call_with_retry(lambda: drive.create(name), "Drive: upload", attempts=5, base_wait=1,
                                on_retry=lambda n, e: (drive.find(name) or [None])[0], log=logs.append)
assert res["id"] == "id1" and drive.creates == 1 and len(drive.find(name)) == 1
# and when the failed attempt really stored nothing, the retry creates it once
drive2 = FakeDrive(fail_after_store=0)
flaky = Flaky(1, HttpError(500, "Internal Error"))
def _create():
    flaky(); return drive2.create(name)
res = api_retry.call_with_retry(_create, "Drive: upload", attempts=5, base_wait=1,
                                on_retry=lambda n, e: (drive2.find(name) or [None])[0], log=logs.append)
assert len(drive2.find(name)) == 1
print("[pass] upload retry reuses an already-stored file — no duplicate Drive file")

# ── 4. delivery steps: completed steps are never repeated ────────────────────
emails, uploads = [], []
state = {"emailed": set()}
upload_flaky = Flaky(0, None, ("https://x/1", "fid1"))
mail_fail = {"n": 1}                               # first e-mail attempt hits a transient error

def st_upload():
    uploads.append(1); return upload_flaky()
def st_emails():
    for r in ["a@x", "b@x", "c@x"]:
        if r in state["emailed"]:
            continue
        if r == "b@x" and mail_fail["n"]:
            mail_fail["n"] -= 1
            raise HttpError(503, "unavailable")     # simulate a transient failure mid-way
        emails.append(r); state["emailed"].add(r)
    return True

api_retry.run_steps_with_retry("Daily", [("upload", st_upload), ("emails", st_emails)], state,
                               attempts=3, base_wait=1, log=logs.append)
assert uploads == [1], "upload must run exactly once even though a later step was retried"
assert emails == ["a@x", "b@x", "c@x"], emails       # a@x was NOT sent twice
# permanent failure → DeliveryFailed names the step; earlier steps stay done
state2 = {}
try:
    api_retry.run_steps_with_retry("Weekly", [("upload", lambda: "u"),
                                              ("share", lambda: (_ for _ in ()).throw(HttpError(403, "does not have permission")))],
                                   state2, attempts=3, base_wait=1, log=logs.append)
    raise AssertionError
except api_retry.DeliveryFailed as e:
    assert e.step == "share" and state2["upload"] == "u" and "403" in str(e)
print("[pass] step-level retry never repeats a completed upload / e-mail")

# ── 5. runner: re-run only when nothing was delivered; never after a delivery ─
import paths                                        # noqa: E402
from pathlib import Path                            # noqa: E402
paths.LOGS_DIR = Path(tempfile.mkdtemp(prefix="retry_test_logs_"))   # keep test logs out of logs\\
import common_utils                                 # noqa: E402
import config_loader                                # noqa: E402
config_loader.get = lambda key, default=None: {"pipeline.report_retries": 2,
                                               "pipeline.report_retry_wait_seconds": 1,
                                               "pipeline.quota_retries": 2,
                                               "pipeline.quota_retry_wait_seconds": 1}.get(key, default)
common_utils.time.sleep = lambda s: None
common_utils.random.randint = lambda a, b: 0

def _script(body):
    fd, path = tempfile.mkstemp(suffix=".py", prefix="fake_report_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(body))
    return path

# (a) exits 3 twice (nothing delivered), succeeds on the 3rd run → re-run, SUCCESS
marker = tempfile.mktemp()
p = _script(f"""
    import os, sys
    n = int(open({marker!r}).read()) if os.path.exists({marker!r}) else 0
    open({marker!r}, "w").write(str(n + 1))
    if n < 2:
        print("HttpError 503 reading master"); sys.exit(3)
    print("  created: https://docs.google.com/x"); print("  [email] sent to a@x"); print("Done.")
""")
r = common_utils.run_script(p, label="fake")
assert r["status"] == "SUCCESS" and r["attempts"] == 3, r
# (b) exits 1 after delivering (partial) → NOT re-run
marker2 = tempfile.mktemp()
p = _script(f"""
    import os, sys
    n = int(open({marker2!r}).read()) if os.path.exists({marker2!r}) else 0
    open({marker2!r}, "w").write(str(n + 1))
    print("  created: https://docs.google.com/x"); print("  [email] sent to a@x")
    print("[FAILED] Monthly: step 'masked' failed: HttpError 500"); sys.exit(1)
""")
r = common_utils.run_script(p, label="fake2")
assert r["status"] == "FAILED" and r["attempts"] == 1 and open(marker2).read() == "1", r
# (c) quota error AFTER a delivery → also NOT re-run (closes an old duplicate risk)
marker3 = tempfile.mktemp()
p = _script(f"""
    import os, sys
    n = int(open({marker3!r}).read()) if os.path.exists({marker3!r}) else 0
    open({marker3!r}, "w").write(str(n + 1))
    print("  [email] sent to a@x"); print("HttpError 429 Quota exceeded"); sys.exit(1)
""")
r = common_utils.run_script(p, label="fake3")
assert r["status"] == "FAILED" and open(marker3).read() == "1", r
# (d) quota error with nothing delivered → existing quota re-run still applies
marker4 = tempfile.mktemp()
p = _script(f"""
    import os, sys
    n = int(open({marker4!r}).read()) if os.path.exists({marker4!r}) else 0
    open({marker4!r}, "w").write(str(n + 1))
    if n < 1:
        print("HttpError 429 Quota exceeded"); sys.exit(1)
    print("Done.")
""")
r = common_utils.run_script(p, label="fake4")
assert r["status"] == "SUCCESS" and r["attempts"] == 2, r
print("[pass] runner re-runs only 'nothing delivered' failures; never after a delivery")

print("ALL CHECKS PASSED")
