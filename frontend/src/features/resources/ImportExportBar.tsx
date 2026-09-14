/**
 * Reusable import/export toolbar with download and upload buttons.
 * Used on resource, skill, and assignment tabs.
 *
 * THREE EXPORT FORMATS, and the distinction is not cosmetic. The Excel matrix is a REPORT: its header
 * spans two rows and group separators sit between the data, so it cannot be imported back — it never
 * could. "Excel (flat)" is the same data in the shape the importer reads, so you get Excel editing AND
 * a way back. The menu now says which is which, because previously both said "Excel" and only one of
 * them worked.
 *
 * THE IMPORT RESULT IS A MODAL, not a toast. The API returns one message per rejected row; the toast
 * showed only how MANY there were and threw the rest away, so the one thing needed to fix the file was
 * generated and discarded.
 */

import { useRef, useState } from 'react'
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Group,
  List,
  Menu,
  Modal,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from '@mantine/core'
import { showErrorNotification } from '../../utils/errorHandling'
import { IconAlertTriangle, IconDownload, IconUpload } from '@tabler/icons-react'
import { useTranslation } from '../../i18n'
import apiClient from '../../api/client'

/** Server-side format name paired with the extension the download should carry. */
const EXPORT_FORMATS = [
  { format: 'xlsx', extension: 'xlsx', labelKey: 'importExport.formatMatrix' },
  { format: 'xlsx-flat', extension: 'xlsx', labelKey: 'importExport.formatFlatXlsx' },
  { format: 'csv', extension: 'csv', labelKey: 'importExport.formatCsv' },
] as const

interface ImportOutcome {
  created: number
  updated: number
  skipped: number
  errors: string[]
}

interface ImportExportBarProps {
  /** API path for export, e.g. '/api/personnel/export' */
  exportPath: string
  /** API path for import, e.g. '/api/personnel/import' */
  importPath: string
  /** Filename base for downloads, e.g. 'personnel' */
  filenameBase: string
  /** Callback after successful import */
  onImportSuccess?: () => void
}

export function ImportExportBar({
  exportPath,
  importPath,
  filenameBase,
  onImportSuccess,
}: ImportExportBarProps) {
  const { t } = useTranslation()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [importing, setImporting] = useState(false)
  const [outcome, setOutcome] = useState<ImportOutcome | null>(null)

  const handleExport = async (format: string, extension: string) => {
    try {
      const response = await apiClient.get(`${exportPath}?format=${format}`, {
        responseType: 'blob',
      })
      const blob = new Blob([response.data])
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      // Extension comes from the table, NOT from the format name: 'xlsx-flat' is a server-side
      // format, and a file called personnel.xlsx-flat is one Excel refuses to open.
      a.download = `${filenameBase}.${extension}`
      a.click()
      URL.revokeObjectURL(url)
    } catch (error: unknown) {
      showErrorNotification(error, t('common.error'), t('importExport.exportFailed'))
    }
  }

  const handleImport = async (file: File) => {
    setImporting(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const response = await apiClient.post(importPath, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const data = response.data
      // Always open the log, success or not. A silent success leaves you wondering whether anything
      // happened, and the counts are the only proof the file did what you expected.
      setOutcome({
        created: data.created ?? 0,
        updated: data.updated ?? 0,
        skipped: data.skipped ?? 0,
        errors: data.errors ?? [],
      })
      onImportSuccess?.()
    } catch (error: unknown) {
      showErrorNotification(error, t('common.error'), t('importExport.importFailed'))
    } finally {
      setImporting(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <Group gap="xs">
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.csv"
        style={{ display: 'none' }}
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) handleImport(file)
        }}
      />

      <Tooltip label={t('importExport.import')}>
        <ActionIcon
          variant="subtle"
          size="md"
          onClick={() => fileInputRef.current?.click()}
          loading={importing}
          aria-label={t('importExport.import')}
        >
          <IconUpload size={18} />
        </ActionIcon>
      </Tooltip>

      <Menu position="bottom-end" withArrow>
        <Menu.Target>
          <Tooltip label={t('importExport.export')}>
            <ActionIcon variant="subtle" size="md" aria-label={t('importExport.export')}>
              <IconDownload size={18} />
            </ActionIcon>
          </Tooltip>
        </Menu.Target>
        <Menu.Dropdown>
          {EXPORT_FORMATS.map(({ format, extension, labelKey }) => (
            <Menu.Item key={format} onClick={() => handleExport(format, extension)}>
              {t(labelKey)}
            </Menu.Item>
          ))}
        </Menu.Dropdown>
      </Menu>

      <Modal
        opened={outcome !== null}
        onClose={() => setOutcome(null)}
        title={t('importExport.logTitle')}
        size="lg"
      >
        {outcome && (
          <Stack gap="sm">
            <Group gap="xs">
              <Badge color="green" variant="light">
                {t('importExport.created')}: {outcome.created}
              </Badge>
              <Badge color="blue" variant="light">
                {t('importExport.updated')}: {outcome.updated}
              </Badge>
              <Badge color="gray" variant="light">
                {t('importExport.skippedLabel')}: {outcome.skipped}
              </Badge>
              {outcome.errors.length > 0 && (
                <Badge color="red" variant="light">
                  {t('importExport.errors')}: {outcome.errors.length}
                </Badge>
              )}
            </Group>

            {outcome.errors.length === 0 ? (
              <Text size="sm" c="dimmed">
                {t('importExport.logNoErrors')}
              </Text>
            ) : (
              <>
                {/* The whole import is ONE transaction: if anything was rejected, nothing was
                    written. Saying so is the difference between "fix these rows" and the false
                    impression that part of the file already landed. */}
                <Alert
                  icon={<IconAlertTriangle size={16} />}
                  color="yellow"
                  title={t('importExport.logRejectedTitle')}
                >
                  {t('importExport.logRejectedBody')}
                </Alert>
                <ScrollArea.Autosize mah={320}>
                  <List size="sm" spacing={4}>
                    {outcome.errors.map((message, i) => (
                      <List.Item key={i}>{message}</List.Item>
                    ))}
                  </List>
                </ScrollArea.Autosize>
              </>
            )}

            <Group justify="flex-end">
              <Button variant="default" onClick={() => setOutcome(null)}>
                {t('importExport.logClose')}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </Group>
  )
}
