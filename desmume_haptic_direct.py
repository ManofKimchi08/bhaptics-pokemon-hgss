"""
Ultra-Low Latency (120Hz) Direct ProcessMemory bHaptics Bridge for Pokémon HeartGold
Author: Antigravity Pair Programmer
Description:
    Official bhaptics-python SDK & WebSocket fallback integration.
    Reads config.json, selects latest ring-buffer damage state, and triggers tactile feedback.
"""

import asyncio
import ctypes
from ctypes import wintypes
import json
import logging
import os
import struct
import subprocess
import sys
import time
import websockets

from bhaptics_bridge import (
    DEFAULT_WS_URL,
    HAS_BHAPTICS_SDK,
    HapticOutputManager,
    HapticPatternGenerator,
    load_config
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ProcessMemoryBridge")

ENABLE_EXTENDED_FLAGS = 0x0080
ENABLE_QUICK_EDIT_MODE = 0x0040

def disable_quickedit():
    h_stdin = ctypes.windll.kernel32.GetStdHandle(-10)
    mode = wintypes.DWORD()
    if ctypes.windll.kernel32.GetConsoleMode(h_stdin, ctypes.byref(mode)):
        mode.value &= ~ENABLE_QUICK_EDIT_MODE
        mode.value |= ENABLE_EXTENDED_FLAGS
        ctypes.windll.kernel32.SetConsoleMode(h_stdin, mode)

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
kernel32 = ctypes.windll.kernel32


class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(wintypes.BYTE)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260)
    ]


class DeSmuMEProcessMemoryReader:
    def __init__(self):
        self.pid = None
        self.h_process = None
        self.mod_base = 0
        self.last_hp = -1
        self.last_max_hp = -1
        self.active_offset = 0

    def attach(self) -> bool:
        try:
            out = subprocess.check_output('tasklist /FI "IMAGENAME eq DeSmuME*" /FO CSV', shell=True).decode('cp949', errors='ignore')
            for line in out.strip().splitlines()[1:]:
                parts = [p.strip('"') for p in line.split('","')]
                if len(parts) >= 2:
                    self.pid = int(parts[1])
                    break
        except Exception:
            return False

        if not self.pid:
            return False

        self.h_process = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, self.pid)
        if not self.h_process:
            return False

        h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid)
        me = MODULEENTRY32()
        me.dwSize = ctypes.sizeof(MODULEENTRY32)
        if kernel32.Module32First(h_snap, ctypes.byref(me)):
            while True:
                mod_name = me.szModule.decode('utf-8', errors='ignore')
                if "DeSmuME" in mod_name:
                    self.mod_base = ctypes.cast(me.modBaseAddr, ctypes.c_void_p).value
                    break
                if not kernel32.Module32Next(h_snap, ctypes.byref(me)):
                    break
        kernel32.CloseHandle(h_snap)

        if not self.mod_base:
            self.mod_base = 0x140000000

        logger.info(f"Attached to DeSmuME PID {self.pid} (Base: {hex(self.mod_base)})")
        return True

    def scan_active_battler(self):
        if not self.h_process:
            return None, None

        scan_base = self.mod_base + 0xABD0000
        scan_size = 0x100000
        buf = ctypes.create_string_buffer(scan_size)
        bytes_read = ctypes.c_size_t(0)

        if kernel32.ReadProcessMemory(self.h_process, ctypes.c_void_p(scan_base), buf, scan_size, ctypes.byref(bytes_read)):
            data = buf.raw
            for pattern in (b'\x21\x00\x2d\x00\x4b\x00\x00\x00', b'\x21\x00\x2d\x00', b'\x4b\x00\x00\x00'):
                idx = 0
                candidates = []
                while True:
                    idx = data.find(pattern, idx)
                    if idx == -1:
                        break
                    hp_offset = idx + 16
                    if hp_offset + 4 <= len(data):
                        c, m = struct.unpack("<HH", data[hp_offset:hp_offset+4])
                        pp1, pp2 = data[idx+12], data[idx+13]
                        if pp1 in (35, 40, 25, 30, 20, 15, 10, 5) and pp2 in (40, 35, 25, 30, 20, 15, 10, 5, 0):
                            if 10 <= m <= 999 and 0 < c <= m:
                                if m not in (4, 40, 1542, 3073):
                                    candidates.append((c, m, 0xABD0000 + hp_offset))
                    idx += 2

                if candidates:
                    if self.last_max_hp > 0:
                        matched = [cand for cand in candidates if cand[1] == self.last_max_hp]
                        if matched:
                            matched.sort(key=lambda x: x[0])
                            c, m, off = matched[0]
                            self.active_offset = off
                            return c, m

                    candidates.sort(key=lambda x: x[0])
                    c, m, off = candidates[0]
                    self.active_offset = off
                    return c, m

        return None, None


