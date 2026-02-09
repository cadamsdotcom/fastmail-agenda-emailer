# Fastmail Daily Agenda Email

Replicates Google Calendar's daily agenda email for Fastmail. Connects via CalDAV, fetches today's events, and sends a formatted HTML email via SMTP.

Timezone is auto-detected from your Fastmail calendar settings — no configuration needed beyond credentials.

## Deploy to GitHub Actions (recommended)

### 1. Create a repo and push the code

```bash
gh repo create fastmail-daily-agenda --private
git init && git add -A && git commit -m "initial commit"
git remote add origin git@github.com:YOUR_USER/fastmail-daily-agenda.git
git push -u origin main
```

### 2. Add secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these two required secrets:

| Secret name | Value |
|---|---|
| `FASTMAIL_USERNAME` | Your Fastmail email, e.g. `chris@cadams.com.au` |
| `FASTMAIL_APP_PASSWORD` | An app password from Fastmail (see below) |

Optional secrets:

| Secret name | Value |
|---|---|
| `DISPLAY_NAME` | Your name for the greeting (e.g. `Chris Adams`) |
| `SEND_TO` | Different recipient address (default: same as username) |
| `CALENDAR_NAMES` | Comma-separated calendar names to include (default: all) |

### 3. Generate a Fastmail app password

1. Go to Fastmail → **Settings** → **Privacy & Security** → **Integrations** → **App passwords**
2. Create a new app password
3. Grant access to: **CalDAV** and **SMTP**
4. Copy the password into the `FASTMAIL_APP_PASSWORD` secret

### 4. Set your preferred send time

Edit `.github/workflows/daily-agenda.yml` and change the cron schedule. GitHub Actions uses **UTC**:

```yaml
# 5:00 AM AEST  = "0 19 * * *"   (UTC+10, fires previous day UTC)
# 5:00 AM US ET = "0 10 * * *"
# 5:00 AM UK    = "0 5 * * *"
# 6:00 AM AEDT  = "0 19 * * *"   (UTC+11, fires previous day UTC)
- cron: "0 19 * * *"
```

### 5. Test it

Go to **Actions** tab → **Send Daily Agenda** → **Run workflow** to trigger manually.

That's it. The workflow runs daily and you'll get an agenda email at your chosen time.

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your credentials
python3 daily_agenda.py --preview    # Test without sending
python3 daily_agenda.py              # Send the email
```

Or schedule with cron:

```cron
0 19 * * * cd /path/to/fastmail-daily-agenda && python3 daily_agenda.py
```

## How timezone detection works

The script reads the `calendar-timezone` CalDAV property from your Fastmail calendars. This means:

- It uses whatever timezone you've set in Fastmail
- If you travel and update your Fastmail timezone, the next email adapts automatically
- The server/runner timezone is irrelevant (GitHub Actions runs on UTC — that's fine)
- "Today" is determined in your calendar's timezone

Falls back to UTC if no timezone is found.

## CLI options

```
python3 daily_agenda.py                      # Send today's agenda
python3 daily_agenda.py --preview            # Print HTML, don't send
python3 daily_agenda.py --date 2026-03-15    # Specific date
```
