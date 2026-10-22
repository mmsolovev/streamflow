import { describe, expect, it } from 'vitest'

import {
  formatDate,
  formatDateKey,
  formatDateNumeric,
  formatDuration,
  formatHours,
  formatHoursMinutes,
  formatHltbTime,
  formatNumber,
  formatReleaseCountdown,
  hasReleaseTime,
  isReleased,
} from '@/lib/format'

/** Неразрывные пробелы (разделитель тысяч) заменяем обычным. */
const norm = (value: string): string => value.replace(/[  ]/g, ' ')

describe('formatNumber', () => {
  it('разделяет тысячи', () => {
    expect(norm(formatNumber(1345))).toBe('1 345')
    expect(formatNumber(0)).toBe('0')
  })

  it('для пустого значения — прочерк', () => {
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(undefined)).toBe('—')
  })
})

describe('formatHours', () => {
  it('показывает часы с одной десятой', () => {
    expect(norm(formatHours(2286))).toBe('2 286 ч')
    expect(formatHours(101.09)).toBe('101,1 ч')
  })

  it('для пустого значения — прочерк', () => {
    expect(formatHours(null)).toBe('—')
  })
})

describe('formatDuration', () => {
  it('переводит минуты в часы и минуты', () => {
    expect(formatDuration(270, 4.5)).toBe('4 ч 30 мин')
    expect(formatDuration(366, 6.1)).toBe('6 ч 6 мин')
  })

  it('опускает минуты, если их нет', () => {
    expect(formatDuration(120, 2)).toBe('2 ч')
  })

  it('когда часов нет — только минуты', () => {
    expect(formatDuration(30, 0.5)).toBe('30 мин')
  })

  it('без минут возвращает часы из fallback', () => {
    expect(formatDuration(null, 4.5)).toBe('4,5 ч')
  })
})

describe('formatHoursMinutes', () => {
  it('собирает часы и минуты', () => {
    expect(formatHoursMinutes(366)).toBe('6 ч 6 м')
    expect(formatHoursMinutes(120)).toBe('2 ч')
    expect(formatHoursMinutes(45)).toBe('45 м')
  })

  it('для пустого значения — прочерк', () => {
    expect(formatHoursMinutes(0)).toBe('—')
    expect(formatHoursMinutes(null)).toBe('—')
  })
})

describe('formatHltbTime', () => {
  it('округляет часы с долями до минут — как в команде !hltb', () => {
    expect(formatHltbTime(101.09)).toBe('101 ч 5 м')
    expect(formatHltbTime(30.03)).toBe('30 ч 2 м')
    expect(formatHltbTime(0.05)).toBe('3 м')
  })

  it('для пустого значения — прочерк', () => {
    expect(formatHltbTime(null)).toBe('—')
    expect(formatHltbTime(0)).toBe('—')
  })
})

describe('даты', () => {
  const iso = '2026-10-23T13:02:00'

  it('formatDateKey — дата в формате YYYY-MM-DD', () => {
    expect(formatDateKey(iso)).toBe('2026-10-23')
  })

  it('formatDateNumeric — дата прописью', () => {
    expect(formatDateNumeric(iso)).toBe('23.10.2026')
  })

  it('formatDate — дата с месяцем текстом', () => {
    expect(formatDate(iso)).toMatch(/2026/)
  })

  it('пустые даты — прочерк', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDateNumeric(null)).toBe('—')
  })
})

describe('релизы', () => {
  it('hasReleaseTime: полночь — заглушка', () => {
    expect(hasReleaseTime('2026-10-23T00:00:00')).toBe(false)
    expect(hasReleaseTime('2026-10-23T13:02:00')).toBe(true)
  })

  it('isReleased: прошедшая дата — вышел', () => {
    expect(isReleased('2020-01-01T00:00:00')).toBe(true)
    expect(isReleased('2999-01-01T00:00:00')).toBe(false)
  })

  it('formatReleaseCountdown: для будущей даты — дни, для прошедшей — пусто', () => {
    expect(formatReleaseCountdown('2999-01-01T00:00:00')).toMatch(/д/)
    expect(formatReleaseCountdown('2020-01-01T00:00:00')).toBe('')
    expect(formatReleaseCountdown(null)).toBe('')
  })
})
