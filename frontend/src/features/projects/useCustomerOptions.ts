import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'

import { getCustomers } from '../../api/customers'
import { queryKeys } from '../../api/queryClient'

/**
 * The customer picker's options, shared by every screen that offers one.
 *
 * TWO COMPONENTS FETCHED THIS LIST INDEPENDENTLY — the project form and the folder tree — each with
 * its own `cancelled` flag and its own copy of the mapping. Opening the folder tree and then a project
 * form fetched it twice, and the two copies could disagree if a customer was renamed in between.
 *
 * Sharing a KEY rather than sharing a hook is what fixes that: any further screen that needs the
 * picker gets the same cache entry, so the number of requests does not grow with the number of places
 * a customer can be chosen. Extracting it here is only how the key gets reused without copying.
 *
 * Retired customers are omitted: a project already naming one keeps it, but nobody should newly assign
 * work to a customer that has been retired.
 *
 * The picker DEGRADES TO EMPTY on failure rather than reporting an error. That is deliberate and
 * unchanged: a project without a customer is valid, the folder may supply one anyway, and a
 * notification here would fire behind a form the user is still filling in.
 */
export function useCustomerOptions(): { value: string; label: string }[] {
  const { data } = useQuery({
    queryKey: queryKeys.customers.list(false),
    queryFn: () => getCustomers(),
  })

  return useMemo(() => (data ?? []).map((c) => ({ value: c.id, label: c.name })), [data])
}
