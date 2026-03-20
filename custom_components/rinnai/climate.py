import logging
from datetime import timedelta
from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode, HVACAction, PRESET_AWAY, PRESET_SLEEP
from homeassistant.const import UnitOfTemperature, ATTR_TEMPERATURE
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity, DataUpdateCoordinator
)
from .const import DOMAIN
from .api import RinnaiAPI

_LOGGER = logging.getLogger(__name__)

PRESET_NORMAL = "일반"
PRESET_SAVE   = "절약"
PRESET_ONDOL  = "온돌"
SCAN_INTERVAL = timedelta(seconds=30)

# 온도 범위 (프로토콜 가이드 §6 기준)
ROOM_TEMP_MIN, ROOM_TEMP_MAX = 10, 40   # 실내온도 모드 (CMD 02)
ONDOL_TEMP_MIN, ONDOL_TEMP_MAX = 20, 80  # 온돌 모드 (CMD 03)


async def async_setup_entry(hass, entry, async_add_entities):
    api: RinnaiAPI = hass.data[DOMAIN][entry.entry_id]

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="rinnai_boiler",
        update_method=lambda: hass.async_add_executor_job(api.get_status),
        update_interval=SCAN_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()
    async_add_entities([RinnaiClimate(coordinator, api)], True)


class RinnaiClimate(CoordinatorEntity, ClimateEntity):

    _attr_name            = "린나이 보일러"
    _attr_unique_id       = "rinnai_boiler"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_hvac_modes      = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes    = [
        PRESET_NORMAL, PRESET_ONDOL, PRESET_AWAY, PRESET_SLEEP, PRESET_SAVE,
    ]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE |
        ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator: DataUpdateCoordinator, api: RinnaiAPI):
        super().__init__(coordinator)
        self._api = api

    @property
    def _status(self) -> dict:
        return self.coordinator.data or {}

    @property
    def _is_ondol(self) -> bool:
        """현재 온돌 모드 여부 (flags bit1)"""
        return self._status.get("heat_mode", False)

    # ── 동적 온도 범위 ──────────────────────────────

    @property
    def min_temp(self):
        return ONDOL_TEMP_MIN if self._is_ondol else ROOM_TEMP_MIN

    @property
    def max_temp(self):
        return ONDOL_TEMP_MAX if self._is_ondol else ROOM_TEMP_MAX

    # ── 상태 프로퍼티 ──────────────────────────────

    @property
    def current_temperature(self):
        return self._status.get("room_temp_cur")

    @property
    def target_temperature(self):
        if self._is_ondol:
            return self._status.get("hw_temp_set")   # 온돌 설정온도
        return self._status.get("room_temp_set")      # 실내 설정온도

    @property
    def hvac_mode(self):
        s = self._status
        if s.get("power") and s.get("heating"):
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def hvac_action(self):
        s = self._status
        if s.get("heating"):
            return HVACAction.HEATING
        if s.get("power"):
            return HVACAction.IDLE
        return HVACAction.OFF

    @property
    def preset_mode(self):
        s = self._status
        if s.get("go_out"):
            return PRESET_AWAY
        if self._is_ondol:
            return PRESET_ONDOL
        return PRESET_NORMAL

    @property
    def extra_state_attributes(self):
        s = self._status
        return {
            "heat_mode":              "온돌" if s.get("heat_mode") else "실내온도",
            "hot_water_temp_set":     s.get("hw_temp_set"),
            "hot_water_temp_current": s.get("hw_temp_cur"),
            "water_use_temp":         s.get("water_temp"),
            "power":                  s.get("power"),
            "heating":                s.get("heating"),
            "hot_water":              s.get("hot_water"),
            "pre_heat":               s.get("pre_heat"),
            "quick_heat":             s.get("quick_heat"),
            "go_out":                 s.get("go_out"),
        }

    # ── 제어 ──────────────────────────────────────

    async def async_set_hvac_mode(self, hvac_mode: str):
        s = self._status
        on = hvac_mode == HVACMode.HEAT
        await self.hass.async_add_executor_job(
            self._api.set_power,
            on,                                     # power
            s.get("heat_mode", False),              # heat_mode 유지
            on,                                     # heating
            s.get("hot_water", False),              # hot_water 유지
            int(self.target_temperature or 22),     # temp 유지
        )
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        temp = int(kwargs[ATTR_TEMPERATURE])
        heat_mode = self._is_ondol
        # CMD 02 (실내온도) 또는 CMD 03 (온돌) 로 온도 설정
        await self.hass.async_add_executor_job(
            self._api.set_temperature, temp, heat_mode,
        )
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str):
        s = self._status
        current_temp = int(self.target_temperature or 22)

        if preset_mode == PRESET_ONDOL:
            # 실내온도 → 온돌 전환
            await self.hass.async_add_executor_job(
                self._api.set_heat_mode, True, current_temp,
            )
        elif preset_mode == PRESET_NORMAL:
            # 온돌 → 실내온도 전환 + 외출/취침/절약 해제
            await self.hass.async_add_executor_job(
                self._api.set_heat_mode, False, current_temp,
            )
            await self.hass.async_add_executor_job(self._api.set_go_out, False)
            await self.hass.async_add_executor_job(self._api.set_sleep_mode, False)
            await self.hass.async_add_executor_job(self._api.set_save_mode, False)
        elif preset_mode == PRESET_AWAY:
            await self.hass.async_add_executor_job(self._api.set_go_out, True)
        elif preset_mode == PRESET_SLEEP:
            await self.hass.async_add_executor_job(self._api.set_sleep_mode, True)
        elif preset_mode == PRESET_SAVE:
            await self.hass.async_add_executor_job(self._api.set_save_mode, True)

        await self.coordinator.async_request_refresh()
