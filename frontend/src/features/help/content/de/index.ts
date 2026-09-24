/**
 * German help content organized by Diátaxis category.
 * Each entry has a slug (URL path), title, category, and markdown body.
 */

export interface HelpArticle {
  slug: string
  title: string
  category: 'tutorial' | 'how-to' | 'reference' | 'explanation'
  body: string
  /** Routes where this article is contextually relevant. */
  routes?: string[]
}

export const articles: HelpArticle[] = [
  // --- Tutorials (learning-oriented) ---
  {
    slug: 'erste-schritte',
    title: 'Erste Schritte',
    category: 'tutorial',
    routes: ['/'],
    body: `
## Willkommen bei Capado

Diese Anleitung führt Sie durch die ersten Schritte nach der Einrichtung.

### 1. Skills anlegen

Bevor Sie mit der Planung beginnen können, benötigen Sie:

- **Skills** und **Attribute** (z.B. "Montage" mit Attributen "Typ Alpha", "Typ Beta")
- **Personelle Ressourcen** mit Abteilung und Verfügbarkeit
- **Infrastruktur-Ressourcen** (Hallen, Arbeitsplätze) mit Standort

### 2. Erstes Projekt erstellen

Navigieren Sie zu *Projekte* und klicken Sie auf "Neues Projekt". Geben Sie Name und Zeitraum an.

### 3. Arbeitspakete hinzufügen

Öffnen Sie das Projekt und erstellen Sie Arbeitspakete mit Start- und Enddatum.

### 4. Ressourcen zuweisen

Unter *Planung* können Sie Ressourcen per Drag & Drop oder über das Formular Arbeitspaketen zuweisen.

### 5. Konflikte prüfen

Das System erkennt automatisch Überlastungen. Prüfen Sie die *Planung*-Seite (Tab „Übersicht") für Details.
    `.trim(),
  },

  // --- How-To Guides (goal-oriented) ---
  {
    slug: 'konflikt-loesen',
    title: 'Einen Konflikt auflösen',
    category: 'how-to',
    routes: ['/planning'],
    body: `
## Einen Konflikt auflösen

### Voraussetzung

Sie haben einen aktiven Konflikt auf der Planungsseite (Tab „Übersicht") identifiziert.

### Schritte

1. Öffnen Sie die **Planung**-Seite (Tab „Übersicht")
2. Klicken Sie auf den betroffenen Konflikt
3. Wählen Sie eine Auflösungsaktion:
   - **Zuweisung reduzieren** — Senken Sie den Zuweisungsprozentsatz
   - **Zeitraum verschieben** — Verschieben Sie die Zuweisung auf einen anderen Zeitraum
   - **Zuweisung entfernen** — Löschen Sie die konfliktverursachende Zuweisung
   - **Ressource tauschen** — Weisen Sie eine andere Ressource zu
4. Der Konflikt verschwindet automatisch nach der Änderung

### Hinweis

Konflikte werden in Echtzeit erkannt. Nach jeder Änderung an Zuweisungen wird die Konfliktliste aktualisiert.
    `.trim(),
  },
  {
    slug: 'benutzer-anlegen',
    title: 'Einen neuen Benutzer anlegen',
    category: 'how-to',
    routes: ['/admin/users'],
    body: `
## Einen neuen Benutzer anlegen

### Voraussetzung

Sie sind als Administrator angemeldet.

### Schritte

1. Navigieren Sie zu **Benutzerverwaltung** (nur für Admins sichtbar)
2. Klicken Sie auf "Benutzer anlegen"
3. Füllen Sie die Pflichtfelder aus:
   - Name, E-Mail, Passwort
   - Rolle: Admin, Editor oder Viewer
4. Bei der Rolle "Editor" — wählen Sie die Berechtigungsbereiche:
   - **Abteilungen**: Welche Abteilungen darf der Benutzer bearbeiten?
   - **Standorte**: Welche Infrastruktur-Standorte?
   - **Projekte**: Welche Projekte?
5. Klicken Sie auf "Speichern"

Der neue Benutzer muss beim ersten Login sein Passwort ändern.
    `.trim(),
  },
  {
    slug: 'projekt-anlegen',
    title: 'Ein neues Projekt anlegen',
    category: 'how-to',
    routes: ['/projects'],
    body: `
## Ein neues Projekt anlegen

### Schritte

1. Navigieren Sie zu **Projekte**
2. Klicken Sie auf "Neues Projekt"
3. Geben Sie ein:
   - **Name**: Projektbezeichnung
   - **Startdatum** und **Enddatum**
4. Klicken Sie auf "Speichern"

### Hinweis für Editoren

Als Editor können Sie nur Projekte erstellen und bearbeiten, die in Ihrem konfigurierten Projektbereich liegen.
    `.trim(),
  },

  // --- Reference (information-oriented) ---
  {
    slug: 'rollen-und-berechtigungen',
    title: 'Rollen und Berechtigungen',
    category: 'reference',
    routes: ['/admin/users', '/settings'],
    body: `
## Rollen und Berechtigungen

### Rollenübersicht

| Rolle | Lesen | Schreiben | Benutzerverwaltung |
|-------|-------|-----------|-------------------|
| **Admin** | Alles | Alles | ✅ |
| **Editor** | Alles | Nur im eigenen Bereich | ❌ |
| **Viewer** | Alles | Nichts | ❌ |

### Editor-Bereiche (Scopes)

Editoren können nur Entitäten bearbeiten, die in ihrem konfigurierten Bereich liegen:

| Bereich | Erlaubt Bearbeitung von |
|---------|------------------------|
| Abteilungen | Personelle Ressourcen, Zuweisungen, Qualifikationsmatrix |
| Standorte | Infrastruktur-Ressourcen, Infrastruktur-Zuweisungen |
| Projekte | Projekte, Arbeitspakete |

### Stammdaten

Den **globalen Katalog** — Skills, ihre Attribute und die Arbeitspaket-Vorlagen — verwalten ausschließlich **Administratoren**. Abteilungs- und Standortleiter *weisen* Skills den Personen ihres Bereichs zu, aber sie legen keine neuen an und benennen keine um.

Der Grund liegt nicht am Löschen, das ohnehin abgesichert ist, sondern am **Umbenennen**. Anforderungen verweisen über eine interne Kennung auf den Skill, nie über den Namen — technisch bricht eine Umbenennung also nichts. Sie ändert aber, was jede bereits bestehende Anforderung *bedeutet*: wird „Schweißen" zu „Schweißen G3", verlangen alle Arbeitspakete, die vorher „Schweißen" forderten, ab sofort G3, und niemand hat geprüft, ob die zugewiesenen Personen das haben. Die Qualifikationsprüfung meldet weiterhin alles in Ordnung, weil Kennung und Stufen unverändert sind.

Kein Fehler, kein Konflikt — nur ein Plan, der etwas behauptet, was nie geprüft wurde. Eine solche Umdeutung gilt für alle Abteilungen gleichzeitig und ist deshalb keine Entscheidung, die eine auf ihren Bereich beschränkte Rolle treffen kann.

Nebenwirkung, die aus demselben Grund Administratoren vorbehalten bleibt: der Skill-Import löst über den **Namen** auf. Nach einer Umbenennung finden gespeicherte Importdateien mit dem alten Namen ihren Skill nicht mehr.
    `.trim(),
  },
  {
    slug: 'tastenkuerzel',
    title: 'Tastenkürzel',
    category: 'reference',
    body: `
## Tastenkürzel

| Aktion | Tastenkürzel |
|--------|-------------|
| Hilfe öffnen und schließen | \`Ctrl+/\` / \`⌘+/\` |
| Inline-Bearbeitung abbrechen | \`Escape\` |

Das ist die vollständige Liste. Es gibt bewusst keine Tastenkürzel zum Speichern: Änderungen werden über die Schaltflächen der jeweiligen Ansicht übernommen. \`Escape\` wirkt nur in Feldern, die direkt in einer Liste bearbeitet werden (etwa Skill- und Gruppennamen), nicht als allgemeines Schließen.
    `.trim(),
  },

  // --- Explanation (understanding-oriented) ---
  {
    slug: 'kapazitaetsmodell',
    title: 'Wie funktioniert die Kapazitätsberechnung?',
    category: 'explanation',
    routes: ['/people', '/infrastructure', '/planning'],
    body: `
## Wie funktioniert die Kapazitätsberechnung?

### Grundprinzip

Jede Ressource hat eine Kapazität von 100% pro Arbeitstag. Zuweisungen belegen einen prozentualen Anteil dieser Kapazität. Die Auslastung ergibt sich aus der Summe aller Zuweisungen und Abwesenheiten:

\`\`\`
Auslastung = Summe(Zuweisungen %) + Summe(Abwesenheiten %)
\`\`\`

### Farbcodierung

- 🟢 **Grün** (< 80%): Ressource hat freie Kapazität
- 🟡 **Gelb** (80–100%): Ressource ist gut ausgelastet
- 🔴 **Rot** (> 100%): Überlastung — ein Konflikt wird erzeugt

### Infrastruktur

Infrastruktur-Ressourcen sind immer zu 100% exklusiv belegt. Wenn sich zwei Buchungen zeitlich überlappen, entsteht ein Konflikt.

### Arbeitszeitmodell

Die Kapazität eines Tages ergibt sich aus drei Schichten, die aufeinander aufbauen:

1. **Wochenprofil** — legt je Wochentag fest, wie viele Minuten gearbeitet wird. Ein Profil kann einer Person direkt oder ihrer Gruppe zugewiesen werden; ohne Zuweisung gilt das Standardprofil. **Teilzeit gehört hierher**, nicht in eine Abwesenheit: nur ein Profil kann „Montag bis Donnerstag voll, Freitag frei" ausdrücken.
2. **Feiertage und Ausnahmen** — überschreiben das Profil für einzelne Tage je Standort. Möglich ist 0 Minuten (Feiertag, Werksferien, Brückentag), weniger als das Profil (halber Tag) und mehr als 0 an einem normalerweise freien Tag (angesetzter Arbeitssamstag).
3. **Abwesenheiten** — reduzieren die verbleibende Verfügbarkeit anteilig über einen Zeitraum.

Was übrig bleibt, ist die verfügbare Zeit. Der Bedarf kommt aus den Zuweisungen: \`allocation_percent\` ist der Anteil eines Normaltags von acht Stunden. An Tagen ohne Kapazität entsteht kein Bedarf und damit auch kein Konflikt — eine Zuweisung über ein Wochenende hinweg verbraucht dort nichts.

> **Teilzeit nicht als Abwesenheit anlegen.** Frühere Versionen kannten kein Wochenprofil und behalfen sich so. Wer beides einträgt, zieht die Reduzierung doppelt ab: einmal über den kürzeren Tag im Profil, einmal über die Abwesenheit.

    `.trim(),
  },
  {
    slug: 'konflikterkennung',
    title: 'Wie funktioniert die Konflikterkennung?',
    category: 'explanation',
    routes: ['/planning'],
    body: `
## Wie funktioniert die Konflikterkennung?

### Automatische Erkennung

Konflikte werden automatisch erkannt, sobald eine Zuweisung erstellt oder geändert wird. Es gibt keine manuelle Prüfung nötig.

### Konflikttypen

1. **Überlastung (Personal)**: Die Summe aller Zuweisungen und Abwesenheiten an einem Tag übersteigt 100%.

2. **Doppelbelegung (Infrastruktur)**: Zwei Zuweisungen für dieselbe Ressource überlappen sich zeitlich.

### Zusammenfassung über Wochenenden

Konflikte, die über ein Wochenende hinweg dieselbe Ursache haben, werden zu einem einzigen Konflikt zusammengefasst.

### Schweregrade

| Schweregrad | Auslastung | Bedeutung |
|-------------|-----------|-----------|
| Niedrig | ≤ 125% | Leichte Überlastung |
| Mittel | 125–150% | Deutliche Überlastung |
| Hoch | > 150% | Kritische Überlastung |
    `.trim(),
  },
  {
    slug: 'skill-abweichungen',
    title: 'Skill-Abweichungen erkennen und lösen',
    category: 'explanation',
    routes: ['/planning'],
    body: `
## Skill-Abweichungen erkennen und lösen

### Was ist eine Skill-Abweichung?

Eine Skill-Abweichung wird erkannt, wenn eine zugewiesene Ressource keinen der vom Arbeitspaket geforderten Skills besitzt.

**Beispiel**: Ein Arbeitspaket erfordert „Montage" und „Schweißen". Eine Ressource die weder Montage- noch Schweißkenntnisse hat wird als Skill-Abweichung markiert. Eine Ressource mit Montagekenntnissen ist dagegen korrekt zugeordnet — sie muss nicht alle Skills besitzen.

### Wie eine Anforderung gedeckt wird

Eine Anforderung wird auf eine von **zwei Arten** gezählt, und der Unterschied ist erheblich:

**Aufwand (FTE)** — die Auslastungen summieren sich zum Vollzeitäquivalent:
- Anforderung: 2 Elektriker
- 4 Elektriker zu je 50 % = 2,0 FTE → gedeckt
- 1 Elektriker zu 100 % = 1,0 FTE → Lücke von 1,0

**Kopfzahl** — jede Person zählt einmal, und nur wenn ihre Auslastung die hinterlegte Mindestauslastung erreicht:
- Anforderung: 2 Elektriker, Mindestauslastung 50 %
- 4 Elektriker zu je 25 % → **nichts gedeckt**, keiner erreicht die Mindestauslastung
- 2 Elektriker zu je 50 % → gedeckt

Die Stolperfalle steckt in der Kopfzahl: Wer eine Aufgabe auf viele Personen mit kleinen Anteilen verteilt, deckt sie nach dieser Zählweise nicht — auch wenn die Summe der Anteile ausreicht. Braucht die Aufgabe zwei Personen gleichzeitig vor Ort, ist das gewollt; geht es nur um Arbeitsstunden, wählen Sie Aufwand.

### Darstellung auf der Planungsseite

Skill-Abweichungen erscheinen in der Übersicht neben Kapazitätskonflikten. Beide werden als aufklappbare Karten dargestellt:

- **Oranges Badge „Skill"** kennzeichnet Skill-Probleme
- **Rotes Badge „Kapazität"** kennzeichnet Überlastungen
- Beide Kartentypen bieten Auflösungsaktionen (Ressource tauschen, Zeitraum verschieben, Zuweisung entfernen)

### Vorgeschlagene Alternativen

Beim Aufklappen einer Skill-Karte werden Ressourcen vorgeschlagen die:
1. Die geforderten Skills des Arbeitspakets besitzen
2. Im Zeitraum Kapazität haben

Über den Anwenden-Button kann direkt getauscht werden.
    `.trim(),
  },

  // --- Additional How-To Guides ---
  {
    slug: 'ressource-anlegen',
    title: 'Eine Ressource anlegen',
    category: 'how-to',
    routes: ['/people', '/infrastructure'],
    body: `
## Eine Ressource anlegen

### Personelle Ressource

1. Navigieren Sie zu **Personen**
2. Wählen Sie den Tab "Mitarbeiter"
3. Klicken Sie auf "Neue Ressource"
4. Füllen Sie aus:
   - **Name**: Vor- und Nachname
   - **Gruppe**: Wählen Sie die Gruppe aus dem Dropdown
5. Klicken Sie auf "Speichern"

### Infrastruktur-Ressource

1. Navigieren Sie zu **Infrastruktur**
2. Wählen Sie den Tab "Ressourcen"
3. Klicken Sie auf "Neue Ressource"
4. Füllen Sie aus:
   - **Name**: Bezeichnung (z.B. "Arbeitsplatz 3")
   - **Gruppe**: Wählen Sie die Gruppe aus dem Dropdown
5. Klicken Sie auf "Speichern"

### Skills zuweisen

Nach dem Anlegen einer Ressource können Sie Skills über das Zertifikat-Icon oder den Skills-Tab in der Verwaltung zuweisen.
    `.trim(),
  },
  {
    slug: 'zuweisung-erstellen',
    title: 'Eine Zuweisung erstellen',
    category: 'how-to',
    routes: ['/planning'],
    body: `
## Eine Zuweisung erstellen

### Voraussetzung

Sie haben mindestens ein Projekt mit Arbeitspaketen und verfügbare Ressourcen.

### Schritte

1. Navigieren Sie zu **Planung**
2. Wählen Sie den Tab "Zuweisungen"
3. Klicken Sie auf "Ressource zuweisen"
4. Wählen Sie die Ressource und den Zeitraum:
   - **Personal**: Start-/Enddatum + Zuweisungsprozent (1–100%)
   - **Infrastruktur**: Start-/Endzeitpunkt (minutengenau)
5. Klicken Sie auf "Speichern"

### Konflikterkennung

Nach dem Speichern prüft das System automatisch auf Konflikte. Wenn die Ressource im gewählten Zeitraum überlastet ist, wird ein Konflikt erzeugt und auf der Planungsseite (Tab „Übersicht") angezeigt.

### Tipps

- Nutzen Sie die **Vorschläge**-Funktion, um verfügbare Ressourcen für einen Zeitraum zu finden
- Im **Gantt** (eigene Seite) sehen Sie auf einen Blick, welche Ressourcen frei sind
- Die **Offene Anforderungen**-Anzeige oben im Zuweisungen-Tab zeigt Arbeitspakete die noch qualifizierte Ressourcen benötigen
    `.trim(),
  },
  {
    slug: 'zuweisungen-import-export',
    title: 'Zuweisungen importieren und exportieren',
    category: 'how-to',
    routes: ['/planning'],
    body: `
## Zuweisungen importieren und exportieren

Zuweisungen können per Excel oder CSV in großer Menge angelegt und heruntergeladen werden.

### Wo finde ich das?

1. Navigieren Sie zu **Planung**
2. Wählen Sie den Tab "Verwaltung"
3. Im Abschnitt "Import / Export" finden Sie die Buttons zum Hoch- und Herunterladen

### Export

Klicken Sie auf das Download-Symbol und wählen Sie das Format (Excel oder CSV). Die Datei enthält alle personellen und infrastrukturellen Zuweisungen.

### Import

1. Klicken Sie auf das Upload-Symbol und wählen Sie Ihre Datei
2. Nach dem Import zeigt eine Benachrichtigung, wie viele Zuweisungen angelegt, übersprungen oder fehlerhaft waren

### Dateiformat

CSV-Format: **Projekt; Arbeitspaket; Ressource; Start; Ende; Auslastung**

- Die Spalte **Arbeitspaket** ist optional. Fehlt sie, wird das Arbeitspaket über die Datumsüberlappung im Projekt ermittelt.
- **Ressourcen** und **Projekte** müssen bereits existieren — sie werden über den Namen aufgelöst.
- Datumsangaben im ISO-Format (JJJJ-MM-TT).
- Doppelte Zuweisungen (gleiche Ressource + Arbeitspaket) werden übersprungen.

Importdateien dürfen höchstens 20 MiB groß sein und einschließlich Kopfzeile höchstens 10.000 Zeilen enthalten. Größere Importe werden vollständig abgelehnt.
    `.trim(),
  },
  {
    slug: 'skills-verwalten',
    title: 'Skills und Attribute verwalten',
    category: 'how-to',
    routes: ['/people', '/infrastructure'],
    body: `
## Skills und Attribute verwalten

Skills und ihre Attribute sind global — einmal angelegt, stehen sie für Personal und Infrastruktur zur Verfügung.

### Skill anlegen

1. Navigieren Sie zu **Personen** oder **Infrastruktur**
2. Wählen Sie den Tab "Administration"
3. Scrollen Sie zum Abschnitt "Skills"
4. Klicken Sie auf "Skill hinzufügen"
5. Geben Sie den Skill-Namen ein (z.B. "Montage", "Schweißen", "Kran")
6. Drücken Sie Enter oder klicken Sie auf das Häkchen

### Attribute hinzufügen

1. Klicken Sie auf einen Skill um ihn aufzuklappen
2. Klicken Sie auf "Attribut hinzufügen"
3. Geben Sie den Attribut-Namen ein (z.B. "Typ Alpha", "Stahl", "50t")
4. Drücken Sie Enter oder klicken Sie auf das Häkchen

### Bearbeiten oder Löschen

- Klicken Sie auf das Stift-Symbol zum Umbenennen
- Klicken Sie auf das Papierkorb-Symbol zum Löschen (nur möglich wenn nicht zugewiesen)

### Import/Export

Nutzen Sie die Import/Export-Icons im Header für die Massenverwaltung per Excel oder CSV.

**Drei Exportformate, und nur zwei davon lassen sich wieder importieren:**

| Format | Zweck | Wieder importierbar |
|--------|-------|---------------------|
| Excel — Skill-Matrix | Bericht zum Ansehen und Ausfüllen auf Papier | **nein** |
| Excel — flach | Bearbeiten in Excel **und** Rückweg | ja |
| CSV | dasselbe als CSV | ja |

Die Skill-Matrix hat ihre Kopfzeile über zwei Zeilen und Trennzeilen zwischen den Gruppen — der Import kann sie nicht lesen. Laden Sie sie trotzdem hoch, sagt Capado es und nennt den flachen Export als Ausweg.

**Dateiformat des flachen Exports:** fünf Spalten — \`Name\`, \`Group\`, \`Skill\`, \`Attribute\`, \`Site\`. Alles außer Name und Group ist optional. **Eine unbekannte Betriebsstätte wird abgelehnt, nicht angelegt** — anders als bei Skills, denn eine Betriebsstätte besitzt den Feiertagskalender, und ein Tippfehler würde ein Werk ohne Feiertage erzeugen. Legen Sie sie zuerst unter Arbeitszeit an. Fehlt die Spalte ganz, bleibt die Zuordnung unverändert; ist die Zelle leer, wird sie **entfernt**. Die Kopfzeile muss mit \`Name\` und \`Group\` **in dieser Reihenfolge** beginnen; die Spalten werden nach Position gelesen, deshalb wird eine vertauschte Kopfzeile abgelehnt statt geraten. Groß-/Kleinschreibung ist gleichgültig, und \`Gruppe\` wird ebenfalls akzeptiert.

Hochgeladen werden nur \`.xlsx\` und \`.csv\`, mit höchstens 20 MiB und 10.000 Zeilen einschließlich Kopfzeile. Gültige Zeilen werden gemeinsam gespeichert; fehlerhafte Zeilen werden übersprungen und im Ergebnisprotokoll aufgeführt. Eine zu große Datei wird vor dem Import vollständig abgelehnt.
    `.trim(),
  },
  {
    slug: 'einstellungen-anpassen',
    title: 'Einstellungen anpassen',
    category: 'how-to',
    routes: ['/settings'],
    body: `
## Einstellungen anpassen

Unter Einstellungen können Sie das Erscheinungsbild der Anwendung konfigurieren.

### Verfügbare Einstellungen

| Einstellung | Beschreibung |
|-------------|-------------|
| Firmenname | Wird im Header und in der Navigation angezeigt |
| Untertitel | Optionaler Zusatztext unter dem Firmennamen |
| Logo-URL | URL zu einem Firmenlogo (wird im Header angezeigt) |
| Primärfarbe | Hauptfarbe der Benutzeroberfläche (Hex-Wert) |

Daneben stehen auf dieser Seite die betrieblichen Einstellungen: Aufbewahrungsfristen für Audit-Einträge und Planstände, die Planungssperre, der Wartungslauf und die Mail-Konfiguration für den Digest.

### Wo was gespeichert wird

Diese Seite ist **Administratoren vorbehalten**, und alles darauf wird **auf dem Server gespeichert und gilt für die ganze Organisation** — ändert ein Administrator den Firmennamen, sehen ihn alle.

**Farbschema und Sprache gehören nicht hierher.** Beide sind persönliche Einstellungen, werden nur im Browser gespeichert und über die Symbole in der Kopfzeile umgeschaltet, nicht über diese Seite. Jeder darf sie für sich ändern, auch ohne Administratorrechte.
    `.trim(),
  },

  // --- Additional Reference ---
  {
    slug: 'dashboard-uebersicht',
    title: 'Dashboard',
    category: 'reference',
    routes: ['/'],
    body: `
## Dashboard

Das Dashboard zeigt eine Übersicht der aktuellen Auslastung und offenen Konflikte.

### Inhalte

- **Auslastungsübersicht**: Aggregierte Kapazitätsauslastung aller Ressourcen
- **Projektliste**: Aktive Projekte mit Konfliktanzahl
- **Schnellzugriff**: Links zu den wichtigsten Bereichen

### Filter

Sie können die Ansicht filtern nach:
- Zeitraum (Start-/Enddatum)
- Abteilung
- Standort
- Projekt(e)
    `.trim(),
  },
  {
    slug: 'gantt-ansicht',
    title: 'Gantt-Ansicht',
    category: 'reference',
    routes: ['/gantt'],
    body: `
## Gantt-Ansicht

Die Gantt-Ansicht ist als eigene Seite über **Gantt** in der Navigation erreichbar und zeigt Zuweisungen auf einer Zeitachse. Drei Perspektiven, und sie beantworten verschiedene Fragen.

### Projekt — wo sind die Lücken?

Diese Perspektive zeigt **alle Projekte auf einer gemeinsamen Zeitachse**, je eine Zeile, mit einem grauen Balken über die Projektlaufzeit. Es gibt keine Einzelauswahl mehr: Überschneidungen und Leerzeiten erkennt man nur, wenn alles gleichzeitig sichtbar ist.

Der Pfeil links klappt ein Projekt auf und zeigt **seine Arbeitspakete** darunter. Bewusst nicht alles von Anfang an: drei Projekte mit je acht Paketen wären 24 Zeilen, bevor eine Frage gestellt ist. Die Arbeitspakete werden erst beim Aufklappen geladen und danach behalten — erneutes Aufklappen ist ohne Wartezeit.

Der Projektbalken ist **grau**, ein Arbeitspaket **blau**. Der Unterschied ist Absicht: ein Projekt ist ein Behälter und belegt selbst keine Ressource.

Die Reihenfolge wählen Sie über **Name**, **Start** oder **Ende**. Sortieren nach Start ist der Weg, ein Projekt zu finden, dessen Balken außerhalb des gerade sichtbaren Zeitfensters liegt.

### Personal und Infrastruktur — was steht wann auf welcher Ressource?

Hier wählen Sie eine **Gruppe** und schalten mit **Nach Projekt | Nach Ressource** um, wonach gruppiert wird.

**Nach Ressource** ist die Ansicht für die Lückensuche: eine Zeile je Ressource, darin ihre Belegung projektübergreifend und chronologisch. So sehen Sie, welche Projekte wann auf einem bestimmten Gleis oder in einer bestimmten Kabine sind — und wann es frei ist. Nach Projekt gruppiert verteilt sich dieselbe Belegung über mehrere Projektüberschriften, und eine freie Woche fällt niemandem auf.

Beide Gruppierungen zeigen dieselben Daten, nur anders gefaltet. Sie können sich nicht widersprechen.

### Darstellung

- **Balken**: eine Zuweisung bzw. ein Arbeitspaket
- **Farben**: Blau im Normalfall, **Rot bei einem Konflikt**. Arbeitspakete haben absichtlich keine eigenen Farben — Rot ist für den Konflikt reserviert, und bunte Balken würden dieses Signal überschreiben
- **Abwechselnde Zeilenhintergründe** und eine **Hervorhebung der Zeile unter dem Mauszeiger**, damit man beim Lesen nach rechts nicht in die Nachbarzeile gerät
- **Abgeschnittene Namen**: Fahren Sie über den Namen, nennt die Quickinfo ihn vollständig
- **Zeitraster**: umschaltbar zwischen Tag, Woche und Monat

### Interaktion

Anklickbar sind **nur rote Balken**; ein Klick führt zur Konfliktansicht. Balken ohne Konflikt reagieren nicht auf Klicks — die Einzelheiten einer Zuweisung bearbeiten Sie auf der Planungsseite, nicht im Diagramm.
    `.trim(),
  },
  {
    slug: 'projektuebersicht',
    title: 'Projektübersicht',
    category: 'reference',
    routes: ['/'],
    body: `
## Projektübersicht

Die Projektübersicht ist Teil des **Dashboards** und zeigt KPIs für alle Projekte auf einen Blick.

### Angezeigte Kennzahlen

| KPI | Beschreibung |
|-----|-------------|
| Fortschritt | Zeitlicher Fortschritt basierend auf Start-/Enddatum |
| Aktive Arbeitspakete | Anzahl der aktuell laufenden Arbeitspakete |
| Nächste Deadline | Frühestes Enddatum eines offenen Arbeitspakets |
| Offene Konflikte | Anzahl ungelöster Konflikte im Projekt |
| Ø Auslastung | Durchschnittliche Ressourcenauslastung |

### Filter

- Nach Projekt-IDs filterbar
- Sortierbar nach Startdatum und Name
    `.trim(),
  },
  {
    slug: 'skill-zuweisungen',
    title: 'Skill-Zuweisungen',
    category: 'reference',
    routes: ['/people', '/infrastructure'],
    body: `
## Skill-Zuweisungen

Skills verknüpfen Ressourcen mit Fähigkeiten und deren spezifischen Attributen.

### Aufbau

Jede Zuweisung besteht aus:
- **Ressource**: Die Person oder Infrastruktur
- **Skill**: Die Fähigkeit (z.B. "Montage")
- **Attribut**: Die spezifische Ausprägung (z.B. "Typ Alpha")

### Einzelverwaltung

1. Öffnen Sie die Personen-Seite
2. Klicken Sie auf das Zertifikat-Icon bei einer Person
3. Aktivieren/deaktivieren Sie Skill-Attribute im Drawer

### Massenverwaltung

Nutzen Sie den Abschnitt "Import/Export" im Tab "Administration" auf der Personen- oder Infrastruktur-Seite:
- **Export**: drei Formate — Excel als Skill-Matrix (ein Bericht, **nicht** re-importierbar), Excel flach, oder CSV
- **Import**: Laden Sie eine Datei hoch um Ressourcen und Skills in einem Schritt anzulegen

Import-Format: fünf Spalten — \`Name\`, \`Group\`, \`Skill\`, \`Attribute\`, \`Site\`. Alles außer Name und Group ist optional; eine unbekannte Betriebsstätte wird abgelehnt statt angelegt. Wählen Sie "Excel — flach" oder CSV, wenn Sie die Datei bearbeiten und wieder hochladen wollen; die Skill-Matrix lässt sich nicht zurücklesen.

### Verwendung

Skill-Zuweisungen werden genutzt für:
- Ressourcenvorschläge (nur qualifizierte Ressourcen werden vorgeschlagen)
- Filterung in der Planungsansicht
    `.trim(),
  },

  // --- Arbeitszeit ---
  {
    slug: 'wochenprofile',
    title: 'Wochenprofile',
    category: 'explanation',
    routes: ['/working-time'],
    body: `
## Wochenprofile

Ein Wochenprofil legt fest, wie viele **Minuten je Wochentag** gearbeitet wird. Es ist die unterste der drei Schichten, aus denen sich Kapazität ergibt.

### Zuweisung

Ein Profil kann einer Person direkt oder ihrer Gruppe zugewiesen werden. Die direkte Zuweisung hat Vorrang; fehlt sie, gilt die der Gruppe; fehlt auch die, gilt das **Standardprofil**.

Genau ein Profil trägt das Standard-Kennzeichen. Zwei Standardprofile würden die Kapazität von der Zeilenreihenfolge abhängig machen, deshalb lässt das System das nicht zu.

### Teilzeit gehört hierher

Teilzeit wird über ein eigenes Wochenprofil abgebildet, **nicht** über eine Abwesenheit. Nur ein Profil kann „Montag bis Donnerstag voll, Freitag frei" ausdrücken — eine Abwesenheit über 20 % verteilt die Reduzierung gleichmäßig über die Woche und trifft damit den falschen Tag.

Wer beides einträgt, zieht doppelt ab: einmal über den kürzeren Tag im Profil, einmal über die Abwesenheit.

### Was beim Löschen passiert

Ein Profil, das noch einer Person oder Gruppe zugewiesen ist, kann nicht gelöscht werden. Andernfalls würden diese Personen unbemerkt auf das Standardprofil rutschen und ihre Kapazität sich ändern, ohne dass jemand sie angefasst hat.

Das Standardprofil selbst ist überhaupt nicht löschbar — ohne es hätte eine Person ohne Zuweisung nirgends eine Arbeitszeit, und die Anlage würde überall null Kapazität melden.
    `.trim(),
  },
  {
    slug: 'feiertage',
    title: 'Feiertage und Kalenderausnahmen',
    category: 'explanation',
    routes: ['/working-time'],
    body: `
## Feiertage und Kalenderausnahmen

Ausnahmen überschreiben das Wochenprofil für einzelne Tage, **je Standort**. Drei Fälle sind möglich, und alle drei kommen in echten Werkskalendern vor:

- **Null Minuten** — Feiertag, Werksferien, Brückentag.
- **Weniger als im Profil** — halber Tag, wie üblicherweise am 24. und 31. Dezember.
- **Mehr als null an einem normalerweise freien Tag** — ein angesetzter Arbeitssamstag.

Deshalb ist es eine Minutenangabe und kein Ankreuzfeld: ein Häkchen könnte nur den ersten Fall abbilden.

### Warum die Feiertage von Hand gepflegt werden

Capado führt eine eigene Tabelle statt eine Feiertagsbibliothek abzufragen. Werkskalender enthalten regelmäßig arbeitsfreie Tage, die nirgends gesetzlich sind — Rosenmontag und Brückentage etwa. Eine Bibliothek hätte für diese Tage Kapazität gemeldet, die es nicht gibt.

### Auswirkung auf Konflikte

An einem Tag mit null Minuten entsteht **kein Bedarf und damit kein Konflikt**. Eine Zuweisung, die über einen Feiertag läuft, liefert dadurch stumm weniger Zeit als geplant. Das ist ein Fehlbetrag, keine Überlast, und erscheint entsprechend bei den offenen Anforderungen statt in der Konfliktliste.
    `.trim(),
  },
  {
    slug: 'standorte',
    title: 'Standorte',
    category: 'reference',
    routes: ['/working-time'],
    body: `
## Standorte

Ein Standort bündelt den Feiertagskalender. Zwei Werke mit unterschiedlichen Betriebsferien sind zwei Standorte.

| Feld | Bedeutung |
|------|-----------|
| Name | Bezeichnung des Standorts |
| Standard | Der Standort, dem Ressourcen ohne eigene Zuordnung zufallen. Genau einer trägt dieses Kennzeichen. |
| Regionscode | Nur ein Hinweis für das Feiertags-Importskript, etwa DE-BY. Wird zur Laufzeit **nie** gelesen. |
| Aktiv | Kennzeichen zum Stilllegen, statt zu löschen |

Der Regionscode ist ausdrücklich keine Automatik: die Feiertagstabelle ist die einzige Quelle der Wahrheit. Der Code hilft nur beim erstmaligen Vorbefüllen und ändert danach nichts mehr.
    `.trim(),
  },

  // --- Terminplanung ---
  {
    slug: 'abhaengigkeiten',
    title: 'Abhängigkeiten zwischen Arbeitspaketen',
    category: 'explanation',
    routes: ['/projects'],
    body: `
## Abhängigkeiten zwischen Arbeitspaketen

Es gibt **eine** Beziehungsart: **Ende–Anfang**, mit optionaler Wartezeit in Arbeitstagen. Paket B beginnt, nachdem Paket A fertig ist, zuzüglich der Wartezeit.

### Warum nur eine Art

Anfang–Anfang und Ende–Ende lassen sich durch Vertauschen des Paares ausdrücken, und Anfang–Ende meint praktisch niemand. Was eine Anlage darüber hinaus wirklich braucht, ist **Wartezeit** — Lack muss aushärten, bevor der nächste Schritt beginnen kann — und dafür genügt die Wartezeit, ohne eine zweite Beziehungsart.

Die Wartezeit zählt in **Arbeitstagen**, nicht Kalendertagen. Ein Wochenende ist keine Aushärtezeit, die jemand eingeplant hat.

### Eine Verletzung blockiert nicht

Wenn die Termine der Abhängigkeit widersprechen, ist das eine **Warnung**, kein abgelehnter Speichervorgang. Würde das System es erzwingen, müsste es die Arbeit anstelle des Planers verschieben. Ein Planer, der nicht eintragen kann, was er tatsächlich vorhat, kehrt zur Tabellenkalkulation zurück — und damit wäre nichts gewonnen.

### Was doch abgelehnt wird

**Zyklen.** Wenn A auf B wartet und B auf A, gibt es keine gültige Lesart, und jeder Auswerter müsste sich dagegen wehren. Solche Verknüpfungen werden schon beim Speichern zurückgewiesen.
    `.trim(),
  },
  {
    slug: 'kritischer-pfad',
    title: 'Puffer und kritischer Pfad',
    category: 'explanation',
    routes: ['/projects', '/project-overview'],
    body: `
## Puffer und kritischer Pfad

Zwei Durchläufe über die Abhängigkeiten: vorwärts der früheste Anfang und Ende jedes Pakets, rückwärts der spätestmögliche. Die Lücke dazwischen ist der **Puffer** — wie lange ein Paket rutschen darf, bevor das Projekt rutscht.

**Puffer null bedeutet: auf dem kritischen Pfad.** Jede Verzögerung dieses Pakets verzögert das ganze Projekt.

### Drei Dinge, die die Zahlen erklären

**Die Dauer kommt aus der Durchlaufzeit, wenn es eine gibt** — sonst aus den eingetragenen Terminen. Ein Paket mit „34 Arbeitstage" beschreibt, wie lange die Arbeit dauert; ein Paket mit nur Anfang und Ende beschreibt, wann sie eingeplant wurde, und das kann länger sein als nötig. Der Vorrang der Durchlaufzeit lässt die Rechnung den Prozess abbilden statt den Kalender, den jemand getippt hat.

**Der Rückwärtslauf beginnt am Kundentermin, wenn einer zugesagt ist** — sonst am geplanten Projektende. Ein kritischer Pfad, gemessen an einem geplanten Ende, das den Kundentermin schon verfehlt, würde bequemen Puffer auf einem Projekt melden, das bereits zu spät ist.

**Alles rechnet in Arbeitstagen.** Puffer zwei heißt zwei Arbeitstage, nicht zwei Kalendertage, die beide ein Wochenende sein könnten.
    `.trim(),
  },

  // --- Qualifikationen ---
  {
    slug: 'qualifikationen',
    title: 'Qualifikationen und ihre Gültigkeit',
    category: 'explanation',
    routes: ['/people'],
    body: `
## Qualifikationen und ihre Gültigkeit

Eine Qualifikation erfüllt eine Anforderung nur, wenn drei Bedingungen zutreffen. Interessant ist jeweils, was die Bedingung **ablehnt**.

### Die Gültigkeit wird gegen die Arbeit geprüft, nicht gegen heute

Ein Zertifikat, das im März abläuft, deckt keine Arbeit ab, die für April geplant ist. Die Frage „ist es jetzt gültig" würde hier Ja sagen und wäre falsch.

Das Gültigkeitsfenster muss die **gesamte Zuweisung** umschließen. Läuft ein Nachweis mitten in der Arbeit ab, gilt die Anforderung für diese Arbeit als nicht erfüllt — nicht zur Hälfte erfüllt. Genau das ist der Sinn eines Ablaufdatums.

### Eine nicht erfasste Stufe erfüllt keine Mindeststufe

Stufen gehen von 1 bis 5. Ist keine Stufe eingetragen, heißt das: **niemand hat sie beurteilt** — und das ist kein Nachweis, gut genug zu sein. Eine leere Stufe zugunsten der Person zu lesen wäre die falsche Richtung für eine Prüfung, die unqualifizierte Personen von einer Aufgabe fernhalten soll.

### Keine Anforderung, kein Problem

Eine Anforderung ohne Mindeststufe wird von jeder gehaltenen Stufe erfüllt, auch von keiner. Sie hat nicht danach gefragt.
    `.trim(),
  },
  {
    slug: 'handlungsbedarf',
    title: 'Handlungsbedarf',
    category: 'explanation',
    routes: ['/'],
    body: `
## Handlungsbedarf

Eine einzige Liste dessen, was Aufmerksamkeit braucht: ablaufende Qualifikationen, Kundentermine, die nicht mehr passen, verletzte Abhängigkeiten, Anforderungen, die niemand deckt.

Capado hat diese Zustände schon immer erkannt. Es konnte sie nur niemandem sagen — jede Prüfung lag dort, wo sie berechnet wurde, und alle zu sehen hieß vier Ansichten zu öffnen und zu wissen, wo man hinsehen muss.

### Der schwierige Teil ist das Weglassen

Ein Plan beliebiger Größe erzeugt hunderte wahrer Aussagen, und eine Liste aus hunderten wahren Aussagen wird binnen einer Woche ignoriert. Dann ist der Mechanismus schlechter als keiner, weil alle glauben, gewarnt zu werden. Drei Begrenzungen:

**Horizont.** Jeder Befund hat ein Fälligkeitsdatum; was dahinter liegt, entfällt. Standardmäßig reichen 90 Tage. Eine Qualifikation, die 2029 abläuft, ist wahr und nutzlos.

**Dringlichkeit aus der Nähe, nicht aus der Art.** Innerhalb von 14 Tagen ist ein Befund kritisch — zu knapp, um ihn durch Umplanen zu lösen. Bis 45 Tage ist er eine Warnung, danach ein Hinweis. Ein Ablauf nächste Woche steht damit über einer Abhängigkeitsverletzung nächstes Jahr, weil das die Reihenfolge ist, in der man tatsächlich arbeitet.

**Bereits Fälliges ist immer kritisch**, egal wie lange es zurückliegt. Sonst würde ein abgelaufenes Zertifikat mit der Zeit unauffälliger — und damit genau die Befunde begraben, bei denen jemand nicht gehandelt hat.

**Ein Befund je Sache.** Eine Zeile je Person und Skill, nicht je betroffener Zuweisung: zehn Zuweisungen, blockiert von einem abgelaufenen Nachweis, sind **ein** Problem.

Die drei Zeitgrenzen sind in den Einstellungen anpassbar.
    `.trim(),
  },

  // --- Nachvollziehbarkeit ---
  {
    slug: 'planungssperre',
    title: 'Planungssperre',
    category: 'explanation',
    routes: ['/settings', '/planning'],
    body: `
## Planungssperre

Ein Plan, über den schon berichtet wurde, soll sich nicht unter dem Bericht verändern. Capado kann festhalten, wie der Plan aussah (Planstände) und wer ihn geändert hat (Protokoll) — aber keines von beidem verhindert, dass jemand stillschweigend eine Zuweisung des Vormonats verschiebt, damit die Zahlen dieses Monats aufgehen. Die Sperre ist die vorbeugende Hälfte.

### Beide Zustände zählen

Der nicht offensichtliche Teil: eine Änderung hat **zwei** Zustände, und beide werden geprüft. Würde nur geprüft, wo die Zuweisung landet, könnte jemand eine gesperrte Buchung aus dem gesperrten Zeitraum herausziehen — die Änderung läge dann vollständig im offenen Zeitraum und hätte doch gesperrte Vergangenheit umgeschrieben.

Geprüft wird daher der Zustand **vor und nach** der Änderung, und blockiert wird, wenn **einer von beiden** in die Sperre reicht.

Die Folge, offen gesagt: eine Zuweisung, die über die Sperrgrenze hinausreicht, ist **überhaupt nicht** bearbeitbar, solange die Sperre steht — auch nicht der Teil, der im offenen Zeitraum liegt. Das ist eine echte Einschränkung und kein Versehen. Nur unter dieser Lesart ist der gesperrte Zeitraum wirklich stabil.

Gesperrt wird tageweise, nie stundenweise — auch für Infrastrukturbuchungen, die sonst mit Uhrzeit rechnen.

### Wer sie umgehen darf

Administratoren, und dafür ist das Protokoll da. Die Alternative — niemand kann es, nie — macht die Korrektur eines echten Eingabefehlers unmöglich und verwandelt die Sperre von einer Absicherung in eine Falle. Sie für alle nur empfehlend zu machen wäre Dekoration.
    `.trim(),
  },
  {
    slug: 'planstaende',
    title: 'Planstände und Vergleich',
    category: 'explanation',
    routes: ['/baselines'],
    body: `
## Planstände und Vergleich

Ein Planstand hält den Plan zu einem Zeitpunkt fest. Der Nutzen liegt aber nicht im Festhalten, sondern im **Vergleich**: was hat sich seit der Freigabe geändert.

Ein Planstand allein beantwortet keine Frage, die nicht auch ein Ausdruck beantwortet. Der Vergleich zwischen dem festgehaltenen und dem aktuellen Plan beantwortet die einzige Frage, die in einer Besprechung wirklich gestellt wird.

### Aufbewahrung

Standardmäßig werden Planstände **unbegrenzt** aufbewahrt. Das ist Absicht: ein Planstand ist der Nachweis, wie zugesagt wurde, und ihn nach einer Frist automatisch zu verwerfen wäre schlimmer als ihn zu behalten. Wer eine Frist braucht, setzt sie in den Einstellungen; das Protokoll wird demgegenüber standardmäßig 24 Monate aufbewahrt.

### Kein Ersatz für die Sperre

Ein Planstand hält fest, was war. Er verhindert nicht, dass sich der laufende Plan rückwirkend ändert — dafür gibt es die Planungssperre. Die beiden ergänzen sich: der Planstand ist der Nachweis, die Sperre die Vorbeugung.
    `.trim(),
  },

  // --- Ansichten und Auswertung ---
  {
    slug: 'wochenplan',
    title: 'Wochenplan des Teams',
    category: 'explanation',
    routes: ['/planning'],
    body: `
## Wochenplan des Teams

Eine Zeile je Person, eine Spalte je Tag. Die Frage lautet: **wer macht am Dienstag was.**

Das ist absichtlich nicht das Gantt-Diagramm. Ein Gantt beantwortet, wann ein Arbeitspaket läuft, gruppiert nach Projekt und gezeichnet über eine Zeitachse. Ein Wochenplan ist eine Schichtliste. Das eine ist für einen Planer am Bildschirm, das andere für einen Ausdruck an der Wand — eines in das andere umzuformen ergäbe von beidem die schlechtere Fassung.

### Drei Regeln, und was jede ablehnt

**Ein Tag zeigt alle Zuweisungen, nicht die größte.** Wer auf zwei Arbeitspakete verteilt ist, hat zwei Einträge in dieser Zelle. Eine Schichtliste, die stillschweigend nur eine zeigt, ist schlechter als eine, die voll aussieht — die Person würde für die Hälfte ihres Tages erscheinen.

**Abwesenheit und Arbeit stehen zusammen, nicht alternativ.** Eine 50-prozentige Abwesenheit lässt einen halben Arbeitstag übrig. Die Zuweisung zu unterdrücken, weil jemand „weg ist", ist der Weg, auf dem niemand von noch geplanter Arbeit erfährt.

**Tage ohne Kalenderzeit werden gekennzeichnet, nicht leer gelassen.** Eine leere Zelle liest sich als „nichts geplant", und das ist von „die Anlage ist zu" nicht zu unterscheiden. Werksferien und ein leerer Dienstag sind zwei verschiedene Aussagen für jemanden, der die Liste liest.
    `.trim(),
  },
  {
    slug: 'kunden-und-berichte',
    title: 'Kunden und Excel-Berichte',
    category: 'explanation',
    routes: ['/projects', '/project-overview'],
    body: `
## Kunden

Ein Projekt erbt seinen Kunden aus dem Ordner, in dem es liegt. Die Regel hat drei Teile:

**Der eigene Kunde des Projekts gewinnt.** Ausdrücklich gesetzt, ist er eine Korrektur, die jemand mit Absicht vorgenommen hat. Ließe der Ordner sich darübersetzen, wäre das Feld unbrauchbar.

**Sonst gilt der Kunde des Ordners, aufwärts durch den Baum.** Ein Unterordner, der keinen Kunden nennt, gehört dem seines übergeordneten Ordners — genau das bedeutet die Verschachtelung hier: ein Auftrag zerfällt in Abschnitte, und die Abschnitte gehören demselben Kunden.

**Es wird nichts erfunden.** Ein Projekt in keinem Ordner, oder in einem Baum, in dem niemand einen Kunden nennt, hat **keinen** Kunden — keinen Platzhalter und nicht den ersten Kunden aus der Liste. Zu raten würde einen Namen auf einen Bericht schreiben, den niemand eingetragen hat.

## Excel-Berichte

**Auslastungsbericht** — Wochen quer, Personen längs. Er ruft dieselbe Berechnung auf, aus der auch die Diagramme des Dashboards stammen, damit eine Zahl in der Datei und dieselbe Zahl auf dem Bildschirm nicht auseinanderlaufen können. Eine Tabelle, die dem Dashboard widerspricht, ist schlechter als keine: irgendwer muss dann entscheiden, welche von beiden lügt.

Die Datei hat **zwei Blätter**, weil zwei verschiedene Personen sie lesen. Das breite Blatt ist zum Ansehen: eine Zeile je Person, eine Spalte je Woche. Das lange Blatt ist zum Weiterarbeiten: eine Zeile je Person und Woche, also die Form, die eine Pivot-Tabelle braucht. Ein breites Blatt lässt sich nicht pivotieren, und jemanden zu bitten, es von Hand umzubauen, ist der Weg, auf dem Zahlen abgetippt werden und dabei falsch werden.

**Projektstatusbericht** — je Projekt der Stand, mit Kunde und den Auftragsnummern von Ordner und Projekt. Beide werden gezeigt, statt dass eine stillschweigend gewinnt.

Der Auslastungsbericht ist auf 104 Wochen begrenzt. Die Grenze besteht, weil die Auslastung je Person und Woche gerechnet wird und ein unbegrenzter Zeitraum eine Anfrage minutenlang laufen ließe.
    `.trim(),
  },
  {
    slug: 'meine-planung',
    title: 'Meine Planung',
    category: 'explanation',
    routes: ['/my-plan'],
    body: `
## Was diese Seite zeigt

Ihre eigenen Zuweisungen, Abwesenheiten und Qualifikationen — und **nur** Ihre eigenen. Die Seite kennt keine Möglichkeit, die Planung einer anderen Person aufzurufen: welche Person gemeint ist, entscheidet allein die Verknüpfung Ihres Kontos, nicht ein Feld auf dieser Seite und nicht ein Wert in der Adresszeile.

Die Seite ist **nur lesend**. Änderungen nehmen die Planenden vor. Sie ändert außerdem nichts daran, wer was sehen darf: dieselben Daten waren bereits für die Planenden und Führungskräfte sichtbar. Neu ist, dass **die betroffene Person selbst** sie einsehen kann.

## „Konto noch nicht mit einer Person verknüpft"

Diese Meldung bedeutet nicht, dass für Sie nichts eingeplant ist. Sie bedeutet, dass niemand hinterlegt hat, **welche** eingeplante Person zu Ihrem Konto gehört.

Der Unterschied ist wichtig, deshalb steht hier eine eigene Meldung und keine leere Tabelle: eine leere Tabelle würde Sie zu dem Schluss verleiten, Sie seien für nichts eingeteilt — während in Wahrheit vielleicht eine volle Woche für Sie geplant ist und lediglich die Zuordnung fehlt.

Behoben wird das von einer Person mit Administrationsrechten in der **Benutzerverwaltung**: das Konto bearbeiten und unter *Verknüpfte Person* die Person auswählen. Die Zuordnung geschieht bewusst je Konto von Hand. Automatisch über den Namen oder die E-Mail-Adresse zu raten würde bei zwei Personen gleichen Namens die falsche Planung offenlegen — und ein Fehler dieser Art wäre ein Datenschutzvorfall, kein Schönheitsfehler.

## Wie die Angaben zu lesen sind

**Zuweisungen** nennen Projekt, Arbeitspaket, Zeitraum und Ihren Anteil. Ein Anteil von 50 % bedeutet die Hälfte Ihrer Arbeitszeit in diesem Zeitraum, nicht die Hälfte des Arbeitspakets.

**Abwesenheiten** tragen einen Status. *Beantragt* heißt, dass die Abwesenheit in der Planung berücksichtigt ist, aber noch nicht bestätigt wurde. Ein Antrag stellen können Sie hier nicht — die Seite zeigt den Stand, sie führt kein Genehmigungsverfahren.

**Qualifikationen** nennen Skill, Attribut, Stufe und Gültigkeit. Steht dort **nicht beurteilt**, hat niemand eine Stufe eingetragen; das ist ausdrücklich **nicht** dasselbe wie die niedrigste Stufe. **Unbefristet** heißt, dass kein Ablaufdatum hinterlegt ist — läuft eine Qualifikation dagegen ab, sollten Sie das Datum im Blick behalten, denn nach Ablauf zählt sie bei der Planung nicht mehr mit.

## Was die Seite bewusst nicht tut

Sie erzeugt **keine neue Auswertung**. Sie zeigt genau die Werte, die ohnehin schon in der Planung stehen, nur eben Ihnen.

Es gibt **keinen Kalender-Abruf** und **keine Anträge** über diese Seite. Beides ist denkbar, aber nicht gebaut — und solange es nicht gebaut ist, wird es hier auch nicht angedeutet.
    `.trim(),
  },
]
