import { dayjs } from '@/lib/dayjs'

const numberFormatter = new Intl.NumberFormat('ru-RU')

/** Русская форма множественного числа: 1 день, 2 дня, 5 дней. */
export function pluralize(count: number, one: string, few: string, many: string): string {
  const mod10 = count % 10
  const mod100 = count % 100
  if (mod10 === 1 && mod100 !== 11) return one
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return few
  return many
}

export function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return numberFormatter.format(value)
}

export function formatHours(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value.toLocaleString('ru-RU', { maximumFractionDigits: 1 })} ч`
}

/** Длительность: минуты → «N ч M мин». Фолбэк на часы, если минут нет. */
export function formatDuration(
  minutes: number | null | undefined,
  hours: number,
): string {
  if (minutes === null || minutes === undefined) return formatHours(hours)
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m} мин`
  return m === 0 ? `${h} ч` : `${h} ч ${m} мин`
}

/** Длительность: минуты → «N ч M м» (часов/минут опускаются, если ноль). */
export function formatHoursMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || minutes <= 0) return '—'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  const parts: string[] = []
  if (h) parts.push(`${h} ч`)
  if (m) parts.push(`${m} м`)
  return parts.join(' ')
}

/** Время прохождения (часа с долями) → «N ч M м», как в команде бота !hltb. */
export function formatHltbTime(hours: number | null | undefined): string {
  if (hours === null || hours === undefined) return '—'
  const totalMinutes = Math.round(hours * 60)
  if (totalMinutes <= 0) return '—'
  const h = Math.floor(totalMinutes / 60)
  const m = totalMinutes % 60
  const parts: string[] = []
  if (h) parts.push(`${h} ч`)
  if (m) parts.push(`${m} м`)
  return parts.join(' ')
}

/** naive UTC → локальная дата, напр. «13 окт. 2026». */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return dayjs.utc(iso).local().format('D MMM YYYY')
}

/** naive UTC → локальная дата «ДД.ММ.ГГГГ». */
export function formatDateNumeric(iso: string | null | undefined): string {
  if (!iso) return '—'
  return dayjs.utc(iso).local().format('DD.MM.YYYY')
}

/** naive UTC → локальный ключ даты «YYYY-MM-DD» (для фильтров/сравнения). */
export function formatDateKey(iso: string | null | undefined): string {
  if (!iso) return ''
  return dayjs.utc(iso).local().format('YYYY-MM-DD')
}

/** naive UTC ISO → миллисекунды для сортировки (null/пусто → null). */
export function toSortTime(iso: string | null | undefined): number | null {
  if (!iso) return null
  return dayjs.utc(iso).valueOf()
}

/** Все текстовые формы даты (ключ, числом, с коротким годом, «13 окт. 2026») — для поиска. */
export function dateSearchText(iso: string | null | undefined): string {
  const key = formatDateKey(iso)
  if (!key) return ''
  const [year, month, day] = key.split('-')
  return `${key} ${day}.${month}.${year} ${day}.${month}.${year.slice(2)} ${formatDate(iso)}`.toLowerCase()
}

/** naive UTC → локальные дата и время, напр. «13 окт. 2026, 13:30». */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return dayjs.utc(iso).local().format('D MMM YYYY, HH:mm')
}

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return dayjs.utc(iso).local().format('HH:mm')
}

/** Точное время релиза известно (00:00 в БД — заглушка). */
export function hasReleaseTime(iso: string | null | undefined): boolean {
  if (!iso) return false
  const utc = dayjs.utc(iso)
  return utc.hour() !== 0 || utc.minute() !== 0 || utc.second() !== 0
}

/** Релиз уже состоялся: календарная дата не позже сегодняшней. */
export function isReleased(iso: string | null | undefined): boolean {
  if (!iso) return false
  return dayjs.utc(iso).local().startOf('day').diff(dayjs().startOf('day'), 'day') <= 0
}

/**
 * Обратный отсчёт до релиза: «XX д XX ч XX м», если время выхода известно, иначе
 * только «XX д» (00:00 в БД — заглушка). Для прошедших релизов/без даты — ''.
 */
export function formatReleaseCountdown(iso: string | null | undefined): string {
  if (!iso || isReleased(iso)) return ''
  if (!hasReleaseTime(iso)) {
    const days = dayjs.utc(iso).local().startOf('day').diff(dayjs().startOf('day'), 'day')
    return `${days} д`
  }
  const diffMs = dayjs.utc(iso).local().diff(dayjs())
  if (diffMs <= 0) return ''
  const totalMinutes = Math.floor(diffMs / 60_000)
  const days = Math.floor(totalMinutes / 1_440)
  const hours = Math.floor((totalMinutes % 1_440) / 60)
  const minutes = totalMinutes % 60
  const parts: string[] = []
  if (days) parts.push(`${days} д`)
  if (hours) parts.push(`${hours} ч`)
  if (minutes) parts.push(`${minutes} м`)
  return parts.length ? parts.join(' ') : '0 м'
}

/** Дельта до релиза: «сегодня», «через 3 дня», «5 дней назад». */
export function formatDeltaDays(days: number | null | undefined): string {
  if (days === null || days === undefined) return '—'
  if (days === 0) return 'сегодня'
  if (days > 0) {
    return `через ${days} ${pluralize(days, 'день', 'дня', 'дней')}`
  }
  const past = Math.abs(days)
  return `${past} ${pluralize(past, 'день', 'дня', 'дней')} назад`
}
