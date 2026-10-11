import { StrictMode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import { AuthProvider } from '../../context/AuthContext'
import { OIDCCallbackPage } from './OIDCCallbackPage'
import { postRefresh } from '../../api/auth'

vi.mock('../../api/auth', () => ({ postRefresh: vi.fn(), postLogin: vi.fn(), postLogout: vi.fn() }))
vi.mock('../../api/client', () => ({ setAuthInterceptorHandlers: vi.fn() }))
vi.mock('../../i18n', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

const token = [
  btoa('{}'),
  btoa(
    JSON.stringify({
      sub: 'test-user',
      email: 'oidc@example.test',
      exp: Math.floor(Date.now() / 1000) + 3600,
    }),
  ),
  'test-signature',
].join('.')

function Destination() {
  const location = useLocation()
  return <div>{location.pathname + location.search}</div>
}

function callback(path = '/auth/oidc/callback') {
  return render(
    <StrictMode>
      <MantineProvider>
        <AuthProvider>
          <MemoryRouter initialEntries={[path]}>
            <Routes>
              <Route path="/auth/oidc/callback" element={<OIDCCallbackPage />} />
              <Route path="/" element={<Destination />} />
              <Route path="/login" element={<Destination />} />
            </Routes>
          </MemoryRouter>
        </AuthProvider>
      </MantineProvider>
    </StrictMode>,
  )
}

beforeEach(() => {
  vi.resetAllMocks()
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    value: vi
      .fn()
      .mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }),
  })
})

it('waits for the cookie bootstrap and uses one refresh under StrictMode', async () => {
  let resolve!: (value: { access_token: string }) => void
  vi.mocked(postRefresh).mockReturnValue(
    new Promise((done) => {
      resolve = done
    }),
  )
  callback()
  expect(screen.getByText('auth.oidc.processing')).toBeDefined()
  expect(postRefresh).toHaveBeenCalledTimes(1)
  resolve({ access_token: token })
  await waitFor(() => expect(screen.getByText('/')).toBeDefined())
  expect(postRefresh).toHaveBeenCalledTimes(1)
})

it.each([
  { name: 'no URL credentials', query: '' },
  { name: 'legacy access token', query: '?access_token=' + token },
  { name: 'provider error', query: '?error=' + token },
])('rejects a missing cookie without trusting or echoing URL values: $name', async ({ query }) => {
  vi.mocked(postRefresh).mockRejectedValue(new Error('missing cookie'))
  callback('/auth/oidc/callback' + query)
  await waitFor(() => expect(screen.getByText('/login?error=oidc_session_failed')).toBeDefined())
  expect(postRefresh).toHaveBeenCalledTimes(1)
  expect(screen.queryByText(token)).toBeNull()
})
