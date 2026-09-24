# Capado — Zweck, Datenumfang und Grenzen

**Adressat:** Betriebsrat und Datenschutzbeauftragte(r)
**Zweck dieses Dokuments:** Grundlage für die Beteiligung nach § 87 BetrVG und für
eine Verarbeitungsübersicht nach Art. 30 DSGVO.

> **Dies ist eine Vorlage, kein ausgefülltes Dokument.** Capado ist ein allgemeines
> Werkzeug, nicht für einen einzelnen Betrieb geschrieben. Die Abschnitte 1 bis 3 und
> 5 bis 9 beschreiben, was die **Software** tut und nicht tut — diese Aussagen gelten
> für jede Installation und sind am Quellcode überprüfbar. Mit `⟨…⟩` markierte Stellen
> muss der einsetzende Betrieb ausfüllen; sie sind betriebsspezifisch und können von
> der Software nicht beantwortet werden.
>
> Übernehmen Sie das Dokument in Ihre Unterlagen, füllen Sie die markierten Stellen
> aus und ergänzen Sie im Kopf Ihren eigenen Stand — Datum, eingesetzte Software-Fassung,
> betroffene Installation und ob produktiv geplant wird. Abschnitt 10 ist die Liste
> dessen, was **Sie** entscheiden müssen.
>
> **Keine Rechtsberatung.** Dieses Dokument beschreibt, was die Software technisch
> tut und nicht tut. Die rechtliche Einordnung — ob und in welchem Umfang
> Mitbestimmung greift — gehört von fachkundiger Stelle geprüft. Die Hinweise auf
> Normen benennen, wo wir eine Berührung sehen, und ersetzen diese Prüfung nicht.

---

## 1. Wozu die Software dient

Capado plant **Kapazitäten im Voraus**: welche Arbeitspakete in welchem Zeitraum
anstehen, welche Personalgruppen und welche Anlagen dafür gebraucht werden, und wo
die Planung nicht aufgeht.

Die drei Fragen, die das Werkzeug beantworten soll:

1. **Reicht die Kapazität?** Sind für einen Zeitraum mehr Zusagen gemacht, als
   Arbeitszeit vorhanden ist?
2. **Passen die Qualifikationen?** Erfordert ein Arbeitspaket eine Qualifikation,
   die im geplanten Zeitraum niemand mitbringt?
3. **Ist der Termin haltbar?** Ergibt die Durchlaufzeit in **Arbeitstagen** ein
   späteres Ende als der zugesagte Termin?

Bisher wird dasselbe in Tabellenkalkulationen gepflegt. ⟨Der Betrieb beschreibt
hier den bisherigen Stand.⟩

## 2. Was die Software ausdrücklich **nicht** tut

Diese Punkte sind Konstruktionsentscheidungen, keine bloßen Absichtserklärungen.
Der Verweis in Klammern nennt die Stelle, an der die Entscheidung im Quellcode
festgehalten ist, damit sie prüfbar und nicht nur behauptet ist.

- **Keine Zeiterfassung.** Es gibt kein Feld für tatsächlich geleistete
  Arbeitszeit, keinen Kommen-/Geht-Zeitpunkt, keinen Soll-Ist-Vergleich pro
  Person. Alle Zeitangaben sind **Planwerte**. (ADR-009 legt diese Grenze fest.)
- **Keine Leistungsmessung.** Es wird nicht erfasst, wie schnell, wie gut oder in
  welcher Menge jemand gearbeitet hat. Ein Arbeitspaket kennt nur „abgeschlossen
  am" — ein Zeitpunkt am Arbeitspaket, nicht eine Bewertung einer Person.
- **Keine Anwesenheitskontrolle.** Ob jemand heute im Betrieb ist, ist der
  Software unbekannt. Sie kennt nur eingetragene Abwesenheiten und Arbeitszeit­
  modelle — beides im Voraus gepflegt, nicht gemessen.
