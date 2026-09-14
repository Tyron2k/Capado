import { useEffect } from 'react'
import type { CSSProperties } from 'react'
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
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
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
import { readableForeground } from '../../utils/contrast'
import { brandShade, HEADER_SHADE, NAVBAR_SHADE } from '../../utils/brand'
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
  const [opened, { toggle }] = useDisclosure()
  const [helpDrawerOpened, { open: openHelpDrawer, close: closeHelpDrawer }] = useDisclosure()
  const location = useLocation()
  const navigate = useNavigate()
  const { settings, updatePreferences, hasUploadedLogo } = useSettings()
  /**
   * The readable foreground for the header, derived from the operator's brand colour.
   *
   * Every label and icon in the header used to be hard-coded white, on a colour the operator sets in
   * settings and `hexToShades` accepts unchecked. A yellow or beige brand therefore produced a header
   * nobody could read — through a field the product invites them to change. This asks which of the two
   * foregrounds actually has more contrast rather than assuming.
   */
  /**
   * TWO BRAND SURFACES, TWO FOREGROUNDS, COMPUTED SEPARATELY.
   *
   * The navigation carries the operator's colour untouched; the header carries a darker step of it. Each
   * one is asked independently which text colour it can actually support, because for a pale brand the
   * answer differs: a light yellow navigation needs dark text while the darkened header of the same
   * yellow needs white. Reusing one foreground for both is the bug this whole helper exists to prevent,
   * just moved one surface along.
   */
  // 68px is the icon plus the navbar's own padding: wide enough that the icons are not touching the
  // edges, narrow enough that the gain over 260px is worth the labels.
  const navCollapsed = settings.navCollapsed

  const navBg = brandShade(settings.primaryColor, NAVBAR_SHADE)
  const headerBg = brandShade(settings.primaryColor, HEADER_SHADE)
  const onNav = readableForeground(navBg)
  const onBrand = readableForeground(headerBg)
  const { t } = useTranslation()

  // Ctrl+/ (⌘+/ on Mac) opens the help drawer
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault()
        openHelpDrawer()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [openHelpDrawer])
  const { colorScheme } = useMantineColorScheme()
  const { user, logout } = useAuth()
  const { isAdmin } = usePermissions()

  const handleLocaleSwitch = (locale: Locale) => {
    updatePreferences({ locale })
  }

  const handleColorSchemeToggle = () => {
    const next = colorScheme === 'dark' ? 'light' : 'dark'
    updatePreferences({ colorScheme: next })
  }

  return (
    <AppShell
      header={{ height: 64 }}
      navbar={{
        // Two independent collapse conditions, and they must not share one flag. `mobile` is the
        // burger: off-canvas, all-or-nothing, driven by `opened`. `desktop` is this feature: the bar
        // stays in the layout and loses its labels. Wiring both to `opened` would mean opening the
        // mobile drawer also un-collapses the desktop bar, and the two have nothing to do with
        // each other.
        width: navCollapsed ? NAV_WIDTH_COLLAPSED : NAV_WIDTH_EXPANDED,
        breakpoint: 'sm',
        collapsed: { mobile: !opened },
      }}
      footer={{ height: 36 }}
      padding="md"
    >
      <AppShell.Header
        // Inline, not a class. Both properties lived in AppLayout.css for one release and it cost a
        // bug: a plain class competes with Mantine's own header rule at equal specificity, so
        // stylesheet order decides — and it decided against ours. The header fell back to Mantine's
        // light default while every icon and label inside it is painted for the brand colour, so they
        // were invisible rather than merely wrong. An inline style beats every class rule, which is
        // the property the white contents depend on, and it needs no !important to get it.
        style={{ backgroundColor: headerBg, borderBottom: 'none' }}
      >
        {/* No LEFT padding on this row: the leading block below supplies its own, because it has to be
            exactly as wide as the collapsed navbar rather than as wide as the header's own gutter. */}
        <Group h="100%" pr="md" justify="space-between">
          <Group gap="sm">
            {/*
              THE CONTROL SITS IN THE SIDEBAR'S OWN COLUMN. This block is `NAV_WIDTH_COLLAPSED` wide and
              centres its single child, which lands the toggle on the same vertical line as the icons in
              the bar it controls — the alignment is derived from the bar's width, not tuned by eye.

              One child at a time, always: the burger is `hiddenFrom="sm"` and the toggle `visibleFrom="sm"`,
              so centring is unambiguous and the two never share the space.
            */}
            <Group w={NAV_WIDTH_COLLAPSED} justify="center" gap={0}>
              <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" color={onBrand} />
              {/*
              The desktop counterpart of the burger, and shown exactly where the burger is not:
              `visibleFrom="sm"` mirrors the burger's `hiddenFrom="sm"`, so there is always one control
              and never two. Below the breakpoint the navigation is off-canvas and "collapse to icons"
              has no meaning there.

              Labelled for both states rather than with a static name: a toggle whose accessible name
              does not change tells a screen-reader user which control it is but not what it will do.
            */}
              <Tooltip
                label={navCollapsed ? t('nav.expand') : t('nav.collapse')}
                position="bottom"
                withArrow
                events={{ hover: true, focus: true, touch: true }}
              >
                <ActionIcon
                  variant="subtle"
                  color={onBrand}
                  visibleFrom="sm"
                  aria-label={navCollapsed ? t('nav.expand') : t('nav.collapse')}
                  aria-expanded={!navCollapsed}
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
            <Group gap="sm">
              {settings.logoUrl || hasUploadedLogo ? (
                <Image
                  src={hasUploadedLogo ? getLogoUrl() : settings.logoUrl}
                  alt="Logo"
                  w={36}
                  h={36}
                  radius={6}
                  fit="contain"
                />
              ) : (
                <Image src="/favicon.svg" alt="Capado" w={36} h={36} fit="contain" />
              )}
              <div>
                <Text size="md" fw={700} c={onBrand} lh={1.2}>
                  {settings.companyName}
                </Text>
                {settings.companySubtitle && (
                  // Opacity rather than a second hard-coded colour: the subtitle wants to sit back
                  // from the company name, and 70% of whatever foreground is readable does that in
                  // both directions. `rgba(255,255,255,0.7)` only worked while the foreground was
                  // always white.
                  <Text size="xs" c={onBrand} opacity={0.7} lh={1.2}>
                    {settings.companySubtitle}
                  </Text>
                )}
              </div>
            </Group>
          </Group>

          <Group gap="xs">
            {/* User indicator: name + role badge */}
            {user && (
              <Group gap="xs">
                <Text size="sm" c={onBrand} fw={500}>
                  {user.name}
                </Text>
                <Badge size="sm" variant="filled" color={ROLE_BADGE_COLORS[user.role] ?? 'gray'}>
                  {user.role}
                </Badge>
              </Group>
            )}

            {/* Language switcher */}
            <Menu shadow="md" width={120}>
              <Menu.Target>
                <ActionIcon
                  variant="subtle"
                  color={onBrand}
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

            {/* Dark mode toggle */}
            <ActionIcon
              variant="subtle"
              color={onBrand}
              size="lg"
              onClick={handleColorSchemeToggle}
              aria-label={t('appLayout.toggleColorScheme')}
            >
              {colorScheme === 'dark' ? <IconSun size={20} /> : <IconMoon size={20} />}
            </ActionIcon>

            {/* Context-sensitive help button */}
            <ActionIcon
              variant="subtle"
              color={onBrand}
              size="lg"
              onClick={openHelpDrawer}
              aria-label={t('appLayout.help')}
            >
              <IconHelp size={20} />
            </ActionIcon>

            {/* Logout button */}
            <ActionIcon
              variant="subtle"
              color={onBrand}
              size="lg"
              onClick={logout}
              aria-label={t('appLayout.logout')}
            >
              <IconLogout size={20} />
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar
        p="sm"
        // `--nav-fg` is read by the state rules in AppLayout.css. They cannot use Mantine's own
        // hover/active variables any more: those are theme greys and the brand colour itself, which on a
        // brand-coloured surface give an invisible hover and a brand-on-brand active row — the exact
        // failure the reference mockup shipped, where its active entry was the least readable thing on
        // the screen.
        style={{ backgroundColor: navBg, borderRight: 'none', '--nav-fg': onNav } as CSSProperties}
      >
        {/*
          A SCROLLING SECTION, because the list is taller than the navbar on a short viewport and the
          last entry ran underneath the footer. That was invisible while the navbar was white — white
          text clipped against a white surface looks like nothing at all — and painting the navbar
          revealed it: "Audit log" sat on the footer's own background, outside the coloured area.

          `grow` gives this section the leftover height rather than the natural height of its content,
          which is what makes the overflow scroll instead of spill.
        */}
        <AppShell.Section grow component={ScrollArea} type="auto" scrollbarSize={6}>
          {NAV_GROUPS.map((group) => {
            const visible = group.items.filter((item) => !('adminOnly' in item) || isAdmin)
            // A group whose every entry is admin-gated must not leave its heading behind for a
            // non-admin: an empty labelled block reads as a broken page, not as a hidden one.
            if (visible.length === 0) return null
            return (
              <Box key={group.labelKey ?? 'entry'} mb="xs">
                {group.labelKey &&
                  (navCollapsed ? (
                    /*
                      A RULE INSTEAD OF THE HEADING, because at 68px the heading cannot be read: it
                      would wrap into fragments of uppercase or be clipped mid-word, and a truncated
                      category name looks like a rendering fault rather than a deliberate omission.

                      The grouping is still worth keeping — twelve icons in one undifferentiated column
                      are harder to scan than four short runs — so the line stays where the words were.

                      `aria-label` carries the name the eye no longer gets. A bare separator would drop
                      the grouping silently for anyone using a screen reader, who cannot see the line
                      either.
                    */
                    <Divider
                      my="xs"
                      mx="sm"
                      color={onNav}
                      opacity={0.25}
                      aria-label={t(group.labelKey)}
                    />
                  ) : (
                    <Text
                      size="xs"
                      fw={600}
                      c={onNav}
                      opacity={0.65}
                      tt="uppercase"
                      px="sm"
                      pt="sm"
                      pb={4}
                    >
                      {t(group.labelKey)}
                    </Text>
                  ))}
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
                      // Only when there is no label to read. A tooltip repeating a visible label is
                      // noise, and it covers the thing next to it while it does so.
                      disabled={!navCollapsed}
                      // Tooltips that appear on hover alone are invisible to anyone navigating by
                      // keyboard, which in a collapsed sidebar means the names are simply gone.
                      events={{ hover: true, focus: true, touch: true }}
                    >
                      <NavLink
                        label={t(item.labelKey)}
                        leftSection={<item.icon size={20} stroke={1.5} />}
                        active={isActive}
                        onClick={() => {
                          navigate(item.path)
                          toggle()
                        }}
                        className={navCollapsed ? 'navLink navLinkCollapsed' : 'navLink'}
                        // The accessible name survives the label being hidden. Without this a screen
                        // reader announces twelve unnamed links, which is worse than a sighted user
                        // guessing at an icon — they at least have the icon.
                        aria-label={t(item.labelKey)}
                        variant="subtle"
                        // INLINE, not in the stylesheet, and measured rather than assumed. `.navLink {
                        // color: var(--nav-fg) }` was tried and lost: it competes with Mantine's own
                        // NavLink rule at equal specificity, so source order decides and it decided
                        // against us — the labels rendered rgb(0,0,0) on the brand surface while the
                        // group headings beside them were correctly white, because those use this same
                        // prop. It is the identical trap already documented for AppShell.Header in this
                        // file. A style prop wins without needing !important.
                        c={onNav}
                      />
                    </Tooltip>
                  )
                })}
              </Box>
            )
          })}
        </AppShell.Section>

        {/* Outside the scrolling section: the subtitle is a footer for the navigation and should stay
            put rather than scroll away with the links.

            DROPPED ENTIRELY WHEN COLLAPSED. A company name is not navigation — it is decoration that
            happens to sit in the navbar — so at 68px it is the one element with nothing to lose by
            going. Keeping it would mean either truncating a proper noun (a name cut mid-word looks
            broken, not abbreviated) or letting it wrap into a stack of fragments, and its divider
            would then read as a rule under nothing. The name is still on screen: it sits beside the
            logo in the header, which the collapse does not touch. */}
        {!navCollapsed && (
          <AppShell.Section>
            {/* A theme divider is a grey line: on a brand surface it either vanishes or reads as dirt.
                A transparency of the surface foreground sits correctly on any brand. */}
            <Divider my="sm" color={onNav} opacity={0.25} />

            <Box px="sm" py="xs">
              {/* Same treatment as the group headings: a theme grey would be the one unreadable element
                  left on a brand surface, and 65% of a foreground that is known to have contrast recedes
                  in both directions -- pale brand or dark. */}
              <Text size="xs" c={onNav} opacity={0.65}>
                {settings.companySubtitle || settings.companyName}
              </Text>
            </Box>
          </AppShell.Section>
        )}
      </AppShell.Navbar>

      <AppShell.Main>
        {/* Suppress page rendering (and its data fetches) until the forced
            password change is complete — protected endpoints reject users
            flagged must_change_password with 403, so mounting pages here would
            only trigger errors behind the blocking modal. */}
        {user?.must_change_password ? null : <Outlet />}
      </AppShell.Main>

      <AppShell.Footer p="xs">
        <Text size="xs" c="dimmed" ta="center">
          Capado v{APP_VERSION}
        </Text>
      </AppShell.Footer>

      {user?.must_change_password && <ChangePasswordModal />}
      <HelpDrawer opened={helpDrawerOpened} onClose={closeHelpDrawer} />
    </AppShell>
  )
}
