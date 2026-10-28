/**
 * Отображаемые псевдонимы тегов: одинаковые по смыслу значения приводим к одному.
 * Например, категория/жанр «Just Chatting» показывается как «Общение».
 */
const TAG_ALIASES: Record<string, string> = {
  'just chatting': 'Общение',
}

/** Приводит значение тега к отображаемому виду. */
export function normalizeTag(value: string): string {
  const trimmed = value.trim()
  return TAG_ALIASES[trimmed.toLowerCase()] ?? trimmed
}

/** Разбирает перечисление через запятую в нормализованные значения. */
function splitList(value: string): string[] {
  return value
    .split(',')
    .map((item) => normalizeTag(item))
    .filter(Boolean)
}

/** Убирает повторы (без учёта регистра), сохраняя первый вариант. */
function dedupe(values: string[]): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const value of values) {
    const key = value.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    result.push(value)
  }
  return result
}

/** Сортировка по длине (короткие раньше), затем по алфавиту. */
function byLength(a: string, b: string): number {
  return a.length - b.length || a.localeCompare(b, 'ru')
}

/** Плоский нормализованный список тегов (для фильтрации по клику). */
export function parseTags(tags: string): string[] {
  return dedupe(splitList(tags.replace(/\|/g, ',')))
}

/**
 * Группы тегов (платформы | жанры): «A, B | C» → [['B', 'A'], ['C']].
 * Внутри каждой группы — сортировка от короткого к длинному,
 * повторы между группами убираются.
 */
export function parseTagGroups(tags: string): string[][] {
  const seen = new Set<string>()
  const groups: string[][] = []
  for (const raw of tags.split('|')) {
    const values: string[] = []
    for (const item of splitList(raw)) {
      const key = item.toLowerCase()
      if (seen.has(key)) continue
      seen.add(key)
      values.push(item)
    }
    if (values.length > 0) groups.push(values.sort(byLength))
  }
  return groups
}

export interface TagFilterEntry {
  /** Исходное значение тега (для сравнения при фильтрации). */
  value: string
  /** Отображаемая подпись (с префиксом «Платформа»/«Жанр»). */
  label: string
}

/** Платформы, используемые в таблицах. */
const KNOWN_PLATFORMS = ['pc', 'ps4', 'ps5']

/**
 * Имена платформ: известные плюс всё, что стоит до знака «|»
 * (формат тегов «платформы | жанры»).
 */
export function collectPlatformNames(tagStrings: string[]): Set<string> {
  const names = new Set<string>(KNOWN_PLATFORMS)
  for (const tags of tagStrings) {
    const [head, ...rest] = tags.split('|')
    if (rest.length === 0) continue
    for (const item of head.split(',')) {
      const value = item.trim().toLowerCase()
      if (value) names.add(value)
    }
  }
  return names
}

/**
 * Собирает уникальные теги в варианты фильтра: платформы (префикс
 * «Платформа») идут первыми, затем жанры (префикс «Жанр»).
 */
export function buildTagFilterEntries(
  tags: string[],
  platformNames: Set<string>,
): TagFilterEntry[] {
  const seen = new Map<string, string>()
  for (const tag of tags) {
    const key = tag.toLowerCase()
    if (!seen.has(key)) seen.set(key, tag)
  }
  const platforms: string[] = []
  const genres: string[] = []
  for (const [key, display] of seen) {
    if (platformNames.has(key)) platforms.push(display)
    else genres.push(display)
  }
  const sortRu = (a: string, b: string) => a.localeCompare(b, 'ru')
  platforms.sort(sortRu)
  genres.sort(sortRu)
  return [
    ...platforms.map((value) => ({ value, label: `Платформа: ${value}` })),
    ...genres.map((value) => ({ value, label: `Жанр: ${value}` })),
  ]
}

/** Плоский нормализованный список тегов стрима (строки могут быть с перечислением). */
export function streamTags(tags: string[]): string[] {
  return dedupe(tags.flatMap((value) => splitList(value)))
}

/** Теги стрима → одна группа, отсортированная от короткого к длинному. */
export function streamTagGroups(tags: string[]): string[][] {
  const values = streamTags(tags)
  return values.length > 0 ? [values.sort(byLength)] : []
}
