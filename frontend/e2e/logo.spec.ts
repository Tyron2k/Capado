import { test, expect } from '@playwright/test'
import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { promisify } from 'node:util'

const command = promisify(execFile)
let seed: { active_svg: string; raster_logos: Record<string, string> }

test.beforeEach(async ({ page }) => {
  await command('uv', ['--directory', '../backend', 'run', '--frozen', '--no-dev', 'python', '-m', 'tests.e2e_server', 'reset'])
  seed = JSON.parse(await readFile('.e2e-state.json', 'utf8')) as typeof seed
  await page.addInitScript(() => localStorage.setItem('user-preferences', JSON.stringify({ locale: 'en', colorScheme: 'light', navCollapsed: false })))
})

test('admin raster uploads render; SVG and disguised SVG uploads are rejected', async ({ page, context }) => {
  await page.goto('/login')
  await page.getByLabel(/^Email/).fill('admin@example.test')
  await page.getByLabel(/^Password/).fill('browser-tests-only')
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  const { access_token } = await (await login).json() as { access_token: string }
  await expect(page).toHaveURL('/')
  await page.getByRole('navigation').getByText('Settings', { exact: true }).click()
  const input = page.locator('input[type="file"][accept*="image/png"]')
  expect(await input.getAttribute('accept')).not.toContain('image/svg+xml')
  for (const [mimeType, encoded] of Object.entries(seed.raster_logos)) {
    const uploaded = page.waitForResponse(response => response.url().endsWith('/api/settings/logo') && response.request().method() === 'POST')
    await input.setInputFiles({ name: 'logo.' + mimeType.split('/')[1], mimeType, buffer: Buffer.from(encoded, 'base64') })
    expect((await uploaded).status()).toBe(204)
    await expect.poll(() => page.getByAltText('Logo preview').evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(1)
  }
  for (const mimeType of ['image/svg+xml', 'image/png']) {
    const rejected = await context.request.post('/api/settings/logo', {
      headers: { Authorization: 'Bearer ' + access_token },
      multipart: { file: { name: 'logo.svg', mimeType, buffer: Buffer.from(seed.active_svg, 'base64') } },
    })
    expect(rejected.status()).toBe(400)
  }
})

test('legacy SVG direct navigation cannot run scripts or event handlers on either endpoint', async ({ page, context }) => {
  await command('uv', ['--directory', '../backend', 'run', '--frozen', '--no-dev', 'python', '-m', 'tests.e2e_server', 'legacy-logo'])
  const external: string[] = []
  const blocked: string[] = []
  const externalResponses: string[] = []
  page.on('request', request => { if (request.url().includes('logo-security-external-probe')) external.push(request.url()) })
  page.on('requestfailed', request => {
    if (request.url().includes('logo-security-external-probe') && ['csp', 'net::ERR_BLOCKED_BY_CSP'].includes(request.failure()?.errorText ?? '')) blocked.push(request.url())
  })
  page.on('response', response => { if (response.url().includes('logo-security-external-probe')) externalResponses.push(response.url()) })
  for (const url of ['/api/settings/logo', 'http://127.0.0.1:38601/api/settings/logo']) {
    const response = await page.goto(url)
    expect(response!.status()).toBe(200)
    expect(await page.evaluate(() => [document.documentElement.getAttribute('data-script'), document.documentElement.getAttribute('data-onload')])).toEqual([null, null])
    expect(response!.headers()['content-security-policy']).toBe("default-src 'none'; style-src 'unsafe-inline'; sandbox")
    expect(response!.headers()['x-content-type-options']).toBe('nosniff')
    expect(response!.headers()['cache-control']).toBe('no-store')
    expect(await page.evaluate(() => {
      const denied = (read: () => unknown) => {
        try { read(); return false } catch (error) { return error instanceof DOMException && error.name === 'SecurityError' }
      }
      return [denied(() => document.cookie), denied(() => localStorage.length)]
    })).toEqual([true, true])
    await expect(page.locator('svg > rect')).toHaveAttribute('fill', 'green')
    // Playwright reports attempted requests even when CSP blocks them before
    // network delivery. Every attempt must fail due to CSP, without a response.
    await expect.poll(() => blocked).toEqual(external)
    expect(externalResponses).toEqual([])
  }
  // Existing logos remain displayable as images without changing stored bytes.
  const embedded = await context.newPage()
  await embedded.setContent('<img src="http://127.0.0.1:38601/api/settings/logo" alt="Legacy logo">')
  await expect.poll(() => embedded.getByAltText('Legacy logo').evaluate(image => (image as HTMLImageElement).naturalWidth)).toBe(36)
  const original = await context.request.get('/api/settings/logo')
  expect(await original.body()).toEqual(Buffer.from(seed.active_svg, 'base64'))
  await embedded.close()
})
