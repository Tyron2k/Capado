/**
 * What the signed-in person may read about themselves.
 *
 * Until this page existed, a person's plan was visible to their leaders and to administrators and
 * not to them: "what am I scheduled for" meant asking a supervisor, and a GDPR Art. 15 request
 * meant an export by hand. Section 8 of the works-council document promises the benefit is not
 * one-sided; this is where that becomes true rather than aspirational.
 *
 * THREE STATES, NOT TWO. Loading, and then either a plan, an error, or "nobody has linked your
 * account yet" — that last one is NOT an empty plan, and rendering it as one would have people
 * conclude they are scheduled for nothing. It gets its own message naming who can fix it.
 *
 * Read-only on purpose. Requesting leave and confirming an assignment are separate workflows with
 * their own consequences; the leave one is a co-determination question of its own.
 */

import { useQuery } from '@tanstack/react-query'
import { Alert, Badge, Group, Loader, Paper, Stack, Table, Text, Title } from '@mantine/core'
import { IconCalendarEvent, IconCertificate, IconInfoCircle } from '@tabler/icons-react'

import { getMyPlan, NoLinkedResourceError, type MyPlan } from '../../api/me'
import { useTranslation } from '../../i18n'
import { queryKeys } from '../../api/queryClient'

export function MyPlanPage() {
  const { t } = useTranslation()

  /**
   * One typed failure is not an error, and the query layer has to be told that.
   *
   * `NoLinkedResourceError` means the account is not linked to a scheduled person — a 409 the backend
   * answers deliberately rather than returning an empty plan (see the self-service limitation). It is
   * a STATE of this screen, not a failure of the request: retrying it cannot help, and reporting it as
   * an error would tell somebody their plan failed to load when in fact nobody has linked them yet.
   *
   * So it is caught in the query function and turned into a value. The alternative — letting it reach
   * `error` and branching there — would also make the client retry it, and would put a "could not
   * load" notification in front of a person whose actual answer is "ask an administrator".
   */
  const planQuery = useQuery({
    queryKey: queryKeys.myPlan.current(),
    queryFn: async (): Promise<MyPlan | 'not-linked'> => {
      try {
        return await getMyPlan()
      } catch (err) {
        if (err instanceof NoLinkedResourceError) return 'not-linked'
        throw err
      }
    },
  })

  const notLinked = planQuery.data === 'not-linked'
  const plan: MyPlan | null =
    planQuery.data !== undefined && planQuery.data !== 'not-linked' ? planQuery.data : null
  const loading = planQuery.isPending
  const error = planQuery.error ? t('myPlan.loadFailed') : null

  if (loading) {
    return (
      <Group justify="center" p="xl">
        <Loader />
      </Group>
    )
  }

  if (notLinked) {
    return (
      <Stack gap="md">
        <Title order={2}>{t('myPlan.title')}</Title>
        <Alert icon={<IconInfoCircle size={16} />} color="blue" title={t('myPlan.notLinkedTitle')}>
          {t('myPlan.notLinkedBody')}
        </Alert>
      </Stack>
    )
  }

  if (error !== null || plan === null) {
    return (
      <Stack gap="md">
        <Title order={2}>{t('myPlan.title')}</Title>
        <Alert color="red">{error ?? t('myPlan.loadFailed')}</Alert>
      </Stack>
    )
  }

  return (
    <Stack gap="lg">
      <Title order={2}>{t('myPlan.title')}</Title>
      <Text size="sm" c="dimmed">
        {t('myPlan.intro')}
      </Text>

      <Paper p="md" withBorder>
        <Group gap="xs" mb="sm">
          <IconCalendarEvent size={18} />
          <Title order={4}>{t('myPlan.assignments')}</Title>
          <Badge variant="light">{plan.assignment_total}</Badge>
        </Group>
        {plan.assignments.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t('myPlan.noAssignments')}
          </Text>
        ) : (
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('myPlan.project')}</Table.Th>
                <Table.Th>{t('myPlan.workPackage')}</Table.Th>
                <Table.Th>{t('myPlan.from')}</Table.Th>
                <Table.Th>{t('myPlan.to')}</Table.Th>
                <Table.Th>{t('myPlan.allocation')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {plan.assignments.map((a) => (
                <Table.Tr key={a.id}>
                  <Table.Td>{a.project_name ?? '—'}</Table.Td>
                  <Table.Td>{a.work_package_name ?? '—'}</Table.Td>
                  <Table.Td>{a.start_date ?? '—'}</Table.Td>
                  <Table.Td>{a.end_date ?? '—'}</Table.Td>
                  <Table.Td>
                    {a.allocation_percent !== null ? `${a.allocation_percent} %` : '—'}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>

      <Paper p="md" withBorder>
        <Group gap="xs" mb="sm">
          <Title order={4}>{t('myPlan.absences')}</Title>
          <Badge variant="light">{plan.absence_total}</Badge>
        </Group>
        {plan.absences.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t('myPlan.noAbsences')}
          </Text>
        ) : (
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('myPlan.from')}</Table.Th>
                <Table.Th>{t('myPlan.to')}</Table.Th>
                <Table.Th>{t('myPlan.share')}</Table.Th>
                <Table.Th>{t('myPlan.status')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {plan.absences.map((absence) => (
                <Table.Tr key={absence.id}>
                  <Table.Td>{absence.start_date}</Table.Td>
                  <Table.Td>{absence.end_date}</Table.Td>
                  <Table.Td>{absence.allocation_percent} %</Table.Td>
                  <Table.Td>
                    <Badge
                      variant="light"
                      color={absence.status === 'confirmed' ? 'green' : 'yellow'}
                    >
                      {t(`myPlan.absenceStatus.${absence.status}`)}
                    </Badge>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>

      <Paper p="md" withBorder>
        <Group gap="xs" mb="sm">
          <IconCertificate size={18} />
          <Title order={4}>{t('myPlan.qualifications')}</Title>
          <Badge variant="light">{plan.skills.length}</Badge>
        </Group>
        {plan.skills.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t('myPlan.noQualifications')}
          </Text>
        ) : (
          <Table striped>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('myPlan.skill')}</Table.Th>
                <Table.Th>{t('myPlan.attribute')}</Table.Th>
                <Table.Th>{t('myPlan.level')}</Table.Th>
                <Table.Th>{t('myPlan.validUntil')}</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {plan.skills.map((skill) => (
                <Table.Tr key={skill.id}>
                  <Table.Td>{skill.skill_name}</Table.Td>
                  <Table.Td>{skill.attribute_name}</Table.Td>
                  {/* A null level is "nobody assessed it", which is not the same as 1. */}
                  <Table.Td>{skill.level ?? t('myPlan.levelUnassessed')}</Table.Td>
                  <Table.Td>{skill.valid_until ?? t('myPlan.noExpiry')}</Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
      </Paper>
    </Stack>
  )
}
