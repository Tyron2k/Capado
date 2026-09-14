# Domain Glossary

| Term (EN) | Term (DE) | Definition |
|-----------|-----------|------------|
| Resource | Ressource | A person or infrastructure item that can be assigned to work packages. |
| Work Package | Arbeitspaket | A unit of work with a time range and required skills, belonging to a project. |
| Assignment | Zuweisung | Links a resource to a work package for a specific time range with an allocation percentage. |
| Skill | Skill | A capability category (e.g. "Assembly", "Welding", "Crane"). |
| SkillAttribute | Skill-Attribut | A specific variant of a skill (e.g. "Series Alpha" for "Assembly"). |
| ResourceGroup | Ressourcengruppe | A named container for organizing resources (hierarchy). Replaces free-text department/location. |
| Site | Betriebsstätte | Top-level organizational or physical location. Owns the working-time calendar, because holidays differ per location. |
| Absence | Abwesenheit | A period of reduced or zero availability. Carries only `planned` / `unplanned` — **not** a cause. Reduces the resource's available time; it is not demand. |
| Conflict | Konflikt | Detected when the minutes demanded by assignments exceed the minutes a resource has available on a given day. |
| Conflict Suggestion | Lösungsvorschlag | Backend-proposed resolution for a conflict (shift, reduce, swap). |
| Allocation Percent | Auslastung (%) | Share of a *normative* working day (480 min) that an assignment demands — not a share of the individual resource's capacity. |
| Normative Working Day | Normarbeitstag | The reference day `allocation_percent` is measured against. 480 minutes by default. |
| WorkWeekProfile | Wochenarbeitszeitprofil | A reusable weekly pattern of available minutes per weekday. Where part-time and shift patterns live. |
| Holiday | Feiertag / Kalenderausnahme | A dated override of the week profile for one site. Carries minutes, so half days and designated working Saturdays are ordinary cases. |
| Availability Window | Verfügbarkeitsfenster | A clock interval on one weekday during which an infrastructure resource may be booked. No windows means unrestricted. |
| Shortfall | Unterdeckung | Work assigned across a non-working day delivers less time than planned. Not a conflict — the plan is under-supplied, not over-allocated. |
| InfraGroup | Infrastrukturgruppe | A group of infrastructure resources (e.g. a hall or workshop area). |
| Project | Projekt | A container for work packages with a time range. |
| Template | Vorlage | A convenience template for copying skill requirements when creating work packages. |
| Capacity | Kapazität | Available working time for a resource on a day, in minutes: week profile, corrected by the site calendar, reduced by absences. |
| Baseline | Planstand | A frozen copy of the plan as it stood when it was reported, so "what did we say in March" stays answerable after March. Compared against the live plan. |
| Audit log | Änderungsprotokoll | Record of every write: who, when, which record, old and new value. Administration only, retained 24 months by default. |
| Self-service | Selbstauskunft | Read-only view a person gets of their **own** assignments, absences and qualifications, once their account is linked to the resource that represents them. |
| Lead time | Durchlaufzeit | Working days a work package needs. Used to test whether a promised date is reachable — the plan warns instead of silently shifting the date. |
| Freeze | Planungssperre | A period in which the plan may not be changed, so a reported plan stays the plan. |
