import { useChannel } from '@/features/meta/useMeta'

/**
 * Аватар канала над разделами боковой панели.
 *
 * Картинка берётся из `user_profiles.profile_image_url` (Twitch CDN);
 * пока данных нет — показывается локальный запасной файл. Клик ведёт на
 * Twitch-страницу стримера (`user_profiles.twitch_url`). Статус эфира
 * приходит из `/meta/channel` и обновляется опросом.
 */
export function ChannelAvatar() {
  const { data } = useChannel()
  const src = data?.profile_image_url || '/images/tabula.png'
  const name = data?.display_name || 'Tabula'
  const isLive = Boolean(data?.is_live)
  const twitchUrl =
    data?.twitch_url || `https://www.twitch.tv/${data?.login || 'tabula'}`

  return (
    <div className="flex h-24 items-center justify-center px-3 pt-2">
      <a
        href={twitchUrl}
        target="_blank"
        rel="noreferrer"
        title={`${name} на Twitch`}
        className="group flex flex-col items-center gap-1"
      >
        <img
          src={src}
          alt={name}
          className="h-14 w-14 rounded-full object-cover transition-opacity group-hover:opacity-80"
          onError={(event) => {
            event.currentTarget.src = '/images/tabula.png'
          }}
        />
        <span className="flex items-center gap-1 text-[10px] uppercase leading-none tracking-wider">
          {isLive ? (
            <>
              <span
                aria-hidden
                className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500"
              />
              <span className="text-[var(--text)]">Online</span>
            </>
          ) : (
            <span className="text-[var(--text-muted)]">Offline</span>
          )}
        </span>
      </a>
    </div>
  )
}
