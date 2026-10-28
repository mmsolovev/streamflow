/**
 * DTO-типы.
 *
 * Основная часть выведена из сгенерированной OpenAPI-схемы
 * (`src/api/schema.d.ts`, команда `npm run gen:api`). Ручные типы — только там,
 * где у бэкенда нет `response_model` (health, meta, поиск игр).
 */
import type { components } from '@/api/schema'

type Schemas = components['schemas']

export type UserView = Schemas['UserView']
export type StreamerAuthStatus = Schemas['StreamerAuthStatus']
export type StreamerAuthorizationView = Schemas['StreamerAuthorizationView']

export type GameView = Schemas['GameView'] & {
  /** Будущее поле: текст отзыва об игре (бэкенд пока не отдаёт). */
  review?: string | null
}
export type GameDetail = Schemas['GameDetail']
export type GameStream = Schemas['GameStream']
export type GameStreamsPage = Schemas['Page_GameStream_']
export type GameStateUpdateBody = Schemas['GameStateUpdateIn']
export type GameStateUpdateResult = Schemas['GameStateUpdateOut']

export type StreamView = Schemas['StreamView']
export type StreamParticipant = Schemas['StreamParticipant']
export type StreamParticipantAddBody = Schemas['StreamParticipantAddIn']
export type StreamParticipantActionResult = Schemas['StreamParticipantActionOut']
export type StreamParticipantDeleteResult = Schemas['StreamParticipantDeleteOut']
export type ReleaseView = Schemas['ReleaseView']
export type InterestUpdateBody = Schemas['InterestUpdateIn']
export type InterestUpdateResult = Schemas['InterestUpdateOut']

export type RecommendationView = Schemas['RecommendationView']
export type RecommendationAddBody = Schemas['RecommendationAddBody']
export type RecommendationActionResult = Schemas['RecommendationActionOut']
export type RecommendationDeleteResult = Schemas['RecommendationDeleteOut']
export type RecommendationSearchOut = Schemas['RecommendationSearchOut']
export type GameCandidate = Schemas['GameCandidate']
export type UserSuggestion = Schemas['UserSuggestion']
export type UsersPage = Schemas['Page_UserSuggestion_']
export type ChannelInfo = Schemas['ChannelInfo']
export type HltbView = Schemas['HltbView']
export type HltbPage = Schemas['Page_HltbView_']
export type HltbLookup = Schemas['HltbLookupOut']
export type HltbAddResult = Schemas['HltbAddOut']

export type GamesPage = Schemas['Page_GameView_']
export type StreamsPage = Schemas['Page_StreamView_']
export type ReleasesPage = Schemas['Page_ReleaseView_']
export type RecommendationsPage = Schemas['Page_RecommendationView_']

/* --- Ручные типы (нет response_model на бэкенде) ----------------------- */

export interface Health {
  status: string
  database: string
}

export interface GameSearchMatch {
  name: string
  streams_count: number
  last_stream: string | null
  hours: number
  rank: number
  liked: boolean
  completed: boolean
}

export interface GameSearchResult {
  query: string
  match: GameSearchMatch | null
}
