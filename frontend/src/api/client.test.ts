import { describe, expect, it } from 'vitest'

import { api } from '@/api/client'

/**
 * Массивы должны уходить повторяющимся параметром без скобок:
 * `filters=a&filters=b`. Со скобками (`filters[]=a`) FastAPI параметр не
 * видит и фильтры молча игнорируются.
 */
describe('сериализация query-параметров', () => {
  const serialize = (params: Record<string, unknown>): string => {
    const serializer = api.defaults.paramsSerializer
    if (typeof serializer === 'function') return serializer(params)
    return serializer?.serialize?.(params) ?? ''
  }

  it('массив — повторяющийся ключ без скобок', () => {
    const query = serialize({ filters: ['liked', 'tag:Shooter'] })
    expect(query).toBe('filters=liked&filters=tag%3AShooter')
    expect(query).not.toContain('filters%5B%5D')
  })

  it('обычные значения — как есть', () => {
    expect(serialize({ limit: 24, offset: 0 })).toBe('limit=24&offset=0')
  })

  it('пустые значения пропускаются', () => {
    expect(serialize({ search: undefined, sort: null, limit: 10 })).toBe('limit=10')
  })

  it('пустой массив не добавляет параметров', () => {
    expect(serialize({ filters: [], limit: 10 })).toBe('limit=10')
  })
})
