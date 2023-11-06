"""Support for a State MQTT media player."""
from __future__ import annotations

from typing import Any, cast

import voluptuous as vol

from homeassistant.components.media_player import (
    ENTITY_ID_FORMAT,
    MediaPlayerState,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_SUPPORTED_FEATURES,
    CONF_NAME,
    STATE_ON,
    STATE_OFF,
    STATE_PLAYING,
    STATE_PAUSED,
)
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.json import json_dumps
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util.json import json_loads_object

from .. import subscription
from ..config import MQTT_BASE_SCHEMA
from ..const import (
    CONF_COMMAND_TOPIC,
    CONF_ENCODING,
    CONF_QOS,
    CONF_RETAIN,
    CONF_STATE_TOPIC,
)
from ..debug_info import log_messages
from ..mixins import MQTT_ENTITY_COMMON_SCHEMA, MqttEntity, write_state_on_attr_change
from ..models import ReceiveMessage
from ..util import valid_publish_topic
from .const import MQTT_MEDIA_PLAYER_ATTRIBUTES_BLOCKED
from .schema import MQTT_MEDIA_PLAYER_SCHEMA, services_to_strings, strings_to_services

SERVICE_TO_STRING: dict[MediaPlayerEntityFeature, str] = {
    MediaPlayerEntityFeature.PAUSE: "pause",
    MediaPlayerEntityFeature.SEEK: "seek",
    MediaPlayerEntityFeature.VOLUME_SET: "volume_set",
    MediaPlayerEntityFeature.VOLUME_MUTE: "volume_mute",
    MediaPlayerEntityFeature.PREVIOUS_TRACK: "previous_track",
    MediaPlayerEntityFeature.NEXT_TRACK: "next_track",
    MediaPlayerEntityFeature.TURN_ON: "turn_on",
    MediaPlayerEntityFeature.TURN_OFF: "turn_off",
    MediaPlayerEntityFeature.PLAY_MEDIA: "play_media",
    MediaPlayerEntityFeature.VOLUME_STEP: "volume_step",
    MediaPlayerEntityFeature.SELECT_SOURCE: "select_source",
    MediaPlayerEntityFeature.STOP: "stop",
    MediaPlayerEntityFeature.CLEAR_PLAYLIST: "clear_playlist",
    MediaPlayerEntityFeature.PLAY: "play",
    MediaPlayerEntityFeature.SHUFFLE_SET: "shuffle_set",
    MediaPlayerEntityFeature.SELECT_SOUND_MODE: "select_sound_mode",
    MediaPlayerEntityFeature.BROWSE_MEDIA: "browse_media",
    MediaPlayerEntityFeature.REPEAT_SET: "repeat_set",
    MediaPlayerEntityFeature.GROUPING: "grouping",
    MediaPlayerEntityFeature.MEDIA_ANNOUNCE: "media_announce",
    MediaPlayerEntityFeature.MEDIA_ENQUEUE: "media_enqueue",
}

STRING_TO_SERVICE = {v: k for k, v in SERVICE_TO_STRING.items()}


DEFAULT_SERVICES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.SELECT_SOURCE
)
ALL_SERVICES = (
    DEFAULT_SERVICES
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.SEEK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.CLEAR_PLAYLIST
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.SHUFFLE_SET
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    | MediaPlayerEntityFeature.BROWSE_MEDIA
    | MediaPlayerEntityFeature.REPEAT_SET
    | MediaPlayerEntityFeature.GROUPING
    | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
    | MediaPlayerEntityFeature.MEDIA_ENQUEUE
)

BATTERY = "battery_level"
FAN_SPEED = "fan_speed"
STATE = "state"

POSSIBLE_STATES: dict[str, str] = {
    STATE_ON: STATE_ON,
    STATE_OFF: STATE_OFF,
    STATE_PLAYING: STATE_PLAYING,
    STATE_PAUSED: STATE_PAUSED,
}

