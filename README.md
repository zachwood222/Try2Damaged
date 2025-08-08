# Fowhand Damage Tracker — Render Free Tier (No Disk)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/zachwood222/Try2Damaged)

This package stores Google OAuth **tokens in Postgres** (via the `oauth_tokens` table) so it works on **Render free tier** (no disks allowed).

## Deploy (Blueprint / render.yaml)
1. Push to GitHub.
2. In Render: **New → Blueprint** and select your repo.
3. Set env vars:
   - `DATABASE_URL` (Render Postgres URL, format `postgresql+psycopg2://...`)
   - `BASE_URL` (your Render URL)
   - `GOOGLE_CLIENT_SECRETS` (file path `client_secret.json` in repo)
   - `DRIVE_UPLOAD_FOLDER_ID`
   - `MONITORED_GMAIL_ACCOUNTS`
   - `SERVICE_GOOGLE_ACCOUNT`
   - `NOTIFY_EMAILS`
   - `TASKS_SECRET`
4. Deploy, then open `/` and click **Connect** for both Gmail inboxes and the Drive/Sender account.

## Cron
- Every 5–10 min: `GET {BASE_URL}/tasks/scan?secret=YOUR_TASKS_SECRET`
- Daily: `GET {BASE_URL}/tasks/daily-summary?secret=YOUR_TASKS_SECRET`

## Local dev
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.sample .env
flask --app app.py --debug run
```
