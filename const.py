"""Shared constants."""
from homeassistant.components import media_player

MQTT_MEDIA_PLAYER_ATTRIBUTES_BLOCKED = frozenset(
    {
        media_player.ATTR_MEDIA_TRACK,
    }
)
