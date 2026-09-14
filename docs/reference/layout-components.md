# Layout Components Reference

Shared layout primitives in `frontend/src/components/layout/`. All page
components must use these to ensure visual consistency.

## PageLayout

Simple page shell without tabs.

```tsx
import { PageLayout } from '../../components/layout'

<PageLayout title="Dashboard" headerActions={<Button>Export</Button>}>
  {/* page content */}
</PageLayout>
```

**Props:**

| Prop            | Type        | Description                              |
|-----------------|-------------|------------------------------------------|
| `title`         | `string`    | Page heading (rendered as `<h2>`)        |
| `headerActions` | `ReactNode` | Optional right-aligned header elements   |
| `children`      | `ReactNode` | Page body content                        |

**Renders:** `Container size="xl"` → `Group justify="space-between" mb="md"` → `Title order={2}` + actions → children.

---

## PageTabs

Tabbed page shell. Use for pages with multiple content sections.

```tsx
import { PageTabs } from '../../components/layout'
import { IconUsers, IconSettings } from '@tabler/icons-react'

<PageTabs
  title="People"
  tabs={[
    { value: 'people', label: 'Employees', icon: IconUsers, content: <Panel /> },
    { value: 'admin', label: 'Admin', icon: IconSettings, content: <AdminPanel /> },
  ]}
  defaultTab="people"
/>
```

**Props:**

| Prop         | Type              | Description                                |
|--------------|-------------------|--------------------------------------------|
| `title`      | `string`          | Page heading (rendered as `<h2>`)          |
| `tabs`       | `TabDefinition[]` | Array of tab configurations                |
| `defaultTab` | `string?`         | Initially active tab (defaults to first)   |

**TabDefinition:**

| Field     | Type        | Description                        |
|-----------|-------------|------------------------------------|
| `value`   | `string`    | Unique identifier for the tab      |
| `label`   | `string`    | Displayed tab label                |
| `icon`    | `Icon`      | Tabler icon component              |
| `content` | `ReactNode` | Tab panel content                  |

---

## DataTable

Table wrapper with consistent styling and built-in loading/empty states.

```tsx
import { DataTable } from '../../components/layout'
import { Table } from '@mantine/core'

<DataTable
  loading={loading}
  empty={items.length === 0}
  emptyMessage="No items found."
  head={
    <Table.Tr>
      <Table.Th>Name</Table.Th>
      <Table.Th>Actions</Table.Th>
    </Table.Tr>
  }
  testId="my-table"
>
  {rows}
</DataTable>
```

**Props:**

| Prop           | Type        | Description                                  |
|----------------|-------------|----------------------------------------------|
| `loading`      | `boolean?`  | Shows centered `<Loader>` when true          |
| `empty`        | `boolean?`  | Shows empty message when true (after load)   |
| `emptyMessage` | `string?`   | Text for empty state                         |
| `head`         | `ReactNode` | Table header row(s)                          |
| `children`     | `ReactNode` | Table body rows                              |
| `testId`       | `string?`   | `data-testid` attribute on the table element |

**Always applies:** `striped`, `highlightOnHover`, `withTableBorder`.

---

## SectionHeader

Sub-section heading within a page or panel.

```tsx
import { SectionHeader } from '../../components/layout'

<SectionHeader
  title="Active Projects"
  actions={<Button size="xs">Add</Button>}
/>
```

**Props:**

| Prop      | Type        | Description                              |
|-----------|-------------|------------------------------------------|
| `title`   | `string`    | Section heading (rendered as `<h4>`)     |
| `actions` | `ReactNode` | Optional right-aligned elements          |

**Renders:** `Group justify="space-between" mb="md"` → `Title order={4}` + actions.

---

## FilterBar

Horizontal filter layout for list pages. Provides consistent spacing for
search inputs, select dropdowns, and segmented controls.

```tsx
import { FilterBar } from '../../components/layout'
import { TextInput, Select } from '@mantine/core'
import { IconSearch } from '@tabler/icons-react'

<FilterBar>
  <TextInput placeholder="Search..." leftSection={<IconSearch size={16} />} />
  <Select data={statusOptions} placeholder="Status" />
</FilterBar>
```

**Props:**

| Prop       | Type        | Description                              |
|------------|-------------|------------------------------------------|
| `children` | `ReactNode` | Filter controls (inputs, selects, etc.)  |

**Renders:** `Group justify="flex-start" gap="sm" mb="md" wrap="wrap"` → children.

Use on list pages with filtering (Planning, Templates).
