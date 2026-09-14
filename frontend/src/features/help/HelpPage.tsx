/**
 * Help page following the Diátaxis framework. Displays user documentation
 * organized into Tutorials, How-To Guides, Reference, and Explanation.
 * Content is served in the user's active locale (de/en).
 *
 * Route: /help and /help/:slug
 */

import { useMemo, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Anchor,
  Badge,
  Card,
  Container,
  Group,
  SegmentedControl,
  SimpleGrid,
  Text,
  Title,
} from '@mantine/core'
import { IconBook, IconBulb, IconChecklist, IconInfoCircle } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { PageLayout } from '../../components/layout'
import { articles as deArticles, type HelpArticle } from './content/de'
import { articles as enArticles } from './content/en'
import { renderMarkdown } from './renderMarkdown'

const CATEGORY_META = {
  tutorial: { icon: IconBook, color: 'blue' },
  'how-to': { icon: IconChecklist, color: 'green' },
  reference: { icon: IconInfoCircle, color: 'violet' },
  explanation: { icon: IconBulb, color: 'orange' },
} as const

const CATEGORY_LABELS: Record<string, Record<HelpArticle['category'], string>> = {
  de: {
    tutorial: 'Tutorials',
    'how-to': 'Anleitungen',
    reference: 'Referenz',
    explanation: 'Erklärungen',
  },
  en: {
    tutorial: 'Tutorials',
    'how-to': 'How-To Guides',
    reference: 'Reference',
    explanation: 'Explanation',
  },
}

/**
 * Renders the help index (all categories) or a single article based on URL.
 */
export function HelpPage() {
  const { slug } = useParams<{ slug?: string }>()
  const navigate = useNavigate()
  const { locale } = useTranslation()
  const [filter, setFilter] = useState<string>('all')

  const allArticles = locale === 'de' ? deArticles : enArticles
  const labels = CATEGORY_LABELS[locale] ?? CATEGORY_LABELS.de

  const filteredArticles = useMemo(() => {
    if (filter === 'all') return allArticles
    return allArticles.filter((a) => a.category === filter)
  }, [allArticles, filter])

  // Single article view
  if (slug) {
    const article = allArticles.find((a) => a.slug === slug)
    if (!article) {
      return (
        <Container size="md" py="xl">
          <Title order={2}>404</Title>
          <Text c="dimmed">Article not found.</Text>
          <Anchor onClick={() => navigate('/help')}>← Back to Help</Anchor>
        </Container>
      )
    }

    return (
      <Container size="md" py="xl">
        <Anchor onClick={() => navigate('/help')} mb="md" style={{ display: 'block' }}>
          ← {locale === 'de' ? 'Zurück zur Hilfe' : 'Back to Help'}
        </Anchor>
        <Group mb="sm">
          <Badge color={CATEGORY_META[article.category].color} variant="light">
            {labels[article.category]}
          </Badge>
        </Group>
        <Title order={2} mb="lg">
          {article.title}
        </Title>
        <div data-mantine-typography style={{ fontSize: 'var(--mantine-font-size-sm)' }}>
          <div
            dangerouslySetInnerHTML={{
              __html: renderMarkdown(article.body.replace(/^## .+\n*/, '')),
            }}
          />
        </div>
      </Container>
    )
  }

  // Index view
  const filterOptions = [
    { value: 'all', label: locale === 'de' ? 'Alle' : 'All' },
    { value: 'tutorial', label: labels.tutorial },
    { value: 'how-to', label: labels['how-to'] },
    { value: 'reference', label: labels.reference },
    { value: 'explanation', label: labels.explanation },
  ]

  return (
    <PageLayout title={locale === 'de' ? 'Hilfe & Dokumentation' : 'Help & Documentation'}>
      <Text c="dimmed" mb="lg">
        {locale === 'de'
          ? 'Anleitungen, Referenzen und Erklärungen zur Nutzung von Capado.'
          : 'Guides, references, and explanations for using Capado.'}
      </Text>

      <SegmentedControl data={filterOptions} value={filter} onChange={setFilter} mb="lg" />

      <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
        {filteredArticles.map((article) => {
          const meta = CATEGORY_META[article.category]
          const Icon = meta.icon
          const preview = article.body
            .replace(/[#*`|[\]]/g, '')
            .replace(/\n+/g, ' ')
            .trim()
            .slice(0, 100)
          return (
            <Card
              key={article.slug}
              withBorder
              padding="lg"
              radius="md"
              style={{ cursor: 'pointer', transition: 'box-shadow 150ms ease' }}
              className="help-article-card"
              onClick={() => navigate(`/help/${article.slug}`)}
              onKeyDown={(e: React.KeyboardEvent) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  navigate(`/help/${article.slug}`)
                }
              }}
              tabIndex={0}
              role="button"
              aria-label={article.title}
            >
              <Group mb="xs">
                <Icon size={20} color={`var(--mantine-color-${meta.color}-6)`} />
                <Badge color={meta.color} variant="light" size="sm">
                  {labels[article.category]}
                </Badge>
              </Group>
              <Text fw={600} size="sm" mb={4}>
                {article.title}
              </Text>
              <Text size="xs" c="dimmed" lineClamp={2}>
                {preview}…
              </Text>
            </Card>
          )
        })}
      </SimpleGrid>
    </PageLayout>
  )
}