- **Keine Standort- oder Verhaltensdaten.** Keine Ortung, keine Auswertung von
  Anmeldezeiten, kein Zugriff auf andere Systeme.
- **Kein automatischer Datenabgleich mit der Personalabteilung.** Es besteht keine
  Schnittstelle zu Lohn-, Zeit- oder Personalsystemen. ⟨Falls später eine
  Anbindung an das ERP geplant wird, ist das eine eigene, erneut zu beteiligende
  Änderung.⟩
- **Keine Entgeltdaten.** Stundensätze sind — sobald die Kostenrechnung ergänzt
  wird — **an Kostenstellen bzw. Gruppen** gebunden, nicht an Personen. Ein
  personenbezogener Stundensatz ist bewusst nicht vorgesehen.

## 3. Welche personenbezogenen Daten verarbeitet werden

Vollständige Aufstellung. Was hier nicht steht, wird nicht gespeichert.

| Gegenstand | Felder | Zweck |
|---|---|---|
| **Person als Ressource** | Name, Zuordnung zu einer Gruppe/Kostenstelle, Standort, aktiv/inaktiv | Planbare Einheit. Kein Geburtsdatum, keine Anschrift, keine Personalnummer, keine Kontaktdaten. |
| **Qualifikationen** | Zuordnung Person ↔ Qualifikation | Prüfung, ob ein Arbeitspaket besetzbar ist |
| **Arbeitszeitmodell** | Arbeitsminuten je Wochentag, gültig ab | Rechengrundlage der Kapazität. Abbildung von Teilzeit und Schichtmodellen |
| **Abwesenheiten** | Zeitraum, Anteil, `geplant`/`ungeplant`, Freitextnotiz | Kapazität im Zeitraum reduzieren. Die Ursache wird nicht erfasst — siehe Abschnitt 5 |
| **Zuordnungen (Planung)** | Person, Arbeitspaket, Zeitraum, Anteil in Prozent | Der eigentliche Plan |
| **Konflikte** | Verweis auf die beteiligten Zuordnungen, Ursache | Automatisch berechnet, nicht eingegeben. Wird bei jeder Neuberechnung ersetzt |
| **Änderungsprotokoll** | Wer, wann, welcher Datensatz, alter und neuer Wert, Grund | Nachvollziehbarkeit von Planänderungen. Siehe Abschnitt 6 |
| **Benutzerkonten** | Anmeldename, Rolle, Berechtigungsumfang | Zugangskontrolle |

**Auslastung ist kein gespeichertes Datum**, sondern eine Berechnung aus Plan und
Arbeitszeitmodell. Sie kann jedoch pro Person angezeigt werden — siehe Abschnitt 7.

## 4. Wer was sehen kann

⟨Der Betrieb legt die Rollenzuordnung fest und trägt sie hier ein.⟩

Die Software unterscheidet:

- **Betrachter** — liest Pläne, ändert nichts.
- **Planer** — ändert Pläne, begrenzt auf ⟨die ihm zugewiesenen Projekte⟩.
- **Administration** — Vollzugriff **einschließlich** Änderungsprotokoll.

Das Änderungsprotokoll ist ausschließlich der Administration zugänglich, und die
Abfrage ist auf 200 Einträge pro Seite begrenzt. Beides ist absichtlich so gebaut:
eine unbegrenzte Abfrage wäre ein Auswertungswerkzeug.

## 5. Abwesenheitsgründe

Frühere Fassungen der Software kannten die Abwesenheitsgründe `Urlaub`, `Krank`,
`Wartung`, `Schulung` und `Sonstiges`. `Krank` ist ein **Gesundheitsdatum** und damit
eine besondere Kategorie nach Art. 9 DSGVO — auch ohne Diagnose. Für die
Kapazitätsrechnung war der Grund **nie erforderlich**: in die Rechnung gehen
ausschließlich Zeitraum und Anteil ein.

