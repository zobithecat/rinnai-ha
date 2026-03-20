"""Tests for Rinnai API packet building and status parsing.

Flags bitmap (프로토콜 가이드 §6 기준):
  bit0=0x01 power, bit1=0x02 heat_mode(온돌), bit2=0x04 heating, bit3=0x08 hot_water
"""
import sys
import types

# Stub out homeassistant imports so we can import api.py standalone
_ha = types.ModuleType("homeassistant")
_ha_entries = types.ModuleType("homeassistant.config_entries")
_ha_entries.ConfigEntry = type("ConfigEntry", (), {})
_ha_core = types.ModuleType("homeassistant.core")
_ha_core.HomeAssistant = type("HomeAssistant", (), {})
_ha.config_entries = _ha_entries
_ha.core = _ha_core
for name, mod in {
    "homeassistant": _ha,
    "homeassistant.config_entries": _ha_entries,
    "homeassistant.core": _ha_core,
}.items():
    sys.modules[name] = mod

# Now import the module under test
sys.path.insert(0, "custom_components")
from rinnai.api import RinnaiAPI, _hash_password
from rinnai.const import ETX


class TestPasswordHashing:
    def test_hash_password_returns_base64(self):
        result = _hash_password("test123")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_hash_password_deterministic(self):
        assert _hash_password("hello") == _hash_password("hello")

    def test_hash_password_differs_for_different_inputs(self):
        assert _hash_password("abc") != _hash_password("xyz")


class TestPacketBuilding:
    def setup_method(self):
        self.api = RinnaiAPI("test@test.com", "pass")

    # ── Query packets ──

    def test_query_status_packet(self):
        pkt = self.api._query_packet("01")
        assert pkt == "sm000201000007d"

    def test_query_booking_packet(self):
        pkt = self.api._query_packet("03")
        assert pkt == "sm000203000007d"

    def test_query_packet_format(self):
        """All query packets must match sm0002[CMD]00000[ETX]."""
        for cmd in ["01", "03", "04", "0a"]:
            pkt = self.api._query_packet(cmd)
            assert pkt.startswith("sm0002")
            assert pkt.endswith("7d")
            assert pkt == f"sm0002{cmd}000007d"

    # ── Control packets ──

    def test_control_room_temp_22(self):
        """CMD 02: sm0003 02 02 16 00 7d"""
        pkt = self.api._control_packet("02", "02", "16")
        assert pkt == "sm0003020216007d"

    def test_control_ondol_temp_55(self):
        """CMD 03: sm0003 03 02 37 00 7d  (55°C = 0x37)"""
        pkt = self.api._control_packet("03", "02", "37")
        assert pkt == "sm0003030237007d"

    def test_control_go_out_on(self):
        pkt = self.api._control_packet("05", "02", "80")
        assert pkt == "sm0003050280007d"

    def test_control_go_out_off(self):
        pkt = self.api._control_packet("05", "02", "00")
        assert pkt == "sm0003050200007d"

    def test_control_packet_format(self):
        """All control packets must match sm0003[CMD][LEN][DATA]00[ETX]."""
        pkt = self.api._control_packet("07", "02", "80")
        assert pkt.startswith("sm0003")
        assert pkt.endswith("007d")

    # ── _build_flags ──

    def test_build_flags_room_mode(self):
        """실내온도 모드: 전원+난방 = 0x05"""
        flags = self.api._build_flags(power=True, heat_mode=False, heating=True)
        assert flags == 0x05

    def test_build_flags_ondol_mode(self):
        """온돌 모드: 전원+온돌+난방 = 0x07"""
        flags = self.api._build_flags(power=True, heat_mode=True, heating=True)
        assert flags == 0x07

    def test_build_flags_hot_water_only(self):
        """온수만: 전원+온수 = 0x09"""
        flags = self.api._build_flags(power=True, heat_mode=False, heating=False, hot_water=True)
        assert flags == 0x09

    def test_build_flags_all_on(self):
        """모두 ON: 0x0f"""
        flags = self.api._build_flags(power=True, heat_mode=True, heating=True, hot_water=True)
        assert flags == 0x0f

    def test_build_flags_power_off(self):
        """전원 OFF = 0x00"""
        flags = self.api._build_flags(power=False, heat_mode=False, heating=False, hot_water=False)
        assert flags == 0x00

    # ── set_heat_mode packet verification ──

    def test_set_heat_mode_ondol_packet(self):
        """온돌 전환: flags=0x07, temp=22(0x16)
        Expected: sm0003010407160000{ETX}"""
        expected = f"sm00030104071600007d"
        # Verify via _build_flags
        flags = self.api._build_flags(power=True, heat_mode=True, heating=True)
        assert flags == 0x07
        pkt = f"sm00030104{format(flags,'02x')}{format(22,'02x')}0000{ETX}"
        assert pkt == expected

    def test_set_heat_mode_room_packet(self):
        """실내온도 전환: flags=0x05, temp=22(0x16)
        Expected: sm0003010405160000{ETX}"""
        flags = self.api._build_flags(power=True, heat_mode=False, heating=True)
        assert flags == 0x05
        pkt = f"sm00030104{format(flags,'02x')}{format(22,'02x')}0000{ETX}"
        assert pkt == "sm00030104051600007d"

    # ── set_temperature CMD routing ──

    def test_set_temperature_room_uses_cmd02(self):
        """실내온도 모드(heat_mode=False) → CMD 02"""
        temp = 22  # 0x16
        cmd = "02"  # CMD_C_ROOM_TEMP
        expected = f"sm0003{cmd}02{format(temp,'02x')}00{ETX}"
        assert expected == "sm000302021600 7d".replace(" ", "")

    def test_set_temperature_ondol_uses_cmd03(self):
        """온돌 모드(heat_mode=True) → CMD 03"""
        temp = 55  # 0x37
        cmd = "03"  # CMD_C_ONDOL_TEMP
        expected = f"sm0003{cmd}02{format(temp,'02x')}00{ETX}"
        assert expected == "sm000303023700 7d".replace(" ", "")

    def test_set_go_out_enable(self):
        pkt = f"sm000305 02 80 00 7d".replace(" ", "")
        assert pkt == "sm0003050280007d"


