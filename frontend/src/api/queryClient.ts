/**
 * Query keys and the client, in one place, because the keys are the convention.
 *
 * WHY THIS FILE EXISTS BEFORE THE SECOND SCREEN IS CONVERTED. A cache is only as good as its
 * invalidation, and invalidation is spelled in keys. If each screen invents its own key shape, a
 * mutation on one screen cannot reliably invalidate a list on another — which is strictly worse than
 * the 57 hand-written refetch calls it replaces, because it LOOKS like a solution. So the shape is
 * fixed here first and screens are converted against it.
 *
 * THE SHAPE. A key is an array, coarse to fine: `[domain, kind, ...parameters]`. Every level is a
 * valid prefix, and TanStack matches by prefix — so `['audit']` invalidates every audit query,
 * `['audit', 'entries']` only the lists, and `['audit', 'entries', filters]` one filter combination.
 * Pick the coarsest prefix that is still correct: over-invalidating costs a request, while
 * under-invalidating shows the user a value that is no longer true.
 *
 * PARAMETERS GO IN THE KEY, ALWAYS. A filter or a page number that is not in the key means two
 * different results share one cache entry, and the user sees the previous filter's rows under the
 * new filter's heading. That failure is indistinguishable from a backend bug from the outside.
 */

import { QueryClient } from '@tanstack/react-query'

/** Filters that identify one audit list request. Not exported: only `queryKeys` builds these. */
interface AuditListKeyParams {
  entityType?: string
  action?: string
  limit: number
  offset: number
}

