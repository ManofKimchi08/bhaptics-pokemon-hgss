"""
bHaptics Bridge Engine for Pokémon HeartGold (KOR) - DeSmuME 0.9.13 x64
Author: Antigravity Pair Programmer
Description:
    Core haptic patterns, scaling algorithms, and WebSocket interface for TactSuit X40 / X16.
"""

import asyncio
import json
import logging
import math
import sys
import time

DEFAULT_UDP_PORT = 8765
DEFAULT_WS_PORT = 15881
DEFAULT_WS_URL = "ws://localhost:15881/v2/feedbacks"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bHapticsBridge")


class HapticPatternGenerator:
    """Generates precise 4-tier damage sensations & heartbeat pulse for TactSuit X40."""

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
        """Top-to-bottom collapse effect when Pokémon faints."""
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
        """Double thump heartbeat pulse on left chest."""
        return [{
            "Position": "VestFront",
            "DotPoints": [
                {"Index": 1, "Intensity": 85},
                {"Index": 5, "Intensity": 70}
            ],
            "DurationMillis": 80
        }]