CONF_SUPPORTED_FEATURES = ATTR_SUPPORTED_FEATURES
CONF_PAYLOAD_PAUSE = "payload_pause"
CONF_PAYLOAD_SEEK = "payload_seek"
CONF_PAYLOAD_VOLUME_SET = "payload_volume_set"
CONF_PAYLOAD_VOLUME_MUTE = "payload_volume_mute"
CONF_PAYLOAD_PREVIOUS_TRACK = "payload_previous_track"
CONF_PAYLOAD_NEXT_TRACK = "payload_next_track"
CONF_PAYLOAD_TURN_ON = "payload_turn_on"
CONF_PAYLOAD_TURN_OFF = "payload_turn_off"
CONF_PAYLOAD_PLAY_MEDIA = "payload_play_media"
CONF_PAYLOAD_VOLUME_STEP = "payload_volume_step"
CONF_PAYLOAD_SELECT_SOURCE = "payload_select_source"
CONF_PAYLOAD_STOP = "payload_stop"
CONF_PAYLOAD_CLEAR_PLAYLIST = "payload_clear_playlist"
CONF_PAYLOAD_PLAY = "payload_play"
CONF_PAYLOAD_SHUFFLE_SET = "payload_shuffle_set"
CONF_PAYLOAD_SELECT_SOUND_MODE = "payload_select_sound_mode"
CONF_PAYLOAD_BROWSE_MEDIA = "payload_browse_media"
CONF_PAYLOAD_REPEAT_SET = "payload_repeat_set"
CONF_PAYLOAD_GROUPING = "payload_grouping"
CONF_PAYLOAD_MEDIA_ANNOUNCE = "payload_media_announce"
CONF_PAYLOAD_MEDIA_ENQUEUE = "payload_media_enqueue"
CONF_SET_VOLUME_TOPIC = "set_volume_topic"
CONF_SOURCE_LIST = "source_list"
CONF_SEND_COMMAND_TOPIC = "send_command_topic"

DEFAULT_NAME = "MQTT State Media Player"
DEFAULT_RETAIN = False
DEFAULT_SERVICE_STRINGS = services_to_strings(DEFAULT_SERVICES, SERVICE_TO_STRING)
DEFAULT_PAYLOAD_PAUSE = "pause"
DEFAULT_PAYLOAD_PREVIOUS_TRACK = "previous"
DEFAULT_PAYLOAD_NEXT_TRACK = "next"
DEFAULT_PAYLOAD_STOP = "stop"
DEFAULT_PAYLOAD_CLEAR_PLAYLIST = "clear_playlist"
DEFAULT_PAYLOAD_PLAY = "play"
DEFAULT_PAYLOAD_BROWSE_MEDIA = "browse"
DEFAULT_PAYLOAD_MEDIA_ANNOUNCE = "media_announce"

_FEATURE_PAYLOADS = {
    MediaPlayerEntityFeature.PAUSE: CONF_PAYLOAD_PAUSE,
    MediaPlayerEntityFeature.SEEK: CONF_PAYLOAD_SEEK,
    MediaPlayerEntityFeature.VOLUME_SET: CONF_PAYLOAD_VOLUME_SET,
    MediaPlayerEntityFeature.VOLUME_MUTE: CONF_PAYLOAD_VOLUME_MUTE,
    MediaPlayerEntityFeature.PREVIOUS_TRACK: CONF_PAYLOAD_PREVIOUS_TRACK,
    MediaPlayerEntityFeature.NEXT_TRACK: CONF_PAYLOAD_NEXT_TRACK,
    MediaPlayerEntityFeature.TURN_ON: CONF_PAYLOAD_TURN_ON,
    MediaPlayerEntityFeature.TURN_OFF: CONF_PAYLOAD_TURN_OFF,
    MediaPlayerEntityFeature.PLAY_MEDIA: CONF_PAYLOAD_PLAY_MEDIA,
    MediaPlayerEntityFeature.VOLUME_STEP: CONF_PAYLOAD_VOLUME_STEP,
    MediaPlayerEntityFeature.SELECT_SOURCE: CONF_PAYLOAD_SELECT_SOURCE,
    MediaPlayerEntityFeature.STOP: CONF_PAYLOAD_STOP,
    MediaPlayerEntityFeature.CLEAR_PLAYLIST: CONF_PAYLOAD_CLEAR_PLAYLIST,
    MediaPlayerEntityFeature.PLAY: CONF_PAYLOAD_PLAY,
    MediaPlayerEntityFeature.SHUFFLE_SET: CONF_PAYLOAD_SHUFFLE_SET,
    MediaPlayerEntityFeature.SELECT_SOUND_MODE: CONF_PAYLOAD_SELECT_SOUND_MODE,
    MediaPlayerEntityFeature.BROWSE_MEDIA: CONF_PAYLOAD_BROWSE_MEDIA,
    MediaPlayerEntityFeature.REPEAT_SET: CONF_PAYLOAD_REPEAT_SET,
    MediaPlayerEntityFeature.GROUPING: CONF_PAYLOAD_GROUPING,
    MediaPlayerEntityFeature.MEDIA_ANNOUNCE: CONF_PAYLOAD_MEDIA_ANNOUNCE,
    MediaPlayerEntityFeature.MEDIA_ENQUEUE: CONF_PAYLOAD_MEDIA_ENQUEUE,
}

