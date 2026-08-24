# Home Assistant Media Tracker

A HACS-installable Home Assistant custom integration for tracking movies and TV shows with TMDB.

## Current features

- Authenticate a TMDB account using TMDB's user session flow.
- Search TMDB directly from a Home Assistant response action.
- Follow/unfollow TV shows and add/remove movies from the TMDB watchlist directly from Home Assistant.
- Read movie and TV watchlists from TMDB.
- Treat TV shows on the TMDB watchlist as followed shows.
- Expose the next episode to air for followed shows.
- Track TV progress locally and expose the next unwatched episode to watch.
- Aggregate scheduled episodes across all followed shows by release date.
- Expose default next-N, today, next-7-days and next-30-days episode sensors.
- Mark individual episodes, selected seasons, or all regular seasons as watched.
- Discover highly rated movies available from selected streaming providers in a configured region.
- Store `watched` and `dismissed` state locally in Home Assistant.
- Marking an item watched removes it from the TMDB watchlist and keeps the local watched history so it is not rediscovered.
- Configure your subscribed TMDB providers, minimum rating, vote threshold and discovery limit in the UI.
- Media availability attributes expose all TMDB streaming providers for the configured region; your provider selection only controls discovery and `available_on_my_services`.

## Installation with HACS

Until the repository is included in the default HACS catalogue:

1. Open HACS.
2. Open Integrations.
3. Add `https://github.com/dennisgranasen/home-assistant-media-tracker` as a custom repository of type **Integration**.
4. Install **Media Watch**.
5. Restart Home Assistant.
6. Go to **Settings > Devices & services > Add integration** and search for **Media Watch**.

## TMDB setup

Create an API Read Access Token in your TMDB account under **Settings > API**.

During Home Assistant setup, Media Watch creates a TMDB request token and shows an authorization URL. Approve it while logged in to TMDB, then return to Home Assistant and submit the form. Media Watch will create and store a TMDB user session.

## Entities

The initial release creates:

- `sensor.media_watch_movie_watchlist`
- `sensor.media_watch_following_tv`
- `sensor.media_watch_upcoming_episodes`
- `sensor.media_watch_next_episodes_to_watch`
- `sensor.media_watch_next_upcoming_episodes`
- `sensor.media_watch_episodes_today`
- `sensor.media_watch_episodes_next_7_days`
- `sensor.media_watch_episodes_next_30_days`
- `sensor.media_watch_upcoming_media_card` (Upcoming Media Card compatibility feed)
- `sensor.media_watch_movie_discovery`

Actual entity IDs can differ if Home Assistant needs to resolve naming conflicts.

## Actions

Example:

```yaml
action: media_watch.mark_watched
data:
  media_type: movie
  tmdb_id: 12345
```

Available actions:

- `media_watch.search` (returns response data)
- `media_watch.follow`
- `media_watch.unfollow`
- `media_watch.mark_watched`
- `media_watch.mark_unwatched`
- `media_watch.dismiss`
- `media_watch.undismiss`
- `media_watch.refresh`

Search example:

```yaml
action: media_watch.search
data:
  query: Severance
  media_type: tv
  limit: 10
response_variable: search_result
```

Follow a TV show after selecting its TMDB ID:

```yaml
action: media_watch.follow
data:
  media_type: tv
  tmdb_id: 95396
```

For TV, the TMDB watchlist is Media Watch's source of truth for followed
shows. For movies, it is the wanted/watchlist queue.

## Scope of v0.5.x

This is intentionally the foundation release. Planned work includes:

- Search and Follow/Watchlist controls directly from Home Assistant.
- A dedicated Lovelace card with posters and buttons.
- Per-episode watched state.
- Notifications when tracked media becomes available.
- Better Swedish streaming availability handling.
- Award/Oscar based discovery.
- Optional import from other watchlist sources when a stable API is available.

## Data sources

Movie, TV and watch-provider metadata is supplied by TMDB. TMDB watch-provider data is powered by JustWatch.

