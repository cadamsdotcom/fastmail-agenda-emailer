#!/usr/bin/env python3
"""
Fastmail Daily Agenda Email

Fetches today's calendar events from Fastmail via CalDAV and sends
a nicely formatted HTML agenda email via SMTP.

The timezone is auto-detected from your Fastmail calendar settings.

Usage:
  python3 daily_agenda.py              # Send today's agenda
  python3 daily_agenda.py --preview    # Print HTML to stdout (no email sent)
  python3 daily_agenda.py --date 2026-02-10  # Agenda for a specific date
"""

import argparse
import datetime
import html as html_module
import os
import re
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import caldav
import caldav.elements.cdav as cdav


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_env(filepath: str = ".env"):
    """Minimal .env loader — no external dependency needed."""
    path = Path(filepath)
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        os.environ.setdefault(key, value)


def get_config() -> dict:
    """Read configuration from environment variables."""
    load_env()

    required = {
        "FASTMAIL_USERNAME":  "Your Fastmail email address (e.g. you@fastmail.com)",
        "FASTMAIL_APP_PASSWORD": "An app password generated in Fastmail settings",
    }

    config = {}
    missing = []
    for key, description in required.items():
        val = os.environ.get(key)
        if not val:
            missing.append(f"  {key}: {description}")
        config[key] = val

    if missing:
        print("ERROR: Missing required environment variables:\n")
        print("\n".join(missing))
        print("\nSee .env.example for details.")
        sys.exit(1)

    config["CALDAV_URL"] = os.environ.get(
        "CALDAV_URL",
        f"https://caldav.fastmail.com/dav/calendars/user/{config['FASTMAIL_USERNAME']}/"
    )
    config["SMTP_HOST"] = os.environ.get("SMTP_HOST", "smtp.fastmail.com")
    config["SMTP_PORT"] = int(os.environ.get("SMTP_PORT", "465"))
    config["SEND_TO"] = os.environ.get("SEND_TO", config["FASTMAIL_USERNAME"])
    config["CALENDAR_NAMES"] = os.environ.get("CALENDAR_NAMES", "")
    config["DISPLAY_NAME"] = os.environ.get("DISPLAY_NAME", "")

    return config


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------

def connect_calendars(config: dict) -> list:
    """Connect to Fastmail CalDAV and return the list of calendars."""
    client = caldav.DAVClient(
        url=config["CALDAV_URL"],
        username=config["FASTMAIL_USERNAME"],
        password=config["FASTMAIL_APP_PASSWORD"],
    )
    principal = client.principal()
    calendars = principal.calendars()

    wanted = set()
    if config["CALENDAR_NAMES"]:
        wanted = {n.strip().lower() for n in config["CALENDAR_NAMES"].split(",")}

    if wanted:
        calendars = [c for c in calendars if (c.name or "").lower() in wanted]

    return calendars


def detect_calendar_timezone(calendars: list) -> str:
    """
    Detect timezone from CalDAV calendar-timezone property.
    Extracts TZID from the VTIMEZONE blob. Falls back to UTC.
    """
    for cal in calendars:
        try:
            props = cal.get_properties([cdav.CalendarTimeZone()])
            tz_data = props.get(cdav.CalendarTimeZone.tag, "")
            if not tz_data:
                continue
            match = re.search(r"TZID:(.+)", str(tz_data))
            if match:
                tzid = match.group(1).strip()
                ZoneInfo(tzid)  # validate
                return tzid
        except Exception:
            continue
    return "UTC"


