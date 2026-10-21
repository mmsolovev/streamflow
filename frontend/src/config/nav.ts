export interface NavTab {
  key: string
  label: string
  /** Маршрут по умолчанию для вкладки. */
  to: string
  /** Префиксы путей, при которых вкладка считается активной (группировка страниц). */
  bases: string[]
  /** Включена ли вкладка (остальные — задел, скрыты до реализации). */
  enabled: boolean
}

export const NAV_TABS: NavTab[] = [
  {
    key: 'stats',
    label: 'Статистика',
    to: '/games',
    bases: ['/games', '/streams', '/releases', '/recommendations', '/hltb'],
    enabled: true,
  },
  {
    key: 'commands',
    label: 'Команды',
    to: '/commands',
    bases: ['/commands'],
    enabled: false,
  },
  {
    key: 'events',
    label: 'Ивенты',
    to: '/events',
    bases: ['/events'],
    enabled: false,
  },
  {
    key: 'interactive',
    label: 'Интерактив',
    to: '/interactive',
    bases: ['/interactive'],
    enabled: false,
  },
]

/** Разделы вкладки «Статистика» (левая панель). */
export type StatsSection = 'games' | 'streams' | 'releases' | 'recommendations' | 'hltb'

export interface StatsTab {
  key: StatsSection
  label: string
  to: string
  /** Не переводить подпись в верхний регистр (брендованные названия). */
  noUppercase?: boolean
}

export const STATS_TABS: StatsTab[] = [
  { key: 'games', label: 'Игры', to: '/games' },
  { key: 'streams', label: 'Стримы', to: '/streams' },
  { key: 'releases', label: 'Релизы', to: '/releases' },
  { key: 'recommendations', label: 'Советы', to: '/recommendations' },
  { key: 'hltb', label: 'HowLongToBeat', to: '/hltb', noUppercase: true },
]

/** Разделы вкладки «Админка» (левая панель). */
export type AdminSection = 'management' | 'connections' | 'telegram'

export interface AdminTab {
  key: AdminSection
  label: string
  to: string
}

export const ADMIN_TABS: AdminTab[] = [
  { key: 'management', label: 'Управление', to: '/admin/management' },
  { key: 'telegram', label: 'Telegram', to: '/admin/telegram' },
  { key: 'connections', label: 'Подключения', to: '/admin/connections' },
]

/** Подразделы раздела «Telegram» (переключатели под шапкой). */
export type TelegramTab = 'start' | 'during' | 'end'

export interface TelegramTabDef {
  key: TelegramTab
  label: string
  /** Значение query-параметра `tab` в URL. */
  param: string
}

export const TELEGRAM_TABS: TelegramTabDef[] = [
  { key: 'start', label: 'Старт стрима', param: 'start' },
  { key: 'during', label: 'Во время стрима', param: 'during' },
  { key: 'end', label: 'Конец стрима', param: 'end' },
]

/** Подраздел, открытый по умолчанию при переходе в «Telegram». */
export const DEFAULT_TELEGRAM_TAB: TelegramTab = 'end'
