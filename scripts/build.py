#!/usr/bin/env python3
"""Holt die THWS-Stundenplaene, baut die Kalender-Feeds und meldet Aenderungen.

Ablauf:
  1. Plaene herunterladen und parsen
  2. Termine auf die konfigurierten Kalender verteilen
  3. .ics-Dateien nach docs/ schreiben
  4. Gegen den letzten Lauf (state.json) diffen
  5. Bei Aenderungen: Telegram-Nachricht
  6. Uebersichtsseite docs/index.html erzeugen
"""
import hashlib
import html
import json
import os
import sys
import tomllib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    BERLIN = ZoneInfo("Europe/Berlin")
except Exception:          # ohne tzdata lieber UTC als Absturz
    BERLIN = timezone.utc

sys.path.insert(0, str(Path(__file__).parent))
from sked_parser import parse_plan
from ics import build_calendar

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
STATE_FILE = ROOT / "state.json"
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Die UID-Domain ist bewusst FEST und haengt nicht an base_url. Sonst
# bekaemen alle Termine neue UIDs, sobald das Repo umbenannt wird - und
# damit stuenden im Kalender alle Termine doppelt.
UID_DOMAIN = "thws-stundenplan.local"

# Sicherheitsnetz: liefert die THWS mal eine halbe Seite (HTTP 200, aber
# unvollstaendig), soll der Lauf abbrechen statt den Kalender zu leeren.
MIN_SHARE_OF_PREVIOUS = 0.5


# ── Hilfsfunktionen ──────────────────────────────────────────────────

def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "thws-kalender/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def event_hash(event):
    """Fingerabdruck eines Termins – aendert sich, sobald etwas verrutscht."""
    payload = "|".join([
        event["date"], event["start"], event["end"],
        event["title"], event["lecturer"], event["room"],
        " ".join(event["notes"]),
    ])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def matches(event, patterns):
    title = event["title"].lower()
    return any(pattern.lower() in title for pattern in patterns)


def as_datetime(event, which="start"):
    return datetime.strptime(f"{event['date']} {event[which]}", "%d.%m.%Y %H:%M")


def now_local():
    return datetime.now(BERLIN)


def label(event):
    day = WEEKDAYS[as_datetime(event).weekday()]
    return f"{day} {event['date']} {event['start']}–{event['end']} · {event['title']}"


# ── Konflikte ────────────────────────────────────────────────────────

def find_conflicts(events):
    """Findet zeitlich ueberlappende Termine im selben Kalender."""
    ordered = sorted(events, key=as_datetime)
    conflicts = []
    for i, first in enumerate(ordered):
        for second in ordered[i + 1:]:
            if as_datetime(second) >= as_datetime(first, "end"):
                break  # sortiert – alles Weitere liegt noch spaeter
            if first["title"] != second["title"]:
                conflicts.append((first, second))
    return conflicts


# ── Benachrichtigung ─────────────────────────────────────────────────

def esc(value):
    """Fuer Telegram-HTML und die Uebersichtsseite: & < > maskieren."""
    return html.escape(str(value), quote=False)


def notify_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Telegram nicht konfiguriert – Nachricht nur im Log:")
        print(text)
        return
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30) as r:
            r.read()
        print("Telegram-Nachricht gesendet.")
    except Exception as error:  # eine kaputte Benachrichtigung darf den Lauf nicht killen
        print(f"Telegram fehlgeschlagen: {error}")


# ── Uebersichtsseite ─────────────────────────────────────────────────