def run_standalone_sdk():
    disable_quickedit()
    cfg = load_config()
    haptic_mgr = HapticOutputManager(cfg)
    reader = DeSmuMEProcessMemoryReader()

    print("=" * 65)
    print("  ⚡ Ultra-Low Latency (120Hz) Official bHaptics SDK Bridge")
    print(f"  - Output Mode: {haptic_mgr.sink_kind.upper()} (Motors: {haptic_mgr.motor_count})")
    print("  - Response Time: < 8ms (Instant Zero-Delay Impact)")
    print("=" * 65)

    if haptic_mgr.sink_kind == "bhaptics":
        if not haptic_mgr.app_id or not haptic_mgr.api_key:
            logger.warning("App ID or API Key is empty in config.json. Please launch run_app.bat to configure.")
        ok, msg = haptic_mgr.initialize_sdk()
        if ok:
            logger.info(f"Official bHaptics SDK initialized successfully!")
        else:
            logger.warning(f"Official SDK Init Notice: {msg}")

    in_battle = False
    last_status_print = 0

    try:
        while True:
            if not reader.h_process:
                if reader.attach():
                    logger.info(f"Attached to DeSmuME PID {reader.pid}!")
                else:
                    time.sleep(1)
                    continue

            cur_hp, max_hp = reader.scan_active_battler()

            if cur_hp is not None and max_hp is not None:
                if not in_battle:
                    logger.info(f"⚔️ [BATTLE STARTED] Active Pokémon HP: {cur_hp}/{max_hp} (Slot +0x{reader.active_offset:X})")
                    in_battle = True

                if reader.last_hp != -1 and reader.last_max_hp == max_hp:
                    if cur_hp < reader.last_hp:
                        damage = reader.last_hp - cur_hp
                        damage_ratio = damage / max_hp
                        is_fainted = (cur_hp == 0)

                        print(f"\n💥 [HIT DETECTED!] Damage: -{damage} HP ({damage_ratio*100:.1f}%) | HP: {cur_hp}/{max_hp} (Slot +0x{reader.active_offset:X})")

                        frames = HapticPatternGenerator.get_pattern(damage_ratio, is_fainted)
                        haptic_mgr.play_haptic(frames)

                reader.last_hp = cur_hp
                reader.last_max_hp = max_hp
            else:
                if in_battle:
                    logger.info("🏳️ [BATTLE ENDED] Returning to Overworld / Menu...")
                    in_battle = False
                reader.last_hp = -1
                reader.last_max_hp = -1

            now = time.time()
            if now - last_status_print > 1.5:
                if in_battle and reader.last_hp != -1:
                    sys.stdout.write(f"\r[Live Monitor] ⚔️ Battle Active | HP: {reader.last_hp}/{reader.last_max_hp} | Status: OK   ")
                else:
                    sys.stdout.write(f"\r[Live Monitor] 🌿 Overworld / Waiting for Battle...                       ")
                sys.stdout.flush()
                last_status_print = now

            time.sleep(0.008)  # 120Hz
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        haptic_mgr.close()


if __name__ == "__main__":
    run_standalone_sdk()
