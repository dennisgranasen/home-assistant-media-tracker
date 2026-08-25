"""Minimal Home Assistant stubs for isolated coordinator unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from types import ModuleType


def _module(name: str) -> ModuleType:
    module = ModuleType(name)
    sys.modules[name] = module
    return module


homeassistant = _module("homeassistant")
config_entries = _module("homeassistant.config_entries")
core = _module("homeassistant.core")
util = _module("homeassistant.util")
dt = _module("homeassistant.util.dt")
helpers = _module("homeassistant.helpers")
update_coordinator = _module("homeassistant.helpers.update_coordinator")
aiohttp_client = _module("homeassistant.helpers.aiohttp_client")
storage = _module("homeassistant.helpers.storage")
aiohttp = _module("aiohttp")

# Import integration submodules without executing the real package __init__,
# which intentionally depends on the complete Home Assistant runtime.
media_watch = _module("custom_components.media_watch")
media_watch.__path__ = [
    str(
        Path(__file__).parents[1]
        / "custom_components"
        / "media_watch"
    )
]


class ClientError(Exception):
    """aiohttp client error stand-in."""


class ClientResponseError(ClientError):
    """aiohttp response error stand-in."""


class ClientSession:
    """aiohttp session type stand-in."""


aiohttp.ClientError = ClientError
aiohttp.ClientResponseError = ClientResponseError
aiohttp.ClientSession = ClientSession


class ConfigEntry:
    """Type placeholder used by coordinator annotations."""


class HomeAssistant:
    """Type placeholder used by coordinator annotations."""


class DataUpdateCoordinator:
    """Small constructor-compatible coordinator stand-in."""

    def __init__(self, hass, *_args, **_kwargs) -> None:
        self.hass = hass

    @classmethod
    def __class_getitem__(cls, _item):
        return cls


class UpdateFailed(Exception):
    """Coordinator update failure stand-in."""


class Store:
    """Storage type stand-in used only while importing the module."""

    @classmethod
    def __class_getitem__(cls, _item):
        return cls


config_entries.ConfigEntry = ConfigEntry
core.HomeAssistant = HomeAssistant
dt.now = lambda: datetime(2026, 8, 25, tzinfo=timezone.utc)
util.dt = dt
update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
update_coordinator.UpdateFailed = UpdateFailed
aiohttp_client.async_get_clientsession = lambda hass: hass.session
storage.Store = Store

homeassistant.config_entries = config_entries
homeassistant.core = core
homeassistant.util = util
homeassistant.helpers = helpers
helpers.update_coordinator = update_coordinator
helpers.aiohttp_client = aiohttp_client
helpers.storage = storage
