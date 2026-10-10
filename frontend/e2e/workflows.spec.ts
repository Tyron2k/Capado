import { test, expect } from '@playwright/test'
import type { Page, Locator } from '@playwright/test'
import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { promisify } from 'node:util'

type Seed = { start: string; end: string; owned: string; foreign: string }
let seed: Seed
const command = promisify(execFile)

const dateText = (value: string) => value.split('-').reverse().join('.')
async function dates(dialog: Locator) {
  await dialog.getByLabel(/^Start Date/).fill(dateText(seed.start))
  await dialog.getByLabel(/^Start Date/).press('Tab')
  await dialog.getByLabel(/^End Date/).fill(dateText(seed.end))
  await dialog.getByLabel(/^End Date/).press('Tab')
}
async function login(page: Page) {
  await page.goto('/login')
  await page.getByLabel(/^Email/).fill('editor@example.test')
  await page.getByLabel(/^Password/).fill('browser-tests-only')
  const response = page.waitForResponse(r => r.url().endsWith('/api/auth/login') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  const body = await (await response).json() as { access_token: string }
  await expect(page).toHaveURL('/')
  return body.access_token
}

test.beforeEach(async ({ page }) => {
  await command('uv', ['--directory', '../backend', 'run', '--frozen', '--no-dev', 'python', '-m', 'tests.e2e_server', 'reset'])
  seed = JSON.parse(await readFile('.e2e-state.json', 'utf8')) as Seed
  await page.addInitScript(() => localStorage.setItem('user-preferences', JSON.stringify({ locale: 'en', colorScheme: 'light', navCollapsed: false })))
})

test('editor creates a project and package, checks overview/Gantt and edits the project', async ({ page }) => {
  await login(page)
  await page.getByRole('navigation').getByText('Projects', { exact: true }).click()
  await page.getByRole('button', { name: 'New Project', exact: true }).click()
  let dialog = page.getByRole('dialog')
  await dialog.getByLabel(/^Name/).fill('Browser created project')
  await dates(dialog)
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toBeHidden()
  let row = page.getByRole('row').filter({ hasText: 'Browser created project' })
  await row.getByRole('button', { name: 'Show work packages' }).click()
  await page.getByRole('button', { name: 'New Work Package', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel(/^Name/).fill('Browser created package')
  await dates(dialog)
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(page.getByRole('row').filter({ hasText: 'Browser created package' })).toBeVisible()
  await page.getByRole('navigation').getByText('Dashboard', { exact: true }).click()
  await expect(page.getByText('Browser created project', { exact: true }).first()).toBeVisible()
  await page.getByRole('navigation').getByText('Gantt', { exact: true }).click()
  await expect(page.getByText('Browser created project', { exact: true }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Browser created project', exact: true }).click()
  await expect(page.getByText('Browser created package', { exact: true }).first()).toBeVisible()
  await page.getByRole('navigation').getByText('Projects', { exact: true }).click()
  row = page.getByRole('row').filter({ hasText: 'Browser created project' })
  await row.getByRole('button', { name: 'Edit project', exact: true }).click()
  dialog = page.getByRole('dialog')
  await dialog.getByLabel(/^Name/).fill('Browser edited project')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('row').filter({ hasText: 'Browser edited project' })).toBeVisible()
  await page.getByRole('navigation').getByText('Dashboard', { exact: true }).click()
  await expect(page.getByText('Browser edited project', { exact: true }).first()).toBeVisible()
  await expect(page.getByText('Browser created project', { exact: true })).toHaveCount(0)
})

async function assignment(page: Page, packageName: string, warning = false) {
  await page.getByRole('button', { name: 'New Assignment', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(/^Resource/).fill('Browser')
  await page.getByRole('option', { name: /Browser Person/ }).click()
  await dialog.getByLabel(/^Project/).fill('Owned')
  await page.getByRole('option', { name: 'Owned project', exact: true }).click()
  await dialog.getByLabel(/^Work Package/).fill(packageName)
  await page.getByRole('option', { name: packageName, exact: true }).click()
  await dates(dialog)
  await dialog.getByLabel(/^Allocation/).fill('60')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  if (warning) {
    await expect(dialog.getByRole('alert', { name: 'Capacity Warning' })).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click()
  }
  await expect(dialog).toBeHidden()
}

test('overbooking becomes a conflict and correcting allocation clears it', async ({ page }) => {
  await login(page)
  await page.getByRole('navigation').getByText('Planning', { exact: true }).click()
  await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
  await assignment(page, 'Owned package')
  await assignment(page, 'Second package', true)
  await page.getByRole('tab', { name: 'Overview', exact: true }).click()
  await expect(page.getByText('Browser Person', { exact: true }).first()).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Conflicts (1)', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: 'Assignments', exact: true }).click()
  await page.getByRole('button', { name: 'Edit assignment', exact: true }).last().click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(/^Allocation/).fill('40')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toBeHidden()
  await page.getByRole('tab', { name: 'Overview', exact: true }).click()
  await expect(page.getByText('No problems detected.', { exact: true })).toBeVisible()
})

test('editor can edit own scope while foreign project writes are denied by UI and API', async ({ page }) => {
  const token = await login(page)
  await page.getByRole('navigation').getByText('Projects', { exact: true }).click()
  const own = page.getByRole('row').filter({ hasText: 'Owned project' })
  await own.getByRole('button', { name: 'Edit project', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel(/^Name/).fill('Owned edited project')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('row').filter({ hasText: 'Owned edited project' })).toBeVisible()
  const foreign = page.getByRole('row').filter({ hasText: 'Foreign project' })
  await expect(foreign.getByRole('button', { name: 'Edit project', exact: true })).toHaveCount(0)
  await foreign.getByRole('button', { name: 'Show work packages' }).click()
  await expect(page.getByRole('row').filter({ hasText: 'Foreign package' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'New Work Package', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Edit work package', exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Delete work package', exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Dependencies', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Add', exact: true })).toHaveCount(0)
  const headers = { Authorization: `Bearer ${token}` }
  const denied = await page.request.put(`/api/projects/${seed.foreign}`, { headers, data: { name: 'Forbidden change' } })
  expect(denied.status()).toBe(403)
  const unchanged = await page.request.get(`/api/projects/${seed.foreign}`, { headers })
  expect(unchanged.ok()).toBeTruthy()
  expect((await unchanged.json() as { name: string }).name).toBe('Foreign project')
})
