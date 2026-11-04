import { test, expect, type Page } from '@playwright/test'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile } from 'node:fs/promises'

const command = promisify(execFile)
async function start(
  page: Page,
  scenario: 'staffing' | 'machine' | 'qualification' | 'overnight' | 'replacement',
) {
  await command('uv', [
    '--directory',
    '../backend',
    'run',
    '--frozen',
    '--no-dev',
    'python',
    '-m',
    'tests.e2e_server',
    'planning-reference',
    scenario,
  ])
  await page.addInitScript(() =>
    localStorage.setItem(
      'user-preferences',
      JSON.stringify({ locale: 'en', colorScheme: 'light', navCollapsed: false }),
    ),
  )
  await page.goto('/login')
  await page.getByLabel(/^Email/).fill('admin@example.test')
  await page.getByLabel(/^Password/).fill('browser-tests-only')
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  await expect(page).toHaveURL('/')
  await page.getByRole('navigation').getByText('Planning', { exact: true }).click()
  return JSON.parse(await readFile('.e2e-state.json', 'utf8')) as { planning_package: string }
}
function measurement() {
  const started = performance.now()
  let interactions = 0
  let diagnosticMs = 0
  return {
    step: async (action: () => Promise<unknown>) => {
      interactions++
      await action()
    },
    diagnostic: async (action: () => Promise<unknown>) => {
      const before = performance.now()
      await action()
      diagnosticMs += performance.now() - before
    },
    result: () => ({
      kind: 'automated browser task, not human usability',
      interactions,
      elapsed_ms: Math.round(performance.now() - started - diagnosticMs),
    }),
  }
}
async function selectPackage(page: Page, step: ReturnType<typeof measurement>['step']) {
  await step(() =>
    page.getByRole('combobox', { name: 'Assess work package', exact: true }).fill('Fixture'),
  )
  await step(() =>
    page.getByRole('option', { name: 'Fixture project · Fixture package', exact: true }).click(),
  )
  await expect(page.getByTestId('work-package-readiness')).toBeVisible()
}