**Der Grund ist auf zwei Werte reduziert: `geplant` und `ungeplant`.** Die
Ursache wird nicht mehr erfasst. Die planungsrelevante Eigenschaft ist, ob eine
Abwesenheit vorhersehbar war — nicht warum.

Ein Detail, das darüber entscheidet, ob das mehr als eine Umbenennung ist: würde nur
`Krank` auf `ungeplant` abgebildet, wäre `ungeplant` ein exaktes Synonym und das
Gesundheitsdatum bliebe unter neuem Namen erhalten. Deshalb wird **auch `Sonstiges`
auf `ungeplant`** abgebildet, sodass der Wert tatsächlich verschiedene Ursachen
zusammenfasst — Krankheit, Notfall in der Familie, Pflegefall, unentschuldigtes
Fehlen.

**Für Installationen, die von einer früheren Fassung aktualisiert wurden**, ist diese
Mischung nur so gut, wie `Sonstiges` dort zuvor verwendet wurde: die
Rückschließbarkeit ist **verringert, nicht beseitigt**. Eine neu eingerichtete
Installation kennt die alten Werte nie.

**Auch das Änderungsprotokoll wird bei der Umstellung bereinigt.** Seine Einträge
enthielten die alten Werte im Klartext. Ohne diese Bereinigung wäre die ganze
Änderung kosmetisch gewesen — das Gesundheitsdatum wäre in der einen Tabelle
geblieben, aus der nichts gelöscht wird.

**Verbleibende Freitextfelder.** Zwei Stellen erlauben weiterhin freie Eingabe, und
technisch verhindert nichts, dass dort Gesundheitsangaben landen:

- die **Notiz an der Abwesenheit** (500 Zeichen),
- das **Begründungsfeld am Änderungsprotokoll**.

Beide dienen der Nachvollziehbarkeit der Planung — „Vertretung durch Kollegin",
„Termin auf Kundenwunsch verschoben". ⟨Der Betrieb legt fest, dass dort keine
Angaben zu Gesundheit oder Person eingetragen werden, und weist die Nutzer darauf
hin.⟩ Eine technische Sperre ist bei Freitext nicht möglich; eine Zweckbindung ist
es.

## 6. Änderungsprotokoll

Das Änderungsprotokoll hält jede Planänderung mit Urheber, Zeitpunkt sowie altem und
neuem Wert. Das ist gewollt: bei Terminstreitigkeiten ist nachvollziehbar, wer wann
was zugesagt hat. Es lässt sich nicht sinnvoll vermeiden, ohne genau diese Funktion
aufzugeben.

**Der Zugriff ist ausschließlich der Administration möglich.** Planer und Betrachter
können das Protokoll nicht einsehen — auch nicht ihre eigenen Einträge. Die Abfrage
ist zusätzlich auf 200 Einträge pro Seite begrenzt, damit sie kein
Massenauswertungswerkzeug ist. Beides ist im Code durchgesetzt, nicht durch
Konfiguration.

Änderungen an Abwesenheiten werden mitprotokolliert. Da der Grund nur noch
`geplant`/`ungeplant` ist (Abschnitt 5) und die Altbestände bereinigt wurden, enthält
das Protokoll insoweit keine Gesundheitsangaben mehr.

**Aufbewahrungsfrist: 24 Monate, einstellbar.** Ältere Einträge werden **gelöscht**,
nicht als gelöscht markiert. Die Frist ist in den Einstellungen änderbar, weil sie
eine rechtliche und organisatorische Entscheidung ist und nicht eine technische. Der
Wert `0` bedeutet unbegrenzte Aufbewahrung; das ist eine bewusst zu treffende Wahl und
kein Zustand, der durch Unterlassen entsteht.

Bestehende Installationen erhalten beim Update ebenfalls 24 Monate — nicht
„unbegrenzt". Die unbegrenzte Aufbewahrung ist der behobene Zustand, sie
stillschweigend fortzuschreiben hätte die Einstellung zur Zierde gemacht.

