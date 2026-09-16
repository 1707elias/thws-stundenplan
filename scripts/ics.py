"""Erzeugt iCalendar-Dateien (RFC 5545), die Apple Kalender sauber abonniert."""
from datetime import datetime, timezone

# Feste Zeitzonen-Definition. Ohne die raet der Kalender-Client bei der
# Sommerzeit-Umstellung, und Termine landen eine Stunde daneben.
VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def escape(text):
    """Sonderzeichen maskieren – sonst zerreisst ein Komma die Zeile."""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line):
    """RFC 5545 erlaubt max. 75 Bytes pro Zeile; laengere werden umgebrochen."""
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line
    chunks, start = [], 0
    while start < len(data):
        end = min(start + (75 if not chunks else 74), len(data))
        # nicht mitten in ein Mehrbyte-Zeichen schneiden
        while end < len(data) and (data[end] & 0xC0) == 0x80:
            end -= 1
        chunks.append(data[start:end].decode("utf-8"))
        start = end
    return "\r\n ".join(chunks)


def _stamp(date_str, time_str):
    dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%Y %H:%M")
    return dt.strftime("%Y%m%dT%H%M%S")


def build_calendar(name, events, domain, refresh_hours=6, alarm_minutes=0,
                   sequences=None, stamps=None):
    """stamps: UID -> DTSTAMP. Unveraenderte Termine behalten ihren
    Zeitstempel, sonst erzeugt jeder Lauf eine neue Datei und damit einen
    sinnlosen Commit."""
    sequences = sequences or {}
    stamps = stamps or {}
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    refresh = f"PT{refresh_hours}H"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//THWS Stundenplan//sked-Import//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(name)}",
        "X-WR-TIMEZONE:Europe/Berlin",
        f"X-PUBLISHED-TTL:{refresh}",
        f"REFRESH-INTERVAL;VALUE=DURATION:{refresh}",
        VTIMEZONE,
    ]

    for event in sorted(events, key=lambda e: (e["date"].split(".")[::-1], e["start"])):
        uid = f"{event['sked_id'] or event['hash'][:12]}@{domain}"
        description = []
        if event["lecturer"]:
            description.append(f"Dozent: {event['lecturer']}")
        if event["notes"]:
            description.extend(event["notes"])
        description.append(f"Quelle: {event['source']}")

        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamps.get(uid, now)}",
            f"SEQUENCE:{sequences.get(uid, 0)}",
            f"DTSTART;TZID=Europe/Berlin:{_stamp(event['date'], event['start'])}",
            f"DTEND;TZID=Europe/Berlin:{_stamp(event['date'], event['end'])}",
            f"SUMMARY:{escape(event['title'])}",
            f"DESCRIPTION:{escape(chr(10).join(description))}",
            "TRANSP:OPAQUE",
        ]
        if event["room"]:
            location = "Online" if event["room"] == "SHL" else event["room"]
            lines.append(f"LOCATION:{escape(location)}")
        if alarm_minutes:
            lines += [
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{escape(event['title'])}",
                f"TRIGGER:-PT{alarm_minutes}M",
                "END:VALARM",
            ]
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")

    out = []
    for line in lines:
        out.extend(fold(part) for part in line.split("\n"))
    return "\r\n".join(out) + "\r\n"
