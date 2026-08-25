"""Config and options flows for Media Watch."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import slugify
from homeassistant.util import dt as dt_util
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .award_registry import async_categories, providers_for_media_type
from .award_taxonomy import aliases_for, generic_categories
from .api import TMDBApi, TMDBAuthError, TMDBError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_FALLBACK_LANGUAGE,
    CONF_LANGUAGE,
    CONF_USE_PROFILE_LANGUAGE,
    CONF_PROVIDERS,
    CONF_UPCOMING_LIMIT,
    CONF_REGION,
    CONF_SESSION_ID,
    CONF_USERNAME,
    CONF_DISCOVERY_PROFILES,
    PROFILE_SOURCE_DISCOVER,
    PROFILE_SOURCE_PERSONALIZED,
    PROFILE_AWARD_NONE,
    PROFILE_AWARD_OSCARS_BEST_PICTURE_2026,
    AWARD_SOURCE_NONE,
    AWARD_SOURCE_ANY,
    AWARD_SOURCE_OSCARS,
    AWARD_STATUS_ANY,
    AWARD_STATUS_WINNER,
    AWARD_STATUS_NOMINATED_NO_WIN,
    AWARD_STATUS_NOMINATED_AND_WON,
    AWARD_PRESET_NONE,
    AWARD_PRESET_LATEST_WINNERS,
    AWARD_PRESET_LATEST_NOMINEES,
    AWARD_PRESET_BEST_PICTURE_WINNERS,
    AWARD_PRESET_BEST_PICTURE_NOMINEES,
    DEFAULT_FALLBACK_LANGUAGE,
    DEFAULT_LANGUAGE,
    DEFAULT_USE_PROFILE_LANGUAGE,
    DEFAULT_PROVIDER_NAMES,
    DEFAULT_UPCOMING_LIMIT,
    DEFAULT_REGION,
    DOMAIN,
)


async def _provider_catalog(
    api: TMDBApi,
    region: str,
) -> list[dict[str, Any]]:
    """Return the union of TMDB movie and TV providers for a region."""
    movie, tv = await asyncio.gather(
        api.get_available_movie_providers(region),
        api.get_available_tv_providers(region),
    )

    providers: dict[int, dict[str, Any]] = {}
    for provider in [*movie, *tv]:
        provider_id = int(provider["provider_id"])
        current = providers.get(provider_id)
        if current is None or int(
            provider.get("display_priority", 9999)
        ) < int(current.get("display_priority", 9999)):
            providers[provider_id] = provider

    return sorted(
        providers.values(),
        key=lambda item: (
            int(item.get("display_priority", 9999)),
            str(item.get("provider_name", "")),
        ),
    )


class MediaWatchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup of Media Watch."""

    VERSION = 1

    def __init__(self) -> None:
        self._access_token: str | None = None
        self._request_token: str | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            token = str(user_input[CONF_ACCESS_TOKEN]).strip()
            api = TMDBApi(async_get_clientsession(self.hass), token)
            try:
                await api.validate_token()
                self._request_token = await api.create_request_token()
            except TMDBAuthError:
                errors["base"] = "invalid_auth"
            except TMDBError:
                errors["base"] = "cannot_connect"
            else:
                self._access_token = token
                return await self.async_step_authorize()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACCESS_TOKEN): str}
            ),
            errors=errors,
        )

    async def async_step_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._access_token is None or self._request_token is None:
            return self.async_abort(reason="missing_auth_data")

        errors: dict[str, str] = {}
        auth_url = (
            "https://www.themoviedb.org/authenticate/"
            f"{self._request_token}"
        )

        if user_input is not None:
            api = TMDBApi(
                async_get_clientsession(self.hass),
                self._access_token,
            )
            try:
                session_id = await api.create_session(
                    self._request_token
                )
                user_api = TMDBApi(
                    async_get_clientsession(self.hass),
                    self._access_token,
                    session_id,
                )
                account = await user_api.account_details()
                providers = await _provider_catalog(
                    user_api, DEFAULT_REGION
                )
            except TMDBAuthError:
                errors["base"] = "not_authorized"
            except TMDBError:
                errors["base"] = "cannot_connect"
            else:
                account_id = int(account["id"])
                await self.async_set_unique_id(
                    f"tmdb_{account_id}"
                )
                self._abort_if_unique_id_configured()

                default_provider_ids = [
                    int(provider["provider_id"])
                    for provider in providers
                    if provider.get("provider_name")
                    in DEFAULT_PROVIDER_NAMES
                ]
                username = (
                    account.get("username")
                    or account.get("name")
                    or str(account_id)
                )

                return self.async_create_entry(
                    title=f"Media Watch ({username})",
                    data={
                        CONF_ACCESS_TOKEN: self._access_token,
                        CONF_SESSION_ID: session_id,
                        CONF_ACCOUNT_ID: account_id,
                        CONF_USERNAME: username,
                    },
                    options={
                        CONF_REGION: DEFAULT_REGION,
                        CONF_LANGUAGE: DEFAULT_LANGUAGE,
                        CONF_FALLBACK_LANGUAGE: DEFAULT_FALLBACK_LANGUAGE,
                        CONF_USE_PROFILE_LANGUAGE: DEFAULT_USE_PROFILE_LANGUAGE,
                        CONF_PROVIDERS: default_provider_ids,
                        CONF_UPCOMING_LIMIT: DEFAULT_UPCOMING_LIMIT,
                    },
                )

        return self.async_show_form(
            step_id="authorize",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"auth_url": auth_url},
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "MediaWatchOptionsFlow":
        return MediaWatchOptionsFlow()