def fetch_events(calendars: list, target_date: datetime.date, tz: ZoneInfo) -> list[dict]:
    """Fetch events for the target date from the given calendars."""
    day_start = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=tz)
    day_end = datetime.datetime.combine(
        target_date + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
    )

    events = []

    for cal in calendars:
        cal_name = cal.name or "(unnamed)"

        try:
            results = cal.search(start=day_start, end=day_end, event=True, expand=True)
        except Exception as e:
            print(f"Warning: could not search calendar '{cal_name}': {e}", file=sys.stderr)
            continue

        for item in results:
            try:
                vevent = item.vobject_instance.vevent
            except AttributeError:
                continue

            summary = str(getattr(vevent, "summary", None) or "Untitled event")
            location = str(getattr(vevent, "location", None) or "")
            description = str(getattr(vevent, "description", None) or "")

            dtstart = vevent.dtstart.value
            dtend = getattr(vevent, "dtend", None)
            dtend = dtend.value if dtend else None

            all_day = isinstance(dtstart, datetime.date) and not isinstance(
                dtstart, datetime.datetime
            )

            if not all_day:
                if dtstart.tzinfo is None:
                    dtstart = dtstart.replace(tzinfo=tz)
                dtstart = dtstart.astimezone(tz)
                if dtend:
                    if dtend.tzinfo is None:
                        dtend = dtend.replace(tzinfo=tz)
                    dtend = dtend.astimezone(tz)

            events.append({
                "summary": summary,
                "location": location,
                "description": description,
                "start": dtstart,
                "end": dtend,
                "all_day": all_day,
                "calendar": cal_name,
            })

    events.sort(key=lambda e: (
        0 if e["all_day"] else 1,
        e["start"] if not e["all_day"] else datetime.datetime.min.replace(tzinfo=tz),
    ))

    return events


# ---------------------------------------------------------------------------
# HTML formatting
# ---------------------------------------------------------------------------

def esc(text: str) -> str:
    """HTML-escape user content."""
    return html_module.escape(text)


def format_time(dt: datetime.datetime) -> str:
    return dt.strftime("%-I:%M %p").lower()


def format_date_short(dt: datetime.date) -> str:
    """e.g. 'Mon 9 Feb'"""
    return dt.strftime("%a %-d %b")


def render_event_row(e: dict, target_date: datetime.date) -> str:
    """Render a single event as a table row, Google Calendar style."""

    # --- Time column ---
    if e["all_day"]:
        time_cell = f"""
        <td style="padding: 14px 12px 14px 0; vertical-align: top; white-space: nowrap; color: #5f6368; font-size: 14px; width: 110px;">
            All day
        </td>
        <td style="padding: 14px 12px; vertical-align: top; white-space: nowrap; color: #5f6368; font-size: 14px; width: 100px;">
            {esc(format_date_short(target_date))}
        </td>"""
    else:
        start_str = format_time(e["start"])
        end_str = format_time(e["end"]) if e["end"] else ""
        time_html = f"{esc(start_str)} –<br>{esc(end_str)}" if end_str else esc(start_str)
        time_cell = f"""
        <td colspan="2" style="padding: 14px 12px 14px 0; vertical-align: top; white-space: nowrap; color: #5f6368; font-size: 14px; width: 210px;">
            {time_html}
        </td>"""

    # --- Color bar (between time and detail) ---
    bar_color = "#34a853" if e["all_day"] else "#4285f4"
    bar_cell = f"""
    <td style="padding: 0; width: 4px; vertical-align: top;">
        <div style="width: 4px; background: {bar_color}; border-radius: 2px; min-height: 40px; height: 100%;"></div>
    </td>"""

    # --- Detail column ---
    parts = []

    # Summary
    summary_color = "#1a73e8" if not e["all_day"] else "#188038"
    parts.append(
        f'<div style="font-size: 14px; color: {summary_color}; font-weight: 500;">{esc(e["summary"])}</div>'
    )

    # Location
    if e["location"]:
        loc_text = e["location"]
        # If location looks like it has an address, make it linkable
        maps_url = f"https://maps.google.com/?q={html_module.escape(loc_text, quote=True)}"
        parts.append(
            f'<div style="font-size: 13px; color: #5f6368; margin-top: 3px;">'
            f'📍 <a href="{maps_url}" style="color: #5f6368; text-decoration: none;">{esc(loc_text)}</a></div>'
        )

    # Description (truncated to keep email scannable)
    if e["description"]:
        desc = e["description"].strip()
        # Collapse multiple newlines and truncate
        desc = re.sub(r"\n{2,}", "\n", desc)
        if len(desc) > 200:
            desc = desc[:200].rsplit(" ", 1)[0] + "…"
        # Convert newlines to <br> for display
        desc_html = esc(desc).replace("\n", "<br>")
        parts.append(
            f'<div style="font-size: 12px; color: #80868b; margin-top: 4px; line-height: 1.4;">{desc_html}</div>'
        )

    # Calendar name
    parts.append(
        f'<div style="font-size: 11px; color: #9aa0a6; margin-top: 4px;">{esc(e["calendar"])}</div>'
    )

    detail_cell = f"""
    <td style="padding: 14px 0 14px 12px; vertical-align: top;">
        {"".join(parts)}
    </td>"""

    return f"""
    <tr style="border-bottom: 1px solid #e8eaed;">
        {time_cell}
        {bar_cell}
        {detail_cell}
    </tr>"""


