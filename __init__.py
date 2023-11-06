"""Support for MQTT media players."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.components import media_player
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, async_get_hass, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.typing import ConfigType

from ..const import DOMAIN
from ..mixins import async_setup_entity_entry_helper
from .schema import CONF_SCHEMA, LEGACY, MQTT_VACUUM_SCHEMA, STATE
from .schema_state import (
    DISCOVERY_SCHEMA_STATE,
    PLATFORM_SCHEMA_STATE_MODERN,
    MqttStateMediaPlayer,
)

_LOGGER = logging.getLogger(__name__)

MQTT_VACUUM_DOCS_URL = "https://www.home-assistant.io/integrations/media_player.mqtt/"

@callback
def validate_mqtt_media_player_discovery(config_value: ConfigType) -> ConfigType:
    """Validate MQTT media player schema."""

    schemas = {STATE: DISCOVERY_SCHEMA_STATE}
    config: ConfigType = schemas[config_value[CONF_SCHEMA]](config_value)
    hass = async_get_hass()
    return config


@callback
def validate_mqtt_media_player_modern(config_value: ConfigType) -> ConfigType:
    """Validate MQTT media player modern schema."""

    schemas = {
        STATE: PLATFORM_SCHEMA_STATE_MODERN,
    }
    config: ConfigType = schemas[config_value[CONF_SCHEMA]](config_value)
    hass = async_get_hass()
    return config


DISCOVERY_SCHEMA = vol.All(
    MQTT_VACUUM_SCHEMA.extend({}, extra=vol.ALLOW_EXTRA), validate_mqtt_media_player_discovery
)

PLATFORM_SCHEMA_MODERN = vol.All(
    MQTT_VACUUM_SCHEMA.extend({}, extra=vol.ALLOW_EXTRA), validate_mqtt_media_player_modern
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up MQTT vacuum through YAML and through MQTT discovery."""
    await async_setup_entity_entry_helper(
        hass,
        config_entry,
        None,
        media_player.DOMAIN,
        async_add_entities,
        DISCOVERY_SCHEMA,
        PLATFORM_SCHEMA_MODERN,
        {"state": MqttStateMediaPlayer},
    )
