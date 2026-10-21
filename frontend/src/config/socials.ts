export type SocialKey = 'twitch' | 'telegram' | 'youtube' | 'boosty' | 'discord'

export interface SocialLink {
  key: SocialKey
  label: string
  /** Ссылка на профиль. Пока заглушка "#" — точные адреса добавим позже. */
  url: string
  /** Иконка из `public/socials/` (заказчик кладёт файлы сюда). */
  icon: string
}

export const SOCIALS: SocialLink[] = [
  { key: 'twitch', label: 'Twitch', url: '#', icon: '/socials/twitch.png' },
  { key: 'telegram', label: 'Telegram', url: '#', icon: '/socials/telegram.png' },
  { key: 'youtube', label: 'YouTube', url: '#', icon: '/socials/youtube.png' },
  { key: 'boosty', label: 'Boosty', url: '#', icon: '/socials/boosty.png' },
  { key: 'discord', label: 'Discord', url: '#', icon: '/socials/discord.png' },
]

export const CHANNEL_NAME = 'Tabula'
