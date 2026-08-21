"""
bHaptics TactSuit Bridge for Pokemon HeartGold (KOR) - DeSmuME
Author: Antigravity Pair Programmer
Description:
    Listens for UDP packets from DeSmuME Lua script and sends real-time
    haptic vibration patterns to bHaptics Player via WebSocket.
"""

import argparse
import asyncio
import json
import logging
import socket
import sys
import threading
import time
from typing import Dict, List, Optional

try:
    import websockets
    import websockets.exceptions
except ImportError:
    websockets = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("bHapticsBridge")

# Default configurations
DEFAULT_WS_URL = "ws://localhost:15881/v2/feedbacks"
DEFAULT_UDP_PORT = 8765

class HapticPatternGenerator:
    """Generates TactSuit DotPoints frames according to damage severity."""

    @staticmethod
    def get_pattern(damage_ratio: float, is_fainted: bool) -> List[Dict]:
        """
        Builds submission payload for bHaptics Player WebSocket.
        Position: 'VestFront', 'VestBack'
        DotPoints: list of {'Index': int, 'Intensity': int} (0-100)
        """
        frames = []

        if is_fainted:
            # [기절 / Faint] 전신 강타 후 바닥으로 꺼지는 롱 럼블링
            front_dots = [{"Index": i, "Intensity": 100} for i in range(20)]
            back_dots = [{"Index": i, "Intensity": 80} for i in range(20)]
            frames.append({
                "Position": "VestFront",
                "DurationMillis": 1000,
                "DotPoints": front_dots
            })
            frames.append({
                "Position": "VestBack",
                "DurationMillis": 1000,
                "DotPoints": back_dots
            })

        elif damage_ratio <= 0.20:
            # [경타 / Light Hit: 1~20%] 가슴 상단 가벼운 탭 (160ms)
            intensity = int(25 + (damage_ratio / 0.20) * 20)  # 25~45%
            front_dots = [{"Index": i, "Intensity": intensity} for i in [4, 5, 6, 7]]
            frames.append({
                "Position": "VestFront",
                "DurationMillis": 160,
                "DotPoints": front_dots
            })

        elif damage_ratio <= 0.50:
            # [중타 / Medium Hit: 21~50%] 가슴 + 명치 + 등 반동 (300ms)
            normalized = (damage_ratio - 0.20) / 0.30
            intensity = int(45 + normalized * 30)  # 45~75%
            front_dots = [{"Index": i, "Intensity": intensity} for i in [4, 5, 6, 7, 8, 9, 10, 11, 12, 13]]
            back_dots = [{"Index": i, "Intensity": int(intensity * 0.4)} for i in [8, 9, 10, 11]]
            frames.append({
                "Position": "VestFront",
                "DurationMillis": 300,
                "DotPoints": front_dots
            })
            frames.append({
                "Position": "VestBack",
                "DurationMillis": 300,
                "DotPoints": back_dots
            })

        elif damage_ratio <= 0.80:
            # [강타 / Heavy Hit: 51~80%] 상체 전신 관통 충격파 (480ms)
            normalized = (damage_ratio - 0.50) / 0.30
            intensity = int(75 + normalized * 20)  # 75~95%
            front_dots = [{"Index": i, "Intensity": intensity} for i in range(20)]
            back_dots = [{"Index": i, "Intensity": int(intensity * 0.7)} for i in range(20)]
            frames.append({
                "Position": "VestFront",
                "DurationMillis": 480,
                "DotPoints": front_dots
            })
            frames.append({
                "Position": "VestBack",
                "DurationMillis": 480,
                "DotPoints": back_dots
            })

        else:
            # [치명타 / 일격필살: 81~100%] 최대 강도 전신 폭발 진동 (650ms)
            front_dots = [{"Index": i, "Intensity": 100} for i in range(20)]
            back_dots = [{"Index": i, "Intensity": 100} for i in range(20)]
            frames.append({
                "Position": "VestFront",
                "DurationMillis": 650,
                "DotPoints": front_dots
            })
            frames.append({
                "Position": "VestBack",
                "DurationMillis": 650,
                "DotPoints": back_dots
            })

        return frames

    @staticmethod
    def get_heartbeat_pattern() -> List[Dict]:
        """[저체력 심장박동] 가슴 중앙 심장 박동 펄스"""
        return [{
            "Position": "VestFront",
            "DurationMillis": 120,
            "DotPoints": [
                {"Index": 4, "Intensity": 45},
                {"Index": 8, "Intensity": 60}
            ]
        }]


