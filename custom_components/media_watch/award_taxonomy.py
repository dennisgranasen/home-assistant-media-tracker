
"""Generic award category taxonomy and provider-specific mappings."""

from __future__ import annotations

from typing import Any

GENERIC_MOVIE_CATEGORIES: list[dict[str, str]] = [
    {"value": "all", "label": "All categories"},
    {"value": "best_film", "label": "Best Film / Best Picture"},
    {"value": "director", "label": "Director"},
    {"value": "actor_lead", "label": "Actor – Leading"},
    {"value": "actress_lead", "label": "Actress – Leading"},
    {"value": "actor_supporting", "label": "Actor – Supporting"},
    {"value": "actress_supporting", "label": "Actress – Supporting"},
    {"value": "screenplay", "label": "Screenplay – Any"},
    {"value": "screenplay_original", "label": "Screenplay – Original"},
    {"value": "screenplay_adapted", "label": "Screenplay – Adapted"},
    {"value": "animated_film", "label": "Animated Film"},
    {"value": "international_film", "label": "International / Foreign-language Film"},
    {"value": "documentary", "label": "Documentary"},
    {"value": "cinematography", "label": "Cinematography"},
    {"value": "editing", "label": "Editing"},
    {"value": "production_design", "label": "Production / Art Design"},
    {"value": "costume_design", "label": "Costume Design"},
    {"value": "score", "label": "Original Score / Music"},
    {"value": "song", "label": "Original Song"},
    {"value": "sound", "label": "Sound"},
    {"value": "visual_effects", "label": "Visual Effects"},
]

GENERIC_TV_CATEGORIES: list[dict[str, str]] = [
    {"value": "all", "label": "All categories"},
    {"value": "drama_series", "label": "Drama Series"},
    {"value": "comedy_series", "label": "Comedy Series"},
    {"value": "limited_series", "label": "Limited / Anthology Series"},
    {"value": "tv_film", "label": "Television Film"},
    {"value": "actor_drama", "label": "Actor – Drama"},
    {"value": "actress_drama", "label": "Actress – Drama"},
    {"value": "actor_comedy", "label": "Actor – Comedy"},
    {"value": "actress_comedy", "label": "Actress – Comedy"},
    {"value": "actor_limited", "label": "Actor – Limited Series / TV Film"},
    {"value": "actress_limited", "label": "Actress – Limited Series / TV Film"},
    {"value": "supporting_actor", "label": "Supporting Actor"},
    {"value": "supporting_actress", "label": "Supporting Actress"},
    {"value": "directing", "label": "Directing"},
    {"value": "writing", "label": "Writing"},
]

