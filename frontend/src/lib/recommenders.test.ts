import { describe, expect, it } from 'vitest'

import {
  buildRecommenderFilterEntries,
  hasRecommender,
  recKey,
  recLogin,
  recommenderLabel,
  recommendersTooltip,
  sortRecommenderEntries,
} from '@/lib/recommenders'

const ENTRIES = [
  { user_login: 'someone', display_name: 'Кто-то' },
  { user_login: 'twitch', display_name: 'Twitch' },
  { user_login: 'tabula', display_name: 'Tabula' },
]

describe('recLogin / recKey', () => {
  it('логин приводится к нижнему регистру', () => {
    expect(recLogin({ user_login: 'TABULA' })).toBe('tabula')
    expect(recLogin({})).toBe('')
  })

  it('ключ фильтра — rec:<логин>', () => {
    expect(recKey('tabula')).toBe('rec:tabula')
  })
})

describe('recommenderLabel', () => {
  it('спец-пользователи показываются своими именами', () => {
    expect(recommenderLabel({ user_login: 'tabula' })).toBe('Tabula')
    expect(recommenderLabel({ user_login: 'twitch' })).toBe('Twitch')
  })

  it('остальные — по display_name, иначе логин', () => {
    expect(recommenderLabel({ user_login: 'x', display_name: 'Имя' })).toBe('Имя')
    expect(recommenderLabel({ user_login: 'x' })).toBe('x')
  })
})

describe('sortRecommenderEntries', () => {
  it('Tabula и Twitch — первыми, остальные по алфавиту', () => {
    const sorted = sortRecommenderEntries([
      { user_login: 'zzz', display_name: 'Яя' },
      { user_login: 'twitch' },
      { user_login: 'aaa', display_name: 'Аа' },
      { user_login: 'tabula' },
    ])
    expect(sorted.map((entry) => entry.user_login)).toEqual([
      'tabula',
      'twitch',
      'aaa',
      'zzz',
    ])
  })
})

describe('hasRecommender', () => {
  it('ищет по логину без учёта регистра', () => {
    const item = { recommenders_list: ENTRIES }
    expect(hasRecommender(item, 'TABULA')).toBe(true)
    expect(hasRecommender(item, 'someone')).toBe(true)
    expect(hasRecommender(item, 'nobody')).toBe(false)
    expect(hasRecommender(item, null)).toBe(false)
  })
})

describe('recommendersTooltip', () => {
  it('собирает подсказку «Имя: заметка»', () => {
    const tooltip = recommendersTooltip([
      { user_login: 'tabula', display_name: 'Tabula', recommendation_note: 'В списке' },
      { user_login: 'x', display_name: 'Имя' },
    ])
    expect(tooltip).toContain('Tabula: В списке')
    expect(tooltip).toContain('Имя')
  })
})

describe('buildRecommenderFilterEntries', () => {
  it('уникальные рекомендовавшие, Tabula и Twitch первыми', () => {
    const entries = buildRecommenderFilterEntries([
      { recommenders_list: ENTRIES },
      { recommenders_list: [{ user_login: 'tabula' }] },
    ])
    expect(entries.map((entry) => entry.login)).toEqual(['tabula', 'twitch', 'someone'])
    expect(entries[0].label).toBe('Tabula')
  })
})
