// Run in a clean checkout without .env files. Uses the existing Compose stack
// and Playwright dependency; owns and removes only its disposable demo stack.
import { execFileSync } from 'node:child_process'
import { mkdtemp, writeFile, access, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { randomUUID } from 'node:crypto'

const root = fileURLToPath(new URL('../../', import.meta.url))
const { chromium, expect } = createRequire(new URL('../../frontend/package.json', import.meta.url))(
  '@playwright/test',
)
const run = (command, args, options = {}) =>
  execFileSync(command, args, { cwd: root, encoding: 'utf8', ...options })
for (const file of [
  '.env',
  'backend/.env',
  'frontend/.env',
  'frontend/.env.local',
  'frontend/.env.development',
  'frontend/.env.development.local',
]) {
  const exists = await access(join(root, file)).then(
    () => true,
    () => false,
  )
  if (exists) throw new Error(`Use a fresh checkout without ${file}`)
}
run('git', [
  'diff',
  '--exit-code',
  'origin/main',
  '--',
  'backend',
  'frontend',
  'docker-compose.yml',
])
const sha = run('git', ['rev-parse', 'origin/main']).trim()
const temporary = await mkdtemp(join(tmpdir(), 'capado-readme-'))
const suffix = randomUUID().slice(0, 8)
const project = `capado-readme-${suffix}`
const database = `capado_e2e_readme_${suffix}`
const envFile = join(temporary, 'demo.env')
const composeFile = join(temporary, 'compose.json')
const password = 'readme-screenshots-only'
const url = 'http://127.0.0.1:43800'
await writeFile(
  envFile,
  `POSTGRES_USER=readme\nPOSTGRES_PASSWORD=${password}\nPOSTGRES_DB=${database}\nDATABASE_URL=postgresql+asyncpg://readme:${password}@db:5432/${database}\nCAPADO_DEV_DATABASE_VOLUME=${project}\n`,
  { mode: 0o600 },
)
const config = JSON.parse(
  run('docker', [
    'compose',
    '--project-name',
    project,
    '--env-file',
    envFile,
    '-f',
    'docker-compose.yml',
    'config',
    '--format',
    'json',
  ]),
)
for (const service of Object.values(config.services)) {
  delete service.container_name
  service.restart = 'no'
  delete service.ports
}
config.services.frontend.ports = [
  { target: 3000, published: '43800', host_ip: '127.0.0.1', protocol: 'tcp' },
]
config.services.backend.environment = {
  DATABASE_URL: `postgresql+asyncpg://readme:${password}@db:5432/${database}`,
  ENVIRONMENT: 'test',
  JWT_SECRET_KEY: 'readme-screenshots-only-never-production',
  COOKIE_SECURE: 'false',
  CORS_ORIGINS: JSON.stringify([url]),
}
config.services.backend.command = [
  'uv',
  'run',
  'uvicorn',
  'app.main:app',
  '--host',
  '0.0.0.0',
  '--port',
  '3001',
]
config.volumes = {
  postgres_data: { name: project, labels: { 'capado.readme': 'true' } },
}
await writeFile(composeFile, JSON.stringify(config), { mode: 0o600 })
const composeArgs = ['compose', '--project-name', project, '-f', composeFile]
const compose = (...args) => run('docker', [...composeArgs, ...args], { stdio: 'inherit' })
let browser
try {
  compose('up', '-d', '--build', '--wait', 'db', 'backend')
  // Resolve once after startup so Docker's intermittent DNS does not interrupt
  // API writes or captures. This address belongs only to this disposable stack.
  const backend = run('docker', [...composeArgs, 'ps', '-q', 'backend']).trim()
  const inspection = JSON.parse(run('docker', ['inspect', backend]))[0]
  const address = inspection.NetworkSettings.Networks[`${project}_default`].IPAddress
  config.services.frontend.environment.VITE_DEV_API_TARGET = `http://${address}:3001`
  await writeFile(composeFile, JSON.stringify(config), { mode: 0o600 })
  compose('up', '-d', '--build', '--wait', '--no-deps', 'frontend')
  // Bootstrap the fictional user via the same application model/password
  // service as the E2E seed. All planning data below uses real API writes.
  compose(
    'exec',
    '-T',
    'backend',
    '.venv/bin/python',
    '-c',
    `
import asyncio
from sqlalchemy import select, func
import app.models
from app.database import async_session_factory, engine
from app.models.user import User
from app.services.auth_service import hash_password
async def main():
    assert engine.url.database == '${database}'
    async with async_session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 0
        session.add(User(email='admin@example.test', name='Demo Admin', role='admin', password_hash=hash_password('${password}'), must_change_password=False))
        await session.commit()
    await engine.dispose()
asyncio.run(main())
`,
  )
  let token
  async function api(path, data, method = 'POST') {
    const response = await fetch(`${url}/api${path}`, {
      method,
      signal: AbortSignal.timeout(30_000),
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    })
    if (!response.ok)
      throw new Error(`${method} ${path}: ${response.status} ${await response.text()}`)
    return response.json()
  }
  token = (await api('/auth/login', { email: 'admin@example.test', password })).access_token
  const today = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Berlin',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
  const monday = new Date(`${today}T12:00:00Z`)
  monday.setUTCDate(monday.getUTCDate() - ((monday.getUTCDay() + 6) % 7))
  const date = (offset) => new Date(monday.getTime() + offset * 86400000).toISOString().slice(0, 10)
  await api(
    '/settings',
    {
      company_name: 'Capado Demo',
      primary_color: '#327e78',
      time_zone: 'Europe/Berlin',
      scheduler_enabled: true,
      smtp_enabled: false,
    },
    'PUT',
  )
  await api('/work-week-profiles', { name: 'Demo · 40 h', is_default: true })
  const sites = [
    await api('/sites', { name: 'Demo Nord', is_default: true }),
    await api('/sites', { name: 'Demo Süd' }),
  ]
  const groups = []
  for (const name of ['Team A', 'Team B', 'Team C'])
    groups.push(await api('/resource-groups', { name, resource_type: 'personal' }))
  const machines = await api('/resource-groups', {
    name: 'Demo Anlagen',
    resource_type: 'infrastructure',
  })
  const people = []
  for (const [index, name] of [
    'Mara Winter',
    'Jonas Falk',
    'Lea Sommer',
    'Nils Berg',
    'Sofia Hart',
    'Emil Wolf',
    'Ella Stern',
    'Paul Linden',
  ].entries())
    people.push(
      await api('/resources/personal', {
        name,
        group_id: groups[Math.floor(index / 3)].id,
        site_id: sites[index % 2].id,
      }),
    )
  const infra = []
  for (const name of ['CNC-1', 'Montage-1', 'Prüfstand-1'])
    infra.push(
      await api('/resources/infrastructure', {
        name,
        group_id: machines.id,
        site_id: sites[0].id,
      }),
    )
  const projects = []
  const packages = []
  // Dates are day offsets from Monday: project name/start/end/delivery, then stages.
  const plans = [
    [
      'Atlas · A-104',
      0,
      18,
      11,
      [
        ['CNC', 0, 9],
        ['Montage', 7, 18],
      ],
    ],
    [
      'Orion · B-207',
      2,
      18,
      18,
      [
        ['Montage', 2, 11],
        ['Prüfung', 10, 18],
      ],
    ],
    [
      'Nova · C-310',
      -3,
      -3,
      -3,
      [
        ['CNC', -3, -3],
        ['Prüfung', -3, -3],
      ],
    ],
    [
      'Lyra · D-402',
      14,
      18,
      18,
      [
        ['CNC', 14, 16],
        ['Prüfung', 17, 18],
      ],
    ],
  ]
  for (const [name, start, end, delivery, stages] of plans) {
    const project = await api('/projects', {
      name,
      start_date: date(start),
      end_date: date(end),
      committed_delivery_date: date(delivery),
    })
    projects.push(project)
    const stagePackages = []
    for (const [name, start, end] of stages)
      stagePackages.push(
        (
          await api(`/projects/${project.id}/work-packages`, {
            name,
            start_date: date(start),
            end_date: date(end),
          })
        ).work_package,
      )
    packages.push(stagePackages)
  }
  for (const wp of packages[2])
    await api(
      `/projects/${projects[2].id}/work-packages/${wp.id}`,
      { completed_at: `${wp.end_date}T15:00:00Z` },
      'PUT',
    )
  const bookings = [
    [0, 0, 0, 0, 9, 60],
    [0, 1, 0, 2, 11, 60],
    [1, 0, 1, 7, 18, 70],
    [2, 1, 0, 2, 11, 50],
    [3, 1, 1, 10, 18, 60],
    [4, 0, 0, 0, 9, 80],
    [5, 3, 0, 14, 16, 75],
    [6, 3, 1, 17, 18, 60],
    [7, 2, 0, -3, -3, 45],
  ]
  for (const [person, project, wp, start, end, percent] of bookings)
    await api('/assignments', {
      resource_id: people[person].id,
      resource_type: 'personal',
      work_package_id: packages[project][wp].id,
      start_date: date(start),
      end_date: date(end),
      allocation_percent: percent,
    })
  for (const [machine, project, wp, start, end] of [
    [0, 0, 0, 0, 9],
    [1, 1, 0, 2, 11],
    [2, 1, 1, 10, 18],
  ])
    await api('/assignments', {
      resource_id: infra[machine].id,
      resource_type: 'infrastructure',
      work_package_id: packages[project][wp].id,
      start_at: `${date(start)}T06:00:00Z`,
      end_at: `${date(end)}T14:00:00Z`,
    })
  const overview = await api('/projects/overview', undefined, 'GET')
  if (!overview.projects.some((project) => project.open_conflict_count > 0))
    throw new Error('The seeded overbooking must create a real conflict')
  const check = await api('/conflicts/check-status', undefined, 'GET')
  if (!check.enabled || check.stale || check.status !== 'succeeded')
    throw new Error('The isolated conflict checker must be healthy before capture')
  browser = await chromium.launch()
  for (const locale of ['de', 'en']) {
    const context = await browser.newContext({
      viewport: { width: 1600, height: 1000 },
      locale: locale === 'de' ? 'de-DE' : 'en-GB',
      timezoneId: 'Europe/Berlin',
      reducedMotion: 'reduce',
    })
    await context.addInitScript(
      (locale) =>
        localStorage.setItem(
          'user-preferences',
          JSON.stringify({ locale, colorScheme: 'light', navCollapsed: false }),
        ),
      locale,
    )
    const page = await context.newPage()
    await page.clock.setFixedTime(new Date(`${today}T12:00:00Z`))
    await page.goto(`${url}/login`)
    await page.getByLabel(/E-Mail|Email/).fill('admin@example.test')
    await page.getByLabel(/Passwort|Password/).fill(password)
    await page
      .getByRole('button', {
        name: locale === 'de' ? 'Anmelden' : 'Sign In',
        exact: true,
      })
      .click()
    await expect(page).toHaveURL(`${url}/`)
    async function capture(name) {
      await page.waitForLoadState('networkidle')
      await expect(page.locator('.mantine-Skeleton-root[data-visible]:visible')).toHaveCount(0)
      await page.mouse.move(1590, 990)
      await expect(page.getByRole('tooltip')).toHaveCount(0)
      await page.screenshot({
        path: resolve(root, `docs/assets/screenshots/${name}-${locale}.png`),
        animations: 'disabled',
      })
    }
    await expect(page.locator('.recharts-surface').first()).toBeVisible()
    await capture('dashboard')
    await page.goto(`${url}/gantt`)
    for (const project of projects) await page.getByTestId(`project-toggle-${project.id}`).click()
    await page
      .getByRole('main')
      .getByText(locale === 'de' ? 'Tag' : 'Day', { exact: true })
      .click()
    for (const wp of packages.flat())
      await expect(page.getByTestId(`gantt-bar-${wp.id}`)).toBeVisible()
    await capture('gantt-projects')
    await page.goto(`${url}/people`)
    for (const person of people)
      await expect(page.getByText(person.name, { exact: true }).first()).toBeVisible()
    await expect(page.locator('[data-density="comfortable"]')).toBeVisible()
    await capture('people')
    await context.close()
  }
  console.log(
    JSON.stringify(
      {
        source: sha,
        planningDate: today,
        viewport: '1600 × 1000',
        projects: projects.length,
        workPackages: packages.flat().length,
        people: people.length,
        infrastructure: infra.length,
        assignments: bookings.length + 3,
        projectConflictCountsSum: overview.projects.reduce((sum, p) => sum + p.open_conflict_count, 0),
        companyColor: '#327e78',
      },
      null,
      2,
    ),
  )
} catch (error) {
  compose('logs', '--tail', '25')
  throw error
} finally {
  await browser?.close()
  compose('down', '--volumes', '--remove-orphans')
  await rm(temporary, { recursive: true, force: true })
}