# Each generic category maps to one or more normalized/source category names.
# Matching is case-insensitive and allows substring matching so adapters can
# preserve the exact historical source label while this taxonomy stays stable.
SOURCE_CATEGORY_ALIASES: dict[str, dict[str, list[str]]] = {
    "oscars": {
        "best_film": ["BEST PICTURE"],
        "director": ["DIRECTING"],
        "actor_lead": ["ACTOR IN A LEADING ROLE", "ACTOR"],
        "actress_lead": ["ACTRESS IN A LEADING ROLE", "ACTRESS"],
        "actor_supporting": ["ACTOR IN A SUPPORTING ROLE"],
        "actress_supporting": ["ACTRESS IN A SUPPORTING ROLE"],
        "screenplay": ["WRITING"],
        "screenplay_original": ["WRITING (ORIGINAL SCREENPLAY)"],
        "screenplay_adapted": ["WRITING (ADAPTED SCREENPLAY)"],
        "animated_film": ["ANIMATED FEATURE FILM"],
        "international_film": ["INTERNATIONAL FEATURE FILM", "FOREIGN LANGUAGE FILM"],
        "documentary": ["DOCUMENTARY FEATURE"],
        "cinematography": ["CINEMATOGRAPHY"],
        "editing": ["FILM EDITING"],
        "production_design": ["PRODUCTION DESIGN", "ART DIRECTION"],
        "costume_design": ["COSTUME DESIGN"],
        "score": ["MUSIC", "ORIGINAL SCORE"],
        "song": ["MUSIC (ORIGINAL SONG)", "ORIGINAL SONG"],
        "sound": ["SOUND"],
        "visual_effects": ["VISUAL EFFECTS"],
    },
    "guldbaggen": {
        "best_film": ["Bästa film", "Best Film"],
        "director": ["Bästa regi", "Best Director"],
        "actor_lead": ["Bästa manliga huvudroll", "Best Actor"],
        "actress_lead": ["Bästa kvinnliga huvudroll", "Best Actress"],
        "actor_supporting": ["Bästa manliga biroll", "Best Supporting Actor"],
        "actress_supporting": ["Bästa kvinnliga biroll", "Best Supporting Actress"],
        "screenplay": ["Bästa manus", "Best Screenplay"],
        "cinematography": ["Bästa foto", "Best Cinematography"],
        "editing": ["Bästa klippning", "Best Editing"],
        "production_design": ["Bästa scenografi", "Best Production Design"],
        "costume_design": ["Bästa kostymdesign", "Best Costume Design"],
        "score": ["Bästa originalmusik", "Best Original Score", "Best Music"],
        "sound": ["Bästa ljud", "Best Sound"],
        "visual_effects": ["Bästa visuella effekter", "Best Visual Effects"],
    },
    "bafta_film": {
        "best_film": ["Best Film"],
        "director": ["Director"],
        "actor_lead": ["Leading Actor"],
        "actress_lead": ["Leading Actress"],
        "actor_supporting": ["Supporting Actor"],
        "actress_supporting": ["Supporting Actress"],
        "screenplay_original": ["Original Screenplay"],
        "screenplay_adapted": ["Adapted Screenplay"],
        "screenplay": ["Screenplay"],
        "animated_film": ["Animated Film"],
        "documentary": ["Documentary"],
        "international_film": ["Film Not in the English Language"],
        "cinematography": ["Cinematography"],
        "editing": ["Editing"],
        "production_design": ["Production Design"],
        "costume_design": ["Costume Design"],
        "score": ["Original Score"],
        "sound": ["Sound"],
        "visual_effects": ["Special Visual Effects"],
    },
    "golden_globes_film": {
        "best_film": ["Best Motion Picture"],
        "director": ["Best Director"],
        "actor_lead": ["Best Performance by a Male Actor in a Motion Picture", "Best Actor"],
        "actress_lead": ["Best Performance by a Female Actor in a Motion Picture", "Best Actress"],
        "actor_supporting": ["Best Supporting Actor"],
        "actress_supporting": ["Best Supporting Actress"],
        "screenplay": ["Best Screenplay"],
        "animated_film": ["Best Motion Picture - Animated", "Best Animated"],
        "international_film": ["Best Motion Picture - Non-English Language", "Foreign Language"],
        "score": ["Best Original Score"],
        "song": ["Best Original Song"],
    },
    "hong_kong_film_awards": {
        "best_film": ["Best Film"],
        "director": ["Best Director"],
        "actor_lead": ["Best Actor"],
        "actress_lead": ["Best Actress"],
        "actor_supporting": ["Best Supporting Actor"],
        "actress_supporting": ["Best Supporting Actress"],
        "screenplay": ["Best Screenplay"],
        "cinematography": ["Best Cinematography"],
        "editing": ["Best Film Editing"],
        "production_design": ["Best Art Direction"],
        "costume_design": ["Best Costume"],
        "score": ["Best Original Film Score"],
        "song": ["Best Original Film Song"],
        "sound": ["Best Sound"],
        "visual_effects": ["Best Visual Effects"],
    },
    "emmys": {
        "drama_series": ["Outstanding Drama Series"],
        "comedy_series": ["Outstanding Comedy Series"],
        "limited_series": ["Outstanding Limited", "Outstanding Miniseries", "Anthology Series"],
        "tv_film": ["Outstanding Television Movie", "Outstanding Made for Television Movie"],
        "actor_drama": ["Lead Actor in a Drama"],
        "actress_drama": ["Lead Actress in a Drama"],
        "actor_comedy": ["Lead Actor in a Comedy"],
        "actress_comedy": ["Lead Actress in a Comedy"],
        "actor_limited": ["Lead Actor in a Limited", "Lead Actor in a Miniseries"],
        "actress_limited": ["Lead Actress in a Limited", "Lead Actress in a Miniseries"],
        "supporting_actor": ["Supporting Actor"],
        "supporting_actress": ["Supporting Actress"],
        "directing": ["Directing"],
        "writing": ["Writing"],
    },
    "bafta_tv": {
        "drama_series": ["Drama Series"],
        "comedy_series": ["Scripted Comedy", "Comedy"],
        "limited_series": ["Limited Drama", "Mini-Series"],
        "actor_drama": ["Leading Actor"],
        "actress_drama": ["Leading Actress"],
        "supporting_actor": ["Supporting Actor"],
        "supporting_actress": ["Supporting Actress"],
    },
    "golden_globes_tv": {
        "drama_series": ["Best Television Series - Drama", "Best TV Series - Drama"],
        "comedy_series": ["Best Television Series - Musical or Comedy", "Best TV Series - Musical or Comedy"],
        "limited_series": ["Best Television Limited Series", "Limited Series, Anthology Series or Motion Picture Made for Television"],
        "actor_drama": ["Male Actor in a Television Series - Drama", "Best Actor - Television Series Drama"],
        "actress_drama": ["Female Actor in a Television Series - Drama", "Best Actress - Television Series Drama"],
        "actor_comedy": ["Male Actor in a Television Series - Musical or Comedy"],
        "actress_comedy": ["Female Actor in a Television Series - Musical or Comedy"],
        "actor_limited": ["Male Actor in a Limited Series", "Actor in a Miniseries"],
        "actress_limited": ["Female Actor in a Limited Series", "Actress in a Miniseries"],
        "supporting_actor": ["Supporting Male Actor on Television", "Supporting Actor"],
        "supporting_actress": ["Supporting Female Actor on Television", "Supporting Actress"],
    },
}


