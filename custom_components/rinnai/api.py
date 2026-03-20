import hmac
import hashlib
import base64
import json
import ssl
import logging
import urllib.request

from .const import (
    URL_USER, URL_QUERY, URL_CONTROL,
    ETX, CMD_Q_STATUS,
    CMD_C_POWER, CMD_C_ROOM_TEMP, CMD_C_ONDOL_TEMP,
    CMD_C_GO_OUT, CMD_C_SAVE, CMD_C_SLEEP,
    HMAC_KEY,
)

_LOGGER = logging.getLogger(__name__)


def _hash_password(password: str) -> str:
    """HmacSHA1 + Base64 패스워드 해싱"""
    return base64.b64encode(
        hmac.new(HMAC_KEY, password.encode(), hashlib.sha1).digest()
    ).decode().strip()


def _ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class RinnaiAPI:
    def __init__(self, email: str, password: str):
        self._email = email
        self._password = password
        self._device_id: str = None
        self._room_control_id: str = None
        self._ctx = _ssl_context()

    # ──────────────────────────────────────────────
    # 내부 HTTP 헬퍼
    # ──────────────────────────────────────────────

    def _post_json(self, url: str, payload: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, context=self._ctx) as res:
            return json.loads(res.read())

    def _post_plain(self, url: str, body: str) -> str:
        req = urllib.request.Request(
            url,
            data=body.encode(),
            headers={
                "Content-Type": "text/plain",
                "Accept": "text/plain",
                "RoomControlId": self._room_control_id,
                "DeviceId": self._device_id,
            },
        )
        with urllib.request.urlopen(req, context=self._ctx) as res:
            return res.read().decode()

    # ──────────────────────────────────────────────
    # 패킷 빌더
    # ──────────────────────────────────────────────

    def _query_packet(self, cmd: str) -> str:
        return f"sm0002{cmd}00000{ETX}"

    def _control_packet(self, cmd: str, length: str, data: str) -> str:
        return f"sm0003{cmd}{length}{data}00{ETX}"

    # ──────────────────────────────────────────────
    # 로그인
    # ──────────────────────────────────────────────

    def login(self) -> bool:
        """로그인 후 roomControlId / deviceId 획득"""
        try:
            # 1단계: user_check_v2 로 deviceId 확인
            r1 = self._post_json(URL_USER, {
                "query": "search",
                "target": "user_check_v2",
                "deviceId": self._device_id or "homeassistant",
            })
            _LOGGER.debug("user_check_v2: %s", r1)

            # 2단계: id_login
            r2 = self._post_json(URL_USER, {
                "query": "search",
                "target": "id_login",
                "email": self._email,
                "password": _hash_password(self._password),
                "deviceId": self._device_id or "homeassistant",
                "deviceToken": "homeassistant",
                "language": "KOR",
                "appVersion": "homeassistant",
                "agreementVersion": "",
            })
            _LOGGER.debug("id_login: %s", r2)

            if r2.get("result") != "OK":
                _LOGGER.error("로그인 실패: %s", r2)
                return False

            boilers = r2.get("boilerData", [])
            users   = r2.get("userData", [])

            if not boilers:
                _LOGGER.error("등록된 보일러 없음")
                return False

            self._room_control_id = boilers[0]["roomControlId"]
            if users:
                self._device_id = users[0].get("deviceId", "homeassistant")

            _LOGGER.info(
                "로그인 성공 | roomControlId=%s deviceId=%s",
                self._room_control_id, self._device_id
            )
            return True

        except Exception as e:
            _LOGGER.error("로그인 예외: %s", e)
            return False

    # ──────────────────────────────────────────────
    # 에러 감지 / 자동 재로그인
    # ──────────────────────────────────────────────

    # 서브코드 (프로토콜 가이드 §3)
    _ERR_SUBCODES = {
        "08": "기기 연결 해제",
        "10": "기기 삭제됨",
        "11": "에러 상태",
        "12": "에러 + 삭제",
    }
    # 재로그인으로 복구 가능한 서브코드
    _RECOVERABLE = {"08", "10"}

    def _is_error(self, raw: str) -> tuple[bool, str]:
        """응답에서 ff 에러 + 서브코드 추출. (is_error, subcode)"""
        if raw and len(raw) >= 12 and raw[8:10] == "ff":
            return True, raw[10:12]
        return False, ""

    def _retry_on_device_error(self, fn, *args) -> str:
        """
        요청 실행 → ff + 08/10 에러 시 재로그인 후 1회 재시도.
        성공 시 raw 응답 반환, 실패 시 원본 에러 응답 반환.
        """
        raw = fn(*args)
        is_err, sub = self._is_error(raw)
        if is_err and sub in self._RECOVERABLE:
            desc = self._ERR_SUBCODES.get(sub, sub)
            _LOGGER.warning("디바이스 에러(%s: %s) → 재로그인 시도", sub, desc)
            if self.login():
                _LOGGER.info("재로그인 성공, 재시도")
                raw = fn(*args)
            else:
                _LOGGER.error("재로그인 실패")
        return raw

    # ──────────────────────────────────────────────
    # 상태 조회
    # ──────────────────────────────────────────────

    def get_status(self) -> dict:
        """보일러 전체 상태 조회 및 파싱 (에러 시 자동 재로그인)"""
        try:
            raw = self._retry_on_device_error(
                self._post_plain, URL_QUERY, self._query_packet(CMD_Q_STATUS),
            )
            _LOGGER.debug("status raw: %s", raw)
            return self._parse_status(raw)
        except Exception as e:
            _LOGGER.error("상태 조회 실패: %s", e)
            return {}

    def _parse_status(self, raw: str) -> dict:
        if not raw or len(raw) < 10:
            return {}
        is_err, sub = self._is_error(raw)
        if is_err:
            desc = self._ERR_SUBCODES.get(sub, sub)
            _LOGGER.error("상태 응답 에러: %s (%s) | raw=%s", desc, sub, raw)
            return {}
        try:
            data_len = int(raw[8:10], 16)
            payload  = raw[10:10 + data_len]

            flags    = int(payload[0:2], 16)
            room_set = int(payload[2:4], 16)
            hw_set   = int(payload[4:6], 16)
            wt_raw   = int(payload[6:8], 16)
            room_cur = int(payload[8:10], 16)
            hw_raw   = int(payload[10:12], 16)
            go_out   = int(payload[14:16], 16) if len(payload) >= 16 else 0

            water_temp = (wt_raw - 128 + 0.5) if wt_raw >= 128 else float(wt_raw)
            hw_cur     = (hw_raw - 128 + 0.5) if hw_raw >= 128 else float(hw_raw)

            return {
                "power":         bool(flags & 0x01),  # bit0: isPwrOn
                "heat_mode":     bool(flags & 0x02),  # bit1: isHeatMode (True=온돌, False=실내온도)
                "heating":       bool(flags & 0x04),  # bit2: isHeatOn
                "hot_water":     bool(flags & 0x08),  # bit3: isHeatWater
                "pre_heat":      bool(flags & 0x10),  # bit4: isPreHeat
                "quick_heat":    bool(flags & 0x20),  # bit5: isQuickHeat
                "go_out":        go_out > 0,
                "room_temp_set": room_set,             # CMD 02 대상 (실내온도)
                "room_temp_cur": room_cur,
                "hw_temp_set":   hw_set,               # CMD 03 대상 (온돌)
                "hw_temp_cur":   hw_cur,
                "water_temp":    water_temp,
            }
        except Exception as e:
            _LOGGER.error("파싱 실패: %s | raw=%s", e, raw)
            return {}

    # ──────────────────────────────────────────────
    # 제어
    # ──────────────────────────────────────────────

    def _control(self, packet: str) -> bool:
        """제어 패킷 전송 (에러 시 자동 재로그인 + 재시도)"""
        try:
            raw = self._retry_on_device_error(
                self._post_plain, URL_CONTROL, packet,
            )
            is_err, sub = self._is_error(raw)
            if is_err:
                desc = self._ERR_SUBCODES.get(sub, sub)
                _LOGGER.error("제어 에러: %s (%s)", desc, sub)
                return False
            return True
        except Exception as e:
            _LOGGER.error("제어 실패: %s", e)
            return False

    def _build_flags(self, power: bool = True, heat_mode: bool = False,
                     heating: bool = True, hot_water: bool = False) -> int:
        """
        CMD 01 FLAGS 비트맵 (프로토콜 가이드 §6 기준)
          bit0=0x01 전원, bit1=0x02 온돌모드, bit2=0x04 난방, bit3=0x08 온수
        """
        return (
            (0x01 if power     else 0) |
            (0x02 if heat_mode else 0) |
            (0x04 if heating   else 0) |
            (0x08 if hot_water else 0)
        )

    def set_power(self, power: bool, heat_mode: bool = False,
                  heating: bool = True, hot_water: bool = False,
                  temp: int = 0) -> bool:
        """CMD 01: sm0003 01 04 [FLAGS] [TEMP] 00 00 7d"""
        flags = self._build_flags(power, heat_mode, heating, hot_water)
        return self._control(
            f"sm00030104{format(flags,'02x')}{format(temp,'02x')}0000{ETX}"
        )

    def set_heat_mode(self, ondol: bool, current_temp: int = 22) -> bool:
        """
        온돌/실내온도 모드 전환 (CMD 01 flags bit1)
        ondol=True  → flags=0x07 (전원+온돌+난방)
        ondol=False → flags=0x05 (전원+난방)
        """
        return self.set_power(
            power=True, heat_mode=ondol, heating=True,
            hot_water=False, temp=current_temp,
        )

    def set_temperature(self, temp: int, heat_mode: bool = False) -> bool:
        """
        모드에 따라 적절한 CMD로 온도 설정
        heat_mode=False → CMD 02 실내온도 (10~40°C)
        heat_mode=True  → CMD 03 온돌온도 (20~80°C)
        """
        cmd = CMD_C_ONDOL_TEMP if heat_mode else CMD_C_ROOM_TEMP
        t_hex = format(temp, "02x")
        return self._control(
            f"sm0003{cmd}02{t_hex}00{ETX}"
        )

    def set_go_out(self, enable: bool) -> bool:
        data = "80" if enable else "00"
        return self._control(
            f"sm000305 02 {data} 00 {ETX}".replace(" ", "")
        )

    def set_save_mode(self, enable: bool) -> bool:
        data = "80" if enable else "00"
        return self._control(
            f"sm000307 02 {data} 00 {ETX}".replace(" ", "")
        )

    def set_sleep_mode(self, enable: bool) -> bool:
        data = "80" if enable else "00"
        return self._control(
            f"sm000308 02 {data} 00 {ETX}".replace(" ", "")
        )