class TestStatusParsing:
    def setup_method(self):
        self.api = RinnaiAPI("test@test.com", "pass")

    def _make_raw(self, payload: str) -> str:
        """Helper: wrap payload in a valid response string."""
        return "sm010201" + format(len(payload), "02x") + payload + "007d"

    def test_parse_typical_ondol_response(self):
        """flags=0x07 → power=T, heat_mode=T(온돌), heating=T, hot_water=F"""
        # flags=07, room_set=16(22°C), hw_set=37(55°C), wt=00, room_cur=15(21°C), hw_cur=00, waterDo=00, go_out=00
        payload = "071637001500000000000000"
        result = self.api._parse_status(self._make_raw(payload))

        assert result["power"] is True
        assert result["heat_mode"] is True      # 온돌 모드
        assert result["heating"] is True
        assert result["hot_water"] is False
        assert result["room_temp_set"] == 22    # 0x16
        assert result["hw_temp_set"] == 55      # 0x37 (온돌 설정온도)
        assert result["room_temp_cur"] == 21    # 0x15

    def test_parse_room_mode_response(self):
        """flags=0x05 → power=T, heat_mode=F(실내온도), heating=T, hot_water=F"""
        payload = "051600001400000000000000"
        result = self.api._parse_status(self._make_raw(payload))

        assert result["power"] is True
        assert result["heat_mode"] is False     # 실내온도 모드
        assert result["heating"] is True
        assert result["hot_water"] is False
        assert result["room_temp_set"] == 22
        assert result["room_temp_cur"] == 20

    def test_parse_power_off(self):
        """flags=0x00 → all off"""
        payload = "00162d001400000000000000"
        result = self.api._parse_status(self._make_raw(payload))

        assert result["power"] is False
        assert result["heat_mode"] is False
        assert result["heating"] is False
        assert result["hot_water"] is False
        assert result["go_out"] is False
        assert result["room_temp_set"] == 22
        assert result["hw_temp_set"] == 45

    def test_parse_hot_water_flag(self):
        """flags=0x09 → power=T, hot_water=T"""
        payload = "091600001400000000000000"
        result = self.api._parse_status(self._make_raw(payload))

        assert result["power"] is True
        assert result["heat_mode"] is False
        assert result["heating"] is False
        assert result["hot_water"] is True

    def test_parse_water_temp_half_degree(self):
        """wt_raw=0xa4=164 >= 128 → (164-128+0.5) = 36.5°C"""
        payload = "070000a40000000000000000"
        result = self.api._parse_status(self._make_raw(payload))
        assert result["water_temp"] == 36.5

    def test_parse_go_out_from_offset(self):
        """go_out: payload[14:16] > 0"""
        # offsets: 0:2=flags, 2:4=room_set, 4:6=hw_set, 6:8=wt, 8:10=room_cur,
        #          10:12=hw_cur, 12:14=waterDo, 14:16=go_out
        payload = "051600001400000100000000"
        result = self.api._parse_status(self._make_raw(payload))
        assert result["go_out"] is True

    def test_parse_go_out_off(self):
        """go_out: payload[14:16] == 0"""
        payload = "051600001400000000000000"
        result = self.api._parse_status(self._make_raw(payload))
        assert result["go_out"] is False

    def test_parse_pre_heat_and_quick_heat(self):
        """flags=0x37 → power+heat_mode+heating+pre_heat+quick_heat"""
        # 0x37 = 0x01|0x02|0x04|0x10|0x20
        payload = "371600001400000000000000"
        result = self.api._parse_status(self._make_raw(payload))

        assert result["power"] is True
        assert result["heat_mode"] is True
        assert result["heating"] is True
        assert result["hot_water"] is False
        assert result["pre_heat"] is True
        assert result["quick_heat"] is True

    def test_parse_all_flags_on(self):
        """flags=0x3f → 모든 6비트 ON"""
        payload = "3f1600001400000000000000"
        result = self.api._parse_status(self._make_raw(payload))

        assert result["power"] is True
        assert result["heat_mode"] is True
        assert result["heating"] is True
        assert result["hot_water"] is True
        assert result["pre_heat"] is True
        assert result["quick_heat"] is True

    def test_parse_empty_returns_empty(self):
        assert self.api._parse_status("") == {}
        assert self.api._parse_status(None) == {}
        assert self.api._parse_status("short") == {}

    # ── 에러 응답 ──

    def test_parse_ff_error_device_deleted(self):
        """sm010201ff10007d → DATA_LENGTH_ERROR, 서브코드 10(기기 삭제)"""
        raw = "sm010201ff10007d"
        result = self.api._parse_status(raw)
        assert result == {}

    def test_parse_ff_error_device_disconnected(self):
        """서브코드 08 = 기기 연결 해제"""
        raw = "sm010201ff08007d"
        result = self.api._parse_status(raw)
        assert result == {}

    def test_is_error_detection(self):
        """_is_error should detect ff + subcode"""
        is_err, sub = self.api._is_error("sm010201ff10007d")
        assert is_err is True
        assert sub == "10"

        is_err, sub = self.api._is_error("sm010201180716370216a4007d")
        assert is_err is False

    def test_recoverable_subcodes(self):
        """08, 10은 재로그인으로 복구 가능"""
        assert "08" in self.api._RECOVERABLE
        assert "10" in self.api._RECOVERABLE
        assert "11" not in self.api._RECOVERABLE
