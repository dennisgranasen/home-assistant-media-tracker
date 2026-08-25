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
are also excluded from award/discovery queues and remain available through the
dedicated watchlist feed.


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


### v0.12.1 discovery genre feed fix

Fixed `sensor.media_watch_discovery` dropping `genre_ids` and `genres` from
its `items` attribute. The coordinator already had the data, but the feed
adapter omitted it, causing every card-side mood/genre filter to return an
empty list.


### v0.12.2 responsive actions

Media Watch service actions no longer block while a full coordinator refresh
runs. The durable local/TMDB mutation is completed first, then the expensive
coordinator refresh is scheduled in the background.

This is especially important now that a refresh can include movie/TV
discovery, personalized recommendations, provider metadata and Oscars data.


### v0.13.0 dynamic discovery profiles

Discovery is no longer limited to one global queue. Add any number of named
profiles under **Options → Discovery profiles**. Every profile becomes its own
sensor and uses the common `items` feed contract.

Profile filters include:

- movie or TV
- general discovery or personalized recommendations
- awards filter (currently Oscars 2026 Best Picture)
- all regional providers or only selected providers
- minimum TMDB rating and vote count
- include/exclude TMDB genre IDs with ANY/ALL matching
- release date range
- sort order
- TMDB page depth and feed size

Examples:

- `Oscar Rom-Coms`: movie + Oscars + Comedy/Romance (ALL) + rating >= 5
- `Modern Horror`: movie + Horror + released >= 2020-01-01
- `Top Rated`: movie + rating >= 8.5 + rating sort

Sensors use the profile name and a stable unique ID based on the profile ID.
Changing options reloads the integration so newly added/removed profile
entities are created/removed automatically.

The older fixed discovery sensors remain for backwards compatibility.


### v0.14.0 historical awards filters

Dynamic discovery profiles can now use the full Academy Awards history rather
than a single hard-coded ceremony.

Oscar data is loaded from `DLu/oscar_data`, a curated dataset derived from the
official Academy Awards Database and containing IMDb title IDs. Media Watch
uses those IMDb IDs to resolve films through TMDB and then applies the normal
language, provider, genre and rating enrichment.

Award profile fields:

- **Awards**: none / Academy Awards (Oscars)
- **Awards quick list**:
  - latest Oscars – all winners
  - latest Oscars – all nominated films
  - all Best Picture winners
  - all Best Picture nominees
  - custom
- **Award category**: canonical Academy category, e.g. `BEST PICTURE`, or `all`
- **Award status**:
  - nominated or winner
  - winner
  - nominated, no win
  - nominated + at least one win
- **Award year from / to**

Award results are collapsed to films before filtering. This enables queries
such as:

- every Oscar-nominated film from 2001 onward
- every film from 1980–1994 that was nominated and won at least one Oscar
- all Best Picture winners, further filtered by streaming provider
- Oscar-nominated Romance+Comedy films with TMDB rating >= 5

The Academy's "Award Year" convention is retained. For example, the 98th
ceremony held in March 2026 is the Academy's 2025 award year.

The historical source is downloaded once per Home Assistant process and then
cached in memory; it is not re-downloaded on each coordinator refresh.


### v0.14.1 award-aware profile UI

Discovery profile configuration is now a multi-step flow:

1. Name, media type and discovery source
2. Award source
3. Award-specific filters
4. Ordinary discovery filters

Award sources are filtered by media type before they are shown. Award
categories are loaded from the selected provider itself, so users cannot
accidentally choose an Oscar category for a TV-only award or a category that
does not exist in the backing historical dataset.

The implementation introduces an award-provider registry. Future Guldbaggen,
BAFTA, Golden Globes and Emmy adapters can provide their own media-type
capabilities and category lists without changing the discovery-profile UI.
Only award providers with a working backend adapter are exposed to users.


### v0.14.2 award adapter SDK

Only the Oscars adapter is currently implemented.

A formal `AwardAdapter` interface and registry are now included, together with
`AWARD_ADAPTERS.md`, which documents how to add new award sources. Config flow
continues to expose only registered, working adapters.

### v0.15.0 award adapters

Implemented and registered award adapters:

- Academy Awards (Oscars) — movies
- Guldbaggen — movies
- BAFTA Film Awards — movies
- BAFTA Television Awards — TV
- Golden Globes — separate Film and Television adapters
- Primetime Emmy Awards — TV
- Festival de Cannes — movies; Official Selection/In Competition is normalized
  as nomination/selection, festival prizes as wins

All web-backed adapters use the award organizations' official archive pages and
share an in-process HTTP cache. Award profile results are resolved to TMDB by
IMDb ID where available, otherwise by candidate title and award-year proximity.

