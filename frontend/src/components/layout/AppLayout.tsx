import { useEffect } from 'react'
import {
  ActionIcon,
  AppShell,
  Badge,
  NavLink,
  ScrollArea,
  Tooltip,
  Group,
  Text,
  Burger,
  Divider,
  Box,
  Image,
  Menu,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { useMantineColorScheme } from '@mantine/core'
import { Link, Outlet, useLocation } from 'react-router-dom'
import {
  IconBriefcase,
  IconBuilding,
  IconCalendarEvent,
  IconCamera,
  IconChartBar,
  IconClockHour4,
  IconDashboard,
  IconHelp,
  IconHistory,
  IconLanguage,
  IconLogout,
  IconMoon,
  IconSettings,
  IconShieldLock,
  IconSun,
  IconUser,
  IconUsers,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
} from '@tabler/icons-react'
import { useSettings } from '../../context/SettingsContext'
import { useTranslation, type Locale } from '../../i18n'
import { useAuth } from '../../context/AuthContext'
import { usePermissions } from '../../hooks/usePermissions'
import { ChangePasswordModal } from '../../features/auth/ChangePasswordModal'
import { HelpDrawer } from '../../features/help/HelpDrawer'
import { getLogoUrl } from '../../api/settings'
import { APP_VERSION } from '../../version'
import './AppLayout.css'

const ROLE_BADGE_COLORS: Record<string, string> = {
  admin: 'red',
  editor: 'blue',
  viewer: 'gray',
}

/**
 * Navigation is grouped by the QUESTION a planner is asking, not by table.
 *
 * A flat list of twelve entries mirrors the data model — one row per table — and
 * leaves the user to work out which of them answers what. A planner's day has
 * three modes instead: plan (assign work), maintain (keep the master data true),
 * and administer (settings that are not planning at all). The entry points
 * (dashboard, own plan) carry no heading: they are where you land, not a mode.
 *
 * `adminOnly` lives on the ITEM, not the group, so a group can mix both. It
 * repeats exactly the set that was admin-gated before this regrouping — the
 * headings are a labelling change and must not move a permission.
 */
/*
  The collapsed width is a SHARED number, not two numbers that happen to match. It sizes the navbar,
  and it also sizes the block in the header that holds the collapse control — which is what puts that
  control in the same vertical line as the icons below it. Written as one constant so the alignment
  cannot drift the next time the bar is retuned: change it here and both move together.

  68px fits a 28px icon inside a NavLink's own padding without the icon looking wedged in.
*/
const NAV_WIDTH_COLLAPSED = 68
const NAV_WIDTH_EXPANDED = 260

const NAV_GROUPS = [
  {
    labelKey: null,
    items: [
      { labelKey: 'nav.dashboard', path: '/', icon: IconDashboard },
      // Everyone, including viewers: this is the one page that shows a person their OWN data, which
      // until now only their leaders and administrators could see. Restricting it by role would
      // defeat the point.
      { labelKey: 'nav.myPlan', path: '/my-plan', icon: IconUser },
    ],
  },
  {
    labelKey: 'nav.groupPlan',
    items: [
      { labelKey: 'nav.planning', path: '/planning', icon: IconCalendarEvent },
      { labelKey: 'nav.gantt', path: '/gantt', icon: IconChartBar },
      // Baselines are READABLE by anyone, but only an admin can freeze or delete one, so
      // the page stays admin-gated — grouped under planning because comparing plan states
      // is part of planning, not of administration.
      { labelKey: 'nav.baselines', path: '/baselines', icon: IconCamera, adminOnly: true },
    ],
  },
  {
    labelKey: 'nav.groupMaintain',
    items: [
      { labelKey: 'nav.people', path: '/people', icon: IconUsers },
      { labelKey: 'nav.infrastructure', path: '/infrastructure', icon: IconBuilding },
      { labelKey: 'nav.projects', path: '/projects', icon: IconBriefcase },
      // Admin-side: editing a week profile silently changes the capacity of every
      // resource using it, which is not a group-scoped edit.
      { labelKey: 'nav.workingTime', path: '/working-time', icon: IconClockHour4, adminOnly: true },
    ],
  },
  {
    labelKey: 'nav.groupAdmin',
    items: [
      { labelKey: 'nav.settings', path: '/settings', icon: IconSettings, adminOnly: true },
      {
        labelKey: 'nav.userManagement',
        path: '/admin/users',
        icon: IconShieldLock,
        adminOnly: true,
      },
      // Admin-only because the log holds behavioural data about the planners themselves,
      // which is § 87 Abs. 1 Nr. 6 BetrVG relevant (ADR-006).
      { labelKey: 'nav.audit', path: '/audit', icon: IconHistory, adminOnly: true },
    ],
  },
] as const

/**
 * Main application shell with header, sidebar navigation, and footer.
 * Renders the active route via Outlet and provides access to help drawer,
 * language switcher, color scheme toggle, and user menu.
 */
export function AppLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const [helpDrawerOpened, { open: openHelpDrawer, close: closeHelpDrawer }] = useDisclosure()
  const location = useLocation()
  const { settings, updatePreferences, hasUploadedLogo } = useSettings()
  const navCollapsed = settings.navCollapsed
  const { t } = useTranslation()
  const { colorScheme } = useMantineColorScheme()
  const { user, logout } = useAuth()
  const { isAdmin } = usePermissions()

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault()
        openHelpDrawer()
      }
      if (e.key === 'Escape') close()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [openHelpDrawer, close])

  const handleLocaleSwitch = (locale: Locale) => updatePreferences({ locale })
  const handleColorSchemeToggle = () =>
    updatePreferences({ colorScheme: colorScheme === 'dark' ? 'light' : 'dark' })

  return (
    <AppShell
      className="capado-shell"
      header={{ height: { base: 112, sm: 76 } }}
      navbar={{
        width: {
          base: NAV_WIDTH_EXPANDED,
          sm: navCollapsed ? NAV_WIDTH_COLLAPSED : NAV_WIDTH_EXPANDED,
        },
        breakpoint: 'sm',
        collapsed: { mobile: !opened },
      }}
      footer={{ height: 28 }}
      padding={{ base: 'sm', md: 'xl' }}
    >
      <AppShell.Header className="capado-header">
        <div className="capado-header-inner">
          <Group gap="sm" wrap="nowrap" className="capado-brand">
            <Group w={{ base: 36, sm: NAV_WIDTH_COLLAPSED }} justify="center" gap={0}>
              <Burger
                opened={opened}
                onClick={toggle}
                hiddenFrom="sm"
                size="sm"
                aria-label={opened ? t('nav.collapse') : t('nav.expand')}
                aria-expanded={opened}
                aria-controls="capado-navigation"
              />
              <Tooltip
                label={navCollapsed ? t('nav.expand') : t('nav.collapse')}
                position="bottom"
                withArrow
                events={{ hover: true, focus: true, touch: true }}
              >
                <ActionIcon
                  variant="subtle"
                  color="var(--capado-muted)"
                  visibleFrom="sm"
                  size="lg"
                  aria-label={navCollapsed ? t('nav.expand') : t('nav.collapse')}
                  aria-expanded={!navCollapsed}
                  aria-controls="capado-navigation"
                  onClick={() => updatePreferences({ navCollapsed: !navCollapsed })}
                >
                  {navCollapsed ? (
                    <IconLayoutSidebarLeftExpand size={20} stroke={1.5} />
                  ) : (
                    <IconLayoutSidebarLeftCollapse size={20} stroke={1.5} />
                  )}
                </ActionIcon>
              </Tooltip>
            </Group>
            <Image
              src={hasUploadedLogo ? getLogoUrl() : settings.logoUrl || '/favicon.svg'}
              alt={settings.logoUrl || hasUploadedLogo ? 'Logo' : 'Capado'}
              w={36}
              h={36}
              radius={8}
              fit="contain"
              className="capado-brand-logo"
            />
            <div className="capado-brand-text">
              <Text size="md" fw={700} lh={1.3} truncate>
                {settings.companyName}
              </Text>
              {settings.companySubtitle && (
                <Text size="xs" c="dimmed" truncate>
                  {settings.companySubtitle}
                </Text>
              )}
            </div>
          </Group>
          <Group gap={4} wrap="nowrap" className="capado-header-actions">
            {user && (
              <Group gap="xs" wrap="nowrap" className="capado-user">
                <Text size="sm" fw={500} truncate>
                  {user.name}
                </Text>
                <Badge size="sm" variant="light" color={ROLE_BADGE_COLORS[user.role] ?? 'gray'}>
                  {user.role}
                </Badge>
              </Group>
            )}
            <Menu shadow="md" width={160}>
              <Menu.Target>
                <ActionIcon
                  variant="subtle"
                  color="var(--capado-muted)"
                  size="lg"
                  aria-label={t('appLayout.language')}
                >
                  <IconLanguage size={20} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item
                  onClick={() => handleLocaleSwitch('de')}
                  fw={settings.locale === 'de' ? 700 : 400}
                >
                  Deutsch
                </Menu.Item>
                <Menu.Item
                  onClick={() => handleLocaleSwitch('en')}
                  fw={settings.locale === 'en' ? 700 : 400}
                >
                  English
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
            <ActionIcon
              variant="subtle"
              color="var(--capado-muted)"
              size="lg"
              onClick={handleColorSchemeToggle}
              aria-label={t('appLayout.toggleColorScheme')}
            >
              {colorScheme === 'dark' ? <IconSun size={20} /> : <IconMoon size={20} />}
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="var(--capado-muted)"
              size="lg"
              onClick={openHelpDrawer}
              aria-label={t('appLayout.help')}
            >
              <IconHelp size={20} />
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="var(--capado-muted)"
              size="lg"
              onClick={logout}
              aria-label={t('appLayout.logout')}
            >
              <IconLogout size={20} />
            </ActionIcon>
          </Group>
        </div>
      </AppShell.Header>

      <AppShell.Navbar
        id="capado-navigation"
        p="sm"
        className="capado-navigation"
        data-collapsed={navCollapsed || undefined}
      >
        <AppShell.Section grow component={ScrollArea} type="auto" scrollbarSize={6}>
          {NAV_GROUPS.map((group) => {
            const visible = group.items.filter((item) => !('adminOnly' in item) || isAdmin)
            if (visible.length === 0) return null
            return (
              <Box key={group.labelKey ?? 'entry'} className="capado-nav-group">
                {group.labelKey && (
                  <>
                    <Text size="xs" fw={600} tt="uppercase" className="capado-nav-heading">
                      {t(group.labelKey)}
                    </Text>
                    <Divider className="capado-nav-separator" aria-label={t(group.labelKey)} />
                  </>
                )}
                {visible.map((item) => {
                  const isActive =
                    location.pathname === item.path ||
                    (item.path !== '/' && location.pathname.startsWith(item.path))
                  return (
                    <Tooltip
                      key={item.path}
                      label={t(item.labelKey)}
                      position="right"
                      withArrow
                      disabled={!navCollapsed || opened}
                      events={{ hover: true, focus: true, touch: true }}
                    >
                      <NavLink
                        component={Link}
                        to={item.path}
                        label={t(item.labelKey)}
                        leftSection={<item.icon size={20} stroke={1.6} />}
                        active={isActive}
                        onClick={close}
                        className="capado-nav-link"
                        aria-label={t(item.labelKey)}
                        aria-current={isActive ? 'page' : undefined}
                        variant="subtle"
                        c="var(--capado-nav-text)"
                      />
                    </Tooltip>
                  )
                })}
              </Box>
            )
          })}
        </AppShell.Section>
        <AppShell.Section className="capado-nav-footer">
          <Divider my="sm" color="rgba(255,255,255,0.12)" />
          <Text size="xs" c="var(--capado-nav-muted)" px="sm" py="xs">
            {settings.companySubtitle || settings.companyName}
          </Text>
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main className="capado-main">
        {/* Protected pages must not fetch before the required password change. */}
        {user?.must_change_password ? null : <Outlet />}
      </AppShell.Main>
      <AppShell.Footer className="capado-footer">
        <Text size="xs" c="dimmed" ta="center">
          Capado {APP_VERSION}
        </Text>
      </AppShell.Footer>
      {user?.must_change_password && <ChangePasswordModal />}
      <HelpDrawer opened={helpDrawerOpened} onClose={closeHelpDrawer} />
    </AppShell>
  )
}