**Ein Hinweis, der zur Ehrlichkeit gehört:** Die Anwendung startet selbst einen
wiederkehrenden Wartungsauftrag, sofern der Scheduler aktiviert ist. Der Betrieb muss
prüfen, ob der Auftrag erfolgreich läuft; die gespeicherten Laufprotokolle sind der
Nachweis, dass die Frist tatsächlich angewendet wird. Ist der Scheduler deaktiviert
oder schlägt der Auftrag fehl, wird trotz eingestellter Frist nichts gelöscht.

## 7. Personenbezogene Auslastung

Die Software kann Auslastung pro Person über einen Zeitraum darstellen, etwa „65 %
über sechs Wochen". Das ist ein **Planwert** und keine Messung: er ergibt sich aus
dem, was jemand zugewiesen bekommen hat, nicht aus dem, was jemand getan hat.

Das lässt sich nicht wegkonstruieren, ohne das Werkzeug seines Zwecks zu berauben —
eine Planung, die nicht sagen kann, ob eine Person überbucht ist, plant nicht. Wir
verbergen es deshalb nicht, sondern benennen es:

- Die Zahl sagt aus, **wie viel Arbeit zugewiesen wurde**, nicht wie viel geleistet
  wurde. Ein Rückschluss auf Leistung ist aus ihr nicht möglich, weil die Software
  gar nicht erfasst, was tatsächlich geschehen ist (Abschnitt 2).
- Sie ist im **Vorhinein** vergeben. Wer sie liest, liest eine Entscheidung der
  Planung — nicht ein Verhalten der Person.
- Eine niedrige Auslastung ist eine Aussage über die Planung, nicht über den
  Menschen.

⟨Der Betrieb legt fest, welche Rollen die personenbezogene Ansicht erreichen und ob
eine Verwendung dieser Zahlen für Personalbeurteilung ausdrücklich ausgeschlossen
wird. Letzteres ist eine organisatorische Zusage — technisch ist eine Anzeige, die
für die Planung gebraucht wird, nicht daran zu hindern, auch anders gelesen zu
werden.⟩

## 8. Was das Werkzeug für die Beschäftigten leisten soll

Der Nutzen soll nicht einseitig sein, und ein Punkt ist ausdrücklich als Schutz
gebaut:

**Überlast wird sichtbar, nicht weggerechnet.** Der Auslastungsanteil bezieht sich
auf einen **normativen Acht-Stunden-Tag**, nicht auf die individuelle Kapazität der
Person. Wäre es umgekehrt, würde eine Teilzeitkraft, der man ihr Pensum doppelt
zuweist, als „100 % ausgelastet" erscheinen. So erscheint sie als **überbucht** —
die Überlastung ist im Plan lesbar, bevor sie im Betrieb ankommt.

Ebenso: Zusagen, die in Arbeitstagen nicht haltbar sind, werden als Warnung
ausgewiesen statt durch stillschweigende Terminverschiebung geglättet. Termindruck
wird damit früher sichtbar und nicht auf die Ausführung abgewälzt.

**Einsicht in die eigenen Daten.** Ein Benutzerkonto kann mit der geplanten Person
verknüpft werden, die es bedient. Ist es verknüpft, sieht diese Person **ihre
eigenen** Zuweisungen, Abwesenheiten und Qualifikationen selbst — bisher war das nur
Vorgesetzten und Administratoren möglich, und eine Auskunft nach Art. 15 DSGVO
musste von Hand erstellt werden.

Drei Punkte dazu, weil sie erfahrungsgemäß gefragt werden:

- Die Verknüpfung **schafft keine neue Auswertbarkeit.** Die personenbezogene
  Auslastung war bereits einer namentlich benannten Person zurechenbar (siehe
  Abschnitt 7); die Verknüpfung gibt der betroffenen Person Zugang dazu.