Source web formats differ. The adapters intentionally isolate that parsing from
the discovery engine so source-specific changes can be fixed without changing
profile sensors or Lovelace cards.


### v0.15.1 Hong Kong Film Awards

Added a film award adapter for the Hong Kong Film Awards using the official
HKFAA historical archive. It participates in the same dynamic award profile
UI and can be combined with year ranges, categories, winner/nominee status,
ratings, genres and provider filters.


## Google TV / Android TV development track

A future TV integration is documented in
[`docs/GOOGLE_TV_INTEGRATION.md`](docs/GOOGLE_TV_INTEGRATION.md).

The proposed architecture keeps Media Watch as the source of recommendation
logic and watched state, with a thin Android TV bridge capable of targeting
both legacy TvProvider/Preview Channels and Google Engage. This work is
deliberately not part of the current runtime integration.


### v0.16.0 discovery entities and category taxonomy

Each configured discovery profile is a dedicated Home Assistant sensor.

The sensor:

- has a stable unique ID based on the config entry and profile ID
- suggests an object ID such as `sensor.media_watch_modern_horror`
- uses the queue length as its sensor state
- exposes the card payload in the common `items` attribute
- exposes profile/media/award metadata as attributes

Example:

```yaml
type: custom:media-tracker-card
entity: sensor.media_watch_modern_horror
title: Modern Horror
```

Award category configuration now supports two category modes:

1. **Generic category** — choose a stable Media Watch concept such as Best
   Film, Director, Screenplay, Drama Series or Comedy Series. Media Watch maps
   that concept to the selected award provider's actual category value(s).
2. **Award-specific category** — choose directly from the selected adapter's
   category dropdown.

The award-specific list is always loaded from the selected adapter. The generic
list is reduced to concepts that can actually map to categories exposed by that
adapter.


### v0.16.1 TMDB genre selectors

Discovery/recommendation profiles no longer require users to type TMDB genre
names or IDs.

After the profile media type has been selected, Media Watch requests the
appropriate TMDB genre catalogue and displays localized multi-select dropdowns
for:

- Include genres
- Exclude genres

The UI displays names such as `Horror`, `Romance` or their localized
equivalents while the profile stores stable TMDB genre IDs internally.

Movie and TV genre catalogues are fetched separately. This avoids incorrect
cross-media assumptions such as movie `Science Fiction` (878) versus TV
`Sci-Fi & Fantasy` (10765).

Legacy profiles that contain comma-separated genre IDs remain compatible and
are normalized into the new selector values when edited.


### v0.16.2 genre selector fix

Fixed an options-flow crash introduced in v0.16.1. Home Assistant selector
options are mapping-like values, so genre option IDs must be read using
`option["value"]` rather than `option.value`.

This affected opening the ordinary discovery-filter step after configuring
award filters.


### v0.16.3 HKFAA configuration fix

Hardened the Hong Kong Film Awards adapter and award profile configuration:

- fixes parsing of bilingual HKFAA category headings by preserving table-cell
  line boundaries
- sends normal browser-style request headers to official award sites
- uses the HKFAA built-in category catalogue if the current archive page is
  unavailable or cannot be parsed
- prevents an award provider/category lookup failure from crashing the Home
  Assistant options flow
- keeps "All categories" available as a safe fallback

This specifically fixes failures while creating a Hong Kong Film Awards
discovery profile.


### v0.16.4 award resolver call fix

Fixed award-backed discovery queues crashing because a stale `media_type=`
keyword was still passed to `_award_profile_candidates()`. Media type is now
derived from the profile inside the resolver.

The profile flow text now explicitly presents the configuration as three
stages: profile basics, optional award constraints, and final discovery
filters.


### v0.16.5 award resolver and profile UX cleanup

Fixed the award-backed discovery crash by removing the stale `award_source=` keyword from `_award_profile_candidates()`. Media type and award source are both read directly from the profile.

The General options page no longer shows the legacy global discovery filters. Rating, votes, genres, provider scope, pages and queue size are configured per Discovery profile. Existing legacy option values are retained internally for backwards compatibility with the older fixed discovery sensors.


### v0.17.0 profile-only discovery

Removed the legacy global discovery model.

Discovery is now exclusively profile-based:

- no global discovery rating/genre/provider/page/limit settings
- no fixed `Discovery`, `TV discovery`, `Personalized movies`,
  `Personalized TV`, `Movie discovery` or legacy Oscars discovery sensors
- no global movie/TV Discover API calls on every coordinator refresh
- each configured Discovery profile remains its own Home Assistant entity
- personalized recommendation candidate pools are generated only when one or
  more personalized profiles actually exist, and their size is derived from
  those profiles' own limits

Global integration options are now reserved for truly shared settings such as
TMDB language/region, selected streaming providers and episode-calendar
behavior.

