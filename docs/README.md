# Developer Documentation

Documentation for contributors, in English — see the language convention in
[CONTRIBUTING.md](../CONTRIBUTING.md). Follows the [Diátaxis](https://diataxis.fr/) framework.

## Structure

```
docs/
├── index.md                      Project site landing page (English)
├── index.de.md                   Project site landing page (Deutsch)
├── how-to/          Practical step-by-step guides (goal-oriented)
│   ├── local-setup.md
│   ├── adding-a-feature.md       Includes the two gates that fail a pull request
│   ├── upgrading.md              Existing installations: back up, pre-check, deploy order
│   └── publishing-a-release.md   Cutting a release, and the manual image-visibility step
├── reference/       Technical descriptions (information-oriented)
│   ├── api.md                    What the generated OpenAPI schema cannot express
│   ├── data-model.md
│   ├── glossary.md
│   ├── layout-components.md
│   ├── date-handling.md
│   ├── import-export.md          The five import/export pairs: columns, resolution, limits
│   ├── ci.md                     What runs when, and why the image build is manual
│   └── known-limitations.md      Deliberate omissions and what each costs
├── explanation/     Conceptual discussions (understanding-oriented)
│   ├── architecture.md           Includes a map from each feature area to its rules
│   ├── capacity-model.md
│   └── conflict-detection.md
├── decisions/       Architecture Decision Records
│   ├── README.md                 Which numbers are absent, and why
│   └── 003…012                   The cross-cutting decisions that are still cited
└── compliance/      For readers outside the development team
    └── zweck-und-grenzen-de.md
```

The endpoint list is **not** in `api.md`. FastAPI generates it and serves it at `/docs`; that file holds
only what a schema cannot say. See its opening section for why a second copy was worse than none.

Decisions taken after ADR-009 live in the module docstring of the service implementing them. See
[decisions/README.md](decisions/README.md) for why, and
[explanation/architecture.md](explanation/architecture.md) for the map that points at them.

## compliance/

Documents written for an audience OUTSIDE the development team — a works council, a
data protection officer, an auditor. They are templates rather than statements about
one deployment: Capado is a general tool, so anything specific to a single operator
is marked with `⟨…⟩` for that operator to fill in.

- `zweck-und-grenzen-de.md` — purpose, the full list of personal data processed, and
  the boundaries, in German, for co-determination under § 87 BetrVG and a processing
  record under Art. 30 GDPR. Its final section separates what is **solved in the software**
  — absence reasons reduced to `planned`/`unplanned`, audit access restricted and its
  retention bounded, the no-time-recording boundary fixed in code — from the **four
  decisions the operating company must take**, which the software cannot answer for it.

Per-person utilisation is named rather than hidden: it cannot be designed away without
robbing the tool of its purpose, so the document states what the number does and does
not mean instead of pretending it is absent.

The design boundary that document promises is fixed in ADR-009, so the promise and
the rule are one statement rather than two that can drift.

## User-facing documentation

End-user documentation (tutorials, how-tos, reference for app features)
lives in the frontend at `/help` and is available in German and English
via the app's i18n system. See `frontend/src/features/help/`.