def render_day_section(events: list[dict], target_date: datetime.date, label: str) -> str:
    """Render a single day's heading + event table."""
    date_str = target_date.strftime("%A %-d %B %Y")

    if not events:
        rows_html = """
        <tr>
          <td colspan="4" style="padding: 24px 16px; text-align: center; color: #5f6368; font-size: 14px; font-style: italic;">
            Nothing scheduled — enjoy your free day! 🎉
          </td>
        </tr>"""
    else:
        rows_html = "\n".join(render_event_row(e, target_date) for e in events)

    return f"""
    <!-- {label} -->
    <tr>
      <td style="padding: 28px 0 0 0;">
        <div style="font-size: 12px; color: #9aa0a6; text-transform: uppercase; letter-spacing: 0.08em; font-weight: 600;">
          {esc(label)}
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding: 2px 0 16px 0;">
        <div style="font-size: 22px; color: #202124; font-weight: 500;">
          {esc(date_str)}
        </div>
      </td>
    </tr>
    <tr>
      <td>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-top: 1px solid #e8eaed;">
          {rows_html}
        </table>
      </td>
    </tr>"""


def render_html(
    days: list[tuple[datetime.date, list[dict], str]],
    timezone: str,
    display_name: str,
    calendars_used: list[str],
) -> str:
    """
    Render the full email.

    days: list of (date, events, label) tuples, e.g. [("Today", ...), ("Tomorrow", ...)]
    """
    greeting_name = f"{esc(display_name)}, here" if display_name else "Here"
    calendars_list = ", ".join(esc(c) for c in sorted(set(calendars_used)))

    day_sections = "\n".join(
        render_day_section(events, date, label)
        for date, events, label in days
    )

    total_events = sum(len(events) for _, events, _ in days)

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin: 0; padding: 0; background: #ffffff; font-family: Google Sans, Roboto, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #202124;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width: 680px; margin: 0 auto; padding: 0 16px;">

    <!-- Header -->
    <tr>
      <td style="padding: 32px 0 0 0;">
        <div style="font-size: 28px; color: #202124; font-weight: 400; letter-spacing: -0.5px;">
          📅 <span style="color: #4285f4;">Daily</span> <span style="color: #202124;">Agenda</span>
        </div>
      </td>
    </tr>
    <tr>
      <td style="padding: 4px 0 0 0;">
        <div style="font-size: 14px; color: #5f6368;">
          {greeting_name} is your schedule:
        </div>
      </td>
    </tr>

    {day_sections}

    <!-- Footer -->
    <tr>
      <td style="padding: 32px 0 16px 0; border-top: 1px solid #e8eaed;">
        <div style="font-size: 12px; color: #9aa0a6; line-height: 1.6;">
          You are receiving this email at {esc(timezone)} time because you are subscribed to daily agendas
          for the following calendars: {calendars_list}.<br><br>
          Sent by your daily agenda script · Powered by Fastmail CalDAV
        </div>
      </td>
    </tr>

  </table>
