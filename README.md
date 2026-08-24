# Home Assistant Media Tracker

A HACS-installable Home Assistant custom integration for tracking movies and TV shows with TMDB.

## Current features

- Authenticate a TMDB account using TMDB's user session flow.
- Read movie and TV watchlists from TMDB.
- Treat TV shows on the TMDB watchlist as followed shows.
- Expose the next episode to air for followed shows.
- Discover highly rated movies available from selected streaming providers in a configured region.
- Store `watched` and `dismissed` state locally in Home Assistant.
- Marking an item watched removes it from the TMDB watchlist and keeps the local watched history so it is not rediscovered.
- Configure provider IDs, minimum rating, vote threshold and discovery limit in the UI.

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

- `media_watch.mark_watched`
- `media_watch.mark_unwatched`
- `media_watch.dismiss`
- `media_watch.undismiss`
- `media_watch.refresh`

## Scope of v0.1.0

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
