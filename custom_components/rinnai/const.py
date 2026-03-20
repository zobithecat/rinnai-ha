import os
import base64

DOMAIN = "rinnai"

BASE_URL = base64.b64decode(
    os.environ.get("RINNAI_BASE_URL_B64", "aHR0cHM6Ly93aWZpQm9pbGVyczEucmlubmFpLmNvLmtyOjExNDQz")
).decode()
URL_USER    = f"{BASE_URL}/user"
URL_QUERY   = f"{BASE_URL}/query"
URL_CONTROL = f"{BASE_URL}/control"

HMAC_KEY = bytes.fromhex(
    os.environ.get("RINNAI_HMAC_KEY_HEX", "52696e6e6169536d6172744b6579")
)

ETX = "7d"

# 조회 명령코드 (sm0002)
CMD_Q_STATUS      = "01"  # 전체 상태
CMD_Q_BOOK_ONOFF  = "03"  # 예약 ON/OFF

# 제어 명령코드 (sm0003)
CMD_C_POWER       = "01"  # 전원/난방/온수
CMD_C_ROOM_TEMP   = "02"  # 실내온도 (heat_mode=False, 10~40°C)
CMD_C_ONDOL_TEMP  = "03"  # 온돌온도 (heat_mode=True, 20~80°C)
CMD_C_WATER_TEMP  = "04"  # 온수사용온도
CMD_C_GO_OUT      = "05"  # 외출모드
CMD_C_MODE        = "06"  # 모드
CMD_C_SAVE        = "07"  # 절약모드
CMD_C_SLEEP       = "08"  # 취침모드
