"""Config and options flows for Media Watch."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
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

from .api import TMDBApi, TMDBAuthError, TMDBError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_ID,
    CONF_DISCOVERY_LIMIT,
    CONF_LANGUAGE,
    CONF_MIN_RATING,
    CONF_MIN_VOTES,
    CONF_PROVIDERS,
    CONF_UPCOMING_LIMIT,
    CONF_REGION,
    CONF_SESSION_ID,
    CONF_USERNAME,
    DEFAULT_DISCOVERY_LIMIT,
    DEFAULT_LANGUAGE,
    DEFAULT_MIN_RATING,
    DEFAULT_MIN_VOTES,
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
                        CONF_PROVIDERS: default_provider_ids,
                        CONF_MIN_RATING: DEFAULT_MIN_RATING,
                        CONF_MIN_VOTES: DEFAULT_MIN_VOTES,
                        CONF_DISCOVERY_LIMIT: DEFAULT_DISCOVERY_LIMIT,
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

    async def async_step_init(
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
            return self.async_create_entry(data=cleaned)

        current_provider_ids = [
            str(item)
            for item in options.get(CONF_PROVIDERS, [])
        ]

        schema = vol.Schema(
            {
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
                    CONF_MIN_RATING,
                    default=options.get(
                        CONF_MIN_RATING, DEFAULT_MIN_RATING
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=10,
                        step=0.1,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MIN_VOTES,
                    default=options.get(
                        CONF_MIN_VOTES, DEFAULT_MIN_VOTES
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=1_000_000,
                        step=100,
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_DISCOVERY_LIMIT,
                    default=options.get(
                        CONF_DISCOVERY_LIMIT,
                        DEFAULT_DISCOVERY_LIMIT,
                    ),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1,
                        max=100,
                        step=1,
                        mode=NumberSelectorMode.BOX,
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
