import { ChevronDown } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { CHANNEL_NAME, SOCIALS } from '@/config/socials'
import { listSocialLinks } from '@/features/socialLinks/api'

function serviceColor(serviceKey: string, url: string): string {
  const colors: Record<string, string> = {
    twitch: 'var(--brand-twitch)',
    telegram: 'var(--brand-telegram)',
    youtube: 'var(--brand-youtube)',
    boosty: 'var(--brand-boosty)',
    discord: 'var(--brand-discord)',
  }
  if (colors[serviceKey.toLowerCase()]) return colors[serviceKey.toLowerCase()]

  try {
    const host = new URL(url).hostname.toLowerCase()
    if (host === 'twitch.tv' || host.endsWith('.twitch.tv')) return colors.twitch
    if (host === 't.me' || host.endsWith('.telegram.me')) return colors.telegram
    if (
      host === 'youtube.com' ||
      host === 'youtu.be' ||
      host.endsWith('.youtube.com')
    ) {
      return colors.youtube
    }
    if (host === 'boosty.to' || host.endsWith('.boosty.to')) return colors.boosty
    if (
      host === 'discord.gg' ||
      host === 'discord.com' ||
      host.endsWith('.discord.com')
    ) {
      return colors.discord
    }
  } catch {
    // Неполная заглушка «#» не имеет брендового домена.
  }
  return 'var(--text)'
}

function SocialIcon({ src, alt }: { src: string; alt: string }) {
  return (
    <img
      src={src}
      alt={alt}
      className="h-4 w-4 shrink-0"
      onError={(event) => {
        event.currentTarget.style.display = 'none'
      }}
    />
  )
}

/** Название канала + выпадающий список соцсетей (шрифт Orbitron). */
export function ChannelMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const linksQuery = useQuery({
    queryKey: ['social-links'],
    queryFn: listSocialLinks,
    staleTime: 10 * 60_000,
  })
  const links =
    linksQuery.data ??
    SOCIALS.map((social, index) => ({
      id: index,
      service_key: social.key,
      name: social.label,
      url: social.url,
      description: '',
      icon_url: social.icon,
      sort_order: index,
      is_active: true,
    }))

  useEffect(() => {
    if (!open) return
    const handlePointer = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex cursor-pointer list-none items-center gap-1.5 font-social text-lg text-[var(--text)] outline-none"
      >
        {CHANNEL_NAME}
        <ChevronDown
          className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open ? (
        <div className="absolute left-0 top-full z-50 mt-2 w-max min-w-56 max-w-[min(42rem,calc(100vw-1rem))] rounded-lg border border-white/10 bg-[#1f1f1f] p-1.5 shadow-xl">
          {links.map((social) => {
            const icon =
              social.icon_url ??
              SOCIALS.find((fallback) => fallback.key === social.service_key)?.icon
            return (
              <a
                key={social.id}
                href={social.url}
                target="_blank"
                rel="noreferrer"
                onClick={() => setOpen(false)}
                className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 transition-colors hover:bg-white/5"
              >
                {icon ? <SocialIcon src={icon} alt={social.name} /> : null}
                <span className="min-w-0 whitespace-normal break-words">
                  <span
                    className="font-social text-sm tracking-wide"
                    style={{ color: serviceColor(social.service_key, social.url) }}
                  >
                    {social.name}
                  </span>
                <span className="ml-1 text-xs text-[var(--text)]">
                    — {social.description || 'описание не задано'}
                  </span>
                </span>
              </a>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