This product uses the TMDB API but is not endorsed or certified by TMDB.


## Provider data

TMDB exposes separate movie and TV provider catalogues. Media Watch combines
both catalogues for the provider selector and stores TMDB provider IDs.

For each movie/show the integration exposes:

- `providers`: all streaming providers returned by TMDB for the configured region.
- `provider_details`: provider IDs, names and TMDB `logo_path` values.
- `my_providers`: matching providers from your selected subscriptions.
- `available_on_my_services`: whether at least one selected subscription matches.
- `availability`: separate `flatrate`, `free`, `ads`, `rent` and `buy` lists.
- `watch_link`: TMDB/JustWatch watch-provider link when available.

The native Home Assistant config-flow select control does not support an image
field per option, so provider logos cannot be rendered inside that selector
without a custom frontend. TMDB logo paths are retained for dashboard/card use.


## TV progress

Media Watch keeps TV progress locally because TMDB does not provide a general
watched-history API.

Mark several seasons watched:

```yaml
action: media_watch.mark_seasons_watched
data:
  tmdb_id: 84773
  seasons:
    - 1
    - 2
```

Mark all regular seasons watched (season 0 / specials is excluded):

```yaml
action: media_watch.mark_seasons_watched
data:
  tmdb_id: 84773
  all_seasons: true
```

Mark one episode watched:

```yaml
action: media_watch.mark_episode_watched
data:
  tmdb_id: 84773
  season: 3
  episode: 1
```

Each followed show exposes both:

- `next_episode_to_air`: TMDB's next scheduled episode.
- `next_episode_to_watch`: the first episode not marked watched in your local progress.

Whole watched seasons are stored compactly. Episode-level progress is only
needed for partially watched seasons, which avoids storing every episode of
long-running shows.


## Upcoming episode search

The default global "next upcoming episodes" sensor exposes 5 episodes, sorted
by `air_date`. The default can be changed in integration options.

Ad-hoc query:

```yaml
action: media_watch.upcoming_episodes
data:
  days: 7
  limit: 10
response_variable: upcoming
```

`days: 0` means today only. The current release supports a maximum window of
30 days.

The integration also exposes ready-made sensors for:

- today
- next 7 days
- next 30 days

Upcoming release data is based on episode air dates supplied by TMDB. If TMDB
has not yet published an episode date, that episode cannot appear in these
lists.


## Upcoming Media Card

Media Watch includes a compatibility sensor for
`custom:upcoming-media-card`. Install **Upcoming Media Card** separately
through HACS, then point the card at the Media Watch feed:

```yaml
type: custom:upcoming-media-card
entity: sensor.media_watch_upcoming_media_card
title: Kommande avsnitt
max: 5
image_style: poster
corner_radius: 12
sort_by: airdate
sort_ascending: true
enable_tooltips: true
url: https://www.themoviedb.org/tv/$tmdb_id
```

The compatibility sensor exposes releases from the next 30 days and includes
TMDB posters, episode code/title, air date, provider information and TMDB ID.

The integration itself does not bundle or copy Upcoming Media Card. It only
produces its expected sensor data format, keeping the projects independently
updatable through HACS.


## Media Tracker Card

The compatibility feed also exposes structured `season`, `episode_number` and
`provider_details` data for the companion `media-tracker-card`, including TMDB
provider `logo_path` values for provider logos and action parameters.

### v0.5.3 upcoming behavior

The main `next upcoming episodes` feed and Upcoming Media Card compatibility
sensor now use each followed show's `next_episode_to_air` without a 30-day
cutoff. The configured `upcoming_limit` (default 5) controls how many are
shown. The today / 7-day / 30-day sensors remain time-windowed.


### v0.6.0 card feed

`sensor.media_watch_upcoming_media_card` now exposes three sections for the
companion card:

- `upcoming_episodes`
- `watchlist_movies`
- `discovery_movies`

