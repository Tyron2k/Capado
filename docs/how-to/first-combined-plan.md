# Your first combined plan

This walkthrough uses fictional people, a crane and dated qualifications. It exercises
the existing CSV ZIP import, work-package assessment and booking corrections. It requires
a version containing the work-package assessment introduced in PR #161; older images may
not have that view. For a current source checkout use the [Docker development setup](local-setup.md).
For released images follow the [README Quick Start](https://github.com/Tyron2k/Capado#schnellstart).

## Start with an empty installation

Use a separate Compose project **and separate database volume**, with free host ports and
unique container names if another Capado stack is running. A different project name alone
does not isolate the fixed container names or external development volume. Never reset
an existing installation just to try these examples.

Create the first administrator through the setup screen, using your own email and password.
Keep that account: the example contains **no users, credentials, sessions or identity-provider
bindings**. The import preserves your bootstrap administrator. No SMTP or hosted service is needed.
On a plain HTTP localhost installation, follow the existing `COOKIE_SECURE=false` instruction;
keep secure cookies for HTTPS deployments.

Download [combined-planning.zip](../assets/examples/combined-planning.zip). It is the normal
versioned all-data CSV ZIP (ten area CSVs and a manifest), produced by the existing exporters
from the shared synthetic planning reference case. No new import format or seed endpoint is used.

Open **Settings → Import / Export**, choose the complete ZIP and import it once. The
destination must contain no planning/master data. You do not need to import its members in
any particular order: the complete ZIP validates their relationships and writes them together.

If importing fails:

- **Empty destination required:** use a fresh evaluation database. Reimporting the ZIP is
  intentionally rejected once planning data exists; it is not a reset or update mechanism.
- **Archive/manifest/reference error:** download the original complete ZIP again. Do not edit
  its CSVs without regenerating the matching manifest. Preserve the error's area, row and field
  if reporting a problem.
- **Conflict refresh failed after import:** the data import may already have committed.
  Check the reported status and the [import documentation](../reference/import-export.md)
  before retrying; do not mistake a derived-check failure for an empty database.

## Understand the starting plan

Open the planning overview and select **Example combined work package**, under **Example
workshop project**, dated **5–7 January 2099**. The fixed future dates keep the example active
and repeatable. They are deliberate, rather than dates to copy into a real production plan.
The display/input time zone is **Europe/Berlin**.

| Record | Starting state |
|---|---|
| Standard working week | Monday–Friday, 480 minutes/day; zero weekend minutes |
| Personnel requirement | Two distinct qualified people, each at 100%, on each standard workday |
| Alex Example | Qualified at level 3, booked 5–7 January at 100% |
| Sam Example | Qualified at level 3 for the full period, not booked yet |
| Machine requirement | One crane with lifting qualification, minimum level 2 |
| Example crane | Qualified at level 3; operating window Monday 22:00–Tuesday 06:00 |
| Crane bookings | Monday 22:00–Tuesday 02:00 and Monday 21:00–Tuesday 01:00 |

Expect a **one-person coverage gap** and two machine conflict causes: the extra booking
starts outside the operating window and overlaps the original booking. Qualification validity
runs through the full package period. The machine's overnight window belongs to Monday,
including its Tuesday portion.

## Complete the staffing

Use the missing-person requirement to inspect qualified alternatives. Choose **Sam Example**
and verify the preview: this is a **person**, for the same work package, **5–7 January 2099**,
at **100%**. Confirm only after checking the proposed resource, period and remaining problems.
If entering the booking directly, use those same fields in the existing assignment form.

The personnel gap should disappear. The machine conflicts must remain visible: completing
staffing does not resolve an equipment booking conflict.

## Repair the machine booking

Open the proposal preview or edit the extra crane booking that currently starts **Monday
5 January at 21:00**. Keep the same crane and work package, and move that booking to
**Tuesday 6 January, 02:00–06:00**. Review the actual before/after timestamps and remaining
conflicts before confirming. The original Monday 22:00–Tuesday 02:00 booking stays unchanged.

The two bookings now meet at 02:00 without overlapping, and both fit Monday's overnight
operating window. The package assessment should have no unmet requirements or conflicts.

**Interpret the remaining limit:** personnel is planned by date and percentage. A covered
personnel requirement does not prove that Alex and Sam are physically present during the
crane's night shift. The displayed precision limit must remain visible. A machine without
configured operating windows is deliberately treated as available 24/7; this example supplies
a window so that the restriction can be evaluated.

## Save the result and give feedback

Export the complete ZIP from Settings if you want to transfer the corrected plan into another
empty installation. Treat that as a planning-data migration, not a credential/session backup.
For operational recovery use the [verified backup procedure](upgrading.md#1-back-up-without-exception).

For an independent setup/usage session, record the application version, task completion,
elapsed time, explicit interactions, errors, confusing steps and what the final verdict means.
Use the [existing observation protocol and session record](../explanation/planning-validation.md#record-a-session)
with synthetic data only. Distinguish a real person's observations from an automated or internal
simulation; publishing the walkthrough does not by itself establish that it is easy to use.

## Internal release check — 11 November 2026

This walkthrough was exercised through the browser with the published **v0.2.0**
images from source `aaeef47bb95bea85ade1f533d7c819119631957c`, using two isolated,
empty PostgreSQL 18 Compose installations. Both images could be pulled anonymously.
The release's [publication record](https://github.com/Tyron2k/Capado/actions/runs/42999796370)
records the paired image digests; the UI displayed `Capado v0.2.0`.

- First-run administrator setup and the original ZIP import succeeded (23 records,
  no import errors); the bootstrap account was retained.
- Adding Sam through the proposal preview closed the personnel gap while keeping
  both machine conflict causes visible. The documented manual machine correction
  then cleared both causes and retained the scope/precision warning.
- The complete ZIP export contained ten area CSVs and a manifest. Importing it into
  the second empty installation preserved all four bookings, including their IDs,
  resource types, dates, percentages and timestamps. Its own administrator remained
  usable, and both the API and UI showed the covered result and precision limit.
- Reimport into the populated first installation was rejected with the explicit
  empty-destination error, zero writes and the corrected plan unchanged.

These are internal automated checks in Chromium at 1440 × 1000 with English labels
and Europe/Berlin display time. They establish a working published-image data flow,
not an independent operator's understanding or a human usability result. Independent
setup and planning sessions remain outstanding; only internal checks are currently
available. Use the session record below when those sessions become possible.
