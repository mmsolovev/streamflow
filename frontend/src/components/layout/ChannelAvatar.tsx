import { useChannel } from '@/features/meta/useMeta'

/**
 * Аватар канала над разделами боковой панели.
 *
 * Картинка берётся из `user_profiles.profile_image_url` (Twitch CDN);
 * пока данных нет — показывается локальный запасной файл.
 */
export function ChannelAvatar() {
  const { data } = useChannel()
  const src = data?.profile_image_url || '/images/tabula.png'
  const name = data?.display_name || 'Tabula'

  return (
    <div className="flex h-24 items-center justify-center px-3 pt-2">
      <img
        src={src}
        alt={name}
        title={name}
        className="h-16 w-16 rounded-full object-cover"
        onError={(event) => {
          event.currentTarget.src = '/images/tabula.png'
        }}
      />
    </div>
  )
}
