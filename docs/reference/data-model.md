# Data Model

## Entity Relationship Diagram

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│   Project    │──1:N──│ WorkPackage   │──1:N──│  Assignment  │
│              │       │              │       │              │
│ name         │       │ name         │       │ resource_id  │
│ start_date   │       │ start_date   │       │ resource_type│
│ end_date     │       │ end_date     │       │ start_date*  │
└──────────────┘       │ project_id   │       │ end_date*    │
                       └──────┬───────┘       │ alloc_%*     │
                              │               │ start_at**   │
                              │ 1:N           │ end_at**     │
                    ┌─────────▼──────────┐    └──────┬───────┘
                    │ WorkPackage        │           │
                    │ Requirement        │    resource_id (polymorphic)
                    │                    │           │
                    │ skill_id           │    ┌──────┴──────────────────────────────┐
                    │ skill_attribute_id │    │                                     │
                    │ quantity           │    │                                     │
                    └────────────────────┘    │                                     │
                                             │                                     │
          ┌──────────────────┐    ┌──────────▼─────────┐    ┌──────────────────────▼───┐
          │ ResourceGroup    │    │ PersonalResource   │    │ InfrastructureResource   │
          │                  │    │                    │    │                          │
          │ name             │◄───│ name               │    │ name                     │
          │ parent_id (self) │    │ group_id           │    │ group_id                 │
          └──────────────────┘    │ is_active          │    │ is_active                │
                    ▲             └─────────┬──────────┘    └──────────┬───────────────┘
                    │                       │                          │
                    └───────────────────────┼──────────────────────────┘
                                            │
          ┌─────────────────────────────────┼─────────────────────────────────┐
          │                                 │                                 │
┌─────────▼──────────┐          ┌───────────▼────────────┐         ┌─────────▼──────────┐
│ PersonalResSkill   │          │      Absence           │         │ InfraResourceSkill │
│ (join table)       │          │                        │         │ (join table)       │
│                    │          │ resource_id            │         │                    │
│ resource_id        │          │ resource_type          │         │ resource_id        │
│ skill_attribute_id │          │ reason (enum)          │         │ skill_attribute_id │
└─────────┬──────────┘          │ start_date             │         └─────────┬──────────┘
          │                     │ end_date               │                   │
          └──────────┬──────────│ allocation_percent     │───────────────────┘
                     │          │ note                   │
                     │          └────────────────────────┘
                     │
           ┌─────────▼──────────┐
           │  SkillAttribute    │
           │                    │
           │ skill_id           │
           │ name               │
           │ UNIQUE(skill,name) │
           └─────────┬──────────┘
                     │ N:1
           ┌─────────▼──────────┐
           │      Skill         │
           │                    │
           │ name (unique)      │
           │ resource_type      │
           └────────────────────┘

          ┌────────────────────┐          ┌────────────────────┐
          │      Conflict      │          │ ConflictAssignment │
          │                    │──1:N─────│ (join table)       │
          │ resource_id        │          │                    │
          │ resource_type      │          │ conflict_id        │
          │ start_date         │          │ assignment_id      │
          │ end_date           │          └────────────────────┘
          │ total_assigned_%   │
          │ available_%        │
          └────────────────────┘

          ┌────────────────────┐          ┌────────────────────┐
          │      User          │          │   RefreshToken     │
          │                    │          │                    │
          │ email (unique)     │──1:N─────│ user_id            │
          │ name               │          │ token_hash         │
          │ password_hash      │          │ expires_at         │
          │ role (enum)        │          │ revoked_at         │
          │ scope_group_ids    │          └────────────────────┘
          │ scope_project_ids  │
          │ is_active          │
          │ must_change_pwd    │
          │ external_id        │
          └────────────────────┘

     ┌──────────────────────────┐     ┌──────────────────────────────────┐
     │ WorkPackageTemplate      │     │ WorkPackageTemplateRequirement   │
     │                          │──N──│                                  │
     │ name                     │     │ template_id                      │
     │ description              │     │ skill_id                         │
     └──────────────────────────┘     │ skill_attribute_id               │
                                      │ quantity                         │
                                      └──────────────────────────────────┘
