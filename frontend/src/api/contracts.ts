/** Wire types for an existing operation; Axios still owns transport and authentication. */
import type { paths } from './generated/schema'

type JsonContent<T> = T extends { content: { 'application/json': infer Data } } ? Data : void
export type ApiResponse<P extends keyof paths, M extends keyof paths[P]> = paths[P][M] extends {
  responses: infer R
}
  ? JsonContent<R[Extract<keyof R, 200 | 201 | 202 | 204>]>
  : never
export type ApiBody<P extends keyof paths, M extends keyof paths[P]> = paths[P][M] extends {
  requestBody?: infer B
}
  ? JsonContent<NonNullable<B>>
  : never
export type ApiQuery<
  P extends keyof paths,
  M extends keyof paths[P] = 'get',
> = paths[P][M] extends { parameters: { query?: infer Q } } ? NonNullable<Q> : never