The legacy `data` TV attribute remains available for compatibility.


### v0.7.0 generic feeds

The companion card now has three dedicated entities. Each exposes one common
`items` attribute:

- `sensor.media_watch_episodes`
- `sensor.media_watch_watchlist`
- `sensor.media_watch_discovery`

`sensor.media_watch_episodes` is a **watch queue**, not a release calendar.
It exposes the first locally unwatched episode of every followed TV show.
Therefore a show with no recorded progress starts at S01E01 even when TMDB
already lists a future season as the next episode to air.

The existing today / 7-day / 30-day sensors remain release-calendar views.

Discovery also excludes movies that are already on the TMDB watchlist, so
using `media_watch.follow` moves a discovery movie to the watchlist feed on
the next coordinator refresh.


### v0.8.0 language handling

Media Watch now uses the primary language/country returned by the authenticated
TMDB account by default. Movie watchlist and discovery items are re-fetched
through the movie-details endpoint in that locale instead of trusting the
language of the discover/watchlist payload.

TMDB's website has a separate **Fallback Language** profile setting, but the
public account API does not expose that setting. Media Watch therefore has a
`Fallback language` option (default `en-US`). Metadata resolution is:

1. TMDB profile language (or manual language override)
2. Media Watch fallback language
3. TMDB original-language metadata

The fallback is field-aware: a missing localized overview can fall back while
a localized title remains in the primary language.


### v0.9.0 provider filtering

Watchlist and Discovery feeds now keep the information needed for frontend
provider filtering.

Discovery is generated across all TMDB streaming providers available in the
configured region. Each enriched movie still exposes
`available_on_my_services`, so `media-tracker-card` can choose between:

- all regional streaming services
- only the user's selected providers

The TMDB movie watchlist itself is never modified by this display filter.


### v0.10.0 Oscars feed

A new `sensor.media_watch_oscars` exposes the latest Academy Awards Best
Picture slate using the same `items` feed contract as the other companion-card
sensors.

The initial feed contains the 98th Academy Awards (2026) Best Picture nominees,
with the winner identified separately. The Academy list is treated as the
award authority; TMDB is used to resolve localized media metadata and Swedish
streaming availability.

Watched and dismissed films are excluded. Movies already on the TMDB watchlist
remain visible and carry `on_watchlist: true`.


### v0.11.0 discovery profiles

New feeds:

- `sensor.media_watch_discovery` — general well-rated movie discovery
- `sensor.media_watch_personalized_movies` — recommendations aggregated from
  movie watchlist + locally watched movies
- `sensor.media_watch_discovery_tv` — general well-rated TV discovery
- `sensor.media_watch_personalized_tv` — recommendations aggregated from
  followed/watchlisted + locally watched TV shows

Discovery items expose localized `genres` and `genre_ids`. Genre selection is
a presentation/feed filter in Media Tracker Card so the same backend feed can
power several cards with different include/exclude rules.

Personalized ranking counts how many seed titles recommend the same candidate
and also weights higher-ranked recommendations. Watched, dismissed and already
watchlisted/followed titles are excluded.


### v0.12.0 backend discovery filtering

Discovery can now be constrained directly in the TMDB discover query.

Options:

- **Discovery provider scope**
  - `all`: all streaming providers in the configured region
  - `my`: only providers selected in Media Watch
- **Discovery pages**: 1–20 TMDB pages fetched before local filtering
- **Backend include genres**: comma-separated TMDB genre IDs
- **Backend exclude genres**: comma-separated TMDB genre IDs
- **Backend genre matching**: `any` or `all`

Backend filtering applies to both movie and TV general discovery feeds. The
card's interactive mood/provider/genre filters remain available as a second,
fast presentation-layer filter.

Example: fetch a much larger Sci-Fi/Fantasy candidate pool from TMDB:

```text
Discovery provider scope: all
Discovery pages: 15
Backend include genres: 878,14
Backend genre matching: any
```
