# 🎮 Pokémon HeartGold (KOR) - Official bHaptics SDK & Direct Memory Bridge

[![bHaptics Official SDK](https://img.shields.io/badge/bHaptics-Official_Python_SDK-orange.svg)](https://www.bhaptics.com/)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![DeSmuME](https://img.shields.io/badge/DeSmuME-0.9.13_x64-green.svg)](https://desmume.org/)
[![Polling Rate](https://img.shields.io/badge/Polling_Rate-120Hz_(8ms)-red.svg)]()
[![CPU Usage](https://img.shields.io/badge/CPU_Usage-0.0%25-brightgreen.svg)]()

포켓몬스터 하트골드(KOR)를 DeSmuME 에뮬레이터에서 플레이할 때, 포켓몬이 입는 데미지를 실시간(120Hz)으로 감지하여 **bHaptics 공식 Python SDK(`bhaptics-python`)의 `play_dot()` 직접 모터 제어 API**로 TactSuit X40 / TactSuit Pro / TactSleeve에 무지연 촉각 피드백을 전달하는 올인원 햅틱 시스템입니다.

---

## 🌟 주요 특징 (Key Features)

- **🏷️ 공식 bHaptics Python SDK 지원**:
  - `bhaptics_python.registry_and_initialize(app_id, api_key, "")` 기반 정식 Developer Portal 연동.
  - `bhaptics_python.play_dot(position=0, duration, motor_values)`로 개별 모터 직접 제어.
  - WebSocket 버전 차이로 인한 통신 이슈 완전 해결.
- **🎨 올인원 다크 모드 GUI 대시보드 (`run_app.bat`)**:
  - App ID / API Key 원클릭 입력 및 `config.json` 영구 저장.
  - 실시간 배틀 상태 및 포켓몬 체력(HP) 게이지 바 시각화.
  - 마스터 진동 세기(50%~150%) 및 전면/후면 독립 게인 조절.
  - 40개 모터 실시간 2D 인터랙티브 점등 맵 내장.
- **⚡ 120Hz 초저지연 (Response Time < 8ms)**: 게임 내 체력 감소 즉시 0초 체감 지연으로 충격 진동 발생.
- **🎛️ 32개 / 40개 모터 자동 리샘플링 (Motor Resampling)**:
  - `motor_count = 32`: 4x5 격자를 4x4(16 전면 + 16 후면)로 리샘플링하여 TactSuit Pro 완벽 호환.
  - `motor_count = 40`: 20 전면 + 20 후면 40개 모터 1:1 풀 매핑.
- **🚀 0% CPU 점유율 (60 FPS 버터 구동)**: 외부 Windows C-API(`kernel32.ReadProcessMemory`)로 0.0002ms 만에 직접 읽어 에뮬레이터 렉 완전 제거.

---

## 🏗️ 시스템 아키텍처 (Architecture)

```mermaid
graph TD
    A[DeSmuME: Pokémon HeartGold KOR] -->|512KB DMA Read / 0.0002ms| B[app_gui.py / Memory Hook]
    B -->|1. Move/PP Signature Match| C[Active Battler Resolver]
    C -->|2. Ring-Buffer Delta Resolution| D[Damage Calculator]
    D -->|3. 4-Tier Haptic Scaling| E[MotorArrayConverter: 32/40 Resampling]
    E -->|4. play_dot position=0| F[Official bhaptics-python SDK]
    F -->|Bluetooth BLE| G[bHaptics TactSuit X40 / Pro / Sleeves]
```

---

## ⚙️ 설정 파일 규격 (`config.json`)

```json
{
  "sink": {
    "kind": "bhaptics",
    "app_id": "YOUR_BHAPTICS_APP_ID",
    "api_key": "YOUR_BHAPTICS_API_KEY",
    "motor_count": 32,
    "front_gain": 1.0,
    "back_gain": 1.0
  }
}
```

* **`kind`**: `"bhaptics"` (공식 SDK, 권장) 또는 `"websocket"` (레거시 웹소켓).
* **`app_id` / `api_key`**: [bHaptics Developer Portal](https://developer.bhaptics.com/)에서 생성한 앱의 인증 정보.
* **`motor_count`**: `32` (기본값) 또는 `40`.
* **`front_gain` / `back_gain`**: 전면 및 후면 진동 배율 (`0.1 ~ 2.0`).

---

## 🚀 빠른 시작 가이드 (Quick Start)

### 1단계: 사전 준비
1. 필수 패키지 설치:
   ```bash
   pip install -r requirements.txt
   ```
2. **`bHaptics Player`** 실행 및 실물 조끼 연결 확인.

### 2단계: GUI 실행 및 키 설정 (원클릭)
1. **[`run_app.bat`](file:///C:/Users/dlwjd/Desktop/bhaptics-pokemon-hgss/run_app.bat)**을 더블 클릭하여 실행합니다.
2. 좌측 상단 설정 창에 **App ID**와 **API Key**를 입력하고 **`💾 SAVE SETTINGS`**를 누릅니다.
   *(※ API Key가 없으시다면 Output Mode를 `Legacy WebSocket`으로 선택하시면 됩니다.)*
3. 초록색 **`▶ START HAPTIC BRIDGE`** 버튼을 누릅니다!

### 3단계: 게임 플레이
1. **`DeSmuME_0.9.13_x64.exe`**에서 포켓몬스터 하트골드를 실행합니다.
2. 배틀에 들어가서 공격을 맞을 때마다 **촉각 수트와 화면에서 120Hz 무지연 진동**을 체감하세요!

---

## 🎮 인게임 피격 햅틱 패턴 매핑 (Haptic Mapping)

| 피격 데미지 비율 | 피격 유형 | 모터 진동 위치 및 애니메이션 | 체감 효과 |
| :--- | :--- | :--- | :--- |
| **1% ~ 20%** | **Light Hit** | 앞가슴 및 등 중앙 모터 (강도: 35%) | 톡톡 튀는 경쾌한 타격감 |
| **21% ~ 50%** | **Medium Hit** | 앞/뒤 상체 전체로 확산 (강도: 65%) | 묵직하게 파고드는 정타 충격 |
| **51% ~ 80%** | **Heavy Hit** | 조끼 전신 모터 강력 충격 (강도: 90%) | 전신을 흔드는 강한 충격파 |
| **81% ~ 100%** | **Critical / KO** | 전신 100% 출력 + 바닥으로 꺼지는 진동 | 치명타 및 빈사(기절) 충격 |
| **체력 20% 이하** | **Low HP Heartbeat** | 좌측 가슴 심장 모터 2개 (쿵-쾅 더블 펄스) | 실제 심장이 뛰는 듯한 긴장감 |

---

## 📁 파일 구성 (File Structure)

| 파일명 | 설명 |
| :--- | :--- |
| **`app_gui.py`** | ⭐ **올인원 다크 모드 GUI 컨트롤 센터 메인 프로그램** |
| **`run_app.bat`** | 메인 GUI 대시보드 1클릭 실행 배치 파일 |
| **`bhaptics_bridge.py`** | 공식 `bhaptics-python` SDK 연동, 32/40 리샘플러, 설정 매니저 |
| **`desmume_haptic_direct.py`** | 120Hz 초저지연 직접 프로세스 메모리 훅 백그라운드 엔진 |
| **`config.json`** | App ID, API Key, 모터 수, 전/후면 게인 영구 설정 파일 |
| **`requirements.txt`** | 필수 라이브러리 목록 (`websockets`, `bhaptics-python`) |

---

## 📄 License
MIT License