def generic_categories(media_type: str) -> list[dict[str, str]]:
    """Return generic categories for movie or TV."""
    return (
        list(GENERIC_TV_CATEGORIES)
        if media_type == "tv"
        else list(GENERIC_MOVIE_CATEGORIES)
    )


def aliases_for(source: str, generic_category: str) -> list[str]:
    """Return source-specific aliases for one generic category."""
    if generic_category == "all":
        return ["all"]
    return SOURCE_CATEGORY_ALIASES.get(source, {}).get(generic_category, [])


def category_matches(
    source: str,
    generic_category: str,
    source_category: str,
) -> bool:
    """Return whether a source category belongs to a generic category."""
    if generic_category == "all":
        return True

    candidate = source_category.casefold()
    for alias in aliases_for(source, generic_category):
        alias_folded = alias.casefold()
        if alias_folded == candidate or alias_folded in candidate:
            return True
    return False


def resolve_generic_category_options(
    source: str,
    media_type: str,
    source_options: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Only expose generic categories that can map to this source's data."""
    available = [
        str(option.get("value", ""))
        for option in source_options
        if option.get("value") != "all"
    ]

    result: list[dict[str, str]] = [
        {"value": "all", "label": "All categories"}
    ]
    for option in generic_categories(media_type):
        value = option["value"]
        if value == "all":
            continue
        if any(category_matches(source, value, category) for category in available):
            result.append(option)
    return result


def resolve_source_categories(
    source: str,
    generic_category: str,
    source_options: list[dict[str, str]],
) -> list[str]:
    """Translate one generic category into actual provider category values."""
    if generic_category == "all":
        return ["all"]
    return [
        str(option["value"])
        for option in source_options
        if option.get("value") != "all"
        and category_matches(
            source,
            generic_category,
            str(option["value"]),
        )
    ]
