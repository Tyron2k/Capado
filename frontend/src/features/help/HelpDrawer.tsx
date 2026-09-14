/**
 * Context-sensitive help drawer with integrated search and inline article view.
 * Opens from the right side. Shows a search bar, context-relevant articles,
 * and renders full article content inside the drawer without navigating away.
 *
 * Keyboard shortcut: Ctrl+/ (⌘+/ on Mac) opens the drawer.
 */

import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  ActionIcon,
  Anchor,
  Badge,
  Card,
  Divider,
  Drawer,
  Group,
  ScrollArea,
  Stack,
  Text,
  TextInput,
} from '@mantine/core'
import {
  IconArrowLeft,
  IconBook,
  IconBulb,
  IconChecklist,
  IconInfoCircle,
  IconSearch,
} from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import { articles as deArticles, type HelpArticle } from './content/de'
import { articles as enArticles } from './content/en'
import { renderMarkdown } from './renderMarkdown'

const CATEGORY_META: Record<HelpArticle['category'], { icon: typeof IconBook; color: string }> = {
  tutorial: { icon: IconBook, color: 'blue' },
  'how-to': { icon: IconChecklist, color: 'green' },
  reference: { icon: IconInfoCircle, color: 'violet' },
  explanation: { icon: IconBulb, color: 'orange' },
}

const CATEGORY_LABELS: Record<string, Record<HelpArticle['category'], string>> = {
  de: {
    tutorial: 'Tutorial',
    'how-to': 'Anleitung',
    reference: 'Referenz',
    explanation: 'Erklärung',
  },
  en: {
    tutorial: 'Tutorial',
    'how-to': 'How-To',
    reference: 'Reference',
    explanation: 'Explanation',
  },
}

/** Check whether an article is relevant to the given pathname. */
function isArticleRelevant(article: HelpArticle, pathname: string): boolean {
  if (!article.routes || article.routes.length === 0) return false
  return article.routes.some((route) => pathname === route || pathname.startsWith(route + '/'))
}

/** Search articles by matching query against title and body (case-insensitive). */
function searchArticles(articles: HelpArticle[], query: string): HelpArticle[] {
  const lower = query.toLowerCase().trim()
  if (!lower) return []
  return articles.filter(
    (a) => a.title.toLowerCase().includes(lower) || a.body.toLowerCase().includes(lower),
  )
}

interface HelpDrawerProps {
  opened: boolean
  onClose: () => void
}

/**
 * Renders a help drawer with search, context-sensitive suggestions, and
 * inline article rendering. Clicking an article shows its full content
 * inside the drawer with a back button to return to the list.
 */
