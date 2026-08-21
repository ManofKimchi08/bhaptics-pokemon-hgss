"""
bHaptics Pokémon HeartGold (KOR) - All-in-One GUI Control Center
Author: Antigravity Pair Programmer
Description:
    Modern Dark-Mode GUI Dashboard for seamless 1-click bHaptics TactSuit integration.
    Includes live HP gauge, 2D motor map, connection monitors, intensity slider, and test triggers.
"""

import asyncio
import ctypes
from ctypes import wintypes
import json
import logging
import math
import os
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
import websockets

from bhaptics_bridge import DEFAULT_WS_PORT, DEFAULT_WS_URL, HapticPatternGenerator

# Windows API Constants for Process Memory Read
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


class PokemonHapticApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("bHaptics Pokémon HeartGold - Haptic Control Center")
        self.geometry("960x680")
        self.configure(bg="#0f111a")
        self.resizable(False, False)

        # State variables
        self.is_running = False
        self.gain = 1.0  # Master intensity multiplier (0.5 ~ 1.5)
        self.ws_client = None
        self.loop = None
        self.reader_thread = None

        # Live stats
        self.cur_hp = 0
        self.max_hp = 0
        self.last_hp = -1
        self.last_max_hp = -1
        self.in_battle = False
        self.pid = None
        self.h_process = None
        self.mod_base = 0
        self.active_offset = 0

        # Motor intensities (0.0 ~ 1.0)
        self.front_intensity = [0.0] * 20
        self.back_intensity = [0.0] * 20

        self._setup_styles()
        self._setup_ui()
        self._start_render_loop()

    def _setup_styles(self):
        self.colors = {
            "bg_dark": "#0f111a",
            "bg_card": "#181a26",
            "bg_card_inner": "#222536",
            "accent_blue": "#58a6ff",
            "accent_green": "#3fb950",
            "accent_orange": "#d29922",
            "accent_red": "#f85149",
            "accent_purple": "#bc8cff",
            "text_primary": "#f0f6fc",
            "text_secondary": "#8b949e",
            "btn_bg": "#2b3044",
            "btn_hover": "#383f5a",
        }

    def _setup_ui(self):
        # 1. Top Header Banner
        header = tk.Frame(self, bg=self.colors["bg_card"], height=65, padx=20)
        header.pack(fill="x", side="top")

        title_box = tk.Frame(header, bg=self.colors["bg_card"])
        title_box.pack(side="left", pady=10)

        tk.Label(
            title_box,
            text="⚡ Pokémon HeartGold bHaptics Bridge",
            font=("Segoe UI", 16, "bold"),
            fg=self.colors["accent_blue"],
            bg=self.colors["bg_card"]
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="120Hz Ultra-Low Latency Direct Memory Haptic Control Panel",
            font=("Segoe UI", 9),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg_card"]
        ).pack(anchor="w")

        # Top Right Badges
        badge_box = tk.Frame(header, bg=self.colors["bg_card"])
        badge_box.pack(side="right", pady=12)

        self.lbl_ws_badge = tk.Label(
            badge_box,
            text="● bHaptics: Disconnected",
            font=("Segoe UI", 9, "bold"),
            fg=self.colors["accent_red"],
            bg="#2c1a24",
            padx=10,
            pady=4,
            bd=1,
            relief="solid"
        )
        self.lbl_ws_badge.pack(side="left", padx=4)

        self.lbl_emu_badge = tk.Label(
            badge_box,
            text="● DeSmuME: Searching",
            font=("Segoe UI", 9, "bold"),
            fg=self.colors["text_secondary"],
            bg="#24283b",
            padx=10,
            pady=4,
            bd=1,
            relief="solid"
        )
        self.lbl_emu_badge.pack(side="left", padx=4)

        # 2. Main Content Split (Left: Control & HP / Right: 2D Suit & Logs)
        content = tk.Frame(self, bg=self.colors["bg_dark"], padx=16, pady=12)
        content.pack(fill="both", expand=True)

        left_col = tk.Frame(content, bg=self.colors["bg_dark"], width=460)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right_col = tk.Frame(content, bg=self.colors["bg_dark"], width=460)
        right_col.pack(side="right", fill="both", expand=True, padx=(10, 0))

        # --- LEFT COLUMN ---
        # Card A: Live Pokémon Status & HP Bar
        hp_card = tk.LabelFrame(
            left_col,
            text="  🎮 LIVE POKÉMON BATTLE STATUS  ",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["accent_blue"],
            bg=self.colors["bg_card"],
            padx=16,
            pady=12,
            bd=1,
            relief="solid"
        )
        hp_card.pack(fill="x", pady=(0, 10))

        self.lbl_battle_status = tk.Label(
            hp_card,
            text="🌿 Status: Overworld / Waiting for Battle...",
            font=("Segoe UI", 11, "bold"),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg_card"]
        )
        self.lbl_battle_status.pack(anchor="w", pady=(0, 6))

        # HP Text
        self.lbl_hp_val = tk.Label(
            hp_card,
            text="HP: -- / -- (100%)",
            font=("Segoe UI", 14, "bold"),
            fg=self.colors["accent_green"],
            bg=self.colors["bg_card"]
        )
        self.lbl_hp_val.pack(anchor="w")

        # Custom HP Canvas Bar
        self.hp_canvas = tk.Canvas(hp_card, width=410, height=20, bg="#11131f", highlightthickness=0)
        self.hp_canvas.pack(fill="x", pady=6)
        self._draw_hp_bar(1.0)

        # Card B: Master Controls & Intensity Slider
        ctrl_card = tk.LabelFrame(
            left_col,
            text="  ⚙️ MASTER CONTROLS  ",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["accent_purple"],
            bg=self.colors["bg_card"],
            padx=16,
            pady=12,
            bd=1,
            relief="solid"
        )
        ctrl_card.pack(fill="x", pady=10)

        # Big Main Start/Stop Button
        self.btn_toggle = tk.Button(
            ctrl_card,
            text="▶ START HAPTIC BRIDGE",
            font=("Segoe UI", 12, "bold"),
            bg=self.colors["accent_green"],
            fg="#0f111a",
            activebackground="#2ea043",
            activeforeground="#ffffff",
            relief="flat",
            pady=8,
            command=self.toggle_bridge
        )
        self.btn_toggle.pack(fill="x", pady=(0, 10))

        # Intensity Slider Box
        slider_box = tk.Frame(ctrl_card, bg=self.colors["bg_card"])
        slider_box.pack(fill="x", pady=4)

        self.lbl_gain = tk.Label(
            slider_box,
            text="Haptic Intensity Gain: 100%",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["text_primary"],
            bg=self.colors["bg_card"]
        )
        self.lbl_gain.pack(anchor="w")

        self.slider = ttk.Scale(
            slider_box,
            from_=50,
            to=150,
            value=100,
            orient="horizontal",
            command=self._on_slider_change
        )
        self.slider.pack(fill="x", pady=(4, 0))

        # Card C: Quick Test Triggers
        test_card = tk.LabelFrame(
            left_col,
            text="  ⚡ QUICK TEST TRIGGERS  ",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["accent_orange"],
            bg=self.colors["bg_card"],
            padx=16,
            pady=12,
            bd=1,
            relief="solid"
        )
        test_card.pack(fill="x", pady=10)

        tests_grid = tk.Frame(test_card, bg=self.colors["bg_card"])
        tests_grid.pack(fill="x")

        tests = [
            ("Light Hit (15%)", lambda: self.trigger_manual_test(0.15, False)),
            ("Medium Hit (35%)", lambda: self.trigger_manual_test(0.35, False)),
            ("Heavy Hit (65%)", lambda: self.trigger_manual_test(0.65, False)),
            ("Critical (90%)", lambda: self.trigger_manual_test(0.90, False)),
            ("Fainted (0 HP)", lambda: self.trigger_manual_test(1.0, True)),
            ("Heartbeat Pulse", lambda: self.trigger_manual_heartbeat()),
        ]

        for idx, (label, cmd) in enumerate(tests):
            r, c = idx // 2, idx % 2
            btn = tk.Button(
                tests_grid,
                text=label,
                font=("Segoe UI", 9),
                bg=self.colors["btn_bg"],
                fg=self.colors["text_primary"],
                activebackground=self.colors["btn_hover"],
                activeforeground="#ffffff",
                relief="flat",
                pady=4,
                command=cmd
            )
            btn.grid(row=r, column=c, padx=4, pady=3, sticky="nsew")
        tests_grid.columnconfigure(0, weight=1)
        tests_grid.columnconfigure(1, weight=1)

        # --- RIGHT COLUMN ---
        # Card D: 2D Interactive TactSuit Map
        suit_card = tk.LabelFrame(
            right_col,
            text="  🦺 TACTSUIT X40 REAL-TIME MOTOR MAP  ",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["accent_blue"],
            bg=self.colors["bg_card"],
            padx=10,
            pady=8,
            bd=1,
            relief="solid"
        )
        suit_card.pack(fill="both", expand=True, pady=(0, 8))

        self.canvas = tk.Canvas(suit_card, width=440, height=270, bg="#11131f", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Card E: Live Hit Activity Log
        log_card = tk.LabelFrame(
            right_col,
            text="  📋 REAL-TIME HIT EVENT LOG  ",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg_card"],
            padx=8,
            pady=6,
            bd=1,
            relief="solid"
        )
        log_card.pack(fill="x")

        self.log_box = tk.Text(
            log_card,
            height=6,
            bg="#11131f",
            fg=self.colors["text_primary"],
            font=("Consolas", 9),
            bd=0,
            padx=6,
            pady=4
        )
        self.log_box.pack(fill="both", expand=True)
        self._log_event("System initialized. Click 'START HAPTIC BRIDGE' to begin.")

    def _draw_hp_bar(self, ratio):
        self.hp_canvas.delete("all")
        w = self.hp_canvas.winfo_width() or 410
        h = 20
        ratio = max(0.0, min(1.0, ratio))

        # Background slot
        self.hp_canvas.create_rectangle(0, 0, w, h, fill="#222536", outline="")

        # Bar color
        if ratio > 0.5:
            color = self.colors["accent_green"]
        elif ratio > 0.2:
            color = self.colors["accent_orange"]
        else:
            color = self.colors["accent_red"]

        if ratio > 0:
            self.hp_canvas.create_rectangle(0, 0, int(w * ratio), h, fill=color, outline="")

    def _on_slider_change(self, val):
        self.gain = float(val) / 100.0
        self.lbl_gain.config(text=f"Haptic Intensity Gain: {int(float(val))}%")

    def _log_event(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{timestamp}] {msg}\n")
        self.log_box.see("end")

    def toggle_bridge(self):
        if not self.is_running:
            self.is_running = True
            self.btn_toggle.config(
                text="⏹ STOP HAPTIC BRIDGE",
                bg=self.colors["accent_red"],
                activebackground="#da3633"
            )
            self._log_event("Starting 120Hz Memory Bridge...")
            self.reader_thread = threading.Thread(target=self._bridge_worker, daemon=True)
            self.reader_thread.start()
        else:
            self.is_running = False
            self.btn_toggle.config(
                text="▶ START HAPTIC BRIDGE",
                bg=self.colors["accent_green"],
                activebackground="#2ea043"
            )
            self._log_event("Haptic Bridge stopped.")
            self.lbl_battle_status.config(text="Status: Bridge Stopped", fg=self.colors["text_secondary"])

    def _bridge_worker(self):
        """Background Asyncio Loop handling both WebSocket & 120Hz Process Memory Scan."""
        async def run_loop():
            while self.is_running:
                try:
                    self.after(0, lambda: self._update_badge("ws", False, "Connecting..."))
                    async with websockets.connect(DEFAULT_WS_URL, max_size=None, ping_interval=None) as ws:
                        self.ws_client = ws
                        self.after(0, lambda: self._update_badge("ws", True, "Connected (:15881)"))
                        self.after(0, lambda: self._log_event("Connected to bHaptics Player!"))

                        while self.is_running:
                            # Attach to DeSmuME if not attached
                            if not self.h_process:
                                if self._attach_desmume():
                                    self.after(0, lambda: self._update_badge("emu", True, f"PID {self.pid}"))
                                    self.after(0, lambda: self._log_event(f"Attached to DeSmuME PID {self.pid}!"))
                                else:
                                    self.after(0, lambda: self._update_badge("emu", False, "Searching..."))
                                    await asyncio.sleep(1)
                                    continue

                            cur_hp, max_hp = self._scan_active_battler()

                            if cur_hp is not None and max_hp is not None:
                                if not self.in_battle:
                                    self.in_battle = True
                                    self.after(0, lambda c=cur_hp, m=max_hp: self._on_battle_start(c, m))

                                # Damage Detection
                                if self.last_hp != -1 and self.last_max_hp == max_hp:
                                    if cur_hp < self.last_hp:
                                        damage = self.last_hp - cur_hp
                                        damage_ratio = damage / max_hp
                                        is_fainted = (cur_hp == 0)

                                        self.after(0, lambda d=damage, r=damage_ratio, c=cur_hp, m=max_hp: self._on_hit_detected(d, r, c, m))

                                        # Generate and dispatch scaled haptic pattern
                                        frames = HapticPatternGenerator.get_pattern(damage_ratio, is_fainted)
                                        submit_list = [{"Type": "turnOff", "Key": "PokemonDamage"}]
                                        for frame in frames:
                                            # Apply gain multiplier
                                            dots = frame.get("DotPoints", [])
                                            for dot in dots:
                                                dot["Intensity"] = min(100, int(dot["Intensity"] * self.gain))
                                            submit_list.append({"Type": "frame", "Key": "PokemonDamage", "Frame": frame})

                                        await ws.send(json.dumps({"Submit": submit_list}))
                                        self.after(0, lambda sl=submit_list: self._animate_motors(sl))

                                self.last_hp = cur_hp
                                self.last_max_hp = max_hp
                            else:
                                if self.in_battle:
                                    self.in_battle = False
                                    self.after(0, self._on_battle_end)
                                self.last_hp = -1
                                self.last_max_hp = -1

                            await asyncio.sleep(0.008)  # 120Hz polling

                except (ConnectionRefusedError, OSError):
                    self.after(0, lambda: self._update_badge("ws", False, "Disconnected"))
                    await asyncio.sleep(2)
                except Exception as e:
                    self.after(0, lambda err=str(e): self._log_event(f"Bridge Error: {err}"))
                    await asyncio.sleep(2)

        asyncio.run(run_loop())

    def _attach_desmume(self) -> bool:
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

        return True

    def _scan_active_battler(self):
        if not self.h_process:
            return None, None

        scan_base = self.mod_base + 0xABD0000
        scan_size = 0x100000 # 1MB
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

    def _update_badge(self, target, connected, label_text):
        if target == "ws":
            color = self.colors["accent_green"] if connected else self.colors["accent_red"]
            bg = "#192b20" if connected else "#2c1a24"
            self.lbl_ws_badge.config(text=f"● bHaptics: {label_text}", fg=color, bg=bg)
        elif target == "emu":
            color = self.colors["accent_green"] if connected else self.colors["text_secondary"]
            bg = "#192b20" if connected else "#24283b"
            self.lbl_emu_badge.config(text=f"● DeSmuME: {label_text}", fg=color, bg=bg)

    def _on_battle_start(self, cur_hp, max_hp):
        self.lbl_battle_status.config(text="⚔️ Status: BATTLE ACTIVE", fg=self.colors["accent_green"])
        ratio = cur_hp / max_hp if max_hp > 0 else 1.0
        self.lbl_hp_val.config(text=f"HP: {cur_hp} / {max_hp} ({ratio*100:.0f}%)")
        self._draw_hp_bar(ratio)
        self._log_event(f"Battle started! Pokémon Locked (HP {cur_hp}/{max_hp})")

    def _on_battle_end(self):
        self.lbl_battle_status.config(text="🌿 Status: Overworld / Waiting for Battle...", fg=self.colors["text_secondary"])
        self.lbl_hp_val.config(text="HP: -- / -- (100%)")
        self._draw_hp_bar(1.0)
        self._log_event("Battle ended. Returning to overworld.")

    def _on_hit_detected(self, damage, ratio, cur_hp, max_hp):
        hp_pct = (cur_hp / max_hp) * 100 if max_hp > 0 else 0
        self.lbl_hp_val.config(text=f"HP: {cur_hp} / {max_hp} ({hp_pct:.0f}%)")
        self._draw_hp_bar(cur_hp / max_hp)
        self._log_event(f"💥 [HIT!] -{damage} HP ({ratio*100:.1f}%) | HP: {cur_hp}/{max_hp}")

    def _animate_motors(self, submit_list):
        for item in submit_list:
            if item.get("Type") == "frame":
                frame = item.get("Frame", {})
                pos = frame.get("Position")
                dots = frame.get("DotPoints", [])
                for dot in dots:
                    idx = dot.get("Index", 0)
                    intensity = dot.get("Intensity", 0) / 100.0
                    if pos == "VestFront" and 0 <= idx < 20:
                        self.front_intensity[idx] = max(self.front_intensity[idx], intensity)
                    elif pos == "VestBack" and 0 <= idx < 20:
                        self.back_intensity[idx] = max(self.back_intensity[idx], intensity)

    def trigger_manual_test(self, damage_ratio, is_fainted):
        frames = HapticPatternGenerator.get_pattern(damage_ratio, is_fainted)
        submit_list = [{"Type": "turnOff", "Key": "PokemonDamage"}]
        for frame in frames:
            dots = frame.get("DotPoints", [])
            for dot in dots:
                dot["Intensity"] = min(100, int(dot["Intensity"] * self.gain))
            submit_list.append({"Type": "frame", "Key": "PokemonDamage", "Frame": frame})

        self._animate_motors(submit_list)
        self._log_event(f"Manual Test Triggered: {int(damage_ratio*100)}% Damage Pattern")

        # Also send to live WebSocket if connected
        if self.ws_client:
            asyncio.run_coroutine_threadsafe(self.ws_client.send(json.dumps({"Submit": submit_list})), self.loop)

    def trigger_manual_heartbeat(self):
        pattern = HapticPatternGenerator.get_heartbeat_pattern()
        for dot in pattern[0]["DotPoints"]:
            self.front_intensity[dot["Index"]] = max(self.front_intensity[dot["Index"]], dot["Intensity"] / 100.0)
        self._log_event("Manual Test Triggered: Low HP Heartbeat Pulse")

    def _draw_motors_layout(self, offset_x, title, intensities):
        self.canvas.create_text(offset_x + 95, 18, text=title, fill=self.colors["text_primary"], font=("Segoe UI", 10, "bold"))

        # Vest body silhouette
        self.canvas.create_rectangle(
            offset_x + 10, 36, offset_x + 180, 255,
            outline="#2b3044", width=2, fill="#181a26"
        )

        cols = 4
        start_x = offset_x + 36
        start_y = 60
        spacing_x = 38
        spacing_y = 38
        radius = 12

        for i in range(20):
            r = i // cols
            c = i % cols
            cx = start_x + c * spacing_x
            cy = start_y + r * spacing_y

            val = intensities[i]
            if val <= 0.05:
                color = "#24283b"
                text_color = "#565f89"
            elif val <= 0.40:
                color = "#58a6ff"
                text_color = "#0f111a"
            elif val <= 0.75:
                color = "#d29922"
                text_color = "#0f111a"
            else:
                color = "#f85149"
                text_color = "#0f111a"

            self.canvas.create_oval(
                cx - radius, cy - radius, cx + radius, cy + radius,
                fill=color, outline="#3b4261", width=1.5
            )
            self.canvas.create_text(
                cx, cy,
                text=str(i),
                fill=text_color,
                font=("Segoe UI", 7, "bold")
            )

    def _render(self):
        self.canvas.delete("all")
        self._draw_motors_layout(20, "VEST FRONT (전면)", self.front_intensity)
        self._draw_motors_layout(225, "VEST BACK (후면)", self.back_intensity)

        decay = 0.03
        for i in range(20):
            if self.front_intensity[i] > 0:
                self.front_intensity[i] = max(0.0, self.front_intensity[i] - decay)
            if self.back_intensity[i] > 0:
                self.back_intensity[i] = max(0.0, self.back_intensity[i] - decay)

        self.after(30, self._render)

    def _start_render_loop(self):
        self.after(30, self._render)


if __name__ == "__main__":
    app = PokemonHapticApp()
    app.mainloop()
