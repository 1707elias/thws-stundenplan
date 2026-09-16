"""Parser fuer sked-campus HTML-Veranstaltungsplaene der THWS.

Der Plan ist eine Folge von Wochen-Tabellen. Jede Tabelle hat eine Kopfzeile
mit Datumsangaben ("Mo, 05.10.2026") und darunter ein Raster aus Zellen mit
rowspan/colspan. Veranstaltungen sind Zellen mit class='v'.

Weil rowspan/colspan die Spaltenposition verschieben, koennen wir die Spalte
einer Zelle nicht einfach abzaehlen. Deshalb bauen wir das Tabellen-Raster
nach, so wie es ein Browser tut: eine Belegungsmatrix, in die jede Zelle an
der naechsten freien Position eingetragen wird.
"""
import re
from html.parser import HTMLParser

DAY_RE = re.compile(r"^(Mo|Di|Mi|Do|Fr|Sa|So), (\d{2}\.\d{2}\.\d{4})$")
TIME_RE = re.compile(r"^(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})$")
ROOM_RE = re.compile(r"^[A-Z]{1,3}[\.\-]?[0-9][\.\-0-9]*[a-zA-Z]?$")
GROUP_RE = re.compile(r"^Gruppe\s*\d+", re.IGNORECASE)


class _TableReader(HTMLParser):
    """Liest alle <table>-Elemente als Listen von Zeilen mit Zell-Dicts."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._table, self._row, self._cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._table = []
            self.tables.append(self._table)
        elif tag == "tr" and self._table is not None:
            self._row = []
            self._table.append(self._row)
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {
                "cls": a.get("class", "").strip(),
                "id": a.get("id"),
                "rowspan": _int(a.get("rowspan"), 1),
                "colspan": _int(a.get("colspan"), 1),
                "parts": [],
            }
            self._row.append(self._cell)
        elif tag == "br" and self._cell is not None:
            self._cell["parts"].append("\n")

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            self._cell = None
        elif tag == "tr":
            self._row = None
        elif tag == "table":
            self._table = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["parts"].append(data)


def _pad(time_str):
    """sked schreibt '9:00'; wir wollen ueberall '09:00'."""
    hour, minute = time_str.split(":")
    return f"{int(hour):02d}:{minute}"


def _int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _layout(rows):
    """Bildet das Tabellen-Raster nach und liefert (zeile, spalte, zelle)."""
    occupied, placed = set(), []
    for r, row in enumerate(rows):
        col = 0
        for cell in row:
            while (r, col) in occupied:
                col += 1
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    occupied.add((r + dr, col + dc))
            placed.append((r, col, cell))
            col += cell["colspan"]
    return placed


def _text_lines(cell):
    raw = "".join(cell["parts"]).replace("\xa0", " ")
    return [line.strip() for line in raw.split("\n") if line.strip()]


def _is_room(line):
    """'I.2.18', 'SHL' oder eine Aufzaehlung wie 'H.1.3, H.1.5'."""
    if line == "SHL":
        return True
    parts = [p.strip() for p in line.split(",") if p.strip()]
    return bool(parts) and all(ROOM_RE.match(p) for p in parts)


def _split_details(rest):
    """Trennt Dozent / Raum / Anmerkung.

    sked liefert je nach Veranstaltung 1-4 Zusatzzeilen, in der Reihenfolge
    [Gruppe] / Dozent / Raum / [Anmerkung]. Die Gruppenangabe steht VOR dem
    Dozenten - wer sie nicht erkennt, haelt 'Gruppe 1' faelschlich fuer den
    Dozentennamen. 'SHL' bedeutet Selbstlernphase, 'Online-Veranstaltung'
    ist eine Anmerkung und kein Raum.
    """
    lecturer, room, group, notes = "", "", "", []
    for line in rest:
        if not group and GROUP_RE.match(line):
            group = line
        elif not room and _is_room(line):
            room = line
        elif not lecturer and not _is_room(line):
            lecturer = line
        else:
            notes.append(line)
    if group:
        notes.insert(0, group)
    return lecturer, room, notes


def parse_plan(html, source=""):
    """Liefert eine Liste von Termin-Dicts aus einem sked-HTML-Plan."""
    reader = _TableReader()
    reader.feed(html)

    events, seen = [], set()
    for rows in reader.tables:
        cells = _layout(rows)

        # Spaltenbereiche der Wochentage aus der Kopfzeile lesen
        day_columns = {}
        for _, col, cell in cells:
            match = DAY_RE.match(" ".join(_text_lines(cell)))
            if match:
                day_columns[(col, col + cell["colspan"])] = match.group(2)
        if not day_columns:
            continue

        for _, col, cell in cells:
            if cell["cls"] != "v":
                continue
            lines = _text_lines(cell)
            if not lines:
                continue
            time_match = TIME_RE.match(lines[0])
            if not time_match:
                continue

            date = None
            for (start_col, end_col), value in day_columns.items():
                if start_col <= col < end_col:
                    date = value
                    break
            if date is None:
                continue

            title = lines[1] if len(lines) > 1 else "(ohne Titel)"
            lecturer, room, notes = _split_details(lines[2:])

            # "V Reserviert" ist ein geblockter Raum; der echte Titel steht
            # dann in der Anmerkung.
            if "Reserviert" in title and notes:
                title, notes = notes[0], notes[1:]

            event = {
                "sked_id": cell["id"] or "",
                "date": date,
                "start": _pad(time_match.group(1)),
                "end": _pad(time_match.group(2)),
                "title": title,
                "lecturer": lecturer,
                "room": room,
                "notes": notes,
                "source": source,
            }
            key = (event["date"], event["start"], event["end"],
                   event["title"], event["room"])
            if key in seen:
                continue  # dieselbe Veranstaltung kann ueber Spalten gespiegelt sein
            seen.add(key)
            events.append(event)
    return events