export function HelpDrawer({ opened, onClose }: HelpDrawerProps) {
  const { locale, t } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [activeArticle, setActiveArticle] = useState<HelpArticle | null>(null)

  const allArticles = locale === 'de' ? deArticles : enArticles
  const labels = CATEGORY_LABELS[locale] ?? CATEGORY_LABELS.de

  // Reset state when drawer opens
  useEffect(() => {
    if (opened) {
      setQuery('')
      setActiveArticle(null)
    }
  }, [opened])

  const contextArticles = useMemo(
    () => allArticles.filter((a) => isArticleRelevant(a, location.pathname)),
    [allArticles, location.pathname],
  )

  const searchResults = useMemo(() => searchArticles(allArticles, query), [allArticles, query])

  const isSearching = query.trim().length > 0
  const displayedArticles = isSearching ? searchResults : contextArticles

  // --- Article detail view ---
  if (activeArticle) {
    const meta = CATEGORY_META[activeArticle.category]
    return (
      <Drawer
        opened={opened}
        onClose={onClose}
        title={
          <Group gap="xs">
            <ActionIcon
              variant="subtle"
              size="sm"
              onClick={() => setActiveArticle(null)}
              data-testid="help-back-button"
              aria-label={t('common.back')}
            >
              <IconArrowLeft size={16} />
            </ActionIcon>
            <Text fw={500} size="sm">
              {activeArticle.title}
            </Text>
          </Group>
        }
        position="right"
        size="lg"
        trapFocus
        returnFocus
      >
        <Group mb="md">
          <Badge color={meta.color} variant="light" size="sm">
            {labels[activeArticle.category]}
          </Badge>
        </Group>
        <ScrollArea.Autosize mah="calc(100vh - 160px)">
          <div data-mantine-typography style={{ fontSize: 'var(--mantine-font-size-sm)' }}>
            <div
              style={{ overflowX: 'auto', overflowWrap: 'break-word', wordBreak: 'break-word' }}
              dangerouslySetInnerHTML={{
                __html: renderMarkdown(activeArticle.body.replace(/^## .+\n*/, '')),
              }}
            />
          </div>
        </ScrollArea.Autosize>
      </Drawer>
    )
  }

  // --- List view ---
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={locale === 'de' ? 'Hilfe' : 'Help'}
      position="right"
      size="lg"
      trapFocus
      returnFocus
    >
      <TextInput
        placeholder={locale === 'de' ? 'Hilfe durchsuchen…' : 'Search help…'}
        leftSection={<IconSearch size={16} />}
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        mb="md"
      />

      {!isSearching && contextArticles.length > 0 && (
        <Text size="xs" c="dimmed" mb="xs">
          {locale === 'de' ? 'Hilfe für diese Seite' : 'Help for this page'}
        </Text>
      )}

      <ScrollArea.Autosize mah="calc(100vh - 200px)">
        {displayedArticles.length === 0 ? (
          <Stack align="center" justify="center" py="xl">
            <Text c="dimmed" ta="center" size="sm">
              {isSearching
                ? locale === 'de'
                  ? 'Keine Ergebnisse.'
                  : 'No results.'
                : locale === 'de'
                  ? 'Keine Hilfe für diese Seite verfügbar.'
                  : 'No help available for this page.'}
            </Text>
            {!isSearching && (
              <Anchor
                size="sm"
                onClick={() => {
                  navigate('/help')
                  onClose()
                }}
              >
                {locale === 'de' ? 'Alle Artikel anzeigen' : 'Show all articles'}
              </Anchor>
            )}
          </Stack>
        ) : (
          <Stack gap="xs">
            {displayedArticles.map((article) => {
              const meta = CATEGORY_META[article.category]
              const Icon = meta.icon
              return (
                <Card
                  key={article.slug}
                  withBorder
                  padding="sm"
                  style={{ cursor: 'pointer' }}
                  onClick={() => setActiveArticle(article)}
                  onKeyDown={(e: React.KeyboardEvent) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setActiveArticle(article)
                    }
                  }}
                  tabIndex={0}
                  role="button"
                  aria-label={article.title}
                >
                  <Group gap="xs" mb={4}>
                    <Icon size={16} color={`var(--mantine-color-${meta.color}-6)`} />
                    <Text fw={500} size="sm">
                      {article.title}
                    </Text>
                    <Badge color={meta.color} variant="light" size="xs">
                      {labels[article.category]}
                    </Badge>
                  </Group>
                  <Text size="xs" c="dimmed" lineClamp={2}>
                    {article.body
                      .replace(/[#*`|[\]]/g, '')
                      .trim()
                      .slice(0, 120)}
                  </Text>
                </Card>
              )
            })}

            {!isSearching && (
              <>
                <Divider my="xs" />
                <Anchor
                  size="xs"
                  ta="center"
                  onClick={() => {
                    navigate('/help')
                    onClose()
                  }}
                >
                  {locale === 'de' ? 'Alle Hilfeartikel →' : 'All help articles →'}
                </Anchor>
              </>
            )}
          </Stack>
        )}
      </ScrollArea.Autosize>
    </Drawer>
  )
}
