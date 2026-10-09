/** Work-package HTTP contracts. Dates are serialized ISO strings, not Date objects. */
import type { components } from '../api/generated/schema'

export type WorkPackage = components['schemas']['WorkPackageResponse']
export type WorkPackageCreate = components['schemas']['WorkPackageCreate']
export type WorkPackageUpdate = components['schemas']['WorkPackageUpdate']
export type WorkPackageWithWarnings = components['schemas']['WorkPackageCreateResponse']
export type WorkPackageRequirement = components['schemas']['WorkPackageRequirementResponse']
export type WorkPackageDependency = components['schemas']['WorkPackageDependencyResponse']
export type WorkPackageDependencies = components['schemas']['WorkPackageDependenciesResponse']
