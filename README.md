# Home Assistant Media Tracker

A HACS-installable Home Assistant custom integration for tracking movies and TV shows with TMDB.

## Current features

- Authenticate a TMDB account using TMDB's user session flow.
- Use the TMDB movie watchlist as the movie queue and the TMDB TV watchlist as
  the list of followed shows.
- Search, follow, remove, dismiss, mark watched and restore media through Home
  Assistant actions.
- Track movie/TV watched state and per-episode TV progress locally.
- Create any number of movie or TV discovery profiles, each with its own sensor.
- Build general TMDB discovery, personalized recommendation and historical
  award queues.
- Filter profiles by providers, rating, votes, genres, release year, rolling
  age, sort order and queue size.
- Query one award organization or combine all compatible organizations with
  **Any award organization**.
- Expose localized titles, English fallback titles, credits, streaming
  availability, award facts and UI-ready badges in feed attributes.
- Start core entities before slow discovery/award work and update discovery
  profiles independently in the background.

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

## Configuration

Open **Settings → Devices & services → Media Watch → Configure**.

Shared options:

- **Use TMDB profile language**: use the authenticated account locale when it
  is available.
- **Language**: manual TMDB locale, for example `sv-SE`, used when profile
  language is disabled or unavailable.
- **Fallback language**: secondary metadata locale; defaults to `en-US`.
- **Region**: TMDB watch-provider region, for example `SE`.
- **Streaming providers**: subscriptions used by the **My providers** profile
  scope and `available_on_my_services`.
- **Upcoming limit**: number of episodes in the default next-upcoming feed.

Rating, genre, release-year, provider-depth and queue-size settings are not
global. They belong to each discovery profile.

### Discovery profiles

Under **Configure → Discovery profiles**, choose **Add profile**, **Edit** or
**Delete**. Creating or editing a profile has four stages:

1. Name, movie/TV media type and source: general discovery or personalized.
2. Optional award organization.
3. Award preset, category, status and award-year range when awards are enabled.
4. Provider, watched, rating, genre, release-year, sorting, page-depth and
   result-limit filters.

Each saved profile creates one sensor with a stable unique ID and an entity-ID
suggestion based on the profile ID, for example
`sensor.media_watch_modern_horror`. The sensor state is the number of items;
the actual queue is in its `items` attribute.

Profile filters:

- **Provider scope**: every streaming provider in the configured region, or
  only the subscriptions selected in the shared options.
- **Exclude watched titles**: enabled by default. Disable it to retain watched
  titles with `watched: true` for UI-side filtering or unmarking.
- **Minimum rating / votes**: TMDB vote thresholds.
- **Include / exclude genres**: localized TMDB multi-select lists. Included
  genres can match any or all selected values.
- **Release year from / to**: absolute year bounds.
- **Maximum age in years**: rolling lower bound. In 2026, `5` means 2021 and
  newer; the bound advances automatically each year.
- **Sort order**: popularity, rating, votes, newest or oldest.
- **TMDB pages**: 1–20 source pages.
- **Limit**: 1–200 visible items.

Award years, release years and maximum age use numeric selectors. Empty values
are genuinely optional and remain valid when an existing profile is edited.

The integration resolves additional candidates until it has filled the limit
after exclusions where the backing source contains enough results. Movies or
shows already on the corresponding TMDB watchlist, and locally dismissed
titles, never appear in discovery profiles. Watched titles are also excluded
unless **Exclude watched titles** is explicitly disabled.

### Award profiles

Registered award sources:

| Source | Movies | TV |
|---|:---:|:---:|
| Academy Awards (Oscars) | Yes | |
| Guldbaggen | Yes | |
| BAFTA Film Awards | Yes | |
| BAFTA Television Awards | | Yes |
| Golden Globes – Film | Yes | |
| Golden Globes – Television | | Yes |
| Primetime Emmy Awards | | Yes |
| Festival de Cannes | Yes | |
| Hong Kong Film Awards | Yes | |

**Any award organization** queries every registered adapter compatible with
the selected media type. Its generic categories—such as Best Film, Director
or Screenplay—are mapped to each organization's own category vocabulary. When
one organization is selected, the category list comes directly from that
adapter.

Available presets are custom, latest winners, latest nominees/selections,
all top-film-category winners and all top-film-category nominees. Status can
be nominated or winner, winner only, nominated without a win, or nominated
and winner. Status is evaluated within the selected category rather than from
unrelated wins for the same film.

Award items expose `award`; combined results also expose `awards`. The compact
`award_summary` contains totals, winner state, organizations, years,
categories, winning categories, recipients and badge metadata. Organization
source IDs are retained for stable logic, while display fields use registered
labels such as `Golden Globes – Film` and `Hong Kong Film Awards`.

Top-film awards from all compatible movie adapters are also attached to films
after they move into the Watchlist. A failure in one adapter does not suppress
facts from the others.

## Entities

Every entry creates these core sensors:

