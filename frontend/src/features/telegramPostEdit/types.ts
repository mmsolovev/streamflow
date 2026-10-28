export interface PostEditSettings {
  enabled: boolean
  delay_seconds: number
  header: string
  item: string
  separator: string
  footer: string
  link_label: string
  updated_at: string | null
}

export interface PostEditRun {
  id: number
  stream_id: string
  stream_title: string | null
  stream_started_at: string | null
  stream_ended_at: string | null
  announcement_id: number | null
  status: string
  vod_url: string | null
  last_error: string | null
  selected_by_admin: boolean
  check_at: string | null
  applied_at: string | null
  undone_at: string | null
}

export interface AnnouncementOption {
  id: number
  message_id: number
  posted_at: string
  media_kind: string | null
  status: string
  manually_edited: boolean
  preview: string
  link_urls: string[]
}

export interface PostEditPreview {
  text: string
  html: string
  media_kind: string | null
}

export interface PostStreamState {
  settings: PostEditSettings
  target: PostEditRun | null
  runs: PostEditRun[]
  announcements: AnnouncementOption[]
  preview: PostEditPreview
}

export interface VodCheckResult {
  available: boolean
  vod_url: string | null
  duration_minutes: number | null
  error: string | null
  checked_at: string
}

export interface ActionAccepted {
  accepted: boolean
  message: string
}
