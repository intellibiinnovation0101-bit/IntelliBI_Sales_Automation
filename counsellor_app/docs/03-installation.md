# 3. Installation / Setup

This installs the app on a host machine (the existing automation PC works fine).
Commands are shown for both Windows (PowerShell/cmd) and Linux/macOS.

## 3.1 Get the folder in place

The `counsellor_app/` folder lives **inside** the Sales project:

```
…\IntelliBI Automation\IntelliBI_Sales_Automation\counsellor_app\
```

It is self-contained. It does not import from, or write to, any of the existing
production scripts.

## 3.2 Create a virtual environment

Keeping this app's dependencies isolated avoids any clash with the existing
automation's packages.

**Windows:**
```bat
cd "C:\Users\vaibh\Documents\IntelliBI Automation\IntelliBI_Sales_Automation\counsellor_app"
python -m venv .venv
.venv\Scripts\activate
```

**Linux/macOS:**
```bash
cd counsellor_app
python3 -m venv .venv
. .venv/bin/activate
```

## 3.3 Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs FastAPI, Uvicorn, Pydantic, PyYAML, bcrypt, gspread and
google-auth. No database server is required.

## 3.4 Verify the install (offline, no credentials)

Run the test suite and a fake-mode boot to confirm everything imports and works:

```bash
python -m pytest -q
python run.py --fake --check      # bootstraps an in-memory sheet and prints status
```

Expected output of `--check` is a line like:
```
OK — bootstrapped 2 leads; pending writes: 0
```

## 3.5 Create your configuration

```bash
cp config.example.yaml config.yaml        # Windows: copy config.example.yaml config.yaml
python -m app.manage_users secret          # copy the printed value into session_secret
```

Edit `config.yaml`: paste the secret into `session_secret`, confirm
`data_sheet_id`, and set `host`/`port` as you want.

## 3.6 Add the Google service account

Follow `docs/05-google-sheets.md` to create a service account and download its
JSON key, then place it at:

```
counsellor_app/credentials/service_account.json
```

and share the Data sheet with the service account's `client_email` as **Editor**.

## 3.7 Add counsellor accounts

For each counsellor (see `docs/04`):

```bash
python -m app.manage_users add <email> "<Full Name>" "<Counselling By value>"
```

You'll be prompted for a password (twice). Only the bcrypt hash is stored in
`config.yaml`.

## 3.8 First real run

```bash
python run.py
```

You should see Uvicorn start on the configured port and a log line indicating
the sheet was bootstrapped. Open `http://<host>:8600/health` to confirm, then
`http://<host>:8600/` to use the app.

Next: `docs/06-running.md` for day-to-day running, or `docs/07-deployment.md` to
run it as an always-on service.