Existing profile entities and their stable unique IDs are unchanged.


### v0.17.1 year-based release filters

Discovery profiles now use release years rather than full dates.

Fields:

- **Release year from** — integer, 1900 through the current year
- **Release year to** — integer, 1900 through the current year
- **Maximum age in years (rolling)** — optional dynamic lower bound

Example:

```text
Maximum age in years: 3
```

In 2026 this means release year >= 2023. In 2027 the same profile
automatically means release year >= 2024.

If both an absolute `Release year from` and a rolling maximum age are set, the
stricter (newer) lower bound wins.

TMDB still receives proper API date bounds internally (`YYYY-01-01` and
`YYYY-12-31`); the user-facing profile is year-based.

Legacy `YYYY-MM-DD` profile values are read safely by extracting their year
and are removed when the profile is next edited.


### v0.17.2 award TMDB resolution fix

Fixed empty award-backed discovery queues.

The generic award resolver called `_resolve_award_title()` with `source` and
`media_type` in the wrong order. For an Oscars movie profile this effectively
became:

```text
media_type = "oscars"
award_source = "movie"
```

so IMDb IDs were resolved against TMDB TV results instead of movie results and
valid films disappeared from the queue.

The argument order is corrected and the resolver now rejects invalid media
types explicitly instead of silently producing an empty feed.


### v0.17.3 award-provider pipeline hardening

All award providers share the same award-to-TMDB resolver. The argument-order
bug fixed in v0.17.2 therefore affected every registered award source, not just
Oscars.

The resolver is now called with explicit keyword arguments:

```python
_resolve_award_title(
    item,
    media_type=media_type,
    award_source=source,
)
```

This prevents future positional swaps between media type and award source.

The registered adapter set is statically checked during development:
Oscars, Guldbaggen, BAFTA Film, BAFTA Television, Golden Globes Film,
Golden Globes Television, Primetime Emmy, Cannes and Hong Kong Film Awards.

Discovery profile sensors also expose award category/status/year diagnostics as
top-level attributes, making empty award queues easier to debug.


### v0.17.4 optional year selector fix

Fixed Home Assistant options-flow validation errors such as:

```text
expected float
```

The optional release-year and rolling-age NumberSelector fields no longer
receive `None` as a default value. When unset, the schema now omits the default
entirely, so Home Assistant treats the fields as genuinely optional.

This affects:

- Release year from
- Release year to
- Maximum age in years (rolling)


### v0.17.5 release-year helper regression fix

Fixed:

```text
'MediaWatchCoordinator' object has no attribute
'_profile_release_date_gte'
```

The release-year-to-TMDB conversion helpers are now explicitly present on the
coordinator and validated during packaging:

- `_profile_release_year_from`
- `_profile_release_date_gte`
- `_profile_release_date_lte`
- `_parse_optional_year`
- `_parse_optional_int`


### v0.17.6 coordinator consistency audit

Fixed the missing `_year_from_date()` helper introduced during the release-year
refactor.

A static consistency audit is now performed during development against
`MediaWatchCoordinator`:

- every local `self._...()` call must resolve to a method on the coordinator
- calls to local methods are checked for unsupported keyword arguments
- legacy date fields are not written by the current options flow
- Python and JSON files are compiled/parsed before packaging

This audit also re-checks the recent award resolver and release-year helper
changes so missing-method regressions are caught before packaging.


### v0.17.8 actual coordinator hotfix

This release is built using the exact `coordinator.py` supplied from the
installed v0.17.6 instance.

That file called `_year_from_date()` from `_profile_post_filter()` but did not
define `_year_from_date()` on `MediaWatchCoordinator`.

The helper is now added directly to the class. The final packaged coordinator
is AST-checked so that:

- every `self._...()` call resolves to a class method or known inherited method
- internal keyword arguments match the target method signatures
- all release-year helper methods are direct members of `MediaWatchCoordinator`


### v0.17.9 watched-profile toggle and movie credits

- Discovery profiles have an **Exclude watched titles** switch. It remains
  enabled by default; disabling it lets watched titles remain in the profile
  sensor with `watched: true` so compatible cards can unmark them.
- Movie profile items expose the release date, director names and the first
  three credited cast members. Credits are appended to the existing TMDB movie
  details request, so this does not add another request per title.
- The same existing movie-details response also supplies `runtime`, localized
  `tagline`, `original_language`, `production_countries` and collection/
  franchise metadata to movie profile and watchlist feeds.
- Award-backed profile items expose a compact `award_summary` containing total
  nominations and wins, winner state, organizations, years, categories and
  winning categories. It is derived from the existing `award`/`awards` data
  and performs no additional award or TMDB requests.
