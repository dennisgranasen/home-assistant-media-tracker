"""Constants for Media Watch."""

from datetime import timedelta

DOMAIN = "media_watch"

CONF_ACCESS_TOKEN = "access_token"
CONF_ACCOUNT_ID = "account_id"
CONF_SESSION_ID = "session_id"
CONF_USERNAME = "username"

CONF_REGION = "region"
CONF_LANGUAGE = "language"
CONF_PROVIDERS = "providers"
CONF_MIN_RATING = "min_rating"
CONF_MIN_VOTES = "min_votes"
CONF_DISCOVERY_LIMIT = "discovery_limit"
CONF_UPCOMING_LIMIT = "upcoming_limit"

DEFAULT_REGION = "SE"
DEFAULT_LANGUAGE = "sv-SE"
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
