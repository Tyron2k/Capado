/** Complete area CSVs are identical whether downloaded here or in the all-data ZIP. */
import { ImportExportBar } from './ImportExportBar'

export type CsvArea =
  | 'working-time'
  | 'skills'
  | 'personnel'
  | 'infrastructure'
  | 'projects'
  | 'templates'
  | 'assignments'
  | 'absences'
  | 'administration'
  | 'history'

export function CsvAreaBar({ area }: { area: CsvArea }) {
  return (
    <ImportExportBar
      exportPath={`/api/data/${area}/export`}
      importPath={`/api/data/${area}/import`}
      filenameBase={area}
      csvOnly
    />
  )
}
