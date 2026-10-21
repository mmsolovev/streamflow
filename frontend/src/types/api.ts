/** Общие типы API: пагинация, конверт ошибок, справочники. */

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ApiErrorBody {
  code: string
  message: string
}

export interface ApiErrorEnvelope {
  detail: ApiErrorBody
}

export interface MetaItem {
  id: number
  name: string
  slug: string | null
  abbreviation: string | null
}

export interface MetaList {
  items: MetaItem[]
}

export interface PageParams {
  limit?: number
  offset?: number
}