PLATFORM_SCHEMA_STATE_MODERN = (
    MQTT_BASE_SCHEMA.extend(
        {
            vol.Optional(CONF_SOURCE_LIST, default=[]): vol.All(
                cv.ensure_list, [cv.string]
            ),
            vol.Optional(CONF_NAME): vol.Any(cv.string, None),
            vol.Optional(
                CONF_PAYLOAD_PAUSE, default=DEFAULT_PAYLOAD_PAUSE
            ): cv.string,
            vol.Optional(
                CONF_PAYLOAD_PREVIOUS_TRACK, default=DEFAULT_PAYLOAD_PREVIOUS_TRACK
            ): cv.string,
            vol.Optional(
                CONF_PAYLOAD_NEXT_TRACK, default=DEFAULT_PAYLOAD_NEXT_TRACK
            ): cv.string,
            vol.Optional(CONF_PAYLOAD_STOP, default=DEFAULT_PAYLOAD_STOP): cv.string,
            vol.Optional(
                CONF_PAYLOAD_CLEAR_PLAYLIST, default=DEFAULT_PAYLOAD_CLEAR_PLAYLIST
            ): cv.string,
            vol.Optional(CONF_PAYLOAD_PLAY, default=DEFAULT_PAYLOAD_PLAY): cv.string,
            vol.Optional(CONF_PAYLOAD_BROWSE_MEDIA, default=DEFAULT_PAYLOAD_BROWSE_MEDIA): cv.string,
            vol.Optional(CONF_PAYLOAD_MEDIA_ANNOUNCE, default=DEFAULT_PAYLOAD_MEDIA_ANNOUNCE): cv.string,
            vol.Optional(CONF_SEND_COMMAND_TOPIC): valid_publish_topic,
            vol.Optional(CONF_SET_VOLUME_TOPIC): valid_publish_topic,
            vol.Optional(CONF_STATE_TOPIC): valid_publish_topic,
            vol.Optional(
                CONF_SUPPORTED_FEATURES, default=DEFAULT_SERVICE_STRINGS
            ): vol.All(cv.ensure_list, [vol.In(STRING_TO_SERVICE.keys())]),
            vol.Optional(CONF_COMMAND_TOPIC): valid_publish_topic,
            vol.Optional(CONF_RETAIN, default=DEFAULT_RETAIN): cv.boolean,
        }
    )
    .extend(MQTT_ENTITY_COMMON_SCHEMA.schema)
    .extend(MQTT_MEDIA_PLAYER_SCHEMA.schema)
)

DISCOVERY_SCHEMA_STATE = PLATFORM_SCHEMA_STATE_MODERN.extend({}, extra=vol.REMOVE_EXTRA)


