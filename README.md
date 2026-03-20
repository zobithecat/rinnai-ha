# Rinnai Boiler - Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

린나이 IoT 보일러를 Home Assistant에서 제어하는 커스텀 통합 컴포넌트입니다.

A Home Assistant custom integration for Rinnai IoT boilers (Korean market).

---

## 지원 기능 / Features

| 기능 | Feature | 상태 |
|------|---------|------|
| 전원 ON/OFF | Power ON/OFF | ✅ |
| 난방 제어 | Heating control | ✅ |
| 온수 제어 | Hot water control | ✅ |
| 실내온도 설정 (10~40°C) | Room temperature setting | ✅ |
| 외출 모드 | Away mode | ✅ |
| 절약 모드 | Economy mode | ✅ |
| 취침 모드 | Sleep mode | ✅ |
| 현재 실내온도 (30초 폴링) | Current room temp (30s poll) | ✅ |
| 온수 온도 표시 | Hot water temp display | ✅ |

---

## 설치 방법 / Installation

### HACS (권장 / Recommended)

1. HACS > **세 점 메뉴** > **Custom repositories**
2. URL: `https://github.com/zobithecat/rinnai-ha`, Category: **Integration**
3. HACS > Integrations > **Rinnai Boiler** 설치
4. Home Assistant **재시작**
5. Settings > Devices & Services > **Add Integration** > "Rinnai" 검색

### 수동 설치 / Manual

1. 이 저장소의 `custom_components/rinnai/` 폴더를 다운로드
2. Home Assistant의 `/config/custom_components/rinnai/` 경로에 복사
3. Home Assistant 재시작
4. Settings > Devices & Services > Add Integration > "Rinnai" 검색

---

## 설정 / Configuration

통합 추가 시 린나이 IoT 앱 계정 정보를 입력합니다:

When adding the integration, enter your Rinnai IoT app credentials:

| 필드 | Field | 설명 |
|------|-------|------|
| 이메일 | Email | 린나이 IoT 앱 가입 이메일 / Rinnai IoT app email |
| 비밀번호 | Password | 린나이 IoT 앱 비밀번호 / Rinnai IoT app password |

> **참고**: 린나이 IoT 앱(Android/iOS)에서 먼저 보일러를 등록해야 합니다.
>
> **Note**: You must register your boiler in the Rinnai IoT app first.

---

## HA UI 구성 / Home Assistant UI

이 통합은 `climate` 엔티티를 생성합니다:

This integration creates a `climate` entity:

- **HVAC 모드**: Heat / Off
- **프리셋**: 일반(Normal) / 외출(Away) / 취침(Sleep) / 절약(Save)
- **온도 범위**: 10°C ~ 40°C
- **추가 속성**: 온수 설정/현재 온도, 전원/난방/온수 상태

---

## 문제 해결 / Troubleshooting

### 로그인 실패 / Login Failed

- 린나이 IoT 앱에서 계정이 정상 작동하는지 확인
- 다른 기기에서 로그인된 경우 충돌 가능 — 앱에서 먼저 로그아웃
- HA 로그 확인: Settings > System > Logs > "rinnai" 검색
- Verify your credentials work in the Rinnai IoT app
- Log out from other devices if session conflicts occur

### 상태가 업데이트되지 않음 / Status Not Updating

- 보일러가 Wi-Fi에 연결되어 있는지 확인
- 린나이 서버 접근 가능 여부 확인
- 폴링 간격: 30초
- Check boiler Wi-Fi connection
- Polling interval: 30 seconds

### HACS 설치 실패 / HACS Installation Failed

- HACS 버전이 최신인지 확인
- Custom repository URL 확인: `https://github.com/zobithecat/rinnai-ha`

---

## 디버거 / Debugger

`src/rinnai_debugger.py` — tkinter 기반 GUI 디버거

```bash
python src/rinnai_debugger.py
```

---

## 라이선스 / License

MIT License — [LICENSE](LICENSE)

---

## 면책 조항 / Disclaimer

이 프로젝트는 린나이 주식회사와 관련이 없는 비공식 통합입니다.
개인 사용 목적으로 제작되었으며, 사용에 따른 책임은 사용자에게 있습니다.

This is an unofficial integration and is not affiliated with Rinnai Corporation.
It is provided for personal use only. Use at your own risk.
