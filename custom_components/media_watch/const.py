"""Constants for Media Watch."""

from datetime import timedelta

DOMAIN = "media_watch"

CONF_ACCESS_TOKEN = "access_token"
CONF_ACCOUNT_ID = "account_id"
CONF_SESSION_ID = "session_id"
CONF_USERNAME = "username"

CONF_REGION = "region"
CONF_LANGUAGE = "language"
CONF_FALLBACK_LANGUAGE = "fallback_language"
CONF_USE_PROFILE_LANGUAGE = "use_profile_language"
CONF_PROVIDERS = "providers"
CONF_MIN_RATING = "min_rating"
CONF_MIN_VOTES = "min_votes"
CONF_DISCOVERY_LIMIT = "discovery_limit"
CONF_UPCOMING_LIMIT = "upcoming_limit"

DEFAULT_REGION = "SE"
DEFAULT_LANGUAGE = "sv-SE"
DEFAULT_FALLBACK_LANGUAGE = "en-US"
DEFAULT_USE_PROFILE_LANGUAGE = True
DEFAULT_MIN_RATING = 7.5
DEFAULT_MIN_VOTES = 1000
DEFAULT_DISCOVERY_LIMIT = 30
DEFAULT_UPCOMING_LIMIT = 5

DEFAULT_PROVIDER_NAMES = {
    "Netflix",
    "Disney Plus",
    "Max",
    "Viaplay",
    "SVT",
    "TV 4 Play",
    "TV4 Play",
}

UPDATE_INTERVAL = timedelta(hours=3)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.storage"

SERVICE_MARK_WATCHED = "mark_watched"
SERVICE_MARK_UNWATCHED = "mark_unwatched"
SERVICE_DISMISS = "dismiss"
SERVICE_UNDISMISS = "undismiss"
SERVICE_REFRESH = "refresh"
SERVICE_SEARCH = "search"
SERVICE_FOLLOW = "follow"
SERVICE_UNFOLLOW = "unfollow"
SERVICE_MARK_EPISODE_WATCHED = "mark_episode_watched"
SERVICE_MARK_EPISODE_UNWATCHED = "mark_episode_unwatched"
SERVICE_MARK_SEASONS_WATCHED = "mark_seasons_watched"
SERVICE_MARK_SEASONS_UNWATCHED = "mark_seasons_unwatched"
SERVICE_UPCOMING_EPISODES = "upcoming_episodes"

ATTR_MEDIA_TYPE = "media_type"
ATTR_TMDB_ID = "tmdb_id"
ATTR_QUERY = "query"
ATTR_LIMIT = "limit"
ATTR_SEASON = "season"
ATTR_EPISODE = "episode"
ATTR_SEASONS = "seasons"
ATTR_ALL_SEASONS = "all_seasons"
ATTR_DAYS = "days"


# 98th Academy Awards (2026), honoring films released in 2025.
# Source: Academy of Motion Picture Arts and Sciences.
OSCAR_BEST_PICTURE_2026 = [
    {"title": "One Battle after Another", "winner": True},
    {"title": "Bugonia", "winner": False},
    {"title": "F1", "winner": False},
    {"title": "Frankenstein", "winner": False},
    {"title": "Hamnet", "winner": False},
    {"title": "Marty Supreme", "winner": False},
    {"title": "The Secret Agent", "winner": False},
    {"title": "Sentimental Value", "winner": False},
    {"title": "Sinners", "winner": False},
    {"title": "Train Dreams", "winner": False},
]




CONF_DISCOVERY_PROFILES = "discovery_profiles"

PROFILE_SOURCE_DISCOVER = "discover"
PROFILE_SOURCE_PERSONALIZED = "personalized"

PROFILE_AWARD_NONE = "none"
PROFILE_AWARD_OSCARS_BEST_PICTURE_2026 = "oscars_best_picture_2026"

AWARD_SOURCE_NONE = "none"
AWARD_SOURCE_OSCARS = "oscars"

AWARD_STATUS_ANY = "any"
AWARD_STATUS_WINNER = "winner"
AWARD_STATUS_NOMINATED_NO_WIN = "nominated_no_win"
AWARD_STATUS_NOMINATED_AND_WON = "nominated_and_won"

AWARD_PRESET_NONE = "none"
AWARD_PRESET_LATEST_WINNERS = "latest_winners"
AWARD_PRESET_LATEST_NOMINEES = "latest_nominees"
AWARD_PRESET_BEST_PICTURE_WINNERS = "best_picture_winners"
AWARD_PRESET_BEST_PICTURE_NOMINEES = "best_picture_nominees"

OSCARS_DATA_URL = (
    "https://raw.githubusercontent.com/DLu/oscar_data/main/oscars.csv"
)
AWARD_SOURCE_GULDBAGGEN = "guldbaggen"
AWARD_SOURCE_BAFTA_FILM = "bafta_film"
AWARD_SOURCE_BAFTA_TV = "bafta_tv"
AWARD_SOURCE_GOLDEN_GLOBES_FILM = "golden_globes_film"
AWARD_SOURCE_GOLDEN_GLOBES_TV = "golden_globes_tv"
AWARD_SOURCE_EMMYS = "emmys"
AWARD_SOURCE_CANNES = "cannes"

AWARD_SOURCE_HONG_KONG_FILM_AWARDS = "hong_kong_film_awards"