class MqttStateMediaPlayer(MqttEntity, MediaPlayerState):
    """Representation of a MQTT-controlled state media player."""

    _default_name = DEFAULT_NAME
    _entity_id_format = ENTITY_ID_FORMAT
    _attributes_extra_blocked = MQTT_MEDIA_PLAYER_ATTRIBUTES_BLOCKED

    _command_topic: str | None
    _set_fan_speed_topic: str | None
    _send_command_topic: str | None
    _payloads: dict[str, str | None]

    def __init__(
        self,
        hass: HomeAssistant,
        config: ConfigType,
        config_entry: ConfigEntry,
        discovery_data: DiscoveryInfoType | None,
    ) -> None:
        """Initialize the media player."""
        self._state_attrs: dict[str, Any] = {}

        MqttEntity.__init__(self, hass, config, config_entry, discovery_data)

    @staticmethod
    def config_schema() -> vol.Schema:
        """Return the config schema."""
        return DISCOVERY_SCHEMA_STATE

    def _setup_from_config(self, config: ConfigType) -> None:
        """(Re)Setup the entity."""
        supported_feature_strings: list[str] = config[CONF_SUPPORTED_FEATURES]
        self._attr_supported_features = MediaPlayerEntityFeature.STATE | strings_to_services(
            supported_feature_strings, STRING_TO_SERVICE
        )
        self._attr_source_list = config[CONF_SOURCE_LIST]
        self._command_topic = config.get(CONF_COMMAND_TOPIC)
        self._set_volume_topic = config.get(CONF_SET_VOLUME_TOPIC)
        self._send_command_topic = config.get(CONF_SEND_COMMAND_TOPIC)

        self._payloads = {
            key: config.get(key)
            for key in (
                CONF_PAYLOAD_PAUSE,
                CONF_PAYLOAD_SEEK,
                CONF_PAYLOAD_VOLUME_SET,
                CONF_PAYLOAD_VOLUME_MUTE,
                CONF_PAYLOAD_PREVIOUS_TRACK,
                CONF_PAYLOAD_NEXT_TRACK,
                CONF_PAYLOAD_TURN_ON,
                CONF_PAYLOAD_TURN_OFF,
                CONF_PAYLOAD_PLAY_MEDIA,
                CONF_PAYLOAD_VOLUME_STEP,
                CONF_PAYLOAD_SELECT_SOURCE,
                CONF_PAYLOAD_STOP,
                CONF_PAYLOAD_CLEAR_PLAYLIST,
                CONF_PAYLOAD_PLAY,
                CONF_PAYLOAD_SHUFFLE_SET,
                CONF_PAYLOAD_SELECT_SOUND_MODE,
                CONF_PAYLOAD_BROWSE_MEDIA,
                CONF_PAYLOAD_REPEAT_SET,
                CONF_PAYLOAD_GROUPING,
                CONF_PAYLOAD_MEDIA_ANNOUNCE,
                CONF_PAYLOAD_MEDIA_ENQUEUE,
            )
        }

    def _update_state_attributes(self, payload: dict[str, Any]) -> None:
        """Update the entity state attributes."""
        self._state_attrs.update(payload)
        self._attr_fan_speed = self._state_attrs.get(FAN_SPEED, 0)
        self._attr_battery_level = max(0, min(100, self._state_attrs.get(BATTERY, 0)))

    def _prepare_subscribe_topics(self) -> None:
        """(Re)Subscribe to topics."""
        topics: dict[str, Any] = {}

        @callback
        @log_messages(self.hass, self.entity_id)
        @write_state_on_attr_change(
            self, {"_attr_battery_level", "_attr_fan_speed", "_attr_state"}
        )
        def state_message_received(msg: ReceiveMessage) -> None:
            """Handle state MQTT message."""
            payload = json_loads_object(msg.payload)
            if STATE in payload and (
                (state := payload[STATE]) in POSSIBLE_STATES or state is None
            ):
                self._attr_state = (
                    POSSIBLE_STATES[cast(str, state)] if payload[STATE] else None
                )
                del payload[STATE]
            self._update_state_attributes(payload)

        if state_topic := self._config.get(CONF_STATE_TOPIC):
            topics["state_position_topic"] = {
                "topic": state_topic,
                "msg_callback": state_message_received,
                "qos": self._config[CONF_QOS],
                "encoding": self._config[CONF_ENCODING] or None,
            }
        self._sub_state = subscription.async_prepare_subscribe_topics(
            self.hass, self._sub_state, topics
        )

    async def _subscribe_topics(self) -> None:
        """(Re)Subscribe to topics."""
        await subscription.async_subscribe_topics(self.hass, self._sub_state)

    async def _async_publish_command(self, feature: MediaPlayerEntityFeature) -> None:
        """Publish a command."""
        if self._command_topic is None:
            return

        await self.async_publish(
            self._command_topic,
            self._payloads[_FEATURE_PAYLOADS[feature]],
            qos=self._config[CONF_QOS],
            retain=self._config[CONF_RETAIN],
            encoding=self._config[CONF_ENCODING],
        )
        self.async_write_ha_state()


    async def async_turn_off(self) -> None:
        """Turn the media player off."""
        await self._async_publish_command(MediaPlayerEntityFeature.TURN_OFF)

    async def async_turn_on(self) -> None:
        """Turn the media player on."""
        await self._async_publish_command(MediaPlayerEntityFeature.TURN_ON)

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self._async_publish_command(MediaPlayerEntityFeature.VOLUME_SET)

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute (True) or unmute (False) media player."""
        if mute:
            await self._async_publish_command(MediaPlayerEntityFeature.VOLUME_MUTE)
        else:
            await self._async_publish_command(MediaPlayerEntityFeature.VOLUME_MUTE)

    async def async_select_source(self, source: str) -> None:
        """Select input source."""
        if self.source_list is not None and source in self.source_list:
            await self._async_publish_command(MediaPlayerEntityFeature.SELECT_SOURCE)
        else:
            raise ValueError(f"Unknown input source: {source}.")
        
    async def async_pause(self) -> None:
        """Pause the media player."""
        await self._async_publish_command(MediaPlayerEntityFeature.PAUSE)

    async def async_media_play(self) -> None:
        """Send play command."""
        await self._async_publish_command(MediaPlayerEntityFeature.PLAY)

    async def async_media_pause(self) -> None:
        """Send pause command."""
        await self._async_publish_command(MediaPlayerEntityFeature.PAUSE)

    async def async_media_previous_track(self) -> None:
        """Send previous track command."""
        await self._async_publish_command(MediaPlayerEntityFeature.PREVIOUS_TRACK)

    async def async_media_next_track(self) -> None:
        """Send next track command."""
        await self._async_publish_command(MediaPlayerEntityFeature.NEXT_TRACK)

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Send a command to a media player."""
        if (
            self._send_command_topic is None
            or self.supported_features & MediaPlayerEntityFeature.SEND_COMMAND == 0
        ):
            return
        if isinstance(params, dict):
            message: dict[str, Any] = {"command": command}
            message.update(params)
            payload = json_dumps(message)
        else:
            payload = command
        await self.async_publish(
            self._send_command_topic,
            payload,
            self._config[CONF_QOS],
            self._config[CONF_RETAIN],
            self._config[CONF_ENCODING],
        )
