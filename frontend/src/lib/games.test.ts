import { describe, expect, it } from 'vitest'

import { GAME_COVER_PLACEHOLDER, normalizeGameName } from '@/lib/games'

describe('normalizeGameName', () => {
  it('убирает пробелы по краям и регистр', () => {
    expect(normalizeGameName('  Hades  ')).toBe('hades')
  })

  it('внутренние пробелы сохраняет', () => {
    expect(normalizeGameName('Death Stranding')).toBe('death stranding')
  })
})

describe('GAME_COVER_PLACEHOLDER', () => {
  it('указывает на файл-заглушку в public', () => {
    expect(GAME_COVER_PLACEHOLDER).toBe('/images/game-placeholder.svg')
  })
})
