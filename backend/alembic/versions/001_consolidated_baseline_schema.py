"""consolidated baseline schema

This single migration replaces the original 26-migration history (001..026), which was
collapsed once the project had no database that needed to be upgraded step by step — only
the Mac Mini test system, whose revision pointer is stamped straight to this baseline.

The body is the exact schema `alembic upgrade head` produced from the old 001..026 chain,
captured with `pg_dump --schema-only` and verified byte-for-byte against the live database
(the only differences were pg_dump's own random \\restrict tokens). It is applied as raw SQL
rather than reconstructed with op.* calls on purpose: autogenerate dropped the import for a
custom column type (app.utils.pg_types.UUIDArray) and produced a file that would not import,
so a hand-authored op.* baseline would have to be verified line by line against the same dump
this SQL already is. The enum types are created here too, so a fresh empty database reaches
the identical schema in one step.

Revision ID: 001
Revises:
Create Date: consolidated
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

BASELINE_SQL = r"""
CREATE TYPE public.absencereason AS ENUM (
    'planned',
    'unplanned'
);

CREATE TYPE public.auditaction AS ENUM (
    'created',
    'updated',
    'deleted'
);

CREATE TYPE public.conflictcause AS ENUM (
    'over_allocation',
    'booking_overlap',
    'outside_availability'
);

CREATE TYPE public.projectpriority AS ENUM (
    'low',
    'normal',
    'high',
    'critical'
);

CREATE TYPE public.requirementmode AS ENUM (
    'headcount',
    'effort_fte'
);

CREATE TYPE public.resourcetype AS ENUM (
    'personal',
    'infrastructure'
);

CREATE TYPE public.userrole AS ENUM (
    'admin',
    'editor',
    'viewer'
);

CREATE TABLE public.absences (
    id uuid NOT NULL,
    resource_id uuid NOT NULL,
    resource_type public.resourcetype NOT NULL,
    reason public.absencereason NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    allocation_percent double precision DEFAULT '100'::double precision NOT NULL,
    note character varying(500),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    status character varying(20) DEFAULT 'confirmed'::character varying NOT NULL,
    CONSTRAINT ck_absences_status CHECK (((status)::text = ANY ((ARRAY['provisional'::character varying, 'confirmed'::character varying])::text[])))
);

