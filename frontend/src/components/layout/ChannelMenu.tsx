import { ChevronDown } from 'lucide-react'

import { CHANNEL_NAME, SOCIALS } from '@/config/socials'

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
  return (
    <details className="group relative">
      <summary className="flex cursor-pointer list-none items-center gap-1.5 font-social text-lg text-[var(--text)] outline-none [&::-webkit-details-marker]:hidden">
        {CHANNEL_NAME}
        <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
      </summary>
      <div className="absolute left-0 top-full z-50 mt-2 w-48 rounded-lg border border-white/10 bg-[#1f1f1f] p-1.5 shadow-xl">
        {SOCIALS.map((social) => (
          <a
            key={social.key}
            href={social.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2.5 rounded-md px-2.5 py-2 font-social text-sm tracking-wide text-[var(--text-muted)] transition-colors hover:bg-white/5 hover:text-[var(--text)]"
          >
            <SocialIcon src={social.icon} alt={social.label} />
            {social.label}
          </a>
        ))}
      </div>
    </details>
  )
}
