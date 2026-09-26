/**
 * Settings page: company branding configuration (admin only).
 * Manages company name, subtitle, logo (upload or URL), and primary color.
 * User preferences (dark mode, locale) are controlled via the header icons.
 */

import { useEffect, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ActionIcon,
  Badge,
  Button,
  ColorInput,
  FileButton,
  Group,
  Image,
  Paper,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core'
import { DateInput } from '@mantine/dates'
import { MaintenanceRuns } from './MaintenanceRuns'
import { MailSettingsSection } from './MailSettingsSection'
import { mailStateFrom, type MailFormState } from './mailFormState'
import { notifications } from '@mantine/notifications'
import { IconTrash, IconUpload } from '@tabler/icons-react'
import { useSettings } from '../../context/SettingsContext'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'
import { PageLayout, SectionHeader } from '../../components/layout'
import {
  deleteLogo,
  getLogoUrl,
  getTenantSettings,
  updateTenantSettings,
  uploadLogo,
} from '../../api/settings'

export function SettingsPage() {
  const { settings, hasUploadedLogo } = useSettings()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const resetRef = useRef<() => void>(null)

  const [companyName, setCompanyName] = useState(settings.companyName)
  const [companySubtitle, setCompanySubtitle] = useState(settings.companySubtitle)
  const [logoUrl, setLogoUrl] = useState(settings.logoUrl)
  const [primaryColor, setPrimaryColor] = useState(settings.primaryColor)
  const [timeZone, setTimeZone] = useState(settings.timeZone)
  const timeZoneOptions = Array.from(
    new Set([
      'UTC',
      timeZone,
      ...(typeof Intl.supportedValuesOf === 'function'
        ? Intl.supportedValuesOf('timeZone')
        : ['Europe/Berlin']),
    ]),
  ).sort()
  // Retention is not branding, so it does not come from the branding context (which
  // exists to feed the header and logo). It is read straight from the API instead.
  const [retentionMonths, setRetentionMonths] = useState<number | ''>(24)
  const [baselineRetentionMonths, setBaselineRetentionMonths] = useState<number | ''>(0)
  // null means no freeze, which is a value rather than an absence — clearing the field is
  // how an operator lifts the freeze.
  const [freezeBefore, setFreezeBefore] = useState<string | null>(null)
  const [schedulerEnabled, setSchedulerEnabled] = useState(true)
  const [maintenanceHour, setMaintenanceHour] = useState<number | ''>(2)
  const [mail, setMail] = useState<MailFormState | null>(null)
  const [passwordStored, setPasswordStored] = useState(false)
  const [mailErrors, setMailErrors] = useState<string[]>([])

  /**
   * A FORM SEEDED FROM A SERVER READ — the one place in this migration where server state and client
   * state legitimately meet, and where the split has to be drawn deliberately rather than by habit.
   *
   * `settings.tenant()` is the server's answer, and it belongs in the cache. The fields below are the
   * user's UNSAVED EDITS, and those are client state: replacing them with query data on every
   * revalidation would overwrite what somebody is in the middle of typing. So the query is the source and
   * the effect seeds the form ONCE per answer, rather than the form reading the query directly.
   *
   * Failure still leaves the fields at their defaults rather than showing an error: the rest of the page
   * is usable, and saving re-reads the value server-side anyway.
   */
  const settingsQuery = useQuery({
    queryKey: queryKeys.settings.tenant(),
    queryFn: () => getTenantSettings(),
  })

  useEffect(() => {
    const data = settingsQuery.data
    if (!data) return
    setRetentionMonths(data.audit_retention_months)
    setTimeZone(data.time_zone)
    setBaselineRetentionMonths(data.baseline_retention_months)
    setFreezeBefore(data.planning_freeze_before)
    setSchedulerEnabled(data.scheduler_enabled)
    setMaintenanceHour(data.maintenance_hour)
    setMail(mailStateFrom(data))
    setPasswordStored(data.smtp_password_set)
    setMailErrors(data.mail_config_errors)
  }, [settingsQuery.data])

  /**
   * ONE INVALIDATION REACHES BOTH CONSUMERS.
   *
   * This page and the app shell's branding context read the SAME key, so declaring `settings` untrue
   * refreshes the header and this form together. `refreshBranding()` is itself now an invalidation of that
   * key, kept because it is part of the context's published contract — calling it here would be harmless
   * but redundant, and leaving it out is what proves the two are actually one mechanism.
   *
   * Before, they were two: the page reloaded its own copy and the context reloaded its own, and it was
   * possible to do one and forget the other.
   */
  const invalidateSettings = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.settings.all })

  const logoUploadMutation = useMutation({
    mutationFn: (file: File) => uploadLogo(file),
    onSuccess: async () => {
      await invalidateSettings()
      notifications.show({
        title: t('common.success'),
        message: t('settings.logoUploadSuccess'),
        color: 'green',
      })
    },
    // The server's message is preferred over a generic one: a rejected logo is usually rejected for a
    // reason the user can act on (too large, wrong format).
    onError: (err: unknown) => {
      notifications.show({
        title: t('common.error'),
        message: err instanceof Error ? err.message : t('common.error'),
        color: 'red',
      })
    },
    // Resets the file input either way, so a rejected file can be replaced rather than re-picked from a
    // control that still shows the old name.
    onSettled: () => resetRef.current?.(),
  })
  const uploading = logoUploadMutation.isPending

  const handleLogoUpload = (file: File | null) => {
    if (!file) return
    logoUploadMutation.mutate(file)
  }

  const logoDeleteMutation = useMutation({
    mutationFn: () => deleteLogo(),
    onSuccess: async () => {
      await invalidateSettings()
      notifications.show({
        title: t('common.success'),
        message: t('settings.logoDeleteSuccess'),
        color: 'green',
      })
    },
    onError: () => {
      notifications.show({
        title: t('common.error'),
        message: t('common.error'),
        color: 'red',
      })
    },
  })

  const handleLogoDelete = () => {
    logoDeleteMutation.mutate()
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      updateTenantSettings({
        company_name: companyName.trim() || 'Capado',
        company_subtitle: companySubtitle.trim(),
        logo_url: logoUrl.trim(),
        primary_color: primaryColor || 'blue',
        time_zone: timeZone,
        audit_retention_months: typeof retentionMonths === 'number' ? retentionMonths : 24,
        baseline_retention_months:
          typeof baselineRetentionMonths === 'number' ? baselineRetentionMonths : 0,
        // Always sent, including as null: the backend reads "mentioned but null" as
        // "lift the freeze", so omitting it would make the freeze unremovable.
        planning_freeze_before: freezeBefore,
        scheduler_enabled: schedulerEnabled,
        maintenance_hour: typeof maintenanceHour === 'number' ? maintenanceHour : 2,
        ...(mail
          ? {
              smtp_enabled: mail.smtp_enabled,
              smtp_host: mail.smtp_host.trim(),
              smtp_port: typeof mail.smtp_port === 'number' ? mail.smtp_port : 587,
              smtp_use_tls: mail.smtp_use_tls,
              smtp_username: mail.smtp_username.trim(),
              // Only sent when the operator touched it. Omitting the key is what tells the
              // backend to keep the stored password; sending '' clears it.
              ...(mail.smtp_password !== null ? { smtp_password: mail.smtp_password } : {}),
              smtp_from_address: mail.smtp_from_address.trim(),
              digest_recipients: mail.digest_recipients,
            }
          : {}),
      }),
    onSuccess: async () => {
      await invalidateSettings()
      notifications.show({
        title: t('common.success'),
        message: t('common.saved'),
        color: 'green',
      })
    },
    onError: () => {
      notifications.show({
        title: t('common.error'),
        message: t('common.error'),
        color: 'red',
      })
    },
  })
  const saving = saveMutation.isPending

  const handleSave = () => {
    saveMutation.mutate()
  }

  return (
    <PageLayout title={t('settings.title')}>
      <Stack gap="lg">
        <Paper withBorder p="md">
          <SectionHeader title={t('settings.branding')} />
          <Stack gap="sm">
            <TextInput
              label={t('settings.companyName')}
              description={t('settings.companyNameDesc')}
              placeholder={t('settingsPage.companyNamePlaceholder')}
              value={companyName}
              onChange={(e) => setCompanyName(e.currentTarget.value)}
            />
            <TextInput
              label={t('settings.subtitle')}
              description={t('settings.subtitleDesc')}
              placeholder={t('settingsPage.subtitlePlaceholder')}
              value={companySubtitle}
              onChange={(e) => setCompanySubtitle(e.currentTarget.value)}
            />
            <ColorInput
              label={t('settings.primaryColor')}
              description={t('settings.primaryColorDesc')}
              value={primaryColor}
              onChange={setPrimaryColor}
              format="hex"
              swatches={[
                '#2b6cb0',
                '#1a73e8',
                '#0d9488',
                '#059669',
                '#d97706',
                '#dc2626',
                '#7c3aed',
                '#db2777',
              ]}
            />

            {/* Logo upload section */}
            <div>
              <Text size="sm" fw={500} mb={2}>
                {t('settings.logoUpload')}
              </Text>
              <Text size="xs" c="dimmed" mb="xs">
                {t('settings.logoUploadDesc')}
              </Text>

              <Group gap="sm" align="center">
                <FileButton
                  resetRef={resetRef}
                  onChange={handleLogoUpload}
                  accept="image/png,image/jpeg,image/svg+xml,image/webp,image/gif"
                >
                  {(props) => (
                    <Button
                      {...props}
                      variant="light"
                      leftSection={<IconUpload size={16} />}
                      loading={uploading}
                      size="sm"
                    >
                      {t('settings.logoUploadButton')}
                    </Button>
                  )}
                </FileButton>

                {hasUploadedLogo && (
                  <>
                    <Image
                      src={getLogoUrl()}
                      alt="Logo preview"
                      w={36}
                      h={36}
                      radius={6}
                      fit="contain"
                    />
                    <Badge variant="light" color="green" size="sm">
                      {t('settings.logoUploaded')}
                    </Badge>
                    <ActionIcon
                      variant="light"
                      color="red"
                      size="sm"
                      onClick={handleLogoDelete}
                      aria-label={t('settings.logoDeleteButton')}
                    >
                      <IconTrash size={14} />
                    </ActionIcon>
                  </>
                )}
              </Group>
            </div>

            {/* Fallback: manual URL entry */}
            <Text size="xs" c="dimmed" mt="xs">
              {t('settings.logoOrUrl')}
            </Text>
            <TextInput
              label={t('settings.logoUrl')}
              description={t('settings.logoUrlDesc')}
              placeholder={t('settingsPage.logoUrlPlaceholder')}
              value={logoUrl}
              onChange={(e) => setLogoUrl(e.currentTarget.value)}
            />
          </Stack>
        </Paper>

        <Paper withBorder p="md">
          <SectionHeader title={t('settings.timeSettings')} />
          <Select
            label={t('settings.timeZone')}
            description={t('settings.timeZoneDesc')}
            data={timeZoneOptions}
            searchable
            value={timeZone}
            onChange={(value) => value && setTimeZone(value)}
          />
        </Paper>

        <Paper withBorder p="md">
          <SectionHeader title={t('settings.dataProtection')} />
          <Stack gap="sm">
            <NumberInput
              label={t('settings.auditRetention')}
              description={t('settings.auditRetentionDesc')}
              value={retentionMonths}
              onChange={(value) => setRetentionMonths(typeof value === 'number' ? value : '')}
              min={0}
              max={600}
              allowDecimal={false}
              allowNegative={false}
            />
            <Text size="xs" c="dimmed">
              {t('settings.auditRetentionJobHint')}
            </Text>
            <NumberInput
              label={t('settings.baselineRetention')}
              description={t('settings.baselineRetentionDesc')}
              value={baselineRetentionMonths}
              onChange={(value) =>
                setBaselineRetentionMonths(typeof value === 'number' ? value : '')
              }
              min={0}
              max={600}
              allowDecimal={false}
              allowNegative={false}
            />
            <Switch
              label={t('settings.schedulerEnabled')}
              description={t('settings.schedulerEnabledDesc')}
              checked={schedulerEnabled}
              onChange={(event) => setSchedulerEnabled(event.currentTarget.checked)}
            />
            <NumberInput
              label={t('settings.maintenanceHour')}
              description={t('settings.maintenanceHourDesc')}
              value={maintenanceHour}
              onChange={(value) => setMaintenanceHour(typeof value === 'number' ? value : '')}
              min={0}
              max={23}
              allowDecimal={false}
              allowNegative={false}
            />
            <MaintenanceRuns />
            <DateInput
              label={t('settings.planningFreeze')}
              description={t('settings.planningFreezeDesc')}
              // Mantine hands back 'YYYY-MM-DD', which is what the API stores. Going via
              // Date and toISOString() would shift the day backwards east of Greenwich.
              value={freezeBefore}
              onChange={(value) => setFreezeBefore(value || null)}
              clearable
              valueFormat="DD.MM.YYYY"
              placeholder={t('settings.planningFreezeNone')}
            />
          </Stack>
        </Paper>

        {mail && (
          <MailSettingsSection
            state={mail}
            onChange={setMail}
            passwordStored={passwordStored}
            configErrors={mailErrors}
          />
        )}

        <Group justify="flex-end">
          <Button onClick={handleSave} loading={saving}>
            {t('common.save')}
          </Button>
        </Group>
      </Stack>
    </PageLayout>
  )
}
