import { describe, expect, it } from 'vitest'

import {
  buildTagFilterEntries,
  collectPlatformNames,
  normalizeTag,
  parseTagGroups,
  parseTags,
  streamTagGroups,
  streamTags,
} from '@/lib/tags'

describe('normalizeTag', () => {
  it('приводит синонимы к одному виду', () => {
    expect(normalizeTag('just chatting')).toBe('Общение')
    expect(normalizeTag('Just Chatting')).toBe('Общение')
  })

  it('остальное не трогает', () => {
    expect(normalizeTag('  RPG  ')).toBe('RPG')
  })
})

describe('parseTags', () => {
  it('разбирает перечисление и убирает повторы', () => {
    expect(parseTags('PC, PS5 | RPG, Adventure')).toEqual([
      'PC',
      'PS5',
      'RPG',
      'Adventure',
    ])
    expect(parseTags('PC, PC | RPG')).toEqual(['PC', 'RPG'])
  })

  it('учитывает псевдонимы', () => {
    expect(parseTags('Just Chatting')).toEqual(['Общение'])
  })

  it('пустая строка — пустой список', () => {
    expect(parseTags('')).toEqual([])
  })
})

describe('parseTagGroups', () => {
  it('делит по «|» и сортирует внутри группы по длине', () => {
    expect(parseTagGroups('PC, PS5 | RPG, Adventure')).toEqual([
      ['PC', 'PS5'],
      ['RPG', 'Adventure'],
    ])
  })

  it('убирает повторы между группами', () => {
    expect(parseTagGroups('PC | PC, RPG')).toEqual([['PC'], ['RPG']])
  })
})

describe('collectPlatformNames', () => {
  it('берёт названия платформ из начала строки тегов', () => {
    const names = collectPlatformNames(['PC, PS5 | RPG', 'Switch, XSX | Action'])
    expect(names.has('switch')).toBe(true)
    expect(names.has('xsx')).toBe(true)
    // Заведомо известные всегда есть.
    expect(names.has('pc')).toBe(true)
  })
})

describe('buildTagFilterEntries', () => {
  it('сначала платформы, потом жанры (по алфавиту), с префиксами в подписи', () => {
    const entries = buildTagFilterEntries(['PC', 'RPG', 'Adventure'], new Set(['pc']))
    expect(entries.map((entry) => entry.label)).toEqual([
      'Платформа: PC',
      'Жанр: Adventure',
      'Жанр: RPG',
    ])
  })

  it('одинаковые значения не дублируются', () => {
    const entries = buildTagFilterEntries(['PC', 'pc'], new Set(['pc']))
    expect(entries).toHaveLength(1)
  })
})

describe('теги стримов', () => {
  it('streamTags собирает значения из нескольких строк', () => {
    expect(streamTags(['Общение, Action', 'Участники'])).toEqual([
      'Общение',
      'Action',
      'Участники',
    ])
  })

  it('streamTagGroups отдаёт одну группу (внутри — от коротких к длинным)', () => {
    expect(streamTagGroups(['Action, RPG'])).toEqual([['RPG', 'Action']])
    expect(streamTagGroups([])).toEqual([])
  })
})
