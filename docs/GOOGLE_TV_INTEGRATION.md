# Development Track: Google TV / Android TV Integration

Status: **Future development track — not implemented**

This document captures a possible future path for exposing Media Watch feeds
on Android TV / Google TV home-screen surfaces.

The goal is to keep this work separate from the core Home Assistant integration
until the platform constraints and deployment model are proven.

## Goals

Potential end-state capabilities:

- expose selected Media Watch discovery profiles as TV home-screen rows
- expose "next episode to watch" / watchlist / continue-watching data
- reuse the existing Media Watch feed/profile model
- keep recommendation logic in Home Assistant
- make the TV component as thin as possible
- support more than one TV integration backend where practical

Example mapping:

```text
Media Watch profile: "Oscar winners"
    -> TV home-screen recommendation row

Media Watch profile: "Modern horror"
    -> TV home-screen recommendation row

Media Watch episode queue
    -> Continue Watching / Watch Next-style surface
```

## Proposed architecture

```text
Home Assistant
└── Media Watch
    ├── discovery profiles
    ├── episode queue
    ├── watchlist
    └── watched state
          |
          | local API / WebSocket
          v
Android TV / Google TV bridge app
          |
          +--> Android TV TvProvider backend
          |    ├── PreviewChannel
          |    ├── PreviewProgram
          |    └── WatchNextProgram
          |
          +--> Google Engage backend
               ├── Recommendation clusters
               └── Continuation cluster
```

The Android app should contain no recommendation algorithm. It should consume
already-resolved Media Watch feeds and translate them into platform-specific
TV entities.

## Backend A: Android TV TvProvider

Android TV provides the `TvContract` / `androidx.tvprovider` APIs for apps to
publish home-screen channels and programs.

Possible Media Watch mapping:

```text
Media Watch discovery profile
    -> PreviewChannel

Media Watch feed item
    -> PreviewProgram

Media Watch next episode / continue item
    -> WatchNextProgram
```

Advantages:

- does not depend on the Google Engage developer program
- suitable for sideloaded/private Android TV applications
- simple mapping from Media Watch profiles to channels
- useful on launchers that expose app-defined Preview Channels

Important limitation:

Google TV's launcher is not guaranteed to expose these app-created channels in
the same way as the classic Android TV launcher.

Therefore support must be tested on actual Google TV hardware before investing
in a complete implementation.

## Backend B: Google Engage for TV

Engage is Google's newer mechanism for contributing app content to Google TV
recommendation and continuation surfaces.

Potential mapping:

```text
Media Watch discovery profile
    -> Engage RecommendationCluster

Media Watch watchlist
    -> ContinuationCluster / WATCHLIST

Media Watch current episode
    -> CONTINUE

Media Watch next unwatched episode
    -> NEXT

Newly released next episode
    -> NEW
```

Advantages:

- native integration with Google TV recommendation surfaces
- semantics map closely to the existing Media Watch model
- could expose Media Watch feeds directly on the Google TV home screen

Constraints:

- production access is controlled by Google's Engage developer program
- a private/sideloaded bridge app may not qualify for production surfaces
- Engage must therefore remain optional and must not be a dependency of the
  Media Watch core integration

Development and verification can still be useful before production approval.

## Media Watch export contract

Before building a TV bridge, Media Watch should expose a small, generic export
format that is independent of Android/Google APIs.

Example:

```json
{
  "profiles": [
    {
      "id": "modern_horror",
      "name": "Modern Horror",
      "media_type": "movie",
      "items": [
        {
          "tmdb_id": 123,
          "title": "Example",
          "poster": "...",
          "backdrop": "...",
          "overview": "...",
          "release_date": "2025-10-31",
          "providers": [],
          "deep_links": {}
        }
      ]
    }
  ],
  "continuation": [
    {
      "media_type": "tv",
      "tmdb_id": 456,
      "title": "Example Show",
      "season": 2,
      "episode": 4,
      "watch_next_type": "NEXT"
    }
  ]
}
```

This API should be useful beyond Google TV, for example:

- alternative Android TV launchers
- Apple TV companion integrations
- wall displays
- mobile clients
- future media-center integrations

## Deep links

The bridge should prefer opening the actual streaming destination when
possible.

Priority:

1. provider-specific deep link
2. Android app intent / universal link
3. Media Watch detail screen
4. TMDB page as a final fallback

Deep-link support should be implemented independently from Engage/TvProvider.

## Security

The TV bridge should not require a full Home Assistant long-lived access token.

Preferred options:

- purpose-specific Media Watch API token
- short-lived signed token
- Home Assistant application credentials / OAuth if practical
- pairing flow between TV and Home Assistant

The export API should be read-only unless an explicit interaction feature is
added later.

If TV actions are added, such as:

```text
Mark watched
Dismiss
Add to watchlist
```

they should use a narrowly-scoped write API.

## Synchronization

Suggested bridge behavior:

- WorkManager periodic sync
- immediate refresh when the app starts
- optional push/WebSocket update while the bridge is active
- local cache so home-screen entries remain available if Home Assistant is
  temporarily unreachable

Home Assistant remains the source of truth.

## Phase 0: feasibility test

Do this before building the real bridge app.

Create a minimal Android TV APK that:

1. creates one `PreviewChannel`
2. adds three hard-coded `PreviewProgram` entries
3. requests channel visibility/browsability where supported
4. is sideloaded onto the target Google TV device
5. verifies whether the stock Google TV launcher shows the row

Example test content:

```text
Media Watch Test
├── Blade Runner
├── Alien
└── The Godfather
```

Decision:

- if the Google TV launcher exposes the channel, continue with TvProvider
- if it does not, retain TvProvider for compatible Android TV launchers and
  treat Engage as the Google TV-specific path

## Phase 1: generic Media Watch export API

Add a small read-only API endpoint exposing:

- selected discovery profiles
- poster/backdrop URLs
- title metadata
- provider/deep-link data
- episode queue
- watchlist/continuation metadata

Do not expose every internal coordinator field.

## Phase 2: Android TV bridge

Build a minimal Kotlin application with:

- pairing/configuration
- Media Watch API client
- local cache
- TvProvider publisher
- WorkManager sync
- no duplicate discovery logic

## Phase 3: Engage backend

Only after the bridge architecture is stable:

- add `engage-tv`
- map feeds to recommendation clusters
- map episode/watchlist state to continuation entities
- validate with Google's Engage verification tooling
- pursue developer-program production access if eligibility permits

## Phase 4: optional TV actions

Possible later actions:

- mark movie watched
- mark episode watched
- add/remove watchlist
- dismiss recommendation

These should call Media Watch rather than maintaining separate TV-side state.

## Non-goals

The bridge should not:

- scrape Google TV recommendations
- modify Google's own recommendation model
- duplicate TMDB discovery logic
- become required for normal Media Watch operation
- store an independent canonical watched history

## Current decision

This track is intentionally deferred.

The Media Watch core should continue to focus on:

- discovery profiles
- watch progress
- recommendations
- awards
- provider filtering
- stable Home Assistant entities/actions

The TV bridge can be developed later without changing those core concepts.