class BHapticsBridge:
    def __init__(self, ws_url: str = DEFAULT_WS_URL, udp_port: int = DEFAULT_UDP_PORT, enable_heartbeat: bool = True):
        self.ws_url = ws_url
        self.udp_port = udp_port
        self.enable_heartbeat = enable_heartbeat

        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.ws_connection = None
        self.is_running = True

        # State tracking
        self.cur_hp = -1
        self.max_hp = -1
        self.last_damage_time = 0.0

    async def send_frames(self, key: str, frames: List[Dict]):
        """Submits haptic frames to bHaptics Player WebSocket."""
        if not self.ws_connection or self.ws_connection.closed:
            return

        submit_list = [{"Type": "turnOff", "Key": key}]
        for frame in frames:
            submit_list.append({
                "Type": "frame",
                "Key": key,
                "Frame": frame
            })

        payload = {"Submit": submit_list}
        try:
            await self.ws_connection.send(json.dumps(payload))
        except Exception as e:
            logger.error(f"Failed to send haptic frame: {e}")

    async def heartbeat_loop(self):
        """Periodically triggers heartbeat pulses when HP <= 20%."""
        while self.is_running:
            try:
                await asyncio.sleep(1.2)
                now = time.time()
                # If recently took hit (< 1.0s), skip heartbeat
                if (now - self.last_damage_time) < 1.0:
                    continue

                if self.enable_heartbeat and self.max_hp > 0 and 0 < self.cur_hp <= (self.max_hp * 0.20):
                    # Double thump (lub-dub)
                    pattern = HapticPatternGenerator.get_heartbeat_pattern()
                    await self.send_frames("PokemonHeartbeat", pattern)
                    await asyncio.sleep(0.18)
                    await self.send_frames("PokemonHeartbeat", pattern)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Heartbeat loop error: {e}")

    async def ws_worker(self):
        """Maintains persistent connection with bHaptics Player."""
        while self.is_running:
            try:
                logger.info(f"Connecting to bHaptics Player at {self.ws_url}...")
                async with websockets.connect(self.ws_url) as ws:
                    self.ws_connection = ws
                    logger.info("Connected to bHaptics Player successfully!")

                    # Process incoming haptic events
                    while self.is_running:
                        event = await self.event_queue.get()
                        damage_ratio = event.get("damage_ratio", 0.0)
                        is_fainted = event.get("is_fainted", False)
                        self.cur_hp = event.get("cur_hp", -1)
                        self.max_hp = event.get("max_hp", -1)
                        self.last_damage_time = time.time()

                        logger.info(
                            f"Triggering Haptics -> Damage: {damage_ratio*100:.1f}%, "
                            f"HP: {self.cur_hp}/{self.max_hp}, Fainted: {is_fainted}"
                        )

                        frames = HapticPatternGenerator.get_pattern(damage_ratio, is_fainted)
                        await self.send_frames("PokemonDamage", frames)

            except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
                logger.warning(f"bHaptics Player not reachable ({e}). Retrying in 3 seconds...")
                self.ws_connection = None
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"Unexpected WebSocket error: {e}. Reconnecting in 3 seconds...")
                self.ws_connection = None
                await asyncio.sleep(3)

    def start_udp_listener(self, loop: asyncio.AbstractEventLoop):
        """Listens on UDP socket for JSON messages from DeSmuME Lua script."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("127.0.0.1", self.udp_port))
        logger.info(f"UDP Listener active on 127.0.0.1:{self.udp_port}")

        while self.is_running:
            try:
                data, _ = sock.recvfrom(2048)
                msg = json.loads(data.decode("utf-8"))
                asyncio.run_coroutine_threadsafe(self.event_queue.put(msg), loop)
            except Exception as e:
                if self.is_running:
                    logger.error(f"UDP packet parse error: {e}")

    async def run(self):
        loop = asyncio.get_running_loop()

        # Start UDP listener thread
        udp_thread = threading.Thread(target=self.start_udp_listener, args=(loop,), daemon=True)
        udp_thread.start()

        # Start background tasks
        ws_task = asyncio.create_task(self.ws_worker())
        hb_task = asyncio.create_task(self.heartbeat_loop())

        await asyncio.gather(ws_task, hb_task)


def main():
    parser = argparse.ArgumentParser(description="bHaptics TactSuit Bridge for Pokemon HGSS (DeSmuME)")
    parser.add_argument("--ws-url", default=DEFAULT_WS_URL, help=f"bHaptics WebSocket URL (default: {DEFAULT_WS_URL})")
    parser.add_argument("--udp-port", type=int, default=DEFAULT_UDP_PORT, help=f"UDP port for DeSmuME (default: {DEFAULT_UDP_PORT})")
    parser.add_argument("--no-heartbeat", action="store_true", help="Disable low HP (<=20 percent) heartbeat vibration")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    bridge = BHapticsBridge(
        ws_url=args.ws_url,
        udp_port=args.udp_port,
        enable_heartbeat=not args.no_heartbeat
    )

    print("=" * 60)
    print("  bHaptics Pokemon HeartGold (KOR) Bridge")
    print(f"  - UDP Port       : {args.udp_port}")
    print(f"  - bHaptics URL   : {args.ws_url}")
    print(f"  - Low HP Pulse   : {'Enabled' if not args.no_heartbeat else 'Disabled'}")
    print("=" * 60)
    print("Press Ctrl+C to exit.\n")

    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        logger.info("Shutting down bridge...")
        sys.exit(0)


if __name__ == "__main__":
    main()