test('combined planning: fill missing staffing while retaining the precision limit', async ({
  page,
}, info) => {
  const seed = await start(page, 'staffing')
  const measure = measurement()
  await selectPackage(page, measure.step)
  const verdict = page.getByTestId('work-package-readiness')
  await expect(verdict.getByText('Missing requirements', { exact: true })).toHaveCount(2)
  await measure.step(() => verdict.getByTestId(`unmet-wp-${seed.planning_package}`).click())
  await measure.step(() => verdict.getByRole('button', { name: 'Preview', exact: true }).click())
  const dialog = page.getByRole('dialog', { name: /Preview.*Person 1/ })
  await expect(dialog).toBeVisible()
  const proposal = dialog.getByRole('table', { name: 'Proposed change' })
  await expect(dialog.getByText('New booking', { exact: true })).toBeVisible()
  await expect(proposal.getByRole('row', { name: /Allocation/ })).toContainText('100 %')
  await expect(proposal.getByRole('row', { name: /Start Date/ })).toContainText('2099-01-05')
  await measure.step(() => dialog.getByRole('button', { name: 'Assign', exact: true }).click())
  await expect(dialog).toBeHidden()
  await expect(verdict.getByText('No blockers within scope', { exact: true })).toHaveCount(4)
  await expect(verdict.getByText(/Shared presence during a particular machine shift/)).toBeVisible()
  await info.attach('staffing-task-measurement', {
    body: JSON.stringify(measure.result()),
    contentType: 'application/json',
  })
  await page.screenshot({ path: info.outputPath('readiness-desktop-light.png'), fullPage: true })
  await page.getByRole('button', { name: 'Toggle color scheme', exact: true }).click()
  await expect(page.locator('html')).toHaveAttribute('data-mantine-color-scheme', 'dark')
  await expect(verdict).toBeVisible()
  await page.screenshot({ path: info.outputPath('readiness-desktop-dark.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(verdict).toBeVisible()
  await expect
    .poll(() =>
      page
        .locator('#capado-navigation')
        .evaluate(
          (node) =>
            getComputedStyle(node).visibility === 'hidden' ||
            node.getBoundingClientRect().right <= 0,
        ),
    )
    .toBe(true)
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth))
    .toBe(true)
  await page.screenshot({ path: info.outputPath('readiness-mobile.png'), fullPage: true })
})

test('combined planning: explain and repair an overnight machine overlap', async ({
  page,
}, info) => {
  await start(page, 'machine')
  const measure = measurement()
  await selectPackage(page, measure.step)
  const verdict = page.getByTestId('work-package-readiness')
  await expect(
    verdict.getByText('Exclusive equipment bookings overlap', { exact: true }),
  ).toBeVisible()
  await expect(
    verdict.getByText('Booking extends outside operating windows', { exact: true }),
  ).toBeVisible()
  const ranked = verdict.getByRole('list', { name: 'Resolution Suggestions', exact: true })
  await expect(ranked.getByRole('listitem')).toHaveCount(5)
  await expect(ranked.getByRole('listitem').first()).toContainText('0 remaining')
  await measure.diagnostic(() =>
    page.screenshot({ path: info.outputPath('readiness-machine-blockers.png'), fullPage: true }),
  )
  await measure.step(() =>
    verdict
      .getByRole('button', { name: 'Review all resource bookings', exact: true })
      .first()
      .click(),
  )
  await expect(page.getByRole('tab', { name: 'Assignments', exact: true })).toHaveAttribute(
    'aria-selected',
    'true',
  )
  await expect(page.getByRole('tab', { name: 'Assignments', exact: true })).toBeFocused()
  await expect(page.getByRole('row').filter({ hasText: 'Fictional crane' })).toHaveCount(2)
  await expect(page.getByText('Person 0', { exact: true })).toHaveCount(0)
  await measure.step(() =>
    page
      .getByRole('row')
      .filter({ hasText: 'Fictional crane' })
      .filter({ hasText: '21:00' })
      .getByRole('button', { name: 'Edit assignment', exact: true })
      .click(),
  )
  const dialog = page.getByRole('dialog', { name: 'Edit Assignment', exact: true })
  await measure.step(() => dialog.getByLabel(/^Occupied From/).click())
  await measure.step(() =>
    page.getByRole('button', { name: '6 January 2099', exact: true }).click(),
  )
  await measure.step(() => page.getByPlaceholder('--', { exact: true }).first().fill('02'))
  await measure.step(() => page.getByPlaceholder('--', { exact: true }).first().press('Tab'))
  await measure.step(() => page.locator('.mantine-DateTimePicker-submitButton').click())
  await expect(page.locator('[data-dates-dropdown]')).toHaveCount(0)
  await measure.step(() => dialog.getByLabel(/^Occupied Until/).click())
  await measure.step(() => page.getByPlaceholder('--', { exact: true }).first().fill('06'))
  await measure.step(() => page.getByPlaceholder('--', { exact: true }).first().press('Tab'))
  await measure.step(() => page.locator('.mantine-DateTimePicker-submitButton').click())
  await expect(page.locator('[data-dates-dropdown]')).toHaveCount(0)
  await measure.step(() => dialog.getByRole('button', { name: 'Save', exact: true }).click())
  await expect(dialog).toBeHidden()
  await measure.step(() => page.getByRole('tab', { name: 'Overview', exact: true }).click())
  await expect(verdict.getByText('No blockers within scope', { exact: true })).toHaveCount(4)
  await expect(
    verdict.getByText('Exclusive equipment bookings overlap', { exact: true }),
  ).toHaveCount(0)
  await expect(
    verdict.getByText('Booking extends outside operating windows', { exact: true }),
  ).toHaveCount(0)
  await info.attach('machine-task-measurement', {
    body: JSON.stringify(measure.result()),
    contentType: 'application/json',
  })
})

test('combined planning: a qualification blocker remains visible beside missing staffing', async ({
  page,
}, info) => {
  await start(page, 'qualification')
  await selectPackage(page, measurement().step)
  const verdict = page.getByTestId('work-package-readiness')
  await expect(verdict.getByText('Conflicting', { exact: true })).toHaveCount(2)
  await expect(verdict.getByText('Missing requirements', { exact: true })).toHaveCount(1)
  await expect(verdict.getByText(/These bookings meet none of the package/)).toBeVisible()
  await expect(verdict.getByText('Person 0', { exact: true })).toBeVisible()
  await page.screenshot({
    path: info.outputPath('readiness-qualification-blocker.png'),
    fullPage: true,
  })
})

test('combined planning: an overnight booking gets a current free-window suggestion', async ({
  page,
}, info) => {
  await start(page, 'overnight')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await selectPackage(page, measurement().step)
  const verdict = page.getByTestId('work-package-readiness')
  await expect(
    verdict.getByText('Booking extends outside operating windows', { exact: true }),
  ).toBeVisible()
  await verdict.getByRole('button', { name: 'Preview', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: /Preview: Move to/ })
  await expect(dialog.getByText('Conflicts: 1 → 0', { exact: true })).toBeVisible()
  const proposal = dialog.getByRole('table', { name: 'Proposed change' })
  const fromRow = proposal.getByRole('row', { name: /Occupied From/ })
  const untilRow = proposal.getByRole('row', { name: /Occupied Until/ })
  await expect(fromRow).toContainText('2099-01-07 21:00:00 (UTC+01:00)')
  await expect(fromRow).toContainText('2099-01-06 02:00:00 (UTC+01:00)')
  await expect(untilRow).toContainText('2099-01-08 01:00:00 (UTC+01:00)')
  await expect(untilRow).toContainText('2099-01-06 06:00:00 (UTC+01:00)')
  await expect(proposal.getByRole('row', { name: /Duration/ })).toContainText('Unchanged')
  await page.screenshot({
    path: info.outputPath('readiness-overnight-preview.png'),
    fullPage: false,
  })
  await page.setViewportSize({ width: 390, height: 844 })
  const mobileProposal = dialog.getByRole('list', { name: 'Proposed change' })
  await expect(mobileProposal).toBeVisible()
  await expect(proposal).toBeHidden()
  await expect(
    mobileProposal.getByRole('listitem').filter({ hasText: 'Occupied From' }),
  ).toContainText('2099-01-06 02:00:00 (UTC+01:00)')
  await expect
    .poll(() => dialog.evaluate((node) => node.scrollWidth <= node.clientWidth))
    .toBe(true)
  await page.screenshot({
    path: info.outputPath('readiness-overnight-preview-mobile.png'),
    fullPage: false,
  })
  const updated = page.waitForResponse(
    (response) =>
      response.url().includes('/api/assignments/') && response.request().method() === 'PUT',
  )
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  const saved = (await (await updated).json()).assignment
  expect(saved.start_at).toBe('2099-01-06T01:00:00Z')
  expect(saved.end_at).toBe('2099-01-06T05:00:00Z')
  await expect(dialog).toBeHidden()
  await expect(verdict.getByText('No blockers within scope', { exact: true })).toHaveCount(4)
})

test('combined planning: equipment alternatives never offer a person and apply with the original type', async ({
  page,
}, info) => {
  await start(page, 'replacement')
  await selectPackage(page, measurement().step)
  const verdict = page.getByTestId('work-package-readiness')
  await verdict.getByRole('button').filter({ hasText: 'SKILL' }).click()
  await expect(
    verdict.getByText("Swap to 'Replacement crane' (available)", { exact: true }),
  ).toBeVisible()
  await expect(verdict.getByText(/Swap to 'Available person'/)).toHaveCount(0)
  await verdict.getByRole('button', { name: 'Preview', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: /Preview: Swap to 'Replacement crane'/ })
  await expect(dialog.getByText('Conflicts: 0 → 0', { exact: true })).toHaveCount(2)
  const proposal = dialog.getByRole('table', { name: 'Proposed change' })
  const resource = proposal.getByRole('row', { name: /Resource/ })
  await expect(resource.getByText('Fictional crane', { exact: true })).toBeVisible()
  await expect(resource.getByText('Replacement crane', { exact: true })).toBeVisible()
  await expect(proposal.getByRole('row', { name: /Occupied From/ })).toContainText('Unchanged')
  await page.screenshot({
    path: info.outputPath('readiness-equipment-swap-preview.png'),
    fullPage: true,
  })
  const updated = page.waitForResponse(
    (response) =>
      response.url().includes('/api/assignments/') && response.request().method() === 'PUT',
  )
  await dialog.getByRole('button', { name: 'Apply', exact: true }).click()
  const response = await updated
  expect(response.ok()).toBe(true)
  expect((await response.json()).assignment.resource_type).toBe('infrastructure')
  await expect(dialog).toBeHidden()
  await expect(verdict.getByText('No blockers within scope', { exact: true })).toHaveCount(4)
})