def render_index(config, calendars, conflicts, generated):
    base = config["base_url"].rstrip("/")
    today = now_local()
    horizon = today + timedelta(days=21)

    upcoming = []
    for calendar in calendars:
        for event in calendar["events"]:
            start = as_datetime(event)
            if today.date() <= start.date() <= horizon.date():
                upcoming.append((start, calendar["name"], event))
    upcoming.sort(key=lambda row: row[0])

    rows = "\n".join(
        f"<tr><td class='d'>{WEEKDAYS[start.weekday()]} {event['date']}</td>"
        f"<td class='t'>{event['start']}–{event['end']}</td>"
        f"<td>{esc(event['title'])}</td>"
        f"<td class='m'>{esc(event['room'] or '—')}</td>"
        f"<td class='m'>{esc(event['lecturer'] or '—')}</td></tr>"
        for start, _, event in upcoming
    ) or "<tr><td colspan='5' class='m'>In den nächsten drei Wochen steht nichts an.</td></tr>"

    webcal = base.replace("https://", "webcal://")
    subs = "\n".join(
        f"<li><strong>{esc(c['name'])}</strong> — {len(c['events'])} Termine<br>"
        f"<a href=\'{webcal}/{c['file']}\'>Abonnieren</a> · "
        f"<code>{base}/{c['file']}</code></li>"
        for c in calendars
    )

    warn = ""
    if conflicts:
        items = "\n".join(
            f"<li>{esc(label(a))}<br>&nbsp;&nbsp;↔&nbsp; {esc(label(b))}</li>"
            for a, b in conflicts[:12]
        )
        if len(conflicts) > 12:
            items += f"<li>… und {len(conflicts) - 12} weitere</li>"
        warn = (f"<div class='warn'><h2>⚠ Terminkonflikte ({len(conflicts)})</h2>"
                f"<ul>{items}</ul></div>")

    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>THWS Stundenplan</title>
