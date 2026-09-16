# THWS Stundenplan → Kalender-Abo

Holt die sked-Stundenpläne der FIW, filtert die für dich relevanten
Veranstaltungen heraus und veröffentlicht sie als Kalender-Abos, die
iPhone und Mac selbstständig aktuell halten. Bei Änderungen kommt eine
Telegram-Nachricht.

```
sked-HTML (2 Pläne)  →  Parser  →  .ics-Dateien auf GitHub Pages
        alle 6 h, via GitHub Actions           ↓
                                    iCloud-Abo → iPhone + Mac
                                        ↓
                            Telegram bei Änderungen
```

## Was drin steckt

| Datei | Zweck |
|---|---|
| `config.toml` | **Deine Stellschrauben** – URLs, Kurse, Erinnerungen |
| `scripts/sked_parser.py` | Liest die sked-HTML-Tabellen aus |
| `scripts/ics.py` | Baut die iCalendar-Dateien |
| `scripts/build.py` | Steuert alles, erkennt Änderungen, meldet |
| `.github/workflows/update.yml` | Der Zeitplan (alle 6 h) |
| `docs/` | Die `.ics`-Dateien + Übersichtsseite (liegen fertig bei, werden bei jedem Lauf neu geschrieben) |
| `state.json` | Stand des letzten Laufs, Grundlage für den Änderungsvergleich |

---

## Einrichtung

### 1. Repository anlegen

Neues Repository auf GitHub, Name z. B. `thws-stundenplan`.

> **Wichtig:** Das Repo muss **öffentlich** sein. GitHub Pages funktioniert
> bei privaten Repos nur mit einem kostenpflichtigen Tarif. Der Inhalt sind
> Vorlesungszeiten, Raumnummern und Dozentennamen – öffentliche Angaben aus
> dem THWS-Plan. Dein eigener Name steht in keiner erzeugten Datei; nur der
> GitHub-Account, dem das Repo gehört, ist natürlich sichtbar.

Dann den Inhalt dieses Ordners hochladen (per `git push` oder im Browser
über „Add file → Upload files").

### 2. GitHub Pages einschalten

Im Repo: **Settings → Pages**

- Source: `Deploy from a branch`
- Branch: `main`, Ordner: `/docs`
- Speichern

Nach ein paar Minuten ist deine Adresse erreichbar:
`https://DEIN-NAME.github.io/thws-stundenplan/`

Dort findest du auch eine Übersichtsseite mit den nächsten drei Wochen,
Warnungen zu Terminkonflikten und Abo-Links zum Antippen.

### 3. `config.toml` anpassen

Trag oben deine Pages-Adresse ein:

```toml
base_url = "https://DEIN-NAME.github.io/thws-stundenplan"
```

Das ist die einzige Pflichtänderung. Die Kurse sind schon eingetragen.

`base_url` wird nur für die Links auf der Übersichtsseite gebraucht. Die
Termin-IDs im Kalender hängen bewusst **nicht** daran – du kannst das Repo
später also umbenennen, ohne dass Termine doppelt auftauchen.

### 4. Telegram einrichten

1. In Telegram **@BotFather** anschreiben → `/newbot` → Namen vergeben.
   Du bekommst einen Token wie `123456789:AAF-xyz...`
2. Deinen neuen Bot anschreiben (irgendwas, z. B. „hallo") – sonst darf
   er dir nichts schicken.
3. Deine Chat-ID holen: **@userinfobot** anschreiben, der nennt sie dir.
4. Im Repo: **Settings → Secrets and variables → Actions → New repository secret**
   - `TELEGRAM_BOT_TOKEN` = der Token
   - `TELEGRAM_CHAT_ID` = deine Chat-ID

Ohne diese Secrets läuft alles trotzdem – die Meldung landet dann nur im
Actions-Log.

### 5. Ersten Lauf starten

Im Repo: **Actions → „Stundenplan aktualisieren" → Run workflow**

Danach sind die `.ics`-Dateien unter `docs/` auf dem aktuellen Stand. Der
Lauf bricht übrigens ab, wenn die THWS-Seite plötzlich nur noch halb so
viele Termine liefert – lieber keine Aktualisierung als ein leergeräumter
Kalender.

### 6. In iCloud abonnieren

Mach das **auf iCloud.com**, nicht direkt am iPhone – nur dann synct das
Abo auf alle deine Geräte und Apple aktualisiert es serverseitig.

1. [icloud.com/calendar](https://www.icloud.com/calendar) öffnen
2. Unten links bei **„Andere Kalender"** auf **+**
3. **Kalenderabonnement hinzufügen**
4. URL einfügen:
   `https://DEIN-NAME.github.io/thws-stundenplan/meine-kurse.ics`
5. Farbe vergeben, fertig. Für die Extras dasselbe mit `fiw-extras.ics`.

Wenn du die Extras nicht willst: einfach nicht abonnieren, oder später den
Haken in der Kalender-App entfernen.

---

## Anpassen

**Kurs hinzufügen oder rauswerfen** – in `config.toml` unter `match` einen
Textbaustein ergänzen oder löschen. Es reicht ein Teil des Titels:

```toml
match = [
  "Tools für Business Software",
  "ABAP/4",
  "Statistik",          # neu
]
```

**Weiteren Plan einlesen** – neuen `[[sources]]`-Block anlegen. Die `id`
muss eindeutig sein.

**Nächstes Semester** – in `config.toml` die URLs auf die neuen Pläne
ändern (`..._2027ss.html`). Alte Termine verschwinden dann automatisch
aus dem Kalender.

**Erinnerung ändern** – `alarm_minutes` pro Kalender. `0` = keine.

---

## Wie Änderungen erkannt werden

Jeder Termin bekommt einen Fingerabdruck (SHA-1 über Datum, Zeit, Titel,
Dozent, Raum, Anmerkungen). Der Stand des letzten Laufs liegt in
`state.json`. Weicht ein Fingerabdruck ab, ist der Termin geändert; fehlt
ein Eintrag, ist er neu bzw. entfallen.

Zwei Vorteile davon:

- Der Kalender-Eintrag behält seine **UID** und wird aktualisiert statt
  doppelt angelegt. Das `SEQUENCE`-Feld wird hochgezählt, damit Apple die
  Änderung auch wirklich übernimmt.
- Läufe ohne Änderung erzeugen **byte-identische Dateien** und damit keinen
  Commit. Jeder Commit in der Historie steht also für eine echte Änderung –
  die **Git-Historie ist dein Änderungsprotokoll**, und du kannst jederzeit
  nachsehen, wann ein Raum gewechselt hat.

## Terminkonflikte

Kalender mit `check_conflicts = true` werden auf zeitliche Überschneidungen
geprüft. Treffer landen als Warnung oben auf der Übersichtsseite.

## Wenn mal nichts passiert

- **Actions laufen nicht mehr:** GitHub pausiert `schedule`-Workflows in
  Repos, in denen 60 Tage nichts passiert ist. Ein Commit oder ein
  manueller Lauf weckt sie wieder.
- **Kalender aktualisiert nicht:** In der Kalender-App unter
  Einstellungen → Accounts → Abonnements das Aktualisierungsintervall
  prüfen. Apple hält sich nur ungefähr an `REFRESH-INTERVAL`.
- **Plan wurde umbenannt:** Wenn die THWS die HTML-Datei umbenennt,
  schlägt der Lauf fehl und du bekommst eine Mail von GitHub. Dann in
  `config.toml` die URL korrigieren.
- **Push schlägt fehl:** Unter *Settings → Actions → General →
  Workflow permissions* muss „Read and write permissions" stehen.
