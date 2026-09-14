/**
 * Excel report downloads.
 *
 * Honours the server's `Content-Disposition` filename rather than composing one here. The server
 * names the file with an ISO date prefix so a folder of reports sorts chronologically, and a
 * client-side name would throw that away — which is what the existing import/export bar does,
 * deliberately left alone because its filenames are part of a round-trip convention.
 */

import apiClient from './client'

/** Pull the filename out of a Content-Disposition header, if it carries one. */
function filenameFrom(header: string | undefined, fallback: string): string {
  if (!header) return fallback
  // Both the quoted and unquoted forms occur; RFC 5987's filename*= is not emitted by this
  // backend, so it is deliberately not parsed rather than half-parsed.
  const match = /filename="?([^"]+)"?/.exec(header)
  return match ? match[1] : fallback
}

async function download(path: string, params: Record<string, string>, fallback: string) {
  const response = await apiClient.get(path, { params, responseType: 'blob' })
  const blob = new Blob([response.data as BlobPart])
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filenameFrom(
    response.headers['content-disposition'] as string | undefined,
    fallback,
  )
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  // Released immediately: a retained object URL keeps the whole blob in memory for the life of
  // the tab, and somebody exporting repeatedly would accumulate every file they downloaded.
  URL.revokeObjectURL(url)
}

/**
 * @param start First week (YYYY-MM-DD). Omit for the current week.
 * @param end Last week. Omit for 12 weeks after start.
 * @param groupId Restrict to one resource group. Omit for everybody.
 */
export async function downloadUtilizationReport(
  start?: string,
  end?: string,
  groupId?: string,
): Promise<void> {
  const params: Record<string, string> = {}
  if (start) params.start = start
  if (end) params.end = end
  if (groupId) params.group_id = groupId
  await download('/api/reports/utilization', params, 'auslastung.xlsx')
}

export async function downloadProjectReport(): Promise<void> {
  await download('/api/reports/projects', {}, 'projekte.xlsx')
}
