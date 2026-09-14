# Capado

*Capacity Done.*

[English](index.md) · **Deutsch**

Kapazitätsplanung für **Personal und Betriebsmittel** in einem Modell, mit Qualifikationsabgleich.
Selbst gehostet, GPL-3.0.

---

## Was Capado löst

In einer Fertigung oder Werkstatt konkurrieren dieselben Leute und dieselben Maschinen um dieselbe
Zeit. Wer wann an welchem Auftrag arbeitet, hängt zusätzlich daran, wer es **darf** — Schweißprüfung,
Kranschein, Staplerausweis, jeweils mit Ablaufdatum.

Diese Planung lebt fast überall in einer Tabellenkalkulation. Die funktioniert, bis drei Dinge
gleichzeitig passieren: jemand überbucht eine Person, ohne es zu merken; ein Nachweis läuft mitten im
Auftrag ab; und niemand kann mehr sagen, wie der Plan letzten Monat aussah, als er berichtet wurde.

Capado ist für genau diesen Punkt gebaut. Es plant Personal **und** Betriebsmittel in einem Modell,
prüft Qualifikationen gegen den Zeitpunkt der Arbeit und meldet Überlast in dem Moment, in dem sie
entsteht.

## Für wen

Fertigungs-, Instandhaltungs- und Werkstattbetriebe im Mittelstand, die Aufträge über Wochen und
Monate planen, deren Arbeit an Qualifikationen hängt und die ihre Daten im eigenen Haus behalten
wollen oder müssen.

Ausdrücklich **keine Zeiterfassung**. Capado plant, was vorgesehen ist; es erfasst nicht, was
tatsächlich gearbeitet wurde ([ADR-009](decisions/009-no-actual-time-recording.md)) — eine bewusste
Grenze, die auch die Mitbestimmung erheblich vereinfacht.

## Was es tut

**Ein Modell für Menschen und Maschinen.** Ein Gleis, eine Lackierkabine und ein Schweißer werden
gleich eingeplant, weil sie sich in einem echten Plan gegenseitig begrenzen.

**Qualifikationen mit Gültigkeitsdatum.** Eine Anforderung wird gegen die Qualifikation geprüft, die
eine Person **am Tag der Arbeit** hat — nicht gegen die von heute. Ein Nachweis, der mitten im Auftrag
abläuft, ist ein Konflikt und keine Überraschung.

**Konflikte, sobald sie entstehen.** Überbuchung, fehlende Qualifikation und verletzte Zeitfenster
werden bei der Zuweisung erkannt und auf einer Seite gesammelt, statt bei der nächsten Übergabe
aufzufallen.

**Planstände.** Ein Planstand friert den Plan so ein, wie er berichtet wurde — „was haben wir im März
gesagt" bleibt also nach dem März beantwortbar.

**Ein Änderungsprotokoll.** Jede Schreibung wird mit wer, wann und was festgehalten, 24 Monate
aufbewahrt.

**Selbstauskunft.** Wer mit seiner eingeplanten Person verknüpft ist, liest seine eigenen Zuweisungen,
Abwesenheiten und Qualifikationen selbst — nur lesend, und ohne den Vorgesetzten fragen zu müssen.

## Wie es aussieht

Eine Demo-Instanz mit **erfundenen Daten** — Namen, Betriebe und Fahrzeugbezeichnungen haben keinen
Bezug zu einem echten Betrieb.

Das Dashboard führt mit dem Handlungsbedarf, nach Dringlichkeit sortiert, statt mit einem Startmenü.

![Capado Dashboard: Liste „Handlungsbedarf" mit Schweregrad-Zählern und relativen Fristen](assets/screenshots/dashboard-de.png)

Ein Projektbalken ist grau, weil ein Projekt ein Behälter ist und keine Ressource belegt; ein
Arbeitspaket ist blau, und rot heißt: hier ist ein Konflikt. Eine eingeklappte Projektzeile trägt die
Zahl der Konflikte, von denen sie betroffen ist.

![Capado Gantt: Projektübersicht mit grauen Projektbalken, blauen Arbeitspaketen und roten Konflikten](assets/screenshots/gantt-projects-de.png)

Menschen und Maschinen liegen in einem Modell, aber sie heißen nicht gleich: Personen sind Personen,
Infrastruktur ist Infrastruktur.

![Capado Personenliste: nach Gruppen, mit Betriebsstätte und Konfliktspalte](assets/screenshots/people-de.png)

## Was es bewusst nicht tut

Über die Grenzen klar zu sein ist Teil des Entwurfs, keine Auslassung:

- **Keine Zeiterfassung**, siehe ADR-009 oben.
- **Keine Mandantenfähigkeit.** Eine Installation dient einer Organisation
  ([ADR-003](decisions/003-single-tenant-and-sites.md)).
- **Keine automatische Planung.** Capado schlägt geeignete Ressourcen vor; entscheiden tut ein Mensch.
- **Kein Selbstzurücksetzen von Passwörtern.** Ein Administrator setzt ein neues
  ([bekannte Grenzen](reference/known-limitations.md)).

## Erste Schritte

Die [Einrichtungsanleitung](how-to/local-setup.md) bringt Backend, Frontend und PostgreSQL mit Docker
Compose zum Laufen und legt den ersten Administrator an. Sie ist auf Englisch, wie die übrige
technische Dokumentation.

Für eine bestehende Installation ist [Upgrading](how-to/upgrading.md) das Wichtigste: Migrationen
laufen automatisch beim Containerstart, das Ausrollen **ist** also das Upgrade.

## Wo es weitergeht

Die Dokumentation ist durchgehend auf **Englisch** — das ist die Sprache, in der sie geschrieben wurde,
und eine zweite Fassung von 4700 Zeilen Referenz würde vor allem auseinanderlaufen.

| Wenn Sie wissen wollen | Lesen Sie |
|------------------------|-----------|
| wie Kapazität gerechnet wird | [Capacity model](explanation/capacity-model.md) |
| wie Konflikte gefunden werden | [Conflict detection](explanation/conflict-detection.md) |
| wie das System aufgebaut ist | [Architecture](explanation/architecture.md) |
| wie die API aufgerufen wird | [API reference](reference/api.md) |
| wie Daten hinein und hinaus kommen | [Import and export](reference/import-export.md) |
| was fehlt | [Known limitations](reference/known-limitations.md) |
| warum etwas so ist, wie es ist | [Decisions](decisions/README.md) |

## Stand

Die Seite [known limitations](reference/known-limitations.md) wird absichtlich aktuell gehalten und ist
die, die man liest, bevor man sich auf Capado einlässt: sie ist nützlicher als eine Funktionsliste, weil
sie vorab sagt, wo Sie an eine Wand laufen.

Jede Veröffentlichung hält fest, was sich geändert hat. Für alles, worauf Sie sich verlassen, eine
Version festnageln statt `latest` zu verfolgen — was die Image-Tags bedeuten, steht in
[publishing a release](how-to/publishing-a-release.md).