</body>
</html>"""


def render_plaintext(days: list[tuple[datetime.date, list[dict], str]], timezone: str) -> str:
    lines = ["Daily Agenda", "=" * 50, ""]

    for target_date, events, label in days:
        date_str = target_date.strftime("%A %-d %B %Y")
        lines.extend([f"{label}: {date_str}", "-" * 40, ""])

        if not events:
            lines.append("  Nothing scheduled. Enjoy your free day!")
        else:
            for e in events:
                if e["all_day"]:
                    lines.append(f"  All day     {e['summary']}")
                else:
                    start = format_time(e["start"])
                    end = format_time(e["end"]) if e["end"] else ""
                    time_range = f"{start} – {end}" if end else start
                    lines.append(f"  {time_range:<22s} {e['summary']}")

                if e["location"]:
                    lines.append(f"{'':26s} 📍 {e['location']}")
                if e["description"]:
                    desc = e["description"].strip()[:150]
                    lines.append(f"{'':26s} {desc}")
                lines.append(f"{'':26s} [{e['calendar']}]")
                lines.append("")

        lines.append("")

    lines.extend([f"Timezone: {timezone}", ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_email(config: dict, subject: str, html: str, plaintext: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config["FASTMAIL_USERNAME"]
    msg["To"] = config["SEND_TO"]

    msg.attach(MIMEText(plaintext, "plain"))
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(config["SMTP_HOST"], config["SMTP_PORT"], context=context) as server:
        server.login(config["FASTMAIL_USERNAME"], config["FASTMAIL_APP_PASSWORD"])
        server.sendmail(config["FASTMAIL_USERNAME"], config["SEND_TO"], msg.as_string())

    print(f"✅ Agenda email sent to {config['SEND_TO']}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fastmail Daily Agenda Email")
    parser.add_argument("--preview", action="store_true", help="Print HTML to stdout (no email sent)")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD (default: today in calendar tz)")
    args = parser.parse_args()

    config = get_config()

    print("Connecting to Fastmail CalDAV...")
    calendars = connect_calendars(config)
    timezone_name = detect_calendar_timezone(calendars)
    tz = ZoneInfo(timezone_name)
    print(f"Detected calendar timezone: {timezone_name}")

    if args.date:
        today = datetime.date.fromisoformat(args.date)
    else:
        today = datetime.datetime.now(tz).date()

    tomorrow = today + datetime.timedelta(days=1)

    print(f"Fetching events for {today} and {tomorrow}...")
    today_events = fetch_events(calendars, today, tz)
    tomorrow_events = fetch_events(calendars, tomorrow, tz)

    # Filter out today's timed events that have already ended (keep all-day events)
    now = datetime.datetime.now(tz)
    today_events = [
        e for e in today_events
        if e["all_day"] or (e["end"] or e["start"]) >= now
    ]
    total = len(today_events) + len(tomorrow_events)
    print(f"Found {len(today_events)} event(s) today, {len(tomorrow_events)} tomorrow ({total} total).")

    days = [
        (today, today_events, "Today"),
        (tomorrow, tomorrow_events, "Tomorrow"),
    ]

    all_events = today_events + tomorrow_events
    calendars_used = list({e["calendar"] for e in all_events}) or [c.name for c in calendars if c.name]
    display_name = config["DISPLAY_NAME"]

    html = render_html(days, timezone_name, display_name, calendars_used)
    plaintext = render_plaintext(days, timezone_name)

    if args.preview:
        print("\n" + html)
        return

    subject = f"📅 Agenda for {today.strftime('%A %-d %b %Y')}"
    send_email(config, subject, html, plaintext)


if __name__ == "__main__":
    main()
