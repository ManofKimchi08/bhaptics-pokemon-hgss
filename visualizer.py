"""
bHaptics TactSuit PC Visualizer & Simulator
Author: Antigravity Pair Programmer
Description:
    Real-time 2D On-Screen Visualizer for TactSuit X40 (Front 20 + Back 20 motors).
    Displays damage animations, motor intensities, and Pokemon HP bar.
    No physical TactSuit required!
"""

import json
import math
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk

from bhaptics_bridge import DEFAULT_UDP_PORT, HapticPatternGenerator


class TactSuitVisualizer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("bHaptics TactSuit X40 - PC Simulator (Pokemon HGSS)")
        self.geometry("780x620")
        self.configure(bg="#1e1e2e")
        self.resizable(False, False)

        # Motor intensities (0.0 ~ 1.0)
        self.front_intensity = [0.0] * 20
        self.back_intensity = [0.0] * 20

        # In-game stats
        self.cur_hp = 100
        self.max_hp = 100
        self.last_damage_text = "Waiting for battle..."

        self._setup_ui()
        self._start_udp_listener()
        self._start_render_loop()

    def _setup_ui(self):
        # Header title
        title_frame = tk.Frame(self, bg="#1e1e2e")
        title_frame.pack(pady=(12, 4))
        tk.Label(
            title_frame,
            text="bHaptics TactSuit X40 Virtual Simulator",
            font=("Segoe UI", 16, "bold"),
            fg="#cdd6f4",
            bg="#1e1e2e"
        ).pack()

        # HP & Status bar frame
        self.status_frame = tk.Frame(self, bg="#181825", bd=1, relief="solid", padx=16, pady=8)
        self.status_frame.pack(fill="x", padx=24, pady=6)

        self.lbl_hp = tk.Label(
            self.status_frame,
            text="Pokemon HP: -- / --",
            font=("Segoe UI", 12, "bold"),
            fg="#a6e3a1",
            bg="#181825"
        )
        self.lbl_hp.pack(anchor="w")

        self.lbl_hit = tk.Label(
            self.status_frame,
            text="Status: Ready (DeSmuME UDP Listener Active on :8765)",
            font=("Segoe UI", 10),
            fg="#89b4fa",
            bg="#181825"
        )
        self.lbl_hit.pack(anchor="w", pady=(2, 0))

        # Canvas for Front & Back suits
        self.canvas = tk.Canvas(self, width=730, height=360, bg="#11111b", highlightthickness=0)
        self.canvas.pack(pady=10)

        # Control & Test buttons at bottom
        btn_frame = tk.Frame(self, bg="#1e1e2e")
        btn_frame.pack(pady=6)

        tk.Label(btn_frame, text="Quick Test: ", font=("Segoe UI", 10, "bold"), fg="#cdd6f4", bg="#1e1e2e").pack(side="left", padx=4)

        tests = [
            ("Light (15%)", lambda: self.trigger_test(0.15, False)),
            ("Medium (35%)", lambda: self.trigger_test(0.35, False)),
            ("Heavy (65%)", lambda: self.trigger_test(0.65, False)),
            ("Critical (90%)", lambda: self.trigger_test(0.90, False)),
            ("Fainted (0 HP)", lambda: self.trigger_test(1.0, True)),
            ("Heartbeat", lambda: self.trigger_heartbeat()),
        ]

        for name, cmd in tests:
            btn = tk.Button(
                btn_frame,
                text=name,
                command=cmd,
                bg="#313244",
                fg="#cdd6f4",
                activebackground="#45475a",
                activeforeground="#ffffff",
                relief="flat",
                padx=8,
                pady=4,
                font=("Segoe UI", 9)
            )
            btn.pack(side="left", padx=4)

    def trigger_test(self, damage_ratio, is_fainted):
        self.cur_hp = 0 if is_fainted else max(0, int(100 * (1.0 - damage_ratio)))
        self.max_hp = 100
        self.process_haptic_event(damage_ratio, is_fainted, self.cur_hp, self.max_hp)

    def trigger_heartbeat(self):
        pattern = HapticPatternGenerator.get_heartbeat_pattern()
        for dot in pattern[0]["DotPoints"]:
            self.front_intensity[dot["Index"]] = max(self.front_intensity[dot["Index"]], dot["Intensity"] / 100.0)
        self.lbl_hit.config(text="Status: [Low HP Heartbeat Pulse] Double Thump!", fg="#f38ba8")

    def process_haptic_event(self, damage_ratio, is_fainted, cur_hp, max_hp):
        frames = HapticPatternGenerator.get_pattern(damage_ratio, is_fainted)
        for frame in frames:
            pos = frame.get("Position")
            dots = frame.get("DotPoints", [])
            for dot in dots:
                idx = dot["Index"]
                intensity = dot["Intensity"] / 100.0
                if pos == "VestFront" and 0 <= idx < 20:
                    self.front_intensity[idx] = max(self.front_intensity[idx], intensity)
                elif pos == "VestBack" and 0 <= idx < 20:
                    self.back_intensity[idx] = max(self.back_intensity[idx], intensity)

        if max_hp > 0:
            hp_pct = (cur_hp / max_hp) * 100
            hp_color = "#a6e3a1" if hp_pct > 50 else ("#f9e2af" if hp_pct > 20 else "#f38ba8")
            self.lbl_hp.config(text=f"Pokemon HP: {cur_hp} / {max_hp} ({hp_pct:.0f}%)", fg=hp_color)

        if is_fainted:
            self.lbl_hit.config(text="Status: [FAINTED] Pokemon collapsed! 1.0s long vibration.", fg="#f38ba8")
        else:
            self.lbl_hit.config(text=f"Status: [HIT] Damage -{damage_ratio*100:.1f}% received!", fg="#fab387")

    def _draw_motors(self, offset_x, title, intensities):
        # Draw Suit outline
        self.canvas.create_text(offset_x + 140, 24, text=title, fill="#cdd6f4", font=("Segoe UI", 12, "bold"))

        # Vest body silhouette
        self.canvas.create_rectangle(
            offset_x + 20, 46, offset_x + 260, 340,
            outline="#45475a", width=2, fill="#181825"
        )

        # 4 cols x 5 rows = 20 motors layout
        cols = 4
        rows = 5
        start_x = offset_x + 55
        start_y = 75
        spacing_x = 55
        spacing_y = 52
        radius = 16

        for i in range(20):
            r = i // cols
            c = i % cols
            cx = start_x + c * spacing_x
            cy = start_y + r * spacing_y

            val = intensities[i]
            # Color transition: Dark Gray -> Cyan -> Orange -> Red
            if val <= 0.05:
                color = "#313244"
                text_color = "#6c7086"
            elif val <= 0.40:
                color = "#89dceb"  # Light Cyan
                text_color = "#11111b"
            elif val <= 0.75:
                color = "#fab387"  # Orange
                text_color = "#11111b"
            else:
                color = "#f38ba8"  # Hot Pink / Red
                text_color = "#11111b"

            self.canvas.create_oval(
                cx - radius, cy - radius, cx + radius, cy + radius,
                fill=color, outline="#585b70", width=1.5
            )
            self.canvas.create_text(
                cx, cy,
                text=str(i),
                fill=text_color,
                font=("Segoe UI", 8, "bold")
            )

    def _render(self):
        self.canvas.delete("all")

        # Draw Front and Back
        self._draw_motors(40, "VEST FRONT (전면)", self.front_intensity)
        self._draw_motors(410, "VEST BACK (후면)", self.back_intensity)

        # Decay intensities smoothly
        decay = 0.04
        for i in range(20):
            if self.front_intensity[i] > 0:
                self.front_intensity[i] = max(0.0, self.front_intensity[i] - decay)
            if self.back_intensity[i] > 0:
                self.back_intensity[i] = max(0.0, self.back_intensity[i] - decay)

        self.after(30, self._render)

    def _start_render_loop(self):
        self.after(30, self._render)

    def _start_udp_listener(self):
        def listener():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.bind(("127.0.0.1", DEFAULT_UDP_PORT))
            except Exception as e:
                print(f"[Visualizer] UDP Bind Note: {e} (Will operate in standalone mode)")
                return

            while True:
                try:
                    data, _ = sock.recvfrom(2048)
                    msg = json.loads(data.decode("utf-8"))
                    dmg = msg.get("damage_ratio", 0.0)
                    faint = msg.get("is_fainted", False)
                    c_hp = msg.get("cur_hp", 100)
                    m_hp = msg.get("max_hp", 100)
                    self.process_haptic_event(dmg, faint, c_hp, m_hp)
                except Exception:
                    pass

        t = threading.Thread(target=listener, daemon=True)
        t.start()


if __name__ == "__main__":
    app = TactSuitVisualizer()
    app.mainloop()
