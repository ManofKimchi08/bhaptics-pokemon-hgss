"""
bHaptics Bridge Engine for Pokémon HeartGold (KOR) - DeSmuME 0.9.13 x64
Author: Antigravity Pair Programmer
Description:
    Core haptic patterns, scaling algorithms, Official bhaptics-python SDK integration,
    and fallback WebSocket IPC interface.
"""

import asyncio
import json
import logging
import math
import os
import sys
import time

try:
    import bhaptics_python
    HAS_BHAPTICS_SDK = True
except ImportError:
    bhaptics_python = None
    HAS_BHAPTICS_SDK = False

DEFAULT_UDP_PORT = 8765
DEFAULT_WS_PORT = 15881
DEFAULT_WS_URL = "ws://localhost:15881/v2/feedbacks"
CONFIG_FILE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bHapticsBridge")


def load_config() -> dict:
    """Loads config.json or returns sensible defaults."""
    default_cfg = {
        "sink": {
            "kind": "bhaptics",
            "app_id": "",
            "api_key": "",
            "motor_count": 32,
            "front_gain": 1.0,
            "back_gain": 1.0
        }
    }
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "sink" in data:
                    for k, v in default_cfg["sink"].items():
                        if k not in data["sink"]:
                            data["sink"][k] = v
                    return data
        except Exception as e:
            logger.warning(f"Failed to read config.json ({e}), using defaults.")
    return default_cfg


def save_config(cfg: dict) -> bool:
    """Saves dictionary to config.json."""
    try:
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Failed to save config.json: {e}")
        return False


class HapticPatternGenerator:
    """Generates precise 4-tier damage sensations & heartbeat pulse for TactSuit X40 / Pro."""

    @staticmethod
    def get_pattern(damage_ratio: float, is_fainted: bool = False):
        if is_fainted:
            return HapticPatternGenerator._get_fainted_pattern()

        if damage_ratio <= 0.20:
            return HapticPatternGenerator._get_light_pattern(damage_ratio)
        elif damage_ratio <= 0.50:
            return HapticPatternGenerator._get_medium_pattern(damage_ratio)
        elif damage_ratio <= 0.80:
            return HapticPatternGenerator._get_heavy_pattern(damage_ratio)
        else:
            return HapticPatternGenerator._get_critical_pattern(damage_ratio)

    @staticmethod
    def _get_light_pattern(ratio: float):
        intensity = int(25 + (ratio / 0.20) * 20)  # 25% ~ 45%
        return [{
            "Position": "VestFront",
            "DotPoints": [
                {"Index": 5, "Intensity": intensity},
                {"Index": 6, "Intensity": intensity},
                {"Index": 9, "Intensity": intensity},
                {"Index": 10, "Intensity": intensity}
            ],
            "DurationMillis": 150
        }, {
            "Position": "VestBack",
            "DotPoints": [
                {"Index": 5, "Intensity": int(intensity * 0.7)},
                {"Index": 6, "Intensity": int(intensity * 0.7)}
            ],
            "DurationMillis": 150
        }]

    @staticmethod
    def _get_medium_pattern(ratio: float):
        intensity = int(45 + ((ratio - 0.20) / 0.30) * 30)  # 45% ~ 75%
        front_dots = [{"Index": i, "Intensity": intensity} for i in [1, 2, 5, 6, 9, 10, 13, 14]]
        back_dots = [{"Index": i, "Intensity": int(intensity * 0.8)} for i in [1, 2, 5, 6, 9, 10]]
        return [{
            "Position": "VestFront",
            "DotPoints": front_dots,
            "DurationMillis": 250
        }, {
            "Position": "VestBack",
            "DotPoints": back_dots,
            "DurationMillis": 250
        }]

    @staticmethod
    def _get_heavy_pattern(ratio: float):
        intensity = int(75 + ((ratio - 0.50) / 0.30) * 20)  # 75% ~ 95%
        front_dots = [{"Index": i, "Intensity": intensity} for i in range(20) if i not in [0, 3, 16, 19]]
        back_dots = [{"Index": i, "Intensity": intensity} for i in range(20) if i not in [0, 3, 16, 19]]
        return [{
            "Position": "VestFront",
            "DotPoints": front_dots,
            "DurationMillis": 400
        }, {
            "Position": "VestBack",
            "DotPoints": back_dots,
            "DurationMillis": 400
        }]

    @staticmethod
    def _get_critical_pattern(ratio: float):
        intensity = 100
        front_dots = [{"Index": i, "Intensity": intensity} for i in range(20)]
        back_dots = [{"Index": i, "Intensity": intensity} for i in range(20)]
        return [{
            "Position": "VestFront",
            "DotPoints": front_dots,
            "DurationMillis": 600
        }, {
            "Position": "VestBack",
            "DotPoints": back_dots,
            "DurationMillis": 600
        }]

    @staticmethod
    def _get_fainted_pattern():
        frames = []
        for row in range(5):
            indices = [row * 4 + c for c in range(4)]
            front_dots = [{"Index": i, "Intensity": 100 - (row * 15)} for i in indices]
            back_dots = [{"Index": i, "Intensity": 100 - (row * 15)} for i in indices]
            frames.append({
                "Position": "VestFront",
                "DotPoints": front_dots,
                "DurationMillis": 150
            })
            frames.append({
                "Position": "VestBack",
                "DotPoints": back_dots,
                "DurationMillis": 150
            })
        return frames

    @staticmethod
    def get_heartbeat_pattern():
        return [{
            "Position": "VestFront",
            "DotPoints": [
                {"Index": 1, "Intensity": 85},
                {"Index": 5, "Intensity": 70}
            ],
            "DurationMillis": 80
        }]