- `sensor.media_watch_movie_watchlist`
- `sensor.media_watch_following_tv`
- `sensor.media_watch_upcoming_episodes`
- `sensor.media_watch_next_episodes_to_watch`
- `sensor.media_watch_next_upcoming_episodes`
- `sensor.media_watch_episodes_today`
- `sensor.media_watch_episodes_next_7_days`
- `sensor.media_watch_episodes_next_30_days`
- `sensor.media_watch_episodes` (`items` feed)
- `sensor.media_watch_watchlist` (`items` feed)
- `sensor.media_watch_upcoming_media_card` (compatibility feed)

In addition, every discovery profile creates one `items` feed sensor. There is
no fixed global discovery, personalized or Oscars sensor in the current
profile-only model.

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
- `media_watch.mark_episode_watched`
- `media_watch.mark_episode_unwatched`
- `media_watch.mark_seasons_watched`
- `media_watch.mark_seasons_unwatched`
- `media_watch.upcoming_episodes` (returns response data)
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

`follow` also clears local watched/dismissed state so the title becomes visible
again. `unfollow` removes a movie or show from TMDB without marking it watched.
`mark_watched` records local watched state and removes the title from TMDB.
`dismiss` only hides it from Media Watch discovery.

## Feed data

The dedicated Watchlist, Episodes and discovery-profile sensors use one common
`items` attribute. Their numeric sensor state is the item count.

Movie items can contain:

- identity: `tmdb_id`, `imdb_id`, `media_type`, `source`
- titles: localized `title`, fallback-language `fallback_title`, and TMDB
  `original_title`
- release and popularity: `release_date`, `vote_average`, `vote_count`
- descriptive metadata: `overview`, `tagline`, `runtime`, genres, production
  countries and collection/franchise
- credits: `directors`, `writers` and the first three credited cast members
- artwork and links: `poster`, `deep_link`
- availability: `providers`, `provider_details`,
  `available_on_my_services`
- local state: `watched` and, where relevant, `dismissed`
- awards: `award`, optional `awards`, and `award_summary`

For a Swedish-language configuration, a Swedish original such as
`Utvandrarna` remains the primary `title`; `The Emigrants` is exposed as
`fallback_title`. A translated Swedish title such as `Konklaven` is likewise
primary while `Conclave` is the fallback. This logic is shared by Watchlist
and every movie discovery profile; it does not depend on which queue found the
film.

Episode feed items include the show title and TMDB ID, season and episode
numbers, episode code/name, air date, runtime, overview, poster, providers and
TMDB link.

Hong Kong Film Awards records use official English person aliases when the
archive supplies them. Remaining Chinese director, writer and cast names are
resolved through cached English TMDB aliases when available.

## Queue and refresh behavior

- Core watchlist and TV entities are registered on the first refresh. Slow
  discovery and external award work starts afterward in Home Assistant
  background tasks.
- Discovery profiles are built and published independently. A slow or failing
  profile does not hold back successful queues, and the last successful result
  remains available across a later profile failure.
- Coordinator data refreshes every three hours and can also be refreshed with
  `media_watch.refresh`.
- TMDB requests are limited to four concurrent calls. HTTP 429 responses are
  retried up to three times, honoring `Retry-After` when TMDB provides it.
- Parsed award pages and adapter instances have a six-hour in-memory lifetime.
  They are cleared when the last Media Watch entry unloads.
- Watchlist award enrichment runs in the background. Successful award sources
  are published even if another adapter fails and is scheduled for retry.

## Data sources

Movie, TV and watch-provider metadata is supplied by TMDB. TMDB watch-provider data is powered by JustWatch.

Award history comes from the registered adapters' datasets or official
organization archives. See [AWARD_ADAPTERS.md](AWARD_ADAPTERS.md) for the
adapter contract and source-specific implementation notes.

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

The compatibility sensor exposes the configured number of next scheduled
episodes (one current next-to-air entry per followed show), sorted by air date.
It includes TMDB posters, episode code/title, provider information and TMDB ID.
The separate today, 7-day and 30-day sensors are calendar windows and can
contain more than one episode from the same show.

The integration itself does not bundle or copy Upcoming Media Card. It only
produces its expected sensor data format, keeping the projects independently
updatable through HACS.


## Media Tracker Card

Use `sensor.media_watch_episodes`, `sensor.media_watch_watchlist` and the
individual discovery-profile sensors as companion `media-tracker-card` feeds.
All expose `items` with provider IDs/logo paths and the action parameters
needed by the card.

The card is maintained in a separate repository and is not bundled with this
integration. Presentation-only filtering belongs in the card; queue
membership, watchlist/dismissed exclusion and profile filters are handled by
this integration.

## Local testing without Home Assistant

The repository includes isolated tests with minimal Home Assistant stubs, so
most coordinator, award-adapter, parser and configuration consistency checks
can run without starting a Home Assistant instance:

```bash
python3 -m pytest -q
python3 scripts/check_service_registrations.py
```

The test suite also performs static AST checks for unresolved private
coordinator calls, unsupported keyword arguments, config-flow/profile field
drift and award-adapter interface mismatches. A real Home Assistant test
instance is still appropriate for end-to-end config-flow, entity-registry and
dashboard-card validation.
