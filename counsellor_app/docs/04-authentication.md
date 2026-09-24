# 4. Authentication & Access Setup

The app has two independent layers of access control:

1. **Who can log in** — counsellor accounts (an allow-list you manage).
2. **What the service account can do** — the Google service account's access to
   the Data sheet (covered in `docs/05`).

## 4.1 How counsellor login works

- Counsellors are an **allow-list** in `config.yaml`. Only listed, `active`
  accounts can log in.
- Each account stores a **bcrypt hash** of the password — never the password
  itself. Claude/AI never sees the plaintext; you create the hash locally with
  the CLI.
- On successful login the server issues a **signed, expiring session cookie**
  (HMAC-SHA256 over `email|expiry` using `session_secret`). There is no
  server-side session store to manage, and a tampered cookie is rejected.
- Cookies are `HttpOnly` and `SameSite=Lax`. Behind HTTPS, set
  `INTELLIBI_APP_SECURE_COOKIE=1` so they are also marked `Secure`.
- Sessions last `session_hours` (default 12), after which the counsellor logs in
  again.

## 4.2 Managing accounts (the admin CLI)

All account management is done with `app.manage_users`. Run these from the
`counsellor_app/` folder with the virtual environment active.

**Generate a session secret** (do this once, put it in `config.yaml`):
```bash
python -m app.manage_users secret
```

**Add or update a counsellor** (prompts for the password, writes the hash):
```bash
python -m app.manage_users add meera@intellibiinnovationstechnologies.in "Meera Nair" "Meera Nair"
```
- Argument 1: login email.
- Argument 2: display name.
- Argument 3: the exact value to write into the sheet's **"Counselling By"**
  column for leads this person saves. Match the spelling used today so reports
  group correctly.

**List configured accounts:**
```bash
python -m app.manage_users list
```

**Just print a hash** (e.g. to paste into `config.yaml` yourself):
```bash
python -m app.manage_users hash
```

**Deactivate someone** without deleting: set `active: false` on their entry in
`config.yaml` and restart. **Change a password:** run `add` again for the same
email — it replaces the existing entry.

> Password policy: choose strong, unique passwords. bcrypt automatically salts
> each hash, so identical passwords still produce different hashes.

## 4.3 Roles

Each account has a `role`: `counsellor` (default) or `admin`. The role is
recorded and returned by `/api/me`. The current UI treats both the same; the
`admin` role is a hook for future admin-only screens (e.g. bulk tools) without
re-architecting auth.

## 4.4 Optional: Google Workspace (OAuth) login

If you would rather counsellors sign in with their `@intellibiinnovationstechnologies.in`
Google account instead of a password, the code has a ready hook
(`auth.verify_google_token`). It is **disabled by default** so the system runs
with zero external auth dependencies.

To enable it later:

1. `pip install google-auth-oauthlib`
2. Create an OAuth **Web** client in Google Cloud Console; note the client ID.
3. In `config.yaml`:
   ```yaml
   google_oauth_enabled: true
   google_client_id: "…apps.googleusercontent.com"
   allowed_email_domain: "intellibiinnovationstechnologies.in"
   ```
4. Still list each person under `counsellors:` (so you control access and their
   *Counselling By* value) — you can leave `password_hash` empty for OAuth-only
   users.
5. Add a Google Sign-In button to the UI that posts the returned ID token to a
   `/api/login/google` route wired to `verify_google_token`. (The verification
   function is provided; the button + route are a small addition documented here
   so you can turn it on when ready.)

Password login and Google login can coexist.

## 4.5 Security summary

- Plaintext passwords never touch disk, logs, or the network — only bcrypt
  hashes are stored.
- Session cookies are signed and expiring; tampering is detected.
- The service-account key and `config.yaml` are git-ignored.
- Only editable fields are accepted from the browser on save; the mobile key,
  timestamp, and *Counselling By* are set server-side, so a crafted request
  cannot corrupt those.
- Put the app behind HTTPS (reverse proxy) for any access beyond localhost — see
  `docs/07`.
