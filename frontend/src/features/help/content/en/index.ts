/**
 * English help content organized by Diátaxis category.
 * Each entry has a slug (URL path), title, category, and markdown body.
 */

import type { HelpArticle } from '../de'

export const articles: HelpArticle[] = [
  // --- Tutorials (learning-oriented) ---
  {
    slug: 'getting-started',
    title: 'Getting Started',
    category: 'tutorial',
    routes: ['/'],
    body: `
## Welcome to Capado

This guide walks you through the first steps after setup.

### 1. Create skills

Before you can start planning, you need:

- **Skills** and **Attributes** (e.g. "Assembly" with attributes "Type Alpha", "Type Beta")
- **People resources** with department and availability
- **Infrastructure resources** (halls, workstations) with location

### 2. Create your first project

Navigate to *Projects* and click "New Project". Enter name and time range.

### 3. Add work packages

Open the project and create work packages with start and end dates.

### 4. Assign resources

Under *Planning*, assign resources to work packages via drag & drop or the assignment form.

### 5. Check for conflicts

The system automatically detects overloads. Check the *Planning* page (Overview tab) for details.
    `.trim(),
  },

  // --- How-To Guides (goal-oriented) ---
  {
    slug: 'resolve-conflict',
    title: 'Resolve a conflict',
    category: 'how-to',
    routes: ['/planning'],
    body: `
## Resolve a conflict

### Prerequisite

You have identified an active conflict on the Planning page (Overview tab).

### Steps

1. Open the **Planning** page (Overview tab)
2. Click on the affected conflict
3. Choose a resolution action:
   - **Reduce allocation** — Lower the allocation percentage
   - **Shift time range** — Move the assignment to a different period
   - **Remove assignment** — Delete the conflicting assignment
   - **Swap resource** — Assign a different resource
4. The conflict disappears automatically after the change

### Note

Conflicts are detected in real-time. After any change to assignments, the conflict list is updated.
    `.trim(),
  },
  {
    slug: 'create-user',
    title: 'Create a new user',
    category: 'how-to',
    routes: ['/admin/users'],
    body: `
## Create a new user

### Prerequisite

You are logged in as an administrator.

### Steps

1. Navigate to **User Management** (only visible to admins)
2. Click "Create User"
3. Fill in the required fields:
   - Name, email, password
   - Role: Admin, Editor, or Viewer
4. For the "Editor" role — select permission scopes:
   - **Departments**: Which departments can the user edit?
   - **Locations**: Which infrastructure locations?
   - **Projects**: Which projects?
5. Click "Save"

The new user must change their password on first login.
    `.trim(),
  },
  {
    slug: 'create-project',
    title: 'Create a new project',
    category: 'how-to',
    routes: ['/projects'],
    body: `
## Create a new project

### Steps

1. Navigate to **Projects**
2. Click "New Project"
3. Enter:
   - **Name**: Project title
   - **Start date** and **End date**
4. Click "Save"

### Note for editors

As an editor, you can only create and edit projects that are within your configured project scope.
    `.trim(),
  },

  // --- Reference (information-oriented) ---
  {
    slug: 'roles-and-permissions',
    title: 'Roles and Permissions',
    category: 'reference',
    routes: ['/admin/users', '/settings'],
    body: `
## Roles and Permissions

### Role overview

| Role | Read | Write | User Management |
|------|------|-------|-----------------|
| **Admin** | Everything | Everything | ✅ |
| **Editor** | Everything | Only within own scope | ❌ |
| **Viewer** | Everything | Nothing | ❌ |

### Editor scopes

Editors can only modify entities within their configured scope:

| Scope | Allows editing |
|-------|---------------|
| Departments | People resources, assignments, qualification matrix |
| Locations | Infrastructure resources, infrastructure assignments |
| Projects | Projects, work packages |

### Master data

The **global catalogue** — skills, their attributes, and the work package templates — is managed by **administrators only**. Department and site managers *assign* skills to the people in their area, but they do not create new ones and do not rename them.

The reason is not deletion, which is guarded anyway, but **renaming**. Requirements reference a skill by an internal identifier, never by its name, so a rename breaks nothing technically. What it changes is what every existing requirement *means*: rename "Welding" to "Welding G3" and every work package that previously required "Welding" now demands G3, with nobody having checked whether the assigned people hold it. The qualification check keeps reporting everything as fine, because the identifier and the levels are unchanged.

No error, no conflict — just a plan asserting something that was never verified. A redefinition like that applies to every department at once, which makes it a decision a role limited to one area cannot take.

A side effect kept with administrators for the same reason: the skill import resolves by **name**. After a rename, stored import files carrying the old name no longer find their skill.
    `.trim(),
  },
  {
    slug: 'keyboard-shortcuts',
    title: 'Keyboard Shortcuts',
    category: 'reference',
    body: `
## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Open and close help | \`Ctrl+/\` / \`⌘+/\` |
| Cancel an inline edit | \`Escape\` |

That is the complete list. There is deliberately no save shortcut: changes are committed through each view's own buttons. \`Escape\` applies only to fields edited directly in a list (skill and group names, for example), not as a general close.
    `.trim(),
  },

  // --- Explanation (understanding-oriented) ---
  {
    slug: 'capacity-model',
    title: 'How does capacity calculation work?',
    category: 'explanation',
    routes: ['/people', '/infrastructure', '/planning'],
    body: `
## How does capacity calculation work?

### Basic principle

Each resource has a capacity of 100% per working day. Assignments consume a percentage of this capacity. Utilization is calculated as:

\`\`\`
Utilization = Sum(Assignments %) + Sum(Absences %)
\`\`\`

### Color coding

- 🟢 **Green** (< 80%): Resource has free capacity
- 🟡 **Yellow** (80–100%): Resource is well utilized
- 🔴 **Red** (> 100%): Overload — a conflict is created

### Infrastructure

Infrastructure resources are always 100% exclusively allocated. If two bookings overlap in time, a conflict is created.

### Work schedule

A day's capacity comes from three layers, applied in order:

1. **Week profile** — sets how many minutes are worked on each weekday. A profile can be assigned to a person directly or to their group; without one, the default profile applies. **Part-time belongs here**, not in an absence: only a profile can express "Monday to Thursday full, Friday off".
2. **Holidays and exceptions** — override the profile for individual days, per site. A day can be 0 minutes (public holiday, shutdown, bridge day), less than the profile (half day, as 24 and 31 December usually are), or more than 0 on a normally free day (a designated working Saturday).
3. **Absences** — reduce whatever availability is left, proportionally, over a date range.

What remains is the available time. Demand comes from assignments: \`allocation_percent\` is a share of a normative eight-hour day. Days with no capacity produce no demand and therefore no conflict — an assignment spanning a weekend consumes nothing there.

> **Do not model part-time as an absence.** Earlier versions had no week profiles and used that workaround. Entering both subtracts the reduction twice: once through the shorter day in the profile, once through the absence.

    `.trim(),
  },
  {
    slug: 'conflict-detection',
    title: 'How does conflict detection work?',
    category: 'explanation',
    routes: ['/planning'],
    body: `
## How does conflict detection work?

### Automatic detection

Conflicts are automatically detected whenever an assignment is created or modified. No manual check is needed.

### Conflict types

1. **Overload (people)**: The sum of all assignment and absence percentages on a day exceeds 100%.

2. **Double booking (infrastructure)**: Two assignments for the same resource overlap in time.

### Weekend merging

Conflicts that span a weekend with the same root cause are merged into a single conflict.

### Severity levels

| Severity | Utilization | Meaning |
|----------|------------|---------|
| Low | ≤ 125% | Slight overload |
| Medium | 125–150% | Significant overload |
| High | > 150% | Critical overload |
    `.trim(),
  },
  {
    slug: 'skill-mismatches',
    title: 'Detecting and resolving skill mismatches',
    category: 'explanation',
    routes: ['/planning'],
    body: `
## Detecting and resolving skill mismatches

### What is a skill mismatch?

A skill mismatch is detected when an assigned resource does not hold any of the skills required by the work package.

**Example**: A work package requires "Assembly" and "Welding". A resource with neither Assembly nor Welding skills is flagged as a skill mismatch. A resource with Assembly skills is correctly assigned — it does not need to have all skills.

### How a requirement is covered

A requirement is counted in one of **two ways**, and the difference matters:

**Effort (FTE)** — allocations add up to a full-time equivalent:
- Requirement: 2 electricians
- 4 electricians at 50% each = 2.0 FTE → satisfied
- 1 electrician at 100% = 1.0 FTE → gap of 1.0

**Headcount** — each person counts once, and only if their allocation reaches the configured minimum:
- Requirement: 2 electricians, minimum allocation 50%
- 4 electricians at 25% each → **nothing is covered**, none reaches the minimum
- 2 electricians at 50% each → satisfied

The trap is in headcount: spreading a task across many people in small slices covers nothing under that rule, even when the slices add up. If the task needs two people present at once, that is the point; if it is only about hours of work, choose effort.

### Display on the Planning page

Skill mismatches appear on the Overview tab alongside capacity conflicts. Both are shown as expandable cards:

- **Orange "Skill" badge** marks skill problems
- **Red "Capacity" badge** marks overloads
- Both card types offer resolution actions (swap resource, shift time range, remove assignment)

### Suggested alternatives

When expanding a skill card, alternative resources are suggested that:
1. Hold the required skills for the work package
2. Have available capacity in the time range

Use the Apply button to swap the resource directly.
    `.trim(),
  },

  // --- Additional How-To Guides ---
  {
    slug: 'create-resource',
    title: 'Create a resource',
    category: 'how-to',
    routes: ['/people', '/infrastructure'],
    body: `
## Create a resource

### People resource

1. Navigate to **People**
2. Select the "Employees" tab
3. Click "New Resource"
4. Fill in:
   - **Name**: Full name
   - **Group**: Select the group from the dropdown
5. Click "Save"

### Infrastructure resource

1. Navigate to **Infrastructure**
2. Select the "Resources" tab
3. Click "New Resource"
4. Fill in:
   - **Name**: Designation (e.g. "Workstation 3")
   - **Group**: Select the group from the dropdown
5. Click "Save"

### Skills

After creating a resource, assign skills via the certificate icon or the Skills tab in Administration.
    `.trim(),
  },
  {
    slug: 'create-assignment',
    title: 'Create an assignment',
    category: 'how-to',
    routes: ['/planning'],
    body: `
## Create an assignment

### Prerequisite

You have at least one project with work packages and available resources.

### Steps

1. Navigate to **Planning**
2. Select the "Assignments" tab
3. Click "Assign Resource"
4. Choose the resource and time range:
   - **People**: Start/end date + allocation percentage (1–100%)
   - **Infrastructure**: Start/end timestamp (minute precision)
5. Click "Save"

### Conflict detection

After saving, the system automatically checks for conflicts. If the resource is overloaded in the selected period, a conflict is created and shown on the Planning page (Overview tab).

### Tips

- Use the **Suggestions** feature to find available resources for a time range
- The **Gantt** page shows at a glance which resources are free
- The **Unmet Requirements** alert at the top of the Assignments tab shows work packages that still need qualified resources
    `.trim(),
  },
  {
    slug: 'import-export-assignments',
    title: 'Import and export assignments',
    category: 'how-to',
    routes: ['/planning'],
    body: `
## Import and export assignments

Assignments can be bulk-created and downloaded via Excel or CSV.

### Where do I find it?

1. Navigate to **Planning**
2. Select the "Administration" tab
3. The "Import / Export" section contains the upload and download buttons

### Export

Click the download icon and choose the format (Excel or CSV). The file contains all personal and infrastructure assignments.

### Import

1. Click the upload icon and select your file
2. After import, a notification shows how many assignments were created, skipped, or errored

### File format

CSV format: **Project; Work Package; Resource; Start; End; Allocation**

- The **Work Package** column is optional. If omitted, the work package is resolved by date overlap within the project.
- **Resources** and **projects** must already exist — they are resolved by name.
- Dates in ISO format (YYYY-MM-DD).
- Duplicate assignments (same resource + work package) are skipped.
    `.trim(),
  },
  {
    slug: 'manage-skills',
    title: 'Manage skills and attributes',
    category: 'how-to',
    routes: ['/people', '/infrastructure'],
    body: `
## Manage skills and attributes

Skills and their attributes are global — once created, they are available for both people and infrastructure.

### Create a skill

1. Navigate to **People** or **Infrastructure**
2. Select the "Administration" tab
3. Scroll to the "Skills" section
4. Click "Add Skill"
5. Enter the skill name (e.g. "Assembly", "Welding", "Crane")
6. Press Enter or click the checkmark

### Add attributes to a skill

1. Click on a skill to expand it
2. Click "Add Attribute"
3. Enter the attribute name (e.g. "Type Alpha", "Steel", "50t")
4. Press Enter or click the checkmark

### Edit or delete

- Click the pencil icon to rename
- Click the trash icon to delete (only possible when not assigned to any resource)

### Import/Export

Use the import/export icons in the header to bulk-manage skills via Excel or CSV.

**Three export formats, and only two of them can be imported back:**

| Format | Purpose | Re-importable |
|--------|---------|---------------|
| Excel — skill matrix | a report, for reading and filling in on paper | **no** |
| Excel — flat | edit in Excel **and** get back in | yes |
| CSV | the same, as CSV | yes |

The skill matrix has its header across two rows and separator rows between groups — the importer cannot read it. Upload it anyway and Capado says so, naming the flat export as the way out.

**File format of the flat export:** five columns — \`Name\`, \`Group\`, \`Skill\`, \`Attribute\`, \`Site\`. Everything but Name and Group is optional. **An unknown site is rejected, not created** — unlike a skill, because a site owns the holiday calendar and a typo would produce a plant with no holidays. Create it under Working time first. A missing column leaves the site untouched; an empty cell **removes** it. The header must start with \`Name\` and \`Group\` **in that order**; columns are read positionally, so a swapped header is refused rather than guessed. Case does not matter, and \`Gruppe\` is accepted too.

Only \`.xlsx\` and \`.csv\` are accepted. The whole import is **one transaction**: if any row is rejected, nothing is written. A log opens afterwards with the counts and every rejected row.
    `.trim(),
  },
  {
    slug: 'customize-settings',
    title: 'Customize settings',
    category: 'how-to',
    routes: ['/settings'],
    body: `
## Customize settings

Under Settings you can configure the appearance of the application.

### Available settings

| Setting | Description |
|---------|-------------|
| Company name | Displayed in the header and navigation |
| Subtitle | Optional additional text below the company name |
| Logo URL | URL to a company logo (shown in the header) |
| Primary color | Main UI accent color (hex value) |

The page also holds the operational settings: retention periods for audit entries and baselines, the planning freeze, the maintenance run, and the mail configuration for the digest.

### Where each setting lives

This page is **administrators only**, and everything on it is **stored on the server and applies to the whole organisation** — when an administrator changes the company name, everyone sees it.

**Colour scheme and language do not belong here.** Both are personal preferences, stored only in your browser and switched through the icons in the header rather than on this page. Anyone may change them for themselves, without administrator rights.
    `.trim(),
  },

  // --- Additional Reference ---
  {
    slug: 'dashboard-overview',
    title: 'Dashboard',
    category: 'reference',
    routes: ['/'],
    body: `
## Dashboard

The dashboard shows an overview of current utilization and open conflicts.

### Contents

- **Utilization overview**: Aggregated capacity utilization across all resources
- **Project list**: Active projects with conflict count
- **Quick access**: Links to the most important areas

### Filters

You can filter the view by:
- Time range (start/end date)
- Department
- Location
- Project(s)
    `.trim(),
  },
  {
    slug: 'gantt-view',
    title: 'Gantt View',
    category: 'reference',
    routes: ['/gantt'],
    body: `
## Gantt View

The Gantt view is available as a standalone page at **Gantt** in the main navigation and shows assignments on a timeline. Three perspectives, answering different questions.

### Project — where are the gaps?

This perspective shows **every project on one shared timeline**, one row each, with a grey bar spanning the project's duration. There is no single-project picker any more: overlaps and idle stretches are only visible when everything is on screen at once.

The arrow on the left expands a project to show **its work packages**. Deliberately not everything at once: three projects with eight packages each would be 24 rows before anyone has asked a question. Work packages are fetched on expand and kept afterwards, so reopening is instant.

The project bar is **grey**, a work package **blue**. The difference is intentional: a project is a container and occupies no resource itself.

Choose the row order with **Name**, **Start** or **End**. Sorting by start is how you find a project whose bar lies outside the currently visible time window.

### Personnel and Infrastructure — what is on which resource, and when?

Here you pick a **group** and switch grouping with **By project | By resource**.

**By resource** is the view for spotting gaps: one row per resource, holding its occupancy across all projects in chronological order. That is how you see which projects are on a given track or in a given booth — and when it is free. Grouped by project, the same occupancy is scattered across several project headings and an idle week goes unnoticed.

Both groupings show the same data, folded differently. They cannot contradict each other.

### Display

- **Bars**: an assignment or a work package
- **Colors**: blue normally, **red where there is a conflict**. Work packages deliberately have no colours of their own — red is reserved for the conflict, and coloured bars would overwrite that signal
- **Alternating row backgrounds** and a **highlight on the row under the pointer**, so reading sideways does not land you in the neighbouring row
- **Truncated names**: hover the name and the tooltip gives it in full
- **Time scale**: switchable between day, week and month

### Interaction

Only **red bars are clickable**; clicking one goes to the conflict view. Bars without a conflict do not respond to clicks — edit an assignment's details on the Planning page, not in the chart.
    `.trim(),
  },
  {
    slug: 'project-overview',
    title: 'Project Overview',
    category: 'reference',
    routes: ['/'],
    body: `
## Project Overview

The project overview is part of the **Dashboard** and shows KPIs for all projects at a glance.

### Displayed metrics

| KPI | Description |
|-----|-------------|
| Progress | Time-based progress from start to end date |
| Active work packages | Number of currently running work packages |
| Next deadline | Earliest end date of an open work package |
| Open conflicts | Number of unresolved conflicts in the project |
| Avg. utilization | Average resource utilization percentage |

### Filters

- Filterable by project IDs
- Sortable by start date and name
    `.trim(),
  },
  {
    slug: 'skill-assignments',
    title: 'Skill Assignments',
    category: 'reference',
    routes: ['/people', '/infrastructure'],
    body: `
## Skill Assignments

Skills link resources with capabilities and their specific attributes.

### Structure

Each assignment consists of:
- **Resource**: The person or infrastructure item
- **Skill**: The capability (e.g. "Assembly")
- **Attribute**: The specific variant (e.g. "Type Alpha")

### Individual management

1. Open the People page
2. Click the certificate icon on a person
3. Check/uncheck skill attributes in the drawer

### Bulk management

Use the "Import/Export" section in the "Administration" tab on the People or Infrastructure page:
- **Export**: three formats — Excel as a skill matrix (a report, **not** re-importable), Excel flat, or CSV
- **Import**: upload a file to create resources and assign skills in one go

Import format: five columns — "Name", "Group", "Skill", "Attribute", "Site". Everything but Name and Group is optional; an unknown site is rejected rather than created. Pick "Excel — flat" or CSV when you intend to edit and upload again; the skill matrix cannot be read back.

### Usage

Skill assignments are used for:
- Resource suggestions (only qualified resources are suggested)
- Filtering in the planning view
    `.trim(),
  },

  // --- Working time ---
  {
    slug: 'week-profiles',
    title: 'Week profiles',
    category: 'explanation',
    routes: ['/working-time'],
    body: `
## Week profiles

A week profile sets how many **minutes are worked on each weekday**. It is the lowest of the three layers that make up capacity.

### Assignment

A profile can be assigned to a person directly or to their group. The direct assignment wins; without one, the group's applies; without that, the **default profile** applies.

Exactly one profile carries the default flag. Two defaults would make capacity depend on row order, so the system does not allow it.

### Part-time belongs here

Part-time is modelled as its own week profile, **not** as an absence. Only a profile can express "Monday to Thursday full, Friday off" — a 20% absence spreads the reduction evenly across the week and therefore hits the wrong day.

Entering both subtracts twice: once through the shorter day in the profile, once through the absence.

### What happens on delete

A profile still assigned to a person or group cannot be deleted. Otherwise those people would quietly fall back to the default profile and their capacity would change without anyone touching them.

The default profile itself cannot be deleted at all — without it, a person with no assignment would have no working time anywhere, and the plant would report zero capacity everywhere.
    `.trim(),
  },
  {
    slug: 'holidays',
    title: 'Holidays and calendar exceptions',
    category: 'explanation',
    routes: ['/working-time'],
    body: `
## Holidays and calendar exceptions

Exceptions override the week profile for individual days, **per site**. Three cases are possible, and all three occur in real plant calendars:

- **Zero minutes** — public holiday, shutdown, bridge day.
- **Less than the profile** — a half day, as 24 and 31 December usually are.
- **More than zero on a normally free day** — a designated working Saturday.

That is why it is a number of minutes and not a checkbox: a checkbox could only express the first case.

### Why holidays are maintained by hand

Capado keeps its own table rather than querying a holiday library. Plant calendars routinely contain non-working days that are not statutory anywhere — carnival Monday and bridge days, for instance. A library would have reported capacity for those days that does not exist.

### Effect on conflicts

A day with zero minutes produces **no demand and therefore no conflict**. An assignment running across a holiday quietly delivers less time than planned. That is a shortfall rather than an over-allocation, and it appears under unmet requirements instead of in the conflict list.
    `.trim(),
  },
  {
    slug: 'sites',
    title: 'Sites',
    category: 'reference',
    routes: ['/working-time'],
    body: `
## Sites

A site groups the holiday calendar. Two plants with different shutdown periods are two sites.

| Field | Meaning |
|-------|---------|
| Name | The site's name |
| Default | The site resources fall back to when none is set. Exactly one carries this flag. |
| Region code | Only a hint for the holiday import script, e.g. DE-BY. **Never** read at runtime. |
| Active | Flag for retiring a site instead of deleting it |

The region code is deliberately not an automation: the holiday table is the single source of truth. The code only helps pre-fill it once and changes nothing afterwards.
    `.trim(),
  },

  // --- Scheduling ---
  {
    slug: 'dependencies',
    title: 'Dependencies between work packages',
    category: 'explanation',
    routes: ['/projects'],
    body: `
## Dependencies between work packages

There is **one** relationship type: **finish to start**, with an optional lag in working days. Package B starts after package A finishes, plus the lag.

### Why only one type

Start-to-start and finish-to-finish are expressible by reordering the pair, and start-to-finish is almost never what anybody means. What a plant actually needs beyond finish-to-start is **waiting time** — paint has to cure before the next step can begin — and a lag covers that without a second relationship type.

The lag counts in **working days**, not calendar days. A weekend is not curing time anybody planned.

### A violation does not block

When the dates contradict the dependency, that is a **warning**, not a rejected save. Enforcing it would mean the system reschedules work on the planner's behalf. A planner who cannot enter what they actually intend to do goes back to the spreadsheet — and nothing is gained.

### What is rejected

**Cycles.** If A waits on B and B waits on A, there is no valid reading at all, and every consumer would have to defend against it. Such links are refused at the write.
    `.trim(),
  },
  {
    slug: 'critical-path',
    title: 'Float and the critical path',
    category: 'explanation',
    routes: ['/projects', '/project-overview'],
    body: `
## Float and the critical path

Two passes over the dependencies: forwards for the earliest each package can start and finish, backwards for the latest it may. The gap between them is **float** — how long a package can slip before the project does.

**Zero float means the package is on the critical path.** Delaying it delays the whole project.

### Three things that explain the numbers

**Duration comes from the lead time where one exists** — otherwise from the entered dates. A package stating "34 working days" describes how long the work takes; one with only a start and an end describes when it was scheduled, which may be longer than the work needs. Preferring the lead time lets the analysis reflect the process rather than the calendar somebody typed in.

**The backwards pass starts from the customer commitment when there is one** — otherwise from the planned project end. A critical path measured against a planned end that already misses the customer date would report comfortable float on a project that is late.

**Everything is in working days.** Float of two means two working days, not two calendar days that might both be a weekend.
    `.trim(),
  },

  // --- Qualifications ---
  {
    slug: 'qualifications',
    title: 'Qualifications and their validity',
    category: 'explanation',
    routes: ['/people'],
    body: `
## Qualifications and their validity

A qualification satisfies a requirement only when three conditions hold. What each condition **refuses** is the interesting part.

### Validity is checked against the work, not against today

A certificate expiring in March does not cover work planned for April. Asking "is it valid now" would answer yes and be wrong.

The validity window must **cover the whole assignment**. If a certificate lapses mid-job, the requirement counts as unmet for that job — not half met. That is precisely what an expiry date is for.

### An unrecorded level does not satisfy a minimum

Levels run from 1 to 5. No level recorded means **nobody assessed it** — which is not evidence of being good enough. Reading an empty level in the person's favour would be the wrong direction for a check that exists to keep unqualified people off a task.

### No requirement, no problem

A requirement without a minimum level is met by any level held, including none. It did not ask.
    `.trim(),
  },
  {
    slug: 'action-required',
    title: 'What needs attention',
    category: 'explanation',
    routes: ['/'],
    body: `
## What needs attention

One list of everything that needs somebody: expiring qualifications, customer commitments that no longer fit, violated dependencies, requirements nobody covers.

Capado always detected these conditions. What it could not do was tell anyone — each check lived where it was computed, so seeing all of them meant opening four screens and knowing where to look.

### The hard part is suppression

A plan of any size produces hundreds of true statements, and a list of hundreds of true statements gets ignored within a week. At that point the mechanism is worse than none, because everyone believes they are being warned. Three limits:

**Horizon.** Every finding carries a due date; anything beyond it is dropped. The default reach is 90 days. A qualification lapsing in 2029 is true and useless.

**Urgency from proximity, not from kind.** Within 14 days a finding is critical — too close to solve by rescheduling. Up to 45 days it is a warning, beyond that informational. An expiry next week therefore outranks a dependency violation next year, because that is the order somebody would actually work in.

**Anything already due is always critical**, however long ago. Otherwise an expired certificate would grow quieter over time — burying exactly the findings nobody acted on.

**One finding per subject.** One line per person per skill, not one per affected assignment: ten assignments blocked by one lapsed certificate is **one** problem.

All three time limits are configurable in the settings.
    `.trim(),
  },

  // --- Traceability ---
  {
    slug: 'planning-freeze',
    title: 'Planning freeze',
    category: 'explanation',
    routes: ['/settings', '/planning'],
    body: `
## Planning freeze

A plan that has already been reported on should not change underneath the report. Capado can record what the plan looked like (baselines) and who changed it (the audit log) — but neither prevents somebody quietly moving last month's assignment so this month's numbers add up. The freeze is the preventive half.

### Both states count

The non-obvious part: a change has **two** states, and both are checked. If only the destination were checked, somebody could drag a frozen booking out of the frozen period — the edit would then lie entirely in the open period while having rewritten frozen history.

So the check takes the state **before and after**, and blocks if **either** touches the freeze.

The consequence, stated plainly: an assignment straddling the freeze boundary **cannot be edited at all** while the freeze stands, not even the part lying in the open period. That is a real restriction rather than an oversight. It is the only reading under which the frozen period is actually stable.

A period is closed by day, never by hour — including for infrastructure bookings, which otherwise work to the minute.

### Who may override

Administrators, and the audit log is what that is for. The alternative — nobody, ever — makes correcting a genuine data-entry error impossible and turns the freeze from a safeguard into a trap. Making it advisory for everybody would make it decoration.
    `.trim(),
  },
  {
    slug: 'baselines',
    title: 'Baselines and comparison',
    category: 'explanation',
    routes: ['/baselines'],
    body: `
## Baselines and comparison

A baseline records the plan at a point in time. Its value is not in the recording, though — it is in the **comparison**: what has changed since sign-off.

A baseline on its own answers no question a printout could not answer. The diff between the recorded plan and the current one answers the only question anybody actually asks in a meeting.

### Retention

Baselines are kept **indefinitely** by default. That is deliberate: a baseline is the evidence of what was committed to, and discarding it automatically after a period would be worse than keeping it. Set a period in the settings if you need one; the audit log, by contrast, is kept for 24 months by default.

### Not a substitute for the freeze

A baseline records what was. It does not stop the live plan from changing retroactively — that is what the planning freeze is for. The two complement each other: the baseline is the evidence, the freeze is the prevention.
    `.trim(),
  },

  // --- Views and reporting ---
  {
    slug: 'team-week',
    title: 'The team week',
    category: 'explanation',
    routes: ['/planning'],
    body: `
## The team week

One row per person, one column per day. The question is: **who does what on Tuesday.**

This is deliberately not the Gantt chart. A Gantt answers when a work package runs, grouped by project and drawn over a timeline. A team week is a shift list. One is for a planner at a screen, the other for a sheet on a wall — reshaping either into the other would produce the worse version of both.

### Three rules, and what each refuses

**A day shows every assignment, not the largest one.** Somebody split across two work packages has two entries in that cell. A shift list that silently shows one of them is worse than one that looks crowded — the person would turn up for half their day.

**Absence and work are shown together, not exclusively.** A 50% absence still leaves half a working day. Suppressing the assignment because somebody "is away" is how nobody hears about work that is still planned.

**Days with no calendar time are marked, not left blank.** A blank cell reads as "nothing planned", which is indistinguishable from "the plant is closed". A shutdown and an empty Tuesday are two different messages to somebody reading the sheet.
    `.trim(),
  },
  {
    slug: 'customers-and-reports',
    title: 'Customers and Excel reports',
    category: 'explanation',
    routes: ['/projects', '/project-overview'],
    body: `
## Customers

A project inherits its customer from the folder it sits in. The rule has three parts:

**The project's own customer wins.** Set explicitly, it is a correction somebody made on purpose. Letting the folder override it would make the field unusable.

**Otherwise the folder's customer applies, walking up the tree.** A sub-folder naming no customer belongs to whatever its parent does — that is what nesting means here: an order splits into stages, and the stages are for the same customer.

**Nothing is invented.** A project in no folder, or in a tree where nobody names a customer, has **no** customer — not a placeholder and not the first customer in the list. Guessing would put a name on a report that nobody entered.

## Excel reports

**Utilization report** — weeks across, people down. It calls the same computation the dashboard charts use, so a number in the file and the same number on screen cannot drift apart. A spreadsheet that contradicts the dashboard is worse than none: somebody then has to decide which of the two is lying.

The file has **two sheets**, because two different people read it. The wide sheet is for looking at: one row per person, one column per week. The long sheet is for working with: one row per person-week, which is the shape a pivot table needs. A wide sheet cannot be pivoted, and asking somebody to unpivot it by hand is how numbers get retyped and go wrong.

**Project status report** — the state of each project, with its customer and the order numbers of both folder and project. Both are shown rather than one silently winning.

The utilization report is capped at 104 weeks. The cap exists because utilization is computed per person per week, and an open-ended range would let one request run for minutes.
    `.trim(),
  },
  {
    slug: 'my-schedule',
    title: 'My schedule',
    category: 'explanation',
    routes: ['/my-plan'],
    body: `
## What this page shows

Your own assignments, absences and qualifications — and **only** yours. The page has no way to open somebody else's schedule: which person is meant is decided solely by the link on your account, not by a field on this page and not by a value in the address bar.

The page is **read-only**. Changes are made by whoever plans the work. It also changes nothing about who may see what: the same data was already visible to planners and leaders. What is new is that **the affected person** can read it too.

## "Account not linked to a person yet"

This message does not mean nothing is scheduled for you. It means nobody has recorded **which** scheduled person your account belongs to.

The difference matters, which is why there is a message here rather than an empty table: an empty table would lead you to conclude you are scheduled for nothing — when in truth a full week may be planned for you and only the link is missing.

Somebody with administrator rights fixes this in **User Management**: edit the account and pick the person under *Linked person*. The link is deliberately made by hand, per account. Guessing it automatically from a name or an email address would expose the wrong person's schedule whenever two people share a name — and a mistake of that kind is a data protection incident, not a cosmetic flaw.

## How to read the entries

**Assignments** name the project, work package, period and your share. A share of 50% means half of your working time in that period, not half of the work package.

**Absences** carry a status. *Requested* means the absence is accounted for in the plan but has not been confirmed. You cannot file a request here — the page shows the state, it does not run an approval process.

**Qualifications** name the skill, attribute, level and validity. Where it says **not assessed**, nobody has recorded a level; that is explicitly **not** the same as the lowest level. **No expiry** means no end date is recorded — where a qualification does expire, keep an eye on the date, because past it the qualification no longer counts towards planning.

## What the page deliberately does not do

It produces **no new analysis**. It shows exactly the values already in the plan, only to you as well.

There is **no calendar feed** and **no request workflow** on this page. Both are conceivable but not built — and while they are not built, nothing here hints that they are.
    `.trim(),
  },
]