class MediaWatchOptionsFlow(config_entries.OptionsFlow):
    """Handle Media Watch options."""

    def __init__(self) -> None:
        self._editing_profile_id: str | None = None
        self._profile_draft: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["general", "discovery_profiles"],
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        options = self.config_entry.options
        current_region = str(
            options.get(CONF_REGION, DEFAULT_REGION)
        )

        # If the submitted region differs, use it immediately when
        # rebuilding the provider catalogue.
        region = (
            str(user_input.get(CONF_REGION, current_region))
            if user_input
            else current_region
        )

        api = TMDBApi(
            async_get_clientsession(self.hass),
            self.config_entry.data[CONF_ACCESS_TOKEN],
            self.config_entry.data[CONF_SESSION_ID],
        )

        errors: dict[str, str] = {}
        try:
            providers = await _provider_catalog(api, region)
        except TMDBError:
            providers = []
            errors["base"] = "cannot_connect"

        # Native Home Assistant select options currently support value +
        # label, not an image/logo field. We therefore retain the TMDB
        # provider ID as value and its canonical provider name as label.
        # TMDB logo_path is retained in runtime data for dashboard use.
        provider_options = [
            SelectOptionDict(
                value=str(provider["provider_id"]),
                label=str(provider["provider_name"]),
            )
            for provider in providers
        ]

        if user_input is not None and not errors:
            cleaned = dict(user_input)
            cleaned[CONF_PROVIDERS] = [
                int(item)
                for item in cleaned.get(CONF_PROVIDERS, [])
            ]
            merged = dict(self.config_entry.options)
            merged.update(cleaned)
            return self.async_create_entry(data=merged)

        current_provider_ids = [
            str(item)
            for item in options.get(CONF_PROVIDERS, [])
        ]

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USE_PROFILE_LANGUAGE,
                    default=options.get(
                        CONF_USE_PROFILE_LANGUAGE,
                        DEFAULT_USE_PROFILE_LANGUAGE,
                    ),
                ): BooleanSelector(),
                vol.Required(
                    CONF_FALLBACK_LANGUAGE,
                    default=options.get(
                        CONF_FALLBACK_LANGUAGE,
                        DEFAULT_FALLBACK_LANGUAGE,
                    ),
                ): TextSelector(TextSelectorConfig()),
                vol.Required(
                    CONF_REGION,
                    default=current_region,
                ): TextSelector(TextSelectorConfig()),
                vol.Required(
                    CONF_LANGUAGE,
                    default=options.get(
                        CONF_LANGUAGE, DEFAULT_LANGUAGE
                    ),
                ): TextSelector(TextSelectorConfig()),
                vol.Required(
                    CONF_PROVIDERS,
                    default=current_provider_ids,
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=provider_options,
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    CONF_UPCOMING_LIMIT,
                    default=options.get(
                        CONF_UPCOMING_LIMIT,
                        DEFAULT_UPCOMING_LIMIT,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=50,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )


    def _profiles(self) -> list[dict[str, Any]]:
        value = self.config_entry.options.get(
            CONF_DISCOVERY_PROFILES, []
        )
        return [
            dict(profile)
            for profile in value
            if isinstance(profile, dict)
        ]

    async def async_step_discovery_profiles(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        profiles = self._profiles()

        action_options = [
            SelectOptionDict(value="add", label="Add profile"),
        ]
        for profile in profiles:
            profile_id = str(profile.get("id", ""))
            name = str(profile.get("name", profile_id))
            action_options.append(
                SelectOptionDict(
                    value=f"edit:{profile_id}",
                    label=f"Edit: {name}",
                )
            )
            action_options.append(
                SelectOptionDict(
                    value=f"delete:{profile_id}",
                    label=f"Delete: {name}",
                )
            )

        if user_input is not None:
            action = str(user_input["profile_action"])
            if action == "add":
                self._editing_profile_id = None
                return await self.async_step_profile()

            operation, profile_id = action.split(":", 1)
            if operation == "delete":
                remaining = [
                    item
                    for item in profiles
                    if str(item.get("id")) != profile_id
                ]
                merged = dict(self.config_entry.options)
                merged[CONF_DISCOVERY_PROFILES] = remaining
                return self.async_create_entry(data=merged)

            self._editing_profile_id = profile_id
            return await self.async_step_profile()

        return self.async_show_form(
            step_id="discovery_profiles",
            data_schema=vol.Schema(
                {
                    vol.Required("profile_action"): SelectSelector(
                        SelectSelectorConfig(
                            options=action_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_profile(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Choose the profile fundamentals first.

        Media type is deliberately selected before award source so subsequent
        steps can expose only valid award providers and categories.
        """
        profiles = self._profiles()
        current = next(
            (
                item
                for item in profiles
                if str(item.get("id")) == self._editing_profile_id
            ),
            {},
        )

        if not self._profile_draft:
            self._profile_draft = dict(current)

        if user_input is not None:
            self._profile_draft.update(user_input)
            return await self.async_step_profile_awards()

        def d(key: str, fallback: Any) -> Any:
            return self._profile_draft.get(key, fallback)

        return self.async_show_form(
            step_id="profile",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "name",
                        default=d("name", "New discovery"),
                    ): TextSelector(TextSelectorConfig()),
                    vol.Required(
                        "media_type",
                        default=d("media_type", "movie"),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {"value": "movie", "label": "Movies"},
                                {"value": "tv", "label": "TV shows"},
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        "source",
                        default=d(
                            "source", PROFILE_SOURCE_DISCOVER
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": PROFILE_SOURCE_DISCOVER,
                                    "label": "General discovery",
                                },
                                {
                                    "value": PROFILE_SOURCE_PERSONALIZED,
                                    "label": "Personalized",
                                },
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
            ),
        )

    async def async_step_profile_awards(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Choose a valid award source for the already-selected media type."""
        media_type = str(
            self._profile_draft.get("media_type", "movie")
        )

        provider_options = [
            {"value": AWARD_SOURCE_NONE, "label": "No awards filter"},
            {
                "value": AWARD_SOURCE_ANY,
                "label": "Any award organization",
            },
        ]
        provider_options.extend(
            {
                "value": info.source,
                "label": info.label,
            }
            for info in providers_for_media_type(media_type)
        )

        if user_input is not None:
            self._profile_draft.update(user_input)

            if (
                self._profile_draft.get("award_source")
                == AWARD_SOURCE_NONE
            ):
                # Clear stale award fields if editing an existing profile.
                self._profile_draft.update(
                    {
                        "award_preset": AWARD_PRESET_NONE,
                        "award_category": "all",
                        "award_status": AWARD_STATUS_ANY,
                        "award_year_from": "",
                        "award_year_to": "",
                    }
                )
                return await self.async_step_profile_filters()

            return await self.async_step_profile_award_details()

        current_source = str(
            self._profile_draft.get(
                "award_source", AWARD_SOURCE_NONE
            )
        )
        valid_sources = {
            option["value"] for option in provider_options
        }
        if current_source not in valid_sources:
            current_source = AWARD_SOURCE_NONE

        return self.async_show_form(
            step_id="profile_awards",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "award_source",
                        default=current_source,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=provider_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_profile_award_details(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Configure award filters with safe category dropdowns."""
        media_type = str(
            self._profile_draft.get("media_type", "movie")
        )
        award_source = str(
            self._profile_draft.get(
                "award_source", AWARD_SOURCE_NONE
            )
        )

        if award_source == AWARD_SOURCE_ANY:
            source_infos = providers_for_media_type(media_type)
            source_category_options = [
                option
                for option in generic_categories(media_type)
                if option["value"] == "all"
                or any(
                    aliases_for(info.source, option["value"])
                    for info in source_infos
                )
            ]
        else:
            source_category_options = await async_categories(
                self.hass,
                award_source,
                media_type,
            )
        if user_input is not None:
            self._profile_draft.update(user_input)
            return await self.async_step_profile_filters()

        source_values = {
            option["value"] for option in source_category_options
        }
        current_source_category = str(
            self._profile_draft.get("award_category", "all")
        )
        if current_source_category not in source_values:
            current_source_category = "all"

        def optional_year_default(key: str) -> int | None:
            value = self._profile_draft.get(key)
            if value in (None, ""):
                return None
            text = str(value).strip()
            if len(text) >= 4 and text[:4].isdigit():
                return int(text[:4])
            try:
                return int(text)
            except (TypeError, ValueError):
                return None

        award_year_from = optional_year_default("award_year_from")
        award_year_to = optional_year_default("award_year_to")
        current_year = dt_util.now().year

        return self.async_show_form(
            step_id="profile_award_details",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "award_preset",
                        default=self._profile_draft.get(
                            "award_preset",
                            AWARD_PRESET_NONE,
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=(
                                [
                                    {
                                        "value": AWARD_PRESET_NONE,
                                        "label": "Custom",
                                    },
                                    {
                                        "value": AWARD_PRESET_LATEST_WINNERS,
                                        "label": "Latest awards – all winners",
                                    },
                                    {
                                        "value": AWARD_PRESET_LATEST_NOMINEES,
                                        "label": "Latest awards – all nominated/selected titles",
                                    },
                                ]
                                + (
                                    [
                                        {
                                            "value": AWARD_PRESET_BEST_PICTURE_WINNERS,
                                            "label": "All top-film-category winners",
                                        },
                                        {
                                            "value": AWARD_PRESET_BEST_PICTURE_NOMINEES,
                                            "label": "All top-film-category nominees",
                                        },
                                    ]
                                    if media_type == "movie"
                                    else []
                                )
                            ),
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        "award_category",
                        default=current_source_category,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=source_category_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        "award_status",
                        default=self._profile_draft.get(
                            "award_status",
                            AWARD_STATUS_ANY,
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": AWARD_STATUS_ANY,
                                    "label": "Nominated or winner",
                                },
                                {
                                    "value": AWARD_STATUS_WINNER,
                                    "label": "Winner",
                                },
                                {
                                    "value": AWARD_STATUS_NOMINATED_NO_WIN,
                                    "label": "Nominated, no win",
                                },
                                {
                                    "value": AWARD_STATUS_NOMINATED_AND_WON,
                                    "label": "Nominated + at least one win",
                                },
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    (
                        vol.Optional(
                            "award_year_from",
                            default=award_year_from,
                        )
                        if award_year_from is not None
                        else vol.Optional("award_year_from")
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1900,
                            max=current_year,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    (
                        vol.Optional(
                            "award_year_to",
                            default=award_year_to,
                        )
                        if award_year_to is not None
                        else vol.Optional("award_year_to")
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1900,
                            max=current_year,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    async def _profile_genre_options(
        self,
        media_type: str,
    ) -> list[SelectOptionDict]:
        """Return localized TMDB genres for one profile media type."""
        api = TMDBApi(
            async_get_clientsession(self.hass),
            self.config_entry.data[CONF_ACCESS_TOKEN],
            self.config_entry.data[CONF_SESSION_ID],
        )

        options = self.config_entry.options
        language = str(
            options.get(
                CONF_LANGUAGE,
                self.config_entry.data.get(
                    CONF_LANGUAGE,
                    DEFAULT_LANGUAGE,
                ),
            )
        )

        try:
            if media_type == "tv":
                genres = await api.get_tv_genres(language)
            else:
                genres = await api.get_movie_genres(language)
        except TMDBError:
            # Genre IDs are stable. Falling back to English labels keeps the
            # form usable even if the configured locale cannot be retrieved.
            try:
                if media_type == "tv":
                    genres = await api.get_tv_genres("en-US")
                else:
                    genres = await api.get_movie_genres("en-US")
            except TMDBError:
                genres = []

        return [
            SelectOptionDict(
                value=str(genre["id"]),
                label=str(genre["name"]),
            )
            for genre in sorted(
                genres,
                key=lambda item: str(item.get("name", "")).casefold(),
            )
            if genre.get("id") is not None
            and genre.get("name")
        ]

    @staticmethod
    def _genre_defaults(value: Any) -> list[str]:
        """Normalize legacy comma-separated genre IDs for multiselect UI."""
        if value is None:
            return []

        if isinstance(value, (list, tuple, set)):
            raw = value
        else:
            raw = str(value).replace(";", ",").split(",")

        result: list[str] = []
        for item in raw:
            text = str(item).strip()
            if text and text not in result:
                result.append(text)
        return result

    async def async_step_profile_filters(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Configure ordinary discovery filters after award constraints."""
        if user_input is not None:
            self._profile_draft.update(user_input)
            return self._save_profile()

        d = lambda key, fallback: self._profile_draft.get(
            key, fallback
        )

        media_type = str(d("media_type", "movie"))
        genre_options = await self._profile_genre_options(media_type)
        valid_genre_ids = {
            str(option["value"])
            for option in genre_options
        }

        include_defaults = [
            value
            for value in self._genre_defaults(
                d("include_genres", [])
            )
            if value in valid_genre_ids
        ]
        exclude_defaults = [
            value
            for value in self._genre_defaults(
                d("exclude_genres", [])
            )
            if value in valid_genre_ids
        ]

        sort_options = [
            {
                "value": "popularity.desc",
                "label": "Popularity ↓",
            },
            {
                "value": "vote_average.desc",
                "label": "Rating ↓",
            },
            {
                "value": "vote_count.desc",
                "label": "Votes ↓",
            },
        ]
        if media_type == "movie":
            sort_options.extend(
                [
                    {
                        "value": "primary_release_date.desc",
                        "label": "Newest first",
                    },
                    {
                        "value": "primary_release_date.asc",
                        "label": "Oldest first",
                    },
                ]
            )
        else:
            sort_options.extend(
                [
                    {
                        "value": "first_air_date.desc",
                        "label": "Newest first",
                    },
                    {
                        "value": "first_air_date.asc",
                        "label": "Oldest first",
                    },
                ]
            )

        current_sort = str(d("sort_by", "popularity.desc"))
        valid_sorts = {x["value"] for x in sort_options}
        if current_sort not in valid_sorts:
            current_sort = "popularity.desc"

        current_year = dt_util.now().year

        def legacy_year(new_key: str, old_key: str) -> int | None:
            value = d(new_key, None)
            if value in (None, ""):
                value = d(old_key, None)
            if value in (None, ""):
                return None
            text = str(value).strip()
            if len(text) >= 4 and text[:4].isdigit():
                return int(text[:4])
            try:
                return int(text)
            except ValueError:
                return None

        release_year_from = legacy_year(
            "release_year_from", "release_date_gte"
        )
        release_year_to = legacy_year(
            "release_year_to", "release_date_lte"
        )

        return self.async_show_form(
            step_id="profile_filters",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "provider_scope",
                        default=d("provider_scope", "all"),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": "all",
                                    "label": "All regional providers",
                                },
                                {
                                    "value": "my",
                                    "label": "My providers",
                                },
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        "min_rating",
                        default=d("min_rating", 0),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=10,
                            step=0.1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        "min_votes",
                        default=d("min_votes", 0),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=1_000_000,
                            step=100,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "include_genres",
                        default=include_defaults,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=genre_options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Optional(
                        "exclude_genres",
                        default=exclude_defaults,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=genre_options,
                            multiple=True,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        "genre_match",
                        default=d("genre_match", "any"),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                {
                                    "value": "any",
                                    "label": "Any included genre",
                                },
                                {
                                    "value": "all",
                                    "label": "All included genres",
                                },
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    (
                        vol.Optional(
                            "release_year_from",
                            default=release_year_from,
                        )
                        if release_year_from is not None
                        else vol.Optional("release_year_from")
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1900,
                            max=current_year,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    (
                        vol.Optional(
                            "release_year_to",
                            default=release_year_to,
                        )
                        if release_year_to is not None
                        else vol.Optional("release_year_to")
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1900,
                            max=current_year,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    (
                        vol.Optional(
                            "release_max_age_years",
                            default=int(d("release_max_age_years", 0)),
                        )
                        if d("release_max_age_years", None) not in (None, "")
                        else vol.Optional("release_max_age_years")
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0,
                            max=50,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        "sort_by",
                        default=current_sort,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=sort_options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        "max_pages",
                        default=d("max_pages", 5),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=20,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        "limit",
                        default=d("limit", 30),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1,
                            max=200,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
        )

    def _save_profile(self) -> FlowResult:
        """Persist the assembled profile draft."""
        profiles = self._profiles()
        profile = dict(self._profile_draft)

        name = str(profile["name"]).strip()
        base_id = (
            self._editing_profile_id
            or slugify(name)
            or "discovery"
        )
        existing_ids = {
            str(item.get("id"))
            for item in profiles
            if str(item.get("id")) != self._editing_profile_id
        }
        profile_id = base_id
        suffix = 2
        while profile_id in existing_ids:
            profile_id = f"{base_id}_{suffix}"
            suffix += 1

        profile["id"] = profile_id
        profile["name"] = name

        for key in (
            "include_genres",
            "exclude_genres",
        ):
            value = profile.get(key, [])
            if isinstance(value, (list, tuple, set)):
                profile[key] = [
                    int(item)
                    for item in value
                    if str(item).strip().isdigit()
                ]
            else:
                profile[key] = [
                    int(item.strip())
                    for item in str(value)
                    .replace(";", ",")
                    .split(",")
                    if item.strip().isdigit()
                ]

        for key in (
            "release_year_from",
            "release_year_to",
            "release_max_age_years",
            "award_year_from",
            "award_year_to",
        ):
            value = profile.get(key)
            if value in (None, ""):
                profile[key] = ""
                continue

            text = str(value).strip()
            if key.startswith("release_year") and len(text) >= 4:
                text = text[:4]

            try:
                profile[key] = int(text)
            except ValueError:
                profile[key] = ""

        # Remove obsolete date-based discovery fields from edited profiles.
        profile.pop("release_date_gte", None)
        profile.pop("release_date_lte", None)
        profile.pop("award_category_mode", None)
        profile.pop("award_generic_category", None)

        updated = [
            item
            for item in profiles
            if str(item.get("id")) != self._editing_profile_id
        ]
        updated.append(profile)

        merged = dict(self.config_entry.options)
        merged[CONF_DISCOVERY_PROFILES] = updated

        self._profile_draft = {}
        self._editing_profile_id = None
        return self.async_create_entry(data=merged)