- Die Einsicht ist **nur lesend.** Urlaub beantragen oder eine Zuweisung bestätigen
  sind eigene Vorgänge und ausdrücklich nicht enthalten. ⟨Eine Urlaubsfreigabe wäre
  eine erneut zu beteiligende Änderung.⟩
- Die Verknüpfung ist **freiwillig und einzeln**: sie wird pro Konto von einem
  Administrator gesetzt, nicht automatisch über Namen oder E-Mail-Adressen
  erschlossen. Ein Konto ohne Verknüpfung verhält sich wie bisher.

Die Grenze aus Abschnitt 2 bleibt davon unberührt: aus der Verknüpfung folgt **kein**
Vergleich von Anmeldeverhalten mit Planwerten, keine Zeiterfassung und keine
Leistungsmessung. Das ist in ADR-009 festgehalten und am Quellcode prüfbar.

## 9. Löschung personenbezogener Daten (Art. 17 DSGVO)

Bis vor kurzem hatte dieses Dokument dazu **nichts** gesagt, und das war die
gravierendste Lücke darin: es beschrieb die Löschfristen des Änderungsprotokolls
ausführlich (Abschnitt 6) und schwieg über die Löschung der Person selbst. Ein
Leser durfte daraus schließen, das Thema sei behandelt. Es war es nicht — die
Software konnte eine Person überhaupt nicht löschen, nur deaktivieren.

**Zwei verschiedene Vorgänge, absichtlich getrennt.**

| Vorgang | Was passiert | Umkehrbar |
|---|---|---|
| **Deaktivieren** | Die Person wird nicht mehr eingeplant, bleibt aber gespeichert und in alten Plänen sichtbar | ja |
| **Löschen** | Die Person und alle Planungsdaten zu ihr werden **entfernt** | nein |

Getrennte Bedienpfade, weil es getrennte Absichten sind: „arbeitet nicht mehr hier"
und „verlangt Löschung ihrer Daten" haben verschiedene Folgen. Löschen darf
ausschließlich die Administration, nicht eine gruppenbeschränkte Bearbeiterin.

### Was beim Löschen tatsächlich entfernt wird

Qualifikationen, Arbeitszeitprofile, Abwesenheiten, Zuweisungen, erkannte Konflikte,
die zugehörigen Protokolleinträge und der Personendatensatz selbst. Ein verknüpftes
Anmeldekonto verliert die Verknüpfung, bleibt aber als Konto bestehen — es gehört zur
Zugangsverwaltung, nicht zur Planung.

Die Software gibt anschließend **je Tabelle die Anzahl der entfernten Datensätze
zurück**, damit der Betrieb die Erfüllung der Anfrage belegen kann.

### Warum wirklich gelöscht und nicht anonymisiert wird

Weil Capado nach ADR-009 ausdrücklich **kein** Nachverfolgungswerkzeug ist. Die
Historie einer ausgeschiedenen Person hat hier keinen Zweck, den man gegen ihr
Löschrecht abwägen könnte. Und für die künftige Planung ist die **Lücke**, die ihr
Fortgang hinterlässt, gerade die gesuchte Information — anonymisierte Datensätze
würden Pläne als besetzt erscheinen lassen, die es nicht sind.

### Was bewusst erhalten bleibt, und warum es keine Personendaten sind

**Eingefrorene Planstände (Baselines).** Ein Planstand hält Projekte, Arbeitspakete
und Zuweisungen fest — **nie** den Personendatensatz. Gespeichert ist dort also eine
technische Kennung ohne Namen, und nach der Löschung verweist diese Kennung auf
nichts mehr. Ein Planstand aus dem letzten Jahr bleibt damit historisch unverändert
lesbar, ohne die gelöschte Person zu benennen. Ihn nachträglich umzuschreiben würde
den historischen Nachweis beschädigen, um Daten zu entfernen, die nicht darin sind.