```

`*` = personal assignment fields, `**` = infrastructure assignment fields

---

## Tables

### `projects`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Project name |
| `folder_id` | UUID | FK → `project_folders.id`, INDEX, NULLABLE | Folder the project sits in. `NULL` means unfiled, which is the normal default |
| `position` | INTEGER | INDEX, NOT NULL | Manual order **within the folder** — units of one order are worked through in sequence. Not a global order |
| `external_ref` | VARCHAR(128) | INDEX, NULLABLE | Identifier from whatever system the customer already uses (unit number, serial) |
| `customer_id` | UUID | FK → `customers.id`, INDEX, NULLABLE | Explicitly set customer. When `NULL`, the customer is inherited from the folder tree upwards; nothing is invented if no folder names one |
| `priority` | VARCHAR(8) | INDEX, NOT NULL | Planning priority |
| `start_date` | DATE | NOT NULL | Project start |
| `end_date` | DATE | NOT NULL | What is PLANNED |
| `committed_delivery_date` | DATE | INDEX, NULLABLE | What was PROMISED, or `NULL` when nothing was. Deliberately separate from `end_date`: one field cannot hold both a commitment and a plan, because the moment they differ is the moment that matters |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `work_packages`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `project_id` | UUID | FK → `projects.id`, INDEX | Parent project |
| `name` | VARCHAR(255) | NOT NULL | Work package name |
| `start_date` | DATE | NOT NULL | Start date |
| `end_date` | DATE | NOT NULL | End date |
| `completed_at` | DATETIME | INDEX, NULLABLE | When the package was finished. A timestamp on the PACKAGE, not an assessment of a person — the distinction matters, because this is the only completion signal in the system and it must not be read as performance data |
| `lead_time_working_days` | INTEGER | NULLABLE | Working days the package needs. Used to test whether a promised date is reachable; the plan warns instead of silently shifting the date. `NULL` means untested |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `work_package_requirements`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `work_package_id` | UUID | FK → `work_packages.id`, INDEX | Parent work package |
| `skill_id` | UUID | FK → `skills.id`, INDEX | Required skill |
| `skill_attribute_id` | UUID | FK → `skill_attributes.id`, INDEX, NULLABLE | Specific attribute (optional) |
| `quantity` | INTEGER | NOT NULL, ≥ 1 | Number of resources needed |
| `requirement_mode` | VARCHAR(10) | INDEX, NOT NULL | How `quantity` is read: as a **headcount** (this many bodies) or as **effort in FTE** (this much capacity, however distributed). The two invert each other's arithmetic, which is why the mode is stored rather than inferred |
| `min_allocation_percent` | FLOAT | NOT NULL | Smallest share of a normative day an assignment against this requirement may carry |
| `min_level` | INTEGER | NULLABLE | Minimum proficiency 1–5. `NULL` means the requirement does not grade — a resource whose level is unassessed still matches |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |

---

### `assignments`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `resource_id` | UUID | INDEX | Assigned resource |
| `resource_type` | VARCHAR | INDEX | `personal` or `infrastructure` |
| `work_package_id` | UUID | FK → `work_packages.id`, INDEX | Target work package |
| `start_date` | DATE | INDEX, NULLABLE | Start (personal only) |
| `end_date` | DATE | INDEX, NULLABLE | End (personal only) |
| `allocation_percent` | FLOAT | NULLABLE, > 0, ≤ 100 | Allocation (personal only) |
| `start_at` | TIMESTAMP | NULLABLE | Start (infrastructure only) |
| `end_at` | TIMESTAMP | NULLABLE | End (infrastructure only) |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `absences`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `resource_id` | UUID | INDEX | Resource on leave |
| `resource_type` | VARCHAR | NOT NULL | `personal` or `infrastructure` |
| `reason` | VARCHAR | NOT NULL | `planned` or `unplanned` — **only those two**. The earlier values (vacation, sick, maintenance, training, other) were removed because `sick` is health data under Art. 9 GDPR even without a diagnosis, and the cause was never needed for the capacity calculation: only period and share enter it. `other` was folded into `unplanned` as well, so the value genuinely aggregates different causes instead of being a synonym for the removed one |
| `status` | VARCHAR(20) | NOT NULL | `provisional` or `confirmed`. Provisional absences reduce capacity in the plan but have not been approved |
| `start_date` | DATE | INDEX | Absence start |
| `end_date` | DATE | INDEX | Absence end |
| `allocation_percent` | FLOAT | NOT NULL, > 0, ≤ 100 | Capacity reduction (default 100) |
| `note` | VARCHAR(500) | NULLABLE | Optional note |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `personal_resources`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Resource name |
| `group_id` | UUID | FK → `resource_groups.id`, INDEX | Organizational group |
| `site_id` | UUID | FK → `sites.id`, INDEX, NULLABLE | Owning site — determines which holiday calendar applies |
| `is_active` | BOOLEAN | INDEX, default TRUE | Soft-delete flag |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `infrastructure_resources`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Resource name |
| `group_id` | UUID | FK → `resource_groups.id`, INDEX | Organizational group |
| `site_id` | UUID | FK → `sites.id`, INDEX, NULLABLE | Owning site |
| `is_active` | BOOLEAN | INDEX, default TRUE | Soft-delete flag |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `resource_groups`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Group name |
| `resource_type` | VARCHAR(20) | NOT NULL, INDEX | `personal` or `infrastructure` |
| `parent_id` | UUID | FK → `resource_groups.id`, INDEX, NULLABLE | Parent group. Read by `WorkingTimeService` to inherit a work-profile binding: the parent's binding applies unless this group carries its own. No depth limit is enforced in code; cycles are guarded where the chain is walked |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `sites`

Top organizational level inside the one organization this deployment serves
([ADR-003](../decisions/003-single-tenant-and-sites.md)). Owns the working-time
calendar, because public holidays differ per location and therefore change the
arithmetic rather than just a label.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Site name |
| `region_code` | VARCHAR(16) | NULLABLE | Region hint for the holiday seed script, e.g. `DE-BY`. Never read at runtime |
| `is_default` | BOOLEAN | INDEX, default FALSE | Fallback site for resources without one |
| `is_active` | BOOLEAN | INDEX, default TRUE | Soft-delete flag |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `holidays`

Calendar exceptions for one site and one date. Carries minutes rather than a
boolean so half days and designated working Saturdays are ordinary cases.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `site_id` | UUID | FK → `sites.id`, INDEX | Owning site |
| `day` | DATE | INDEX | The date this exception applies to |
| `name` | VARCHAR(255) | NOT NULL | Label, e.g. "Rosenmontag" |
| `working_minutes` | INTEGER | NOT NULL, 0–1440, default 0 | 0 = non-working; below the profile = half day; above 0 on a free day = working Saturday |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

**Unique constraint:** `uq_holidays_site_day` on `(site_id, day)`

---

### `work_week_profiles`

Reusable weekly availability patterns in minutes per weekday. Named and shared,
because a plant has a handful of patterns and hundreds of resources. This is
where part-time and shift patterns live.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | UNIQUE, NOT NULL | Profile name |
| `description` | VARCHAR(1000) | NULLABLE | Optional description |
| `monday_minutes` … `friday_minutes` | INTEGER | NOT NULL, 0–1440, default 480 | Available minutes per weekday |
| `saturday_minutes`, `sunday_minutes` | INTEGER | NOT NULL, 0–1440, default 0 | Weekend, free by default |
| `is_default` | BOOLEAN | INDEX, default FALSE | Fallback for resources without a binding |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

**Unique constraint:** `uq_work_week_profiles_name` on `(name)`

---

### `resource_work_profiles`

Binds a resource to a week profile for a validity range. Dated rather than a
plain foreign key on the resource, so a contract change is a new row and the
capacity of a past period stays reproducible.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `resource_id` | UUID | INDEX | Bound resource |
| `profile_id` | UUID | FK → `work_week_profiles.id`, INDEX | Applied profile |
| `group_id` | UUID | FK → `resource_groups.id`, INDEX, NULLABLE | Binds the profile to a whole group rather than one resource. `NULL` means the binding is for the single resource named above |
| `valid_from` | DATE | INDEX | First day the binding applies |
| `valid_until` | DATE | INDEX, NULLABLE | Last day, or NULL for open-ended |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

**Check constraint:** `valid_until IS NULL OR valid_until >= valid_from`

---

### `infrastructure_availability_windows`

Clock windows during which an infrastructure resource may be booked
([ADR-005](../decisions/005-infrastructure-availability-windows.md)). Several
rows per weekday express a multi-shift operation. A resource with **no** rows is
available around the clock, which preserves the behaviour that existed before
windows.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `resource_id` | UUID | FK → `infrastructure_resources.id`, INDEX | Owning resource |
| `weekday` | INTEGER | INDEX, 0–6 | Monday = 0 through Sunday = 6 |
| `start_time` | TIME | NOT NULL | Window start, local clock time |
| `end_time` | TIME | NOT NULL, <> `start_time` | Window end; before `start_time` means the window runs past midnight |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `organization_settings`

Single-row settings table. Renamed from `tenant_settings`, which implied a
multi-tenancy model the project has rejected — it was only ever a singleton.

It started as branding alone and has since absorbed retention, the maintenance scheduler, the digest
thresholds and the SMTP configuration. Grouped below by what they govern, because a flat list of 24
columns hides which ones belong together.

**Branding**

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `company_name` | VARCHAR(255) | NOT NULL, default `Capado` | Header name |
| `company_subtitle` | VARCHAR(255) | NOT NULL, default `''` | Subtitle |
| `logo_url` | VARCHAR(1024) | NOT NULL, default `''` | External logo URL |
| `primary_color` | VARCHAR(50) | NOT NULL, default `blue` | UI accent color |
| `logo_data` | BYTEA | NULLABLE | Uploaded logo, max 2 MB, deferred on read |
| `logo_mime_type` | VARCHAR(100) | NULLABLE | MIME type of the upload |

**Retention and planning**

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `audit_retention_months` | INTEGER | NOT NULL | How long audit entries are kept. `0` means unlimited, which is a deliberate choice rather than a state reached by omission. Enforced by a scheduled job — without that job nothing is deleted, whatever this says |
| `baseline_retention_months` | INTEGER | NOT NULL | How long baselines are kept |
| `planning_freeze_before` | DATE | NULLABLE | Plans before this date may not be changed. `NULL` means no freeze |

**Maintenance scheduler**

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `scheduler_enabled` | BOOLEAN | NOT NULL | Master switch for the recurring maintenance run |
| `maintenance_hour` | INTEGER | NOT NULL | Hour of day (0–23) the run starts |

**Digest thresholds**

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `digest_horizon_days` | INTEGER | NOT NULL | How far ahead the digest looks at all |
| `digest_critical_days` | INTEGER | NOT NULL | Horizon within which a finding counts as critical |
| `digest_warning_days` | INTEGER | NOT NULL | Horizon within which a finding counts as a warning |
| `digest_max_findings` | INTEGER | NOT NULL | Cap on findings per digest, so one bad day does not produce an unreadable mail |
| `digest_recipients` | VARCHAR(2000) | NOT NULL, default `''` | Comma-separated addresses |

**SMTP**

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `smtp_enabled` | BOOLEAN | NOT NULL | Whether mail is sent at all |
| `smtp_host` | VARCHAR(255) | NOT NULL, default `''` | Server host |
| `smtp_port` | INTEGER | NOT NULL | Server port |
| `smtp_use_tls` | BOOLEAN | NOT NULL | STARTTLS |
| `smtp_username` | VARCHAR(255) | NOT NULL, default `''` | Login name |
| `smtp_password` | VARCHAR(512) | NOT NULL, default `''` | **Stored in plaintext** — see [known limitations](known-limitations.md). Redacted from the audit log, so a change is recorded as an event without the value |
| `smtp_from_address` | VARCHAR(255) | NOT NULL, default `''` | Envelope sender |

**Singleton**

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `singleton_key` | VARCHAR(10) | UNIQUE, NOT NULL, default `default` | Singleton sentinel |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

**Unique constraint:** `uq_organization_settings_singleton` on `(singleton_key)`

---

### `conflicts`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `resource_id` | UUID | INDEX | Affected resource |
| `resource_type` | VARCHAR | NOT NULL | `personal` or `infrastructure` |
| `cause` | VARCHAR(20) | INDEX, NOT NULL | What kind of conflict this is — overload, a missing qualification, or a violated availability window. Recomputed with the conflict, never entered |
| `start_date` | DATE | INDEX | Conflict period start |
| `end_date` | DATE | INDEX | Conflict period end |
| `total_assigned_percent` | FLOAT | NOT NULL | Peak demand during the period, derived from minutes |
| `available_percent` | FLOAT | NOT NULL | Availability on the day with the largest shortfall, derived from minutes — no longer always 100 |
| `detected_at` | TIMESTAMP | NOT NULL | Detection timestamp |

---

### `conflict_assignments`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `conflict_id` | UUID | PK, FK → `conflicts.id` | Parent conflict |
| `assignment_id` | UUID | PK, FK → `assignments.id`, INDEX | Contributing assignment |

---

### `skills`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(100) | UNIQUE, NOT NULL | Skill name |
| `resource_type` | VARCHAR(20) | NOT NULL, default `personal` | Scoped to personal or infrastructure |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |

---

### `skill_attributes`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `skill_id` | UUID | FK → `skills.id`, INDEX | Parent skill |
| `name` | VARCHAR(100) | NOT NULL | Attribute name |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |

**Unique constraint:** `uq_skill_attributes_skill_name` on `(skill_id, name)`

---

### `personal_resource_skills`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `resource_id` | UUID | FK → `personal_resources.id`, INDEX | Resource |
| `skill_attribute_id` | UUID | FK → `skill_attributes.id`, INDEX | Assigned attribute |
| `valid_from` | DATE | NULLABLE | Qualification holds from this date. `NULL` means no start bound |
| `valid_until` | DATE | INDEX, NULLABLE | Qualification expires after this date. `NULL` means no expiry. Matching tests the qualification against the date the WORK happens, not against today — a certificate expiring mid-order is a conflict, not a surprise |
| `level` | INTEGER | NULLABLE | Proficiency 1–5. `NULL` means **nobody has assessed it**, which is not the same as level 1 |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |

**Unique constraint:** `uq_personal_resource_skills_resource_attribute` on `(resource_id, skill_attribute_id)`

---

### `infrastructure_resource_skills`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `resource_id` | UUID | FK → `infrastructure_resources.id`, INDEX | Resource |
| `skill_attribute_id` | UUID | FK → `skill_attributes.id`, INDEX | Assigned attribute |
| `valid_from` | DATE | NULLABLE | Capability holds from this date. `NULL` means no start bound |
| `valid_until` | DATE | INDEX, NULLABLE | Capability expires after this date — an inspection interval on a machine behaves like a certificate on a person. `NULL` means no expiry |
| `level` | INTEGER | NULLABLE | Grading 1–5. `NULL` means nobody assessed it |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |

**Unique constraint:** `uq_infrastructure_resource_skills_resource_attribute` on `(resource_id, skill_attribute_id)`

---

### `users`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL | Login email |
| `name` | VARCHAR(255) | NOT NULL | Display name |
| `password_hash` | VARCHAR(255) | NOT NULL | Bcrypt hash |
| `role` | ENUM(admin, editor, viewer) | NOT NULL, default `viewer` | Access level |
| `scope_group_ids` | UUID[] | NULLABLE | Editor group scope |
| `scope_project_ids` | UUID[] | NULLABLE | Editor project scope |
| `is_active` | BOOLEAN | NOT NULL, default TRUE | Soft-delete flag |
| `must_change_password` | BOOLEAN | NOT NULL, default TRUE | Force password change |
| `external_id` | VARCHAR(255) | NULLABLE | External system identifier |
| `resource_id` | UUID | FK → `personal_resources.id`, NULLABLE, UNIQUE, ON DELETE SET NULL | The scheduled person this account belongs to. What lets that person read their own plan |
| `created_at` | TIMESTAMP | INDEX, NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `refresh_tokens`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `user_id` | UUID | FK → `users.id`, INDEX | Token owner |
| `token_hash` | VARCHAR(255) | INDEX, NOT NULL | SHA-256 hash of token |
| `expires_at` | TIMESTAMP | NOT NULL | Expiration time |
| `revoked_at` | TIMESTAMP | NULLABLE | Revocation time (null = active) |
| `replaced_by_id` | UUID | NULLABLE | The token this one was rotated into. Makes the rotation chain walkable, which is what turns "an old token was presented" into "this family is compromised" — see ADR-002 |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |

---

### `work_package_templates`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Template name |
| `description` | VARCHAR(1000) | NULLABLE | Optional description |
| `lead_time_working_days` | INTEGER | NULLABLE | Default lead time copied onto work packages created from this template |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

---

### `work_package_template_requirements`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `template_id` | UUID | FK → `work_package_templates.id`, INDEX | Parent template |
| `skill_id` | UUID | FK → `skills.id` | Required skill |
| `skill_attribute_id` | UUID | FK → `skill_attributes.id`, NULLABLE | Specific attribute (optional) |
| `quantity` | INTEGER | NOT NULL, ≥ 1 | Number of resources needed |
| `requirement_mode` | VARCHAR(10) | NOT NULL | Headcount or effort in FTE, copied onto the work package requirement when the template is applied |
| `min_allocation_percent` | FLOAT | NOT NULL | Copied onto the requirement |
| `min_level` | INTEGER | NULLABLE | Copied onto the requirement. `NULL` means no grading |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |

---

### `project_folders`

Optional grouping above projects, nesting to any depth (ADR-008). The unit that gets scheduled is the
project, not the folder — a folder is the order, and the projects inside it are what is worked on.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Folder name |
| `parent_id` | UUID | FK → `project_folders.id`, NULLABLE, INDEX | Parent folder; NULL at the top level |
| `position` | INTEGER | NOT NULL, INDEX, default 0 | Order among siblings |
| `external_ref` | VARCHAR(128) | NULLABLE, INDEX | The folder's own identifier — typically an order number |
| `customer_id` | UUID | FK → `customers.id`, NULLABLE, INDEX | Customer; inherited downward by projects that name none |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

Deleting a folder does not delete its projects: they survive, unfiled.

---

### `customers`

Replaced a free-text column where "Acme" and "Acme GmbH" were two customers and nothing could say they
were one.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Customer name; unique case-insensitively |
| `reference` | VARCHAR(128) | NOT NULL, default `''` | The operator's own customer number |
| `note` | VARCHAR(1000) | NOT NULL, default `''` | Free note |
| `is_active` | BOOLEAN | NOT NULL, default true | Soft-delete flag, consistent with resources |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

Uniqueness is enforced case-insensitively rather than by a plain unique index, which would happily
accept "Acme" beside "acme" and reintroduce exactly the duplication this table exists to prevent.

A project's customer is resolved through `resolve_customer_id`, never by reading `projects.customer_id`
directly — a caller reading that column alone loses every project that inherits from its folder, which
is the normal case.

---

### `work_package_dependencies`

One relationship type: **finish to start**, with an optional lag in working days.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `predecessor_id` | UUID | FK → `work_packages.id`, NOT NULL, INDEX | Must finish first |
| `successor_id` | UUID | FK → `work_packages.id`, NOT NULL, INDEX | Starts after the predecessor plus the lag |
| `lag_working_days` | INTEGER | NOT NULL, default 0 | Waiting time — curing, drying — in working days, not calendar days |
| `created_at` | TIMESTAMP | NOT NULL | Creation timestamp |
| `updated_at` | TIMESTAMP | NOT NULL | Last update timestamp |

**Unique constraint:** `uq_work_package_dependencies_pair` on `(predecessor_id, successor_id)`

Dates that contradict a dependency are a **warning**, not a rejected write. Cycles are the exception and
are refused at the write, because a cycle has no valid reading and every consumer would otherwise have
to defend against it.

---

### `baselines`

A frozen snapshot of the schedule. The diff against the live plan is the deliverable, not the snapshot
itself (ADR-007).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `name` | VARCHAR(255) | NOT NULL | Label, e.g. "Customer sign-off ORD-4711" |
| `note` | VARCHAR(1000) | NULLABLE | Free note |
| `created_by` | UUID | FK → `users.id`, NULLABLE, INDEX | Who froze it; NULL once that user is deleted |
| `is_current` | BOOLEAN | NOT NULL, INDEX, default false | The reference baseline — never pruned, however old |
| `created_at` | TIMESTAMP | NOT NULL, INDEX | When it was frozen |

Retention defaults to **0, meaning keep everything** — deliberately the opposite of the audit log's 24
months. An audit entry accumulates as a side effect of working; a baseline is a state somebody
deliberately froze because it mattered.

---

### `baseline_entries`

The rows of a snapshot. Immutable: nothing edits a baseline, a wrong one is superseded by a new one.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `baseline_id` | UUID | FK → `baselines.id`, NOT NULL, INDEX | Owning baseline |
| `entity_type` | VARCHAR(64) | NOT NULL, INDEX | What was captured — project, work package, assignment |
| `entity_id` | UUID | NOT NULL, INDEX | The captured row's id |
| `payload` | JSON | NOT NULL | Field values at freeze time |

`payload` is generic JSON rather than typed columns, so a schema change to the captured entity does not
invalidate old snapshots — the price is that a value comes back as JSON gave it, so a date is a string.

---

### `audit_log`

Who changed what, and why where a reason was given (ADR-006).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `entity_type` | VARCHAR(64) | NOT NULL, INDEX | Which kind of row changed |
| `entity_id` | UUID | NOT NULL, INDEX | Which row |
| `action` | VARCHAR(7) | NOT NULL, INDEX | create, update or delete |
| `actor_id` | UUID | FK → `users.id`, NULLABLE, INDEX | Who; NULL for system actions and deleted users |
| `reason` | VARCHAR(500) | NULLABLE | Supplied where the UI asks for one, e.g. a freeze override |
| `changes` | JSON | NOT NULL | The changed fields, JSON-encoded — a date arrives back as a string |
| `recorded_at` | TIMESTAMP | NOT NULL, INDEX | When it happened |

Retention defaults to **24 months** and is applied by the maintenance job, not an external timer. An
empty `scheduled_job_runs` log means nothing has been deleted, so the configured period is an intention
rather than a state.

---

### `scheduled_job_runs`

Evidence that the maintenance jobs actually ran. Without it a retention period looks configured while
deleting nothing.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | UUID | PK | Primary key |
| `job_name` | VARCHAR(100) | NOT NULL, INDEX | Which job |
| `started_at` | TIMESTAMP | NOT NULL, INDEX | Start |
| `finished_at` | TIMESTAMP | NULLABLE | End; NULL while running or after a crash |
| `status` | VARCHAR(20) | NOT NULL, default `running` | running, succeeded or failed |
| `items_affected` | INTEGER | NULLABLE | Rows deleted — the number that proves retention applied |
| `detail` | VARCHAR(1000) | NOT NULL, default `''` | Failure reason, or a note that a batch limit was hit |

Pruning deletes in batches and loops up to 50 batches per run, so on a large backlog the first run may
not finish it. `detail` says so rather than reporting a clean sweep. A missed day is made up **once** on
return, not once per missed day.

---

## Allocation and Capacity

`allocation_percent` (1–100%) is what users author. The arithmetic underneath is
in **integer minutes**, because conflict detection sums across long ranges and
compares near a threshold, where float drift turns into phantom or missed
conflicts. See [ADR-004](../decisions/004-hours-as-capacity-base.md) and
[capacity-model.md](../explanation/capacity-model.md).

- **Personal resources**: `allocation_percent` is a share of a **normative
  working day** (480 minutes), not of the resource's own capacity. Supply comes
  from `work_week_profiles` corrected by `holidays` for the resource's site.
  A conflict is raised when demanded minutes exceed available minutes.
- **Infrastructure resources**: implicitly 100% exclusive. Any two overlapping
  time intervals on the same resource produce a conflict. Week profiles do not
  apply; availability windows do
  ([ADR-005](../decisions/005-infrastructure-availability-windows.md)).
- **Absences**: carry `allocation_percent` as a share of the resource's **own**
  day. They reduce availability rather than adding demand — summing them into
  load would count a vacation twice.

An assignment places demand only on days where calendar minutes are greater than
zero. Assignments are date ranges and span weekends; charging them there would
flag every Saturday and Sunday of every multi-week assignment.

`AbsenceReason` no longer contains `part_time`. A part-time employee is not
absent, and an absence cannot express a weekday shape — that belongs to
`work_week_profiles`.

## Unified Skill System

The skill system is shared between personal and infrastructure resources:

- **Skill**: A capability (e.g. "Assembly", "Welding", "Crane", "Painting").
  Scoped to a `resource_type` (personal or infrastructure).
- **SkillAttribute**: A specific variant of a skill (e.g. "Series Alpha", "50t", "Wet Area")
- Each attribute belongs to exactly one skill
- A resource is qualified by being assigned one or more skill attributes
- Same schema for both resource types, separate assignment tables

### Work Package Requirements

Skill requirements are stored directly on work packages via the
`work_package_requirements` table. Each requirement specifies a skill
(and optionally a specific attribute) plus a quantity. Templates
(`work_package_templates`) serve only as a convenience for copying
requirements when creating a work package — they are not referenced at
runtime.

## Erasing a person, and why it is hand-written

`resource_service.erase_personal_resource` deletes across seven tables explicitly. It reads like
something a cascade should do, and the reason it is not is in the schema: `absences`, `assignments`,
`conflicts` and `resource_work_profiles` carry `resource_id` with **no foreign key**, because one key
cannot target both resource tables. The database therefore neither cascades nor complains — a
forgotten table leaves rows behind and every query still succeeds.

That is why the function returns per-table counts and why `tests/test_erase_personal_resource.py`
asserts that a DELETE was issued against every one of them. The completeness of an erasure is not
something this schema can enforce, so it is asserted instead.

Order matters in two places: `conflict_assignments` before `conflicts`, or the join rows are orphaned;
and the audit sweep after the row deletions, because the audit listener writes its own `deleted`
entries on flush and sweeping first would leave them behind.

**Not touched:** `baseline_entries`. Baselines freeze projects, work packages and assignments, never
`personal_resources`, so a payload holds a `resource_id` UUID and no name — after erasure that
identifier resolves to nothing, which is what makes the deletion complete rather than cosmetic.

## Key Constraints

- `ResourceGroup.parent_id` → self-referencing FK. **No depth limit is enforced** — earlier text here claimed a maximum of 2 levels, and nothing in the code checks it. The traversal that reads it guards against cycles rather than depth
- `SkillAttribute` has a composite unique on `(skill_id, name)`
- `PersonalResourceSkill` has a composite unique on `(resource_id, skill_attribute_id)`
- `InfrastructureResourceSkill` has a composite unique on `(resource_id, skill_attribute_id)`
- `Skill.name` is unique (case-insensitive enforced at service level)
- `User.email` is unique
- Soft-delete via `is_active` flag (resources, users) — no hard deletes
- Delete protection: skills/attributes cannot be deleted while assignments reference them

## Assignment Dual-Shape Invariant

The `assignments` table stores two mutually exclusive field sets:

| resource_type | Required fields | Null fields |
|---------------|----------------|-------------|
| `personal` | `start_date`, `end_date`, `allocation_percent` | `start_at`, `end_at` |
| `infrastructure` | `start_at`, `end_at` | `start_date`, `end_date`, `allocation_percent` |

This invariant is enforced at the service layer, not via DB constraints.

## Authoritative Source

The SQLModel classes in `backend/app/models/` are the single source of truth.
Alembic auto-generates migrations from these definitions.