<style>
:root {{ --bg:#fff; --fg:#1a1a1a; --mut:#6b7280; --line:#e5e7eb; --acc:#1d4ed8; --wbg:#fef3c7; --wfg:#92400e; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#111418; --fg:#e8eaed; --mut:#9aa0a6; --line:#2c3238; --acc:#7aa2f7; --wbg:#3a2f12; --wfg:#fcd34d; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:24px 16px 64px; background:var(--bg); color:var(--fg);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:860px; margin:0 auto; }}
h1 {{ font-size:22px; margin:0 0 4px; }}
h2 {{ font-size:15px; margin:28px 0 10px; text-transform:uppercase;
  letter-spacing:.06em; color:var(--mut); }}
.warn h2 {{ color:var(--wfg); margin-top:0; }}
.sub {{ color:var(--mut); font-size:13px; margin:0 0 20px; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
td {{ padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
.d {{ white-space:nowrap; font-variant-numeric:tabular-nums; }}
.t {{ white-space:nowrap; color:var(--mut); font-variant-numeric:tabular-nums; }}
.m {{ color:var(--mut); }}
.warn {{ background:var(--wbg); color:var(--wfg); padding:14px 18px;
  border-radius:10px; margin:20px 0; font-size:14px; }}
.warn ul, ul.subs {{ margin:0; padding-left:20px; }}
ul.subs li {{ margin-bottom:12px; }}
code {{ font-size:12px; color:var(--acc); word-break:break-all; }}
footer {{ margin-top:36px; color:var(--mut); font-size:12px; }}
</style></head><body><div class="wrap">
<h1>THWS Stundenplan</h1>
<p class="sub">Automatisch aus den sked-Plänen der FIW erzeugt · letzte Änderung {generated}</p>
{warn}
<h2>Nächste drei Wochen</h2>
<table>{rows}</table>
<h2>Kalender-Abos</h2>
<ul class="subs">{subs}</ul>
<footer>Aktualisiert sich alle {config['refresh_hours']} Stunden über GitHub Actions.</footer>
</div></body></html>
"""


# ── Hauptlauf ────────────────────────────────────────────────────────

def main():
    config = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    DOCS.mkdir(exist_ok=True)

    previous = {}
    if STATE_FILE.exists():
        previous = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    old_events = previous.get("events", {})

    # 1. Plaene einlesen
    all_events = []
    for source in config["sources"]:
        print(f"Lade {source['name']} …")
        events = parse_plan(fetch(source["url"]), source["name"])
        print(f"  {len(events)} Termine")
        all_events.extend(events)

    # Dieselbe Veranstaltung steht oft in mehreren Plaenen (z.B. die
    # Karriere-Reihe im 3. und 7. Semester). Einmal reicht.
    unique, seen = [], set()
    for event in all_events:
        key = (event["date"], event["start"], event["end"],
               event["title"], event["room"])
        if key in seen:
            continue
        seen.add(key)
        event["hash"] = event_hash(event)
        unique.append(event)
    if len(unique) < len(all_events):
        print(f"{len(all_events) - len(unique)} Doppel-Einträge zusammengeführt")
    all_events = unique

    # Plausibilitaet: lieber abbrechen als den Kalender leerraeumen
    expected = previous.get("total_parsed", 0)
    if expected and len(all_events) < expected * MIN_SHARE_OF_PREVIOUS:
        raise SystemExit(
            f"Abbruch: nur {len(all_events)} statt zuletzt {expected} Termine "
            "gefunden. Sieht nach einer unvollständigen Seite aus – "
            "state.json und docs/ bleiben unangetastet."
        )

    # 2./3. Kalender bauen
    calendars, current, conflicts = [], {}, []
    stamp_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for spec in config["calendars"]:
        events = [e for e in all_events if matches(e, spec["match"])]
        print(f"{spec['name']}: {len(events)} Termine")

        sequences, stamps = {}, {}
        for event in events:
            uid = f"{event['sked_id'] or event['hash'][:12]}@{UID_DOMAIN}"
            old = old_events.get(uid)
            unchanged = bool(old) and old["hash"] == event["hash"]
            sequences[uid] = (old.get("sequence", 0) if old else 0) + (0 if unchanged else (1 if old else 0))
            # Unveraenderte Termine behalten ihren DTSTAMP – sonst
            # unterscheidet sich jede erzeugte Datei und wir committen
            # viermal taeglich Rauschen.
            stamps[uid] = old.get("dtstamp", stamp_now) if unchanged else stamp_now
            current[uid] = {
                "hash": event["hash"], "sequence": sequences[uid],
                "dtstamp": stamps[uid], "label": label(event),
                "calendar": spec["name"], "room": event["room"],
                "lecturer": event["lecturer"],
            }

        ics = build_calendar(
            spec["name"], events, UID_DOMAIN,
            refresh_hours=config["refresh_hours"],
            alarm_minutes=spec.get("alarm_minutes", 0),
            sequences=sequences, stamps=stamps,
        )
        (DOCS / spec["file"]).write_text(ics, encoding="utf-8", newline="")
        calendars.append({**spec, "events": events})

        if spec.get("check_conflicts"):
            conflicts.extend(find_conflicts(events))

    # 4. Diff gegen den letzten Lauf
    added = [uid for uid in current if uid not in old_events]
    removed = [uid for uid in old_events if uid not in current]
    changed = [uid for uid in current
               if uid in old_events and old_events[uid]["hash"] != current[uid]["hash"]]
    has_changes = bool(added or removed or changed)

    # "Stand" nur fortschreiben, wenn sich wirklich etwas geaendert hat
    last_change = previous.get("last_change") or now_local().strftime("%d.%m.%Y, %H:%M")
    if has_changes or not old_events:
        last_change = now_local().strftime("%d.%m.%Y, %H:%M")

    STATE_FILE.write_text(
        json.dumps({"last_change": last_change,
                    "total_parsed": len(all_events),
                    "events": current},
                   ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    (DOCS / "index.html").write_text(
        render_index(config, calendars, conflicts, last_change), encoding="utf-8"
    )

    # 5. Melden
    if not old_events:
        print("Erster Lauf – keine Benachrichtigung.")
        return
    if not has_changes:
        print("Keine Änderungen.")
        return

    def block(title, uids, render):
        lines = [f"\n{title}"]
        lines += [render(uid) for uid in uids[:10]]
        if len(uids) > 10:
            lines.append(f"… und {len(uids) - 10} weitere")
        return lines

    parts = [f"<b>Stundenplan-Änderung</b> ({esc(last_change)})"]
    if added:
        parts += block("🆕 <b>Neu</b>", added,
                       lambda u: f"• {esc(current[u]['label'])}")
    if changed:
        def render_change(uid):
            before, after = old_events[uid], current[uid]
            text = [f"• {esc(after['label'])}"]
            if before.get("room") != after.get("room"):
                text.append(f"   Raum: {esc(before.get('room') or '—')} → "
                            f"{esc(after.get('room') or '—')}")
            if before["label"] != after["label"]:
                text.append(f"   vorher: {esc(before['label'])}")
            return "\n".join(text)
        parts += block("✏️ <b>Geändert</b>", changed, render_change)
    if removed:
        parts += block("❌ <b>Entfallen</b>", removed,
                       lambda u: f"• {esc(old_events[u]['label'])}")
    parts.append(f"\n{config['base_url']}")

    notify_telegram("\n".join(parts))


if __name__ == "__main__":
    main()
