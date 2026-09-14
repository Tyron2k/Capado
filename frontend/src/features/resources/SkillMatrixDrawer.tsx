/**
 * Drawer wrapper for the skill assignment matrix of a resource.
 * Works for both personal and infrastructure resources.
 */

import { Drawer } from '@mantine/core'
import { SkillMatrix } from './SkillMatrix'

interface QualificationMatrixDrawerProps {
  resourceId: string
  resourceName: string
  resourceType?: 'personal' | 'infrastructure'
  opened: boolean
  onClose: () => void
}

export function SkillMatrixDrawer({
  resourceId,
  resourceName,
  resourceType = 'personal',
  opened,
  onClose,
}: QualificationMatrixDrawerProps) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title={`Skills – ${resourceName}`}
      position="right"
      size="xl"
      trapFocus
      returnFocus
    >
      {opened && <SkillMatrix resourceId={resourceId} resourceType={resourceType} />}
    </Drawer>
  )
}