class MotorArrayConverter:
    """Converts Front 20 + Back 20 motor frames into unified 32 or 40-element SDK arrays."""

    @staticmethod
    def frames_to_motor_array(frames: list, motor_count: int = 32, front_gain: float = 1.0, back_gain: float = 1.0, master_gain: float = 1.0) -> list:
        front_20 = [0] * 20
        back_20 = [0] * 20

        for frame in frames:
            pos = frame.get("Position")
            dots = frame.get("DotPoints", [])
            for dot in dots:
                idx = dot.get("Index", 0)
                val = dot.get("Intensity", 0)
                if pos == "VestFront" and 0 <= idx < 20:
                    front_20[idx] = max(front_20[idx], val)
                elif pos == "VestBack" and 0 <= idx < 20:
                    back_20[idx] = max(back_20[idx], val)

        # Apply gain and clamping
        f_multiplier = front_gain * master_gain
        b_multiplier = back_gain * master_gain
        front_20_scaled = [min(100, max(0, int(v * f_multiplier))) for v in front_20]
        back_20_scaled = [min(100, max(0, int(v * b_multiplier))) for v in back_20]

        if motor_count == 40:
            return front_20_scaled + back_20_scaled

        # motor_count == 32 (TactSuit Pro / 4x4 Resampling: 16 Front + 16 Back)
        # Resample 4x5 grid to 4x4:
        # Rows 0..2 (12 motors) map directly.
        # Row 3 (12..15) and Row 4 (16..19) are merged using max value.
        front_16 = front_20_scaled[0:12] + [max(front_20_scaled[12 + c], front_20_scaled[16 + c]) for c in range(4)]
        back_16 = back_20_scaled[0:12] + [max(back_20_scaled[12 + c], back_20_scaled[16 + c]) for c in range(4)]

        return front_16 + back_16


class HapticOutputManager:
    """Manages output routing between Official bhaptics-python SDK and WebSocket."""

    def __init__(self, config: dict = None):
        self.config = config or load_config()
        self.sink_kind = self.config.get("sink", {}).get("kind", "bhaptics")
        self.app_id = self.config.get("sink", {}).get("app_id", "").strip()
        self.api_key = self.config.get("sink", {}).get("api_key", "").strip()
        self.motor_count = int(self.config.get("sink", {}).get("motor_count", 32))
        self.front_gain = float(self.config.get("sink", {}).get("front_gain", 1.0))
        self.back_gain = float(self.config.get("sink", {}).get("back_gain", 1.0))
        self.is_initialized = False

    def initialize_sdk(self) -> tuple[bool, str]:
        """Initializes the official bhaptics-python SDK."""
        if not HAS_BHAPTICS_SDK or bhaptics_python is None:
            return False, "bhaptics-python package is not installed."

        if not self.app_id or not self.api_key:
            return False, "App ID and API Key are required for official bHaptics SDK."

        try:
            # Official SDK initialization
            bhaptics_python.registry_and_initialize(self.app_id, self.api_key, "")
            self.is_initialized = True
            return True, "bHaptics SDK initialized successfully."
        except Exception as e:
            return False, f"bHaptics SDK init error: {e}"

    def play_haptic(self, frames: list, master_gain: float = 1.0) -> bool:
        """Dispatches haptic frames via the official SDK."""
        if not self.is_initialized or not HAS_BHAPTICS_SDK:
            return False

        try:
            duration_ms = 250
            if frames:
                duration_ms = max(f.get("DurationMillis", 250) for f in frames)

            motor_values = MotorArrayConverter.frames_to_motor_array(
                frames,
                motor_count=self.motor_count,
                front_gain=self.front_gain,
                back_gain=self.back_gain,
                master_gain=master_gain
            )

            # Position 0 = TactSuit / Vest
            bhaptics_python.play_dot(0, duration_ms, motor_values)
            return True
        except Exception as e:
            logger.error(f"Failed to play dot via bHaptics SDK: {e}")
            return False

    def stop_all(self):
        """Stops all active vibrations."""
        if HAS_BHAPTICS_SDK and bhaptics_python is not None:
            try:
                bhaptics_python.stop_all()
            except Exception:
                pass

    def close(self):
        """Closes the official SDK session."""
        if HAS_BHAPTICS_SDK and bhaptics_python is not None:
            try:
                bhaptics_python.stop_all()
                bhaptics_python.close()
                self.is_initialized = False
            except Exception:
                pass