**Ein einzelner Protokolleintrag** hält fest, *dass* eine Löschung stattgefunden hat,
mit Zeitpunkt, ausführendem Konto und der technischen Kennung — **ohne Namen und ohne
inhaltliche Werte**. Ohne diesen Eintrag könnte der Betrieb nicht belegen, dass er
eine Löschanfrage erfüllt hat; mit den alten Einträgen wäre die Löschung nicht
vollzogen.

⟨Der Betrieb legt fest, wer Löschanfragen annimmt, in welcher Frist sie bearbeitet
werden und wie die zurückgemeldeten Zahlen dokumentiert werden.⟩

## 10. Technischer Rahmen

- **Betrieb im eigenen Haus.** Keine Cloud, kein externer Dienstleister, keine
  Datenübermittlung an Dritte. ⟨Der Betrieb benennt Server und Verantwortlichen.⟩
- **Quelloffen** unter GPL-3.0. Jede Aussage in diesem Dokument ist am Quellcode
  überprüfbar — auch von einer Stelle, die der Betriebsrat selbst hinzuzieht.
- **Zugang** über persönliche Konten mit Rollen; keine Sammelkonten vorgesehen.
- ⟨Löschkonzept, Sicherungskonzept und Verantwortlichkeiten trägt der Betrieb
  nach.⟩

## 11. Was in der Software gelöst ist — und was der Betrieb entscheiden muss

### In der Software gelöst

Diese Punkte sind nicht zugesagt, sondern gebaut, und im Quellcode nachprüfbar:

- Abwesenheitsgründe auf `geplant`/`ungeplant` reduziert; bei einer Aktualisierung
  werden Altbestände und Änderungsprotokoll mitbereinigt (Abschnitt 5).
- Änderungsprotokoll ausschließlich für die Administration, Abfrage auf 200 Einträge
  je Seite begrenzt, Aufbewahrung standardmäßig 24 Monate und einstellbar
  (Abschnitt 6).
- Grenze „keine Zeiterfassung, keine Leistungsmessung, kein personenbezogener
  Stundensatz" als Entscheidung im Quellcode festgehalten (Abschnitt 2), damit sie
  nicht durch eine spätere Erweiterung unbemerkt entfällt.
- Überlast wird gegen einen normativen Acht-Stunden-Tag gerechnet und damit sichtbar,
  statt gegen die individuelle Kapazität und damit weggerechnet (Abschnitt 8).
- Einsicht in die eigenen Daten ist nur lesend und nur bei ausdrücklich gesetzter
  Verknüpfung möglich (Abschnitt 8).

### Was der einsetzende Betrieb entscheiden und festhalten muss

Diese vier Punkte kann die Software nicht für Sie beantworten. Ohne sie ist das
Dokument nicht vollständig:

1. **Löschauftrag überwachen.** Der interne Scheduler führt den Auftrag aus, sofern
   er aktiviert ist. Prüfen Sie die gespeicherten Laufprotokolle auf erfolgreiche
   Ausführungen; die eingestellte Frist allein beweist noch keine tatsächliche Löschung.
2. **Rollenzuordnung** festlegen und entscheiden, ob die personenbezogene
   Auslastungsansicht auf bestimmte Rollen begrenzt wird (Abschnitt 7).
3. **Organisatorische Zusagen** treffen: Zweckbindung der Freitextfelder
   (Abschnitt 5) und Ausschluss der Auslastungszahlen für Personalbeurteilung
   (Abschnitt 7). Beides ist technisch nicht erzwingbar und deshalb eine Zusage.
4. **Weitere Grenzen benennen**, falls gewünscht. Sollen bestimmte Auswertungen
   ausgeschlossen sein, können sie als Grenze **eingebaut** werden statt nur zugesagt
   — das ist der Unterschied zwischen einer Absichtserklärung und einer prüfbaren
   Eigenschaft. Ein solcher Wunsch gehört an das Projekt gerichtet.