CREATE TABLE public.assignments (
    id uuid NOT NULL,
    resource_id uuid NOT NULL,
    resource_type public.resourcetype NOT NULL,
    work_package_id uuid NOT NULL,
    start_date date,
    end_date date,
    allocation_percent double precision,
    start_at timestamp without time zone,
    end_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE TABLE public.audit_log (
    id uuid NOT NULL,
    entity_type character varying(64) NOT NULL,
    entity_id uuid NOT NULL,
    action public.auditaction NOT NULL,
    actor_id uuid,
    reason character varying(500),
    changes json NOT NULL,
    recorded_at timestamp without time zone NOT NULL
);

CREATE TABLE public.baseline_entries (
    id uuid NOT NULL,
    baseline_id uuid NOT NULL,
    entity_type character varying(64) NOT NULL,
    entity_id uuid NOT NULL,
    payload json NOT NULL
);

CREATE TABLE public.baselines (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    note character varying(1000),
    created_by uuid,
    is_current boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE TABLE public.conflict_assignments (
    conflict_id uuid NOT NULL,
    assignment_id uuid NOT NULL
);

CREATE TABLE public.conflicts (
    id uuid NOT NULL,
    resource_id uuid NOT NULL,
    resource_type public.resourcetype NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    total_assigned_percent double precision NOT NULL,
    available_percent double precision NOT NULL,
    detected_at timestamp without time zone NOT NULL,
    cause public.conflictcause DEFAULT 'over_allocation'::public.conflictcause NOT NULL
);

CREATE TABLE public.customers (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    reference character varying(128) DEFAULT ''::character varying NOT NULL,
    note character varying(1000) DEFAULT ''::character varying NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE TABLE public.holidays (
    id uuid NOT NULL,
    site_id uuid NOT NULL,
    day date NOT NULL,
    name character varying(255) NOT NULL,
    working_minutes integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_holidays_working_minutes_range CHECK (((working_minutes >= 0) AND (working_minutes <= 1440)))
);

CREATE TABLE public.infrastructure_availability_windows (
    id uuid NOT NULL,
    resource_id uuid NOT NULL,
    weekday integer NOT NULL,
    start_time time without time zone NOT NULL,
    end_time time without time zone NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_infra_windows_times_differ CHECK ((end_time <> start_time)),
    CONSTRAINT ck_infra_windows_weekday_range CHECK (((weekday >= 0) AND (weekday <= 6)))
);

CREATE TABLE public.infrastructure_resource_skills (
    id uuid NOT NULL,
    resource_id uuid NOT NULL,
    skill_attribute_id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    valid_from date,
    valid_until date,
    level integer,
    CONSTRAINT ck_infrastructure_resource_skills_level_range CHECK (((level IS NULL) OR ((level >= 1) AND (level <= 5)))),
    CONSTRAINT ck_infrastructure_resource_skills_validity_order CHECK (((valid_from IS NULL) OR (valid_until IS NULL) OR (valid_from <= valid_until)))
);

CREATE TABLE public.infrastructure_resources (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    group_id uuid NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    site_id uuid
);

CREATE TABLE public.organization_settings (
    id uuid NOT NULL,
    company_name character varying(255) DEFAULT 'Capado'::character varying NOT NULL,
    company_subtitle character varying(255) DEFAULT ''::character varying NOT NULL,
    logo_url character varying(1024) DEFAULT ''::character varying NOT NULL,
    primary_color character varying(50) DEFAULT 'blue'::character varying NOT NULL,
    logo_data bytea,
    logo_mime_type character varying(100),
    updated_at timestamp without time zone NOT NULL,
    singleton_key character varying(10) DEFAULT 'default'::character varying NOT NULL,
    audit_retention_months integer DEFAULT 24 NOT NULL,
    baseline_retention_months integer DEFAULT 0 NOT NULL,
    digest_horizon_days integer DEFAULT 90 NOT NULL,
    digest_critical_days integer DEFAULT 14 NOT NULL,
    digest_warning_days integer DEFAULT 45 NOT NULL,
    digest_max_findings integer DEFAULT 100 NOT NULL,
    planning_freeze_before date,
    scheduler_enabled boolean DEFAULT true NOT NULL,
    maintenance_hour integer DEFAULT 2 NOT NULL,
    smtp_enabled boolean DEFAULT false NOT NULL,
    smtp_host character varying(255) DEFAULT ''::character varying NOT NULL,
    smtp_port integer DEFAULT 587 NOT NULL,
    smtp_use_tls boolean DEFAULT true NOT NULL,
    smtp_username character varying(255) DEFAULT ''::character varying NOT NULL,
    smtp_password character varying(512) DEFAULT ''::character varying NOT NULL,
    smtp_from_address character varying(255) DEFAULT ''::character varying NOT NULL,
    digest_recipients character varying(2000) DEFAULT ''::character varying NOT NULL,
    CONSTRAINT ck_organization_settings_audit_retention_range CHECK (((audit_retention_months >= 0) AND (audit_retention_months <= 600))),
    CONSTRAINT ck_organization_settings_baseline_retention_range CHECK (((baseline_retention_months >= 0) AND (baseline_retention_months <= 600))),
    CONSTRAINT ck_organization_settings_digest_critical_days_range CHECK (((digest_critical_days >= 0) AND (digest_critical_days <= 365))),
    CONSTRAINT ck_organization_settings_digest_horizon_days_range CHECK (((digest_horizon_days >= 1) AND (digest_horizon_days <= 730))),
    CONSTRAINT ck_organization_settings_digest_max_findings_range CHECK (((digest_max_findings >= 1) AND (digest_max_findings <= 1000))),
    CONSTRAINT ck_organization_settings_digest_warning_days_range CHECK (((digest_warning_days >= 0) AND (digest_warning_days <= 730))),
    CONSTRAINT ck_organization_settings_maintenance_hour_range CHECK (((maintenance_hour >= 0) AND (maintenance_hour <= 23))),
    CONSTRAINT ck_organization_settings_smtp_port_range CHECK (((smtp_port >= 1) AND (smtp_port <= 65535)))
);

CREATE TABLE public.personal_resource_skills (
    id uuid NOT NULL,
    resource_id uuid NOT NULL,
    skill_attribute_id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL,
    valid_from date,
    valid_until date,
    level integer,
    CONSTRAINT ck_personal_resource_skills_level_range CHECK (((level IS NULL) OR ((level >= 1) AND (level <= 5)))),
    CONSTRAINT ck_personal_resource_skills_validity_order CHECK (((valid_from IS NULL) OR (valid_until IS NULL) OR (valid_from <= valid_until)))
);

CREATE TABLE public.personal_resources (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    group_id uuid NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    site_id uuid
);

CREATE TABLE public.project_folders (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    parent_id uuid,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    external_ref character varying(128),
    customer_id uuid
);

CREATE TABLE public.projects (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    folder_id uuid,
    "position" integer DEFAULT 0 NOT NULL,
    external_ref character varying(128),
    committed_delivery_date date,
    priority public.projectpriority DEFAULT 'normal'::public.projectpriority NOT NULL,
    customer_id uuid
);

CREATE TABLE public.refresh_tokens (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash character varying(255) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    revoked_at timestamp without time zone,
    created_at timestamp without time zone NOT NULL,
    replaced_by_id uuid
);

CREATE TABLE public.resource_groups (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    resource_type character varying(20) NOT NULL,
    parent_id uuid,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE TABLE public.resource_work_profiles (
    id uuid NOT NULL,
    resource_id uuid,
    profile_id uuid NOT NULL,
    valid_from date NOT NULL,
    valid_until date,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    group_id uuid,
    CONSTRAINT ck_resource_work_profiles_one_target CHECK ((((resource_id IS NOT NULL) AND (group_id IS NULL)) OR ((resource_id IS NULL) AND (group_id IS NOT NULL)))),
    CONSTRAINT ck_resource_work_profiles_validity_order CHECK (((valid_until IS NULL) OR (valid_until >= valid_from)))
);

CREATE TABLE public.scheduled_job_runs (
    id uuid NOT NULL,
    job_name character varying(100) NOT NULL,
    started_at timestamp without time zone NOT NULL,
    finished_at timestamp without time zone,
    status character varying(20) NOT NULL,
    items_affected integer,
    detail character varying(1000) DEFAULT ''::character varying NOT NULL,
    CONSTRAINT ck_scheduled_job_runs_status CHECK (((status)::text = ANY ((ARRAY['running'::character varying, 'succeeded'::character varying, 'failed'::character varying, 'skipped'::character varying])::text[])))
);

CREATE TABLE public.sites (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    region_code character varying(16),
    is_default boolean DEFAULT false NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);

CREATE TABLE public.skill_attributes (
    id uuid NOT NULL,
    skill_id uuid NOT NULL,
    name character varying(100) NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE TABLE public.skills (
    id uuid NOT NULL,
    name character varying(100) NOT NULL,
    resource_type character varying(20) NOT NULL,
    created_at timestamp without time zone NOT NULL
);

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    password_hash character varying(255) NOT NULL,
    role public.userrole DEFAULT 'viewer'::public.userrole NOT NULL,
    scope_group_ids uuid[],
    scope_project_ids uuid[],
    is_active boolean DEFAULT true NOT NULL,
    must_change_password boolean DEFAULT true NOT NULL,
    external_id character varying(255),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    resource_id uuid
);

CREATE TABLE public.work_package_dependencies (
    id uuid NOT NULL,
    predecessor_id uuid NOT NULL,
    successor_id uuid NOT NULL,
    lag_working_days integer DEFAULT 0 NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_work_package_dependencies_lag_non_negative CHECK ((lag_working_days >= 0)),
    CONSTRAINT ck_work_package_dependencies_not_self CHECK ((predecessor_id <> successor_id))
);

CREATE TABLE public.work_package_requirements (
    id uuid NOT NULL,
    work_package_id uuid NOT NULL,
    skill_id uuid NOT NULL,
    skill_attribute_id uuid,
    quantity integer DEFAULT 1 NOT NULL,
    created_at timestamp without time zone NOT NULL,
    requirement_mode public.requirementmode DEFAULT 'headcount'::public.requirementmode NOT NULL,
    min_allocation_percent double precision DEFAULT '100'::double precision NOT NULL,
    min_level integer,
    CONSTRAINT ck_work_package_requirements_min_allocation_range CHECK (((min_allocation_percent > (0)::double precision) AND (min_allocation_percent <= (100)::double precision))),
    CONSTRAINT ck_work_package_requirements_min_level_range CHECK (((min_level IS NULL) OR ((min_level >= 1) AND (min_level <= 5))))
);

CREATE TABLE public.work_package_template_requirements (
    id uuid NOT NULL,
    template_id uuid NOT NULL,
    skill_id uuid NOT NULL,
    skill_attribute_id uuid,
    quantity integer DEFAULT 1 NOT NULL,
    created_at timestamp without time zone NOT NULL,
    requirement_mode public.requirementmode DEFAULT 'headcount'::public.requirementmode NOT NULL,
    min_allocation_percent double precision DEFAULT '100'::double precision NOT NULL,
    min_level integer,
    CONSTRAINT ck_work_package_template_requirements_min_allocation_range CHECK (((min_allocation_percent > (0)::double precision) AND (min_allocation_percent <= (100)::double precision))),
    CONSTRAINT ck_work_package_template_requirements_min_level_range CHECK (((min_level IS NULL) OR ((min_level >= 1) AND (min_level <= 5))))
);

CREATE TABLE public.work_package_templates (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(1000),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    lead_time_working_days integer,
    CONSTRAINT ck_work_package_templates_lead_time_positive CHECK (((lead_time_working_days IS NULL) OR (lead_time_working_days >= 1)))
);

CREATE TABLE public.work_packages (
    id uuid NOT NULL,
    project_id uuid NOT NULL,
    name character varying(255) NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    completed_at timestamp without time zone,
    lead_time_working_days integer,
    CONSTRAINT ck_work_packages_lead_time_positive CHECK (((lead_time_working_days IS NULL) OR (lead_time_working_days >= 1)))
);

CREATE TABLE public.work_week_profiles (
    id uuid NOT NULL,
    name character varying(255) NOT NULL,
    description character varying(1000),
    monday_minutes integer DEFAULT 480 NOT NULL,
    tuesday_minutes integer DEFAULT 480 NOT NULL,
    wednesday_minutes integer DEFAULT 480 NOT NULL,
    thursday_minutes integer DEFAULT 480 NOT NULL,
    friday_minutes integer DEFAULT 480 NOT NULL,
    saturday_minutes integer DEFAULT 0 NOT NULL,
    sunday_minutes integer DEFAULT 0 NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_work_week_profiles_friday_minutes_range CHECK (((friday_minutes >= 0) AND (friday_minutes <= 1440))),
    CONSTRAINT ck_work_week_profiles_monday_minutes_range CHECK (((monday_minutes >= 0) AND (monday_minutes <= 1440))),
    CONSTRAINT ck_work_week_profiles_saturday_minutes_range CHECK (((saturday_minutes >= 0) AND (saturday_minutes <= 1440))),
    CONSTRAINT ck_work_week_profiles_sunday_minutes_range CHECK (((sunday_minutes >= 0) AND (sunday_minutes <= 1440))),
    CONSTRAINT ck_work_week_profiles_thursday_minutes_range CHECK (((thursday_minutes >= 0) AND (thursday_minutes <= 1440))),
    CONSTRAINT ck_work_week_profiles_tuesday_minutes_range CHECK (((tuesday_minutes >= 0) AND (tuesday_minutes <= 1440))),
    CONSTRAINT ck_work_week_profiles_wednesday_minutes_range CHECK (((wednesday_minutes >= 0) AND (wednesday_minutes <= 1440)))
);

ALTER TABLE ONLY public.absences
    ADD CONSTRAINT absences_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assignments_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.baseline_entries
    ADD CONSTRAINT baseline_entries_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT baselines_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.conflict_assignments
    ADD CONSTRAINT conflict_assignments_pkey PRIMARY KEY (conflict_id, assignment_id);

ALTER TABLE ONLY public.conflicts
    ADD CONSTRAINT conflicts_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.customers
    ADD CONSTRAINT customers_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.holidays
    ADD CONSTRAINT holidays_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.infrastructure_availability_windows
    ADD CONSTRAINT infrastructure_availability_windows_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.infrastructure_resource_skills
    ADD CONSTRAINT infrastructure_resource_skills_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.infrastructure_resources
    ADD CONSTRAINT infrastructure_resources_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.personal_resource_skills
    ADD CONSTRAINT personal_resource_skills_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.personal_resources
    ADD CONSTRAINT personal_resources_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.project_folders
    ADD CONSTRAINT project_folders_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.resource_groups
    ADD CONSTRAINT resource_groups_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.resource_work_profiles
    ADD CONSTRAINT resource_work_profiles_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.scheduled_job_runs
    ADD CONSTRAINT scheduled_job_runs_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.sites
    ADD CONSTRAINT sites_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.skill_attributes
    ADD CONSTRAINT skill_attributes_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.organization_settings
    ADD CONSTRAINT tenant_settings_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.baseline_entries
    ADD CONSTRAINT uq_baseline_entries_entity UNIQUE (baseline_id, entity_type, entity_id);

ALTER TABLE ONLY public.holidays
    ADD CONSTRAINT uq_holidays_site_day UNIQUE (site_id, day);

ALTER TABLE ONLY public.infrastructure_resource_skills
    ADD CONSTRAINT uq_infrastructure_resource_skills_resource_attribute UNIQUE (resource_id, skill_attribute_id);

ALTER TABLE ONLY public.organization_settings
    ADD CONSTRAINT uq_organization_settings_singleton UNIQUE (singleton_key);

ALTER TABLE ONLY public.personal_resource_skills
    ADD CONSTRAINT uq_personal_resource_skills_resource_attribute UNIQUE (resource_id, skill_attribute_id);

ALTER TABLE ONLY public.skill_attributes
    ADD CONSTRAINT uq_skill_attributes_skill_name UNIQUE (skill_id, name);

ALTER TABLE ONLY public.skills
    ADD CONSTRAINT uq_skills_name UNIQUE (name);

ALTER TABLE ONLY public.work_package_dependencies
    ADD CONSTRAINT uq_work_package_dependencies_pair UNIQUE (predecessor_id, successor_id);

ALTER TABLE ONLY public.work_week_profiles
    ADD CONSTRAINT uq_work_week_profiles_name UNIQUE (name);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.work_package_dependencies
    ADD CONSTRAINT work_package_dependencies_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.work_package_requirements
    ADD CONSTRAINT work_package_requirements_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.work_package_template_requirements
    ADD CONSTRAINT work_package_template_requirements_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.work_package_templates
    ADD CONSTRAINT work_package_templates_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.work_packages
    ADD CONSTRAINT work_packages_pkey PRIMARY KEY (id);

ALTER TABLE ONLY public.work_week_profiles
    ADD CONSTRAINT work_week_profiles_pkey PRIMARY KEY (id);

CREATE INDEX ix_absences_end_date ON public.absences USING btree (end_date);

CREATE INDEX ix_absences_resource_id ON public.absences USING btree (resource_id);

CREATE INDEX ix_absences_start_date ON public.absences USING btree (start_date);

CREATE INDEX ix_absences_status ON public.absences USING btree (status);

CREATE INDEX ix_assignments_end_date ON public.assignments USING btree (end_date);

CREATE INDEX ix_assignments_resource_id ON public.assignments USING btree (resource_id);

CREATE INDEX ix_assignments_resource_type ON public.assignments USING btree (resource_type);

CREATE INDEX ix_assignments_start_date ON public.assignments USING btree (start_date);

CREATE INDEX ix_assignments_work_package_id ON public.assignments USING btree (work_package_id);

CREATE INDEX ix_audit_log_action ON public.audit_log USING btree (action);

CREATE INDEX ix_audit_log_actor_id ON public.audit_log USING btree (actor_id);

CREATE INDEX ix_audit_log_entity_history ON public.audit_log USING btree (entity_type, entity_id, recorded_at);

CREATE INDEX ix_audit_log_entity_id ON public.audit_log USING btree (entity_id);

CREATE INDEX ix_audit_log_entity_type ON public.audit_log USING btree (entity_type);

CREATE INDEX ix_audit_log_recorded_at ON public.audit_log USING btree (recorded_at);

CREATE INDEX ix_baseline_entries_baseline_id ON public.baseline_entries USING btree (baseline_id);

CREATE INDEX ix_baseline_entries_entity_id ON public.baseline_entries USING btree (entity_id);

CREATE INDEX ix_baseline_entries_entity_type ON public.baseline_entries USING btree (entity_type);

CREATE INDEX ix_baselines_created_at ON public.baselines USING btree (created_at);

CREATE INDEX ix_baselines_created_by ON public.baselines USING btree (created_by);

CREATE INDEX ix_baselines_is_current ON public.baselines USING btree (is_current);

CREATE INDEX ix_conflict_assignments_assignment_id ON public.conflict_assignments USING btree (assignment_id);

CREATE INDEX ix_conflicts_cause ON public.conflicts USING btree (cause);

CREATE INDEX ix_conflicts_end_date ON public.conflicts USING btree (end_date);

CREATE INDEX ix_conflicts_resource_id ON public.conflicts USING btree (resource_id);

CREATE INDEX ix_conflicts_start_date ON public.conflicts USING btree (start_date);

CREATE INDEX ix_holidays_day ON public.holidays USING btree (day);

CREATE INDEX ix_holidays_site_id ON public.holidays USING btree (site_id);

CREATE INDEX ix_infra_windows_resource_id ON public.infrastructure_availability_windows USING btree (resource_id);

CREATE INDEX ix_infra_windows_weekday ON public.infrastructure_availability_windows USING btree (weekday);

CREATE INDEX ix_infrastructure_resource_skills_resource_id ON public.infrastructure_resource_skills USING btree (resource_id);

CREATE INDEX ix_infrastructure_resource_skills_skill_attribute_id ON public.infrastructure_resource_skills USING btree (skill_attribute_id);

CREATE INDEX ix_infrastructure_resource_skills_valid_until ON public.infrastructure_resource_skills USING btree (valid_until);

CREATE INDEX ix_infrastructure_resources_group_id ON public.infrastructure_resources USING btree (group_id);

CREATE INDEX ix_infrastructure_resources_is_active ON public.infrastructure_resources USING btree (is_active);

CREATE INDEX ix_infrastructure_resources_site_id ON public.infrastructure_resources USING btree (site_id);

CREATE INDEX ix_personal_resource_skills_resource_id ON public.personal_resource_skills USING btree (resource_id);

CREATE INDEX ix_personal_resource_skills_skill_attribute_id ON public.personal_resource_skills USING btree (skill_attribute_id);

CREATE INDEX ix_personal_resource_skills_valid_until ON public.personal_resource_skills USING btree (valid_until);

CREATE INDEX ix_personal_resources_group_id ON public.personal_resources USING btree (group_id);

CREATE INDEX ix_personal_resources_is_active ON public.personal_resources USING btree (is_active);

CREATE INDEX ix_personal_resources_site_id ON public.personal_resources USING btree (site_id);

CREATE INDEX ix_project_folders_customer_id ON public.project_folders USING btree (customer_id);

CREATE INDEX ix_project_folders_external_ref ON public.project_folders USING btree (external_ref);

CREATE INDEX ix_project_folders_parent_id ON public.project_folders USING btree (parent_id);

CREATE INDEX ix_project_folders_position ON public.project_folders USING btree ("position");

CREATE INDEX ix_projects_committed_delivery_date ON public.projects USING btree (committed_delivery_date);

CREATE INDEX ix_projects_customer_id ON public.projects USING btree (customer_id);

CREATE INDEX ix_projects_external_ref ON public.projects USING btree (external_ref);

CREATE INDEX ix_projects_folder_id ON public.projects USING btree (folder_id);

CREATE INDEX ix_projects_position ON public.projects USING btree ("position");

CREATE INDEX ix_projects_priority ON public.projects USING btree (priority);

CREATE INDEX ix_refresh_tokens_token_hash ON public.refresh_tokens USING btree (token_hash);

CREATE INDEX ix_refresh_tokens_user_id ON public.refresh_tokens USING btree (user_id);

CREATE INDEX ix_resource_groups_parent_id ON public.resource_groups USING btree (parent_id);

CREATE INDEX ix_resource_groups_resource_type ON public.resource_groups USING btree (resource_type);

CREATE INDEX ix_resource_work_profiles_group_id ON public.resource_work_profiles USING btree (group_id);

CREATE INDEX ix_resource_work_profiles_profile_id ON public.resource_work_profiles USING btree (profile_id);

CREATE INDEX ix_resource_work_profiles_resource_id ON public.resource_work_profiles USING btree (resource_id);

CREATE INDEX ix_resource_work_profiles_valid_from ON public.resource_work_profiles USING btree (valid_from);

CREATE INDEX ix_resource_work_profiles_valid_until ON public.resource_work_profiles USING btree (valid_until);

CREATE INDEX ix_scheduled_job_runs_job_name ON public.scheduled_job_runs USING btree (job_name);

CREATE INDEX ix_scheduled_job_runs_job_name_started_at ON public.scheduled_job_runs USING btree (job_name, started_at);

CREATE INDEX ix_sites_is_active ON public.sites USING btree (is_active);

CREATE INDEX ix_sites_is_default ON public.sites USING btree (is_default);

CREATE INDEX ix_skill_attributes_skill_id ON public.skill_attributes USING btree (skill_id);

CREATE INDEX ix_users_created_at ON public.users USING btree (created_at);

CREATE INDEX ix_work_package_dependencies_predecessor_id ON public.work_package_dependencies USING btree (predecessor_id);

CREATE INDEX ix_work_package_dependencies_successor_id ON public.work_package_dependencies USING btree (successor_id);

CREATE INDEX ix_work_package_requirements_requirement_mode ON public.work_package_requirements USING btree (requirement_mode);

CREATE INDEX ix_work_package_requirements_skill_attribute_id ON public.work_package_requirements USING btree (skill_attribute_id);

CREATE INDEX ix_work_package_requirements_skill_id ON public.work_package_requirements USING btree (skill_id);

CREATE INDEX ix_work_package_requirements_work_package_id ON public.work_package_requirements USING btree (work_package_id);

CREATE INDEX ix_work_packages_completed_at ON public.work_packages USING btree (completed_at);

CREATE INDEX ix_work_packages_project_id ON public.work_packages USING btree (project_id);

CREATE INDEX ix_work_week_profiles_is_default ON public.work_week_profiles USING btree (is_default);

CREATE INDEX ix_wpt_requirements_template_id ON public.work_package_template_requirements USING btree (template_id);

CREATE UNIQUE INDEX uq_customers_name_lower ON public.customers USING btree (lower((name)::text));

CREATE UNIQUE INDEX uq_users_resource_id ON public.users USING btree (resource_id);

ALTER TABLE ONLY public.assignments
    ADD CONSTRAINT assignments_work_package_id_fkey FOREIGN KEY (work_package_id) REFERENCES public.work_packages(id);

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.users(id);

ALTER TABLE ONLY public.baseline_entries
    ADD CONSTRAINT baseline_entries_baseline_id_fkey FOREIGN KEY (baseline_id) REFERENCES public.baselines(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.baselines
    ADD CONSTRAINT baselines_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.users(id);

ALTER TABLE ONLY public.conflict_assignments
    ADD CONSTRAINT conflict_assignments_assignment_id_fkey FOREIGN KEY (assignment_id) REFERENCES public.assignments(id);

ALTER TABLE ONLY public.conflict_assignments
    ADD CONSTRAINT conflict_assignments_conflict_id_fkey FOREIGN KEY (conflict_id) REFERENCES public.conflicts(id);

ALTER TABLE ONLY public.infrastructure_resource_skills
    ADD CONSTRAINT fk_infrastructure_resource_skills_resource_id FOREIGN KEY (resource_id) REFERENCES public.infrastructure_resources(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.infrastructure_resource_skills
    ADD CONSTRAINT fk_infrastructure_resource_skills_skill_attribute_id FOREIGN KEY (skill_attribute_id) REFERENCES public.skill_attributes(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.infrastructure_resources
    ADD CONSTRAINT fk_infrastructure_resources_group_id FOREIGN KEY (group_id) REFERENCES public.resource_groups(id);

ALTER TABLE ONLY public.infrastructure_resources
    ADD CONSTRAINT fk_infrastructure_resources_site_id FOREIGN KEY (site_id) REFERENCES public.sites(id);

ALTER TABLE ONLY public.personal_resource_skills
    ADD CONSTRAINT fk_personal_resource_skills_resource_id FOREIGN KEY (resource_id) REFERENCES public.personal_resources(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.personal_resource_skills
    ADD CONSTRAINT fk_personal_resource_skills_skill_attribute_id FOREIGN KEY (skill_attribute_id) REFERENCES public.skill_attributes(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.personal_resources
    ADD CONSTRAINT fk_personal_resources_group_id FOREIGN KEY (group_id) REFERENCES public.resource_groups(id);

ALTER TABLE ONLY public.personal_resources
    ADD CONSTRAINT fk_personal_resources_site_id FOREIGN KEY (site_id) REFERENCES public.sites(id);

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT fk_projects_folder_id FOREIGN KEY (folder_id) REFERENCES public.project_folders(id);

ALTER TABLE ONLY public.resource_groups
    ADD CONSTRAINT fk_resource_groups_parent_id FOREIGN KEY (parent_id) REFERENCES public.resource_groups(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.resource_work_profiles
    ADD CONSTRAINT fk_resource_work_profiles_group_id FOREIGN KEY (group_id) REFERENCES public.resource_groups(id);

ALTER TABLE ONLY public.skill_attributes
    ADD CONSTRAINT fk_skill_attributes_skill_id FOREIGN KEY (skill_id) REFERENCES public.skills(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_users_resource_id_personal_resources FOREIGN KEY (resource_id) REFERENCES public.personal_resources(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.work_package_template_requirements
    ADD CONSTRAINT fk_wpt_requirements_skill_attribute_id FOREIGN KEY (skill_attribute_id) REFERENCES public.skill_attributes(id);

ALTER TABLE ONLY public.work_package_template_requirements
    ADD CONSTRAINT fk_wpt_requirements_skill_id FOREIGN KEY (skill_id) REFERENCES public.skills(id);

ALTER TABLE ONLY public.work_package_template_requirements
    ADD CONSTRAINT fk_wpt_requirements_template_id FOREIGN KEY (template_id) REFERENCES public.work_package_templates(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.holidays
    ADD CONSTRAINT holidays_site_id_fkey FOREIGN KEY (site_id) REFERENCES public.sites(id);

ALTER TABLE ONLY public.infrastructure_availability_windows
    ADD CONSTRAINT infrastructure_availability_windows_resource_id_fkey FOREIGN KEY (resource_id) REFERENCES public.infrastructure_resources(id);

ALTER TABLE ONLY public.project_folders
    ADD CONSTRAINT project_folders_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.project_folders
    ADD CONSTRAINT project_folders_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.project_folders(id);

ALTER TABLE ONLY public.projects
    ADD CONSTRAINT projects_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customers(id) ON DELETE SET NULL;

ALTER TABLE ONLY public.refresh_tokens
    ADD CONSTRAINT refresh_tokens_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.resource_work_profiles
    ADD CONSTRAINT resource_work_profiles_profile_id_fkey FOREIGN KEY (profile_id) REFERENCES public.work_week_profiles(id);

ALTER TABLE ONLY public.work_package_dependencies
    ADD CONSTRAINT work_package_dependencies_predecessor_id_fkey FOREIGN KEY (predecessor_id) REFERENCES public.work_packages(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.work_package_dependencies
    ADD CONSTRAINT work_package_dependencies_successor_id_fkey FOREIGN KEY (successor_id) REFERENCES public.work_packages(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.work_package_requirements
    ADD CONSTRAINT work_package_requirements_skill_attribute_id_fkey FOREIGN KEY (skill_attribute_id) REFERENCES public.skill_attributes(id);

ALTER TABLE ONLY public.work_package_requirements
    ADD CONSTRAINT work_package_requirements_skill_id_fkey FOREIGN KEY (skill_id) REFERENCES public.skills(id);

ALTER TABLE ONLY public.work_package_requirements
    ADD CONSTRAINT work_package_requirements_work_package_id_fkey FOREIGN KEY (work_package_id) REFERENCES public.work_packages(id) ON DELETE CASCADE;

ALTER TABLE ONLY public.work_packages
    ADD CONSTRAINT work_packages_project_id_fkey FOREIGN KEY (project_id) REFERENCES public.projects(id);
"""


def upgrade() -> None:
    # The dump is many statements; the driver rejects a multi-statement string in one execute
    # (asyncpg / SQLAlchemy f405), so split on the statement terminator and run them in order.
    # The baseline SQL contains no PL/pgSQL bodies, so a bare ';' split has no dollar-quoted
    # semicolons to trip over.
    # A fresh database built from this baseline differs from the old 001..026 chain in exactly
    # two CHECK constraints (ck_absences_status, ck_scheduled_job_runs_status): Postgres re-parses
    # the ANY(ARRAY[...]) text into a different but semantically identical normal form than it did
    # when the original migration built the same constraint from a SQLAlchemy expression.
    # pg_get_constraintdef proves the logic is the same; the difference is cosmetic and only shows
    # up in a raw pg_dump text diff. Left as-is rather than hand-massaged into a matching string.
    for statement in BASELINE_SQL.split(";\n"):
        statement = statement.strip()
        if statement:
            op.execute(statement)


def downgrade() -> None:
    # Baseline: there is nothing beneath it to downgrade to. Dropping the whole schema here
    # would be a destructive surprise for anyone who ran `downgrade base`, so this is a no-op.
    pass