export const queryKeys = {
  audit: {
    /** Everything audit-related. Use as an invalidation prefix, not as a query key. */
    all: ['audit'] as const,
    /** One page of the audit list under one set of filters. */
    entries: (params: AuditListKeyParams) => ['audit', 'entries', params] as const,
    /** The history of one entity, served by its own indexed endpoint. */
    history: (entityType: string, entityId: string, limit: number) =>
      ['audit', 'history', entityType, entityId, limit] as const,
  },
  settings: {
    all: ['settings'] as const,
    /** Organisation-wide settings. One entry, shared by every screen that reads them. */
    tenant: () => ['settings', 'tenant'] as const,
  },
  sites: {
    all: ['sites'] as const,
    /** The site list, including inactive ones when asked for. */
    list: () => ['sites', 'list'] as const,
  },
  /**
   * The three things that DEFINE capacity: week profiles, holidays and availability windows.
   *
   * Editing any of them changes how many minutes a resource actually has, which changes whether an
   * assignment fits — so a write here can create or clear a conflict without touching a single
   * assignment. That is why these mutations invalidate the DIGEST and the CONFLICTS as well as their
   * own list: the number they changed is not on their own screen.
   *
   * Holidays belong to a site, so their key carries the site id. A profile is organisation-wide.
   */
  capacity: {
    all: ['capacity'] as const,
    weekProfiles: () => ['capacity', 'week-profiles'] as const,
    holidays: (siteId: string) => ['capacity', 'holidays', siteId] as const,
    /** One resource's absences. An absence reduces its available minutes. */
    absences: (resourceId: string) => ['capacity', 'absences', resourceId] as const,
    /** Which week profile one resource is bound to, and what it inherits from its group. */
    profileBindings: (resourceId: string) => ['capacity', 'profile-bindings', resourceId] as const,
    /** One infrastructure resource's operating windows. Outside them, it is not bookable. */
    availabilityWindows: (resourceId: string) =>
      ['capacity', 'availability-windows', resourceId] as const,
  },
  /** Detected conflicts. Derived from capacity and assignments, never edited directly. */
  conflicts: {
    all: ['conflicts'] as const,
    checkStatus: () => ['conflicts', 'check-status'] as const,
    /**
     * Who is FREE and QUALIFIED for a window, as searched from the assignment form.
     *
     * Every search parameter is in the key, including the qualification filter, because the answer is
     * different for each combination. The form debounces the inputs before they reach the key, so the
     * cache holds settled searches rather than one entry per keystroke — and going back to a combination
     * already tried answers instantly.
     */
    resourceSearch: (params: {
      startDate: string
      endDate: string
      allocationPercent: number
      skillId: string | null
      skillAttributeId: string | null
    }) => ['conflicts', 'resource-search', params] as const,
    /** Resolution suggestions for one conflict, computed on request from the current plan. */
    suggestions: (conflictId: string) => ['conflicts', 'suggestions', conflictId] as const,
    /**
     * Who could take over one assignment: requirements, then qualified resources, then availability.
     *
     * One key for three requests, because it is one logical answer — a candidate list is only correct
     * if all three parts agree, and caching the parts separately would let a stale qualification
     * survive a changed requirement.
     */
    swapCandidates: (assignmentId: string, excludeResourceId: string) =>
      ['conflicts', 'swap-candidates', assignmentId, excludeResourceId] as const,
  },
  /**
   * Assignments: the plan itself.
   *
   * Writing one is the most consequential mutation in the product. It changes whether a resource is
   * overbooked (conflicts), whether a requirement is covered (the digest), and what every Gantt
   * perspective draws — none of which is on the screen that made the change.
   */
  assignments: {
    all: ['assignments'] as const,
    list: () => ['assignments', 'list'] as const,
  },
  /** Aggregated planning figures. A derived view of assignments and capacity. */
  planning: {
    all: ['planning'] as const,
    overview: () => ['planning', 'overview'] as const,
  },
  /**
   * Projects and their work packages.
   *
   * A work package carries dates and a requirement, so editing one changes the plan; a project's own
   * master data (name, folder, customer) does not. The two therefore invalidate different sets, which
   * is why they are separate kinds rather than one `projects` blob.
   */
  projects: {
    all: ['projects'] as const,
    list: () => ['projects', 'list'] as const,
    workPackages: (projectId: string) => ['projects', 'work-packages', projectId] as const,
    /** The folder tree projects are filed in. Master data: renaming one changes no date. */
    folders: () => ['projects', 'folders'] as const,
    /** One project's computed schedule — derived from its work packages' dates and dependencies. */
    schedule: (projectId: string) => ['projects', 'schedule', projectId] as const,
    /** What one work package waits for. A dependency shifts dates, so it is plan data. */
    dependencies: (workPackageId: string) => ['projects', 'dependencies', workPackageId] as const,
    /** The skills one work package needs. Changing them changes whether an assignment still fits. */
    requirements: (workPackageId: string) => ['projects', 'requirements', workPackageId] as const,
    /** A stored template's contents, keyed by which template. Read-only here. */
    template: (templateKey: string) => ['projects', 'template', templateKey] as const,
  },
  /**
   * Requirement templates — a BLUEPRINT, not plan data.
   *
   * A template is copied INTO a work package when one is created; editing the template afterwards
   * changes nothing that is already planned. That is why a template write invalidates only templates,
   * and the copy — which does change the plan — invalidates from the work-package screen that performs
   * it. Confusing the two would refetch the whole plan every time somebody tidied up a blueprint.
   */
  templates: {
    all: ['templates'] as const,
    list: () => ['templates', 'list'] as const,
    detail: (templateId: string) => ['templates', 'detail', templateId] as const,
  },
  /**
   * The skill catalogue: skills and their attributes, per resource type.
   *
   * A SKILL IS WHAT A REQUIREMENT POINTS AT, which makes this catalogue the one piece of master data in
   * the product that reaches into the plan. A work package requires "welding, certified"; a person is
   * qualified for "welding, certified"; whether the assignment between them is sound is decided by
   * comparing the two through this catalogue. Delete that attribute and the requirement it satisfied is
   * suddenly uncovered — the assignment did not change, but its correctness did.
   *
   * That is why a skill write invalidates the digest, where a customer or a folder write does not.
   */
  skills: {
    all: ['skills'] as const,
    withAttributes: (resourceType: string) => ['skills', 'with-attributes', resourceType] as const,
  },
  /**
   * Customers. Master data: a project points at one, and its name is displayed on project lists.
   *
   * `includeInactive` IS IN THE KEY, and it has to be. The admin panel lists retired customers too,
   * while the pickers list only active ones — same endpoint, different answers. Sharing one entry would
   * let whichever screen loaded first decide whether retired customers appear in the other, which is
   * the precise failure the parameter-in-the-key rule exists to prevent.
   *
   * `customers.all` is still the invalidation prefix, so a write refreshes both variants at once.
   */
  customers: {
    all: ['customers'] as const,
    list: (includeInactive: boolean) => ['customers', 'list', includeInactive] as const,
  },
  resources: {
    /**
     * Everything resource-related. Declared here although no resource LIST screen is on the query
     * layer yet, because a site or group rename has to invalidate it: the resource lists display
     * `site_name` and `group_name`, so a rename leaves them showing the old value until something
     * refetches.
     *
     * Invalidating it today is a no-op, and writing it anyway is the point. The alternative is that
     * whoever converts those screens has to REMEMBER to come back and add the invalidation to a
     * mutation in a different feature — which is the exact class of forgetting this layer exists to
     * remove. A no-op with a reason costs nothing; a missing invalidation shows a stale name.
     */
    all: ['resources'] as const,
    /** The groups of one resource type. Their names appear on every resource list. */
    groups: (resourceType: string) => ['resources', 'groups', resourceType] as const,
    /**
     * One group's printable week sheet — a DERIVED view of assignments, absences and capacity.
     *
     * Filed under `resources` on purpose: every plan-changing mutation already invalidates
     * `resources.all`, so the sheet is refreshed by writes made on screens that have never heard of
     * it. The anchor week is in the key, so paging back and forth reuses weeks already fetched instead
     * of re-requesting each one.
     */
    teamWeek: (groupId: string, anchor: string) =>
      ['resources', 'team-week', groupId, anchor] as const,
    /** One resource's held qualifications. Read by the matrix and written a cell at a time. */
    qualifications: (resourceId: string) => ['resources', 'qualifications', resourceId] as const,
    /**
     * The people tree, for pickers that need every person rather than one group's.
     *
     * Note that `groups('all')` and `groups('personal')` are DIFFERENT entries on purpose: the same
     * endpoint answers differently when the type filter is omitted, and the admin scope picker means
     * every group where a team sheet means the personal ones.
     */
    personalTree: () => ['resources', 'personal-tree'] as const,
    /** The resource list of one type, with its filters in the key. */
    list: (resourceType: string, includeInactive: boolean) =>
      ['resources', 'list', resourceType, includeInactive] as const,
  },
  /**
   * The dashboard digest, which is DOWNSTREAM OF EVERYTHING.
   *
   * It is computed from qualifications, commitments, dependencies and requirements, so almost any
   * write in the product can change it — an assignment, an absence, a date, a certificate. That makes
   * it the one key whose invalidation is easiest to forget and most visible when it is: the dashboard
   * is the screen a planner reads first, and a stale digest tells them to act on something already
   * dealt with, or stays silent about something new.
   *
   * Recorded here rather than discovered later: every mutation converted from now on should ask
   * whether it changes the plan, and invalidate this if it does.
   */
  digest: {
    all: ['digest'] as const,
    today: () => ['digest', 'today'] as const,
  },
  /** One person's own plan. Read-only by design — see ADR-009 and the self-service limitation. */
  myPlan: {
    all: ['my-plan'] as const,
    current: () => ['my-plan', 'current'] as const,
  },
  /** Logins and roles. Nothing about the plan, so nothing plan-shaped is invalidated by a user write. */
  admin: {
    all: ['admin'] as const,
    /**
     * One PAGE of users. The page is in the key, so paging back reuses what was already fetched and a
     * slow request for page 3 can never land while page 2 is on screen.
     */
    users: (skip: number, limit: number) => ['admin', 'users', skip, limit] as const,
  },
  /**
   * Baselines: frozen copies of the plan, plus each one's comparison against the plan as it is now.
   *
   * A BASELINE IS THE ONE READ IN THE PRODUCT THAT MUST NOT GO STALE ON A PLAN CHANGE — it is a
   * SNAPSHOT. The whole point is that it keeps saying what the plan looked like in March however much
   * March's plan has moved since. So no plan mutation invalidates the list, and creating one invalidates
   * only the list it was added to.
   *
   * THE DIFF IS THE EXACT OPPOSITE and the distinction matters: it compares a frozen baseline against
   * the LIVE plan, so it goes stale the moment anything is edited. It is therefore invalidated by plan
   * mutations even though the baseline beside it is not — the same screen holding one value that must
   * never change and one that must.
   */
  baselines: {
    all: ['baselines'] as const,
    list: () => ['baselines', 'list'] as const,
    diff: (baselineId: string) => ['baselines', 'diff', baselineId] as const,
  },
  /**
   * The dashboard's own aggregates, distinct from `digest`.
   *
   * `digest` is the findings list; these are the figures and the project overview around it. Both are
   * downstream of the whole plan, so both are invalidated by the same writes.
   */
  dashboard: {
    all: ['dashboard'] as const,
    summary: () => ['dashboard', 'summary'] as const,
    projectOverview: () => ['dashboard', 'project-overview'] as const,
  },
  /**
   * Gantt data, per perspective.
   *
   * THREE PERSPECTIVES OVER THE SAME PLAN — by department, by infrastructure group, and by project —
   * each computed by its own endpoint. The perspective and its parameter are in the key, so switching
   * tabs cannot render one perspective's bars under another's heading, and switching back reuses what
   * was already fetched.
   *
   * Every plan-changing mutation in the product invalidates `gantt.all` through nothing but its own
   * prefix, because these charts were the screens most visibly wrong before: they draw the dates that
   * other screens edit.
   */
  gantt: {
    all: ['gantt'] as const,
    department: (groupId: string) => ['gantt', 'department', groupId] as const,
    infraGroup: (groupId: string) => ['gantt', 'infra-group', groupId] as const,
    projects: (projectId: string) => ['gantt', 'projects', projectId] as const,
  },
  /**
   * Autocomplete search results, per entity type and search term.
   *
   * A SEARCH RESULT IS SERVER STATE, which is easy to miss because it feels transient. Keying it means
   * backspacing over a term and retyping it answers from cache instead of re-requesting — the single most
   * common thing a person does in an autocomplete. `staleTime` is left at the client default: a name that
   * matched a prefix thirty seconds ago still matches it.
   */
  autocomplete: {
    all: ['autocomplete'] as const,
    search: (type: string, term: string) => ['autocomplete', 'search', type, term] as const,
  },
  /** Maintenance job history. Operational, not planning data. */
  maintenance: {
    all: ['maintenance'] as const,
    runs: (limit: number) => ['maintenance', 'runs', limit] as const,
  },
  /**
   * What the sign-in screens need to know before anybody is signed in.
   *
   * Cached like anything else, but nothing ever invalidates them: they are read once on a page the user
   * leaves permanently as soon as they get past it. They are here so those screens use one mechanism
   * rather than a second hand-written one — not because they participate in the invalidation graph.
   */
  auth: {
    all: ['auth'] as const,
    oidcStatus: () => ['auth', 'oidc-status'] as const,
    setupStatus: () => ['auth', 'setup-status'] as const,
  },
} as const

/**
 * The shared client.
 *
 * Every default here is a decision about a planning tool, not a copy of the library's suggestions:
 *
 * `staleTime: 30_000` — a plan is edited by people over minutes, not by a feed over seconds. Thirty
 * seconds stops the same list being refetched when a user switches tabs and comes back, which is the
 * common case, without letting a figure go stale long enough to act on. Zero (the library default)
 * would refetch on every mount and make the cache mostly ceremony.
 *
 * `refetchOnWindowFocus: false` — this application is left open on a second monitor all day. Every
 * click back into the window would fire a refetch, which is load without a reader: nothing changed
 * because nobody was in here to change it.
 *
 * `retry: 1` — one retry catches a dropped connection; more of them turn a 500 into a four-second
 * wait before the user is told anything, and this backend answers 401 and 409 meaningfully, which are
 * not worth retrying at all.
 *
 * There is deliberately no global `onError`: errors are reported per screen through
 * `showErrorNotification`, so the message can say WHICH thing failed. A single global toast saying
 * "something went wrong" is what that replaces, and it is worse.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: 1,
      },
    },
  })
}
