"""
포켓몬스터 하트골드(KOR) - bHaptics 촉각 수트 통합 제어판 (All-in-One GUI)
작성자: Antigravity Pair Programmer
설명:
    공식 bhaptics-python SDK 및 120Hz 초저지연 메모리 훅 기반의 사용자 친화형 한글 GUI 대시보드입니다.
    실시간 체력 게이지, 2D 조끼 모터 맵, 진동 강도 조절, 원터치 진동 테스트, 설정 저장 기능을 제공합니다.
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

from bhaptics_bridge import (
    DEFAULT_WS_URL,
    HAS_BHAPTICS_SDK,
    HapticOutputManager,
    HapticPatternGenerator,
    MotorArrayConverter,
    load_config,
    save_config
)

# Windows API 메모리 읽기 상수
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
        self.title("포켓몬스터 하트골드 - bHaptics 촉각 수트 제어 센터")
        self.geometry("1020x760")
        self.configure(bg="#0f111a")
        self.resizable(False, False)

        # 설정 불러오기
        self.config = load_config()
        self.haptic_mgr = HapticOutputManager(self.config)

        # 상태 변수
        self.is_running = False
        self.gain = 1.0
        self.ws_client = None
        self.reader_thread = None

        # 실시간 게임 데이터
        self.cur_hp = 0
        self.max_hp = 0
        self.last_hp = -1
        self.last_max_hp = -1
        self.in_battle = False
        self.pid = None
        self.h_process = None
        self.mod_base = 0
        self.active_offset = 0

        # 모터 진동 강도 (0.0 ~ 1.0)
        self.front_intensity = [0.0] * 20
        self.back_intensity = [0.0] * 20

        self._setup_styles()
        self._setup_ui()
        self._load_config_to_ui()
        self._start_render_loop()

        # 창 닫기 시 자원 정리
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
            "input_bg": "#12141f",
            "input_border": "#30363d"
        }

    def _setup_ui(self):
        # 1. 상단 타이틀 배너
        header = tk.Frame(self, bg=self.colors["bg_card"], height=62, padx=20)
        header.pack(fill="x", side="top")

        title_box = tk.Frame(header, bg=self.colors["bg_card"])
        title_box.pack(side="left", pady=8)

        tk.Label(
            title_box,
            text="⚡ 포켓몬스터 하트골드 촉각 수트(bHaptics) 연동 센터",
            font=("Malgun Gothic", 15, "bold"),
            fg=self.colors["accent_blue"],
            bg=self.colors["bg_card"]
        ).pack(anchor="w")

        tk.Label(
            title_box,
            text="120Hz 초저지연 메모리 감지 및 공식 bHaptics SDK 통합 제어 대시보드",
            font=("Malgun Gothic", 9),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg_card"]
        ).pack(anchor="w")

        # 우측 상단 실시간 상태 뱃지
        badge_box = tk.Frame(header, bg=self.colors["bg_card"])
        badge_box.pack(side="right", pady=10)

        self.lbl_mode_badge = tk.Label(
            badge_box,
            text="● 모드: 공식 SDK",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["accent_purple"],
            bg="#2c1a3b",
            padx=8,
            pady=3,
            bd=1,
            relief="solid"
        )
        self.lbl_mode_badge.pack(side="left", padx=4)

        self.lbl_ws_badge = tk.Label(
            badge_box,
            text="● 햅틱: 대기 중",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["accent_orange"],
            bg="#2c221a",
            padx=8,
            pady=3,
            bd=1,
            relief="solid"
        )
        self.lbl_ws_badge.pack(side="left", padx=4)

        self.lbl_emu_badge = tk.Label(
            badge_box,
            text="● 에뮬레이터: 탐색 중",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["text_secondary"],
            bg="#24283b",
            padx=8,
            pady=3,
            bd=1,
            relief="solid"
        )
        self.lbl_emu_badge.pack(side="left", padx=4)

        # 2. 메인 컨텐츠 영역 (좌측: 설정 및 제어 / 우측: 실시간 배틀 및 2D 모터 맵)
        content = tk.Frame(self, bg=self.colors["bg_dark"], padx=14, pady=10)
        content.pack(fill="both", expand=True)

        left_col = tk.Frame(content, bg=self.colors["bg_dark"], width=480)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 8))

        right_col = tk.Frame(content, bg=self.colors["bg_dark"], width=480)
        right_col.pack(side="right", fill="both", expand=True, padx=(8, 0))

        # --- 좌측 열 (설정 및 제어) ---
        # 카드 1: bHaptics 촉각 수트 연결 설정
        cfg_card = tk.LabelFrame(
            left_col,
            text="  🛠️ bHaptics 촉각 수트 연동 설정  ",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["accent_purple"],
            bg=self.colors["bg_card"],
            padx=14,
            pady=8,
            bd=1,
            relief="solid"
        )
        cfg_card.pack(fill="x", pady=(0, 8))

        # 출력 방식 선택 (공식 SDK vs 웹소켓)
        mode_frame = tk.Frame(cfg_card, bg=self.colors["bg_card"])
        mode_frame.pack(fill="x", pady=2)
        tk.Label(mode_frame, text="연동 방식:", font=("Malgun Gothic", 9, "bold"), fg=self.colors["text_primary"], bg=self.colors["bg_card"]).pack(side="left")

        self.var_mode = tk.StringVar(value="bhaptics")
        rb_sdk = tk.Radiobutton(
            mode_frame, text="공식 SDK 모드 (권장)", variable=self.var_mode, value="bhaptics",
            font=("Malgun Gothic", 9), fg=self.colors["accent_green"], bg=self.colors["bg_card"],
            selectcolor=self.colors["bg_dark"], activebackground=self.colors["bg_card"],
            command=self._on_mode_change
        )
        rb_sdk.pack(side="left", padx=6)

        rb_ws = tk.Radiobutton(
            mode_frame, text="일반 웹소켓 모드 (키 불필요)", variable=self.var_mode, value="websocket",
            font=("Malgun Gothic", 9), fg=self.colors["text_secondary"], bg=self.colors["bg_card"],
            selectcolor=self.colors["bg_dark"], activebackground=self.colors["bg_card"],
            command=self._on_mode_change
        )
        rb_ws.pack(side="left", padx=4)

        # App ID & API Key 입력
        grid_f = tk.Frame(cfg_card, bg=self.colors["bg_card"])
        grid_f.pack(fill="x", pady=4)

        tk.Label(grid_f, text="앱 아이디 (App ID):", font=("Malgun Gothic", 9), fg=self.colors["text_secondary"], bg=self.colors["bg_card"]).grid(row=0, column=0, sticky="w", pady=2)
        self.entry_app_id = tk.Entry(grid_f, font=("Consolas", 9), bg=self.colors["input_bg"], fg=self.colors["text_primary"], bd=1, relief="solid")
        self.entry_app_id.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=2)

        tk.Label(grid_f, text="인증 키 (API Key):", font=("Malgun Gothic", 9), fg=self.colors["text_secondary"], bg=self.colors["bg_card"]).grid(row=1, column=0, sticky="w", pady=2)
        self.entry_api_key = tk.Entry(grid_f, font=("Consolas", 9), bg=self.colors["input_bg"], fg=self.colors["text_primary"], bd=1, relief="solid", show="*")
        self.entry_api_key.grid(row=1, column=1, sticky="ew", padx=(8, 4), pady=2)

        self.btn_show_key = tk.Button(grid_f, text="👁", font=("Segoe UI", 8), bg=self.colors["btn_bg"], fg=self.colors["text_primary"], bd=1, relief="flat", command=self._toggle_key_visibility)
        self.btn_show_key.grid(row=1, column=2, sticky="e", pady=2)
        grid_f.columnconfigure(1, weight=1)

        # 조끼 모터 수 및 앞/뒤 개별 강도
        tune_f = tk.Frame(cfg_card, bg=self.colors["bg_card"])
        tune_f.pack(fill="x", pady=4)

        tk.Label(tune_f, text="조끼 모델:", font=("Malgun Gothic", 9), fg=self.colors["text_secondary"], bg=self.colors["bg_card"]).pack(side="left")
        self.combo_motors = ttk.Combobox(tune_f, values=["32개 (TactSuit Pro / 일반)", "40개 (TactSuit X40 풀버전)"], state="readonly", width=22)
        self.combo_motors.current(0)
        self.combo_motors.pack(side="left", padx=(4, 10))

        tk.Label(tune_f, text="앞면배율:", font=("Malgun Gothic", 9), fg=self.colors["text_secondary"], bg=self.colors["bg_card"]).pack(side="left")
        self.spin_fgain = tk.Spinbox(tune_f, from_=0.1, to=2.0, increment=0.1, format="%.1f", width=4, bg=self.colors["input_bg"], fg=self.colors["text_primary"])
        self.spin_fgain.pack(side="left", padx=(2, 6))

        tk.Label(tune_f, text="뒷면배율:", font=("Malgun Gothic", 9), fg=self.colors["text_secondary"], bg=self.colors["bg_card"]).pack(side="left")
        self.spin_bgain = tk.Spinbox(tune_f, from_=0.1, to=2.0, increment=0.1, format="%.1f", width=4, bg=self.colors["input_bg"], fg=self.colors["text_primary"])
        self.spin_bgain.pack(side="left", padx=(2, 6))

        # 설정 저장 버튼
        btn_save = tk.Button(
            cfg_card,
            text="💾 설정 저장하기 (config.json 저장)",
            font=("Malgun Gothic", 9, "bold"),
            bg=self.colors["btn_bg"],
            fg=self.colors["accent_blue"],
            activebackground=self.colors["btn_hover"],
            activeforeground="#ffffff",
            relief="flat",
            pady=4,
            command=self.save_settings
        )
        btn_save.pack(fill="x", pady=(4, 0))

        # 카드 2: 브릿지 시작 및 전체 진동 조절
        ctrl_card = tk.LabelFrame(
            left_col,
            text="  ⚙️ 햅틱 브릿지 실행 및 강도 제어  ",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["accent_blue"],
            bg=self.colors["bg_card"],
            padx=14,
            pady=8,
            bd=1,
            relief="solid"
        )
        ctrl_card.pack(fill="x", pady=6)

        self.btn_toggle = tk.Button(
            ctrl_card,
            text="▶ 햅틱 브릿지 시작 (진동 연동 켜기)",
            font=("Malgun Gothic", 11, "bold"),
            bg=self.colors["accent_green"],
            fg="#0f111a",
            activebackground="#2ea043",
            activeforeground="#ffffff",
            relief="flat",
            pady=7,
            command=self.toggle_bridge
        )
        self.btn_toggle.pack(fill="x", pady=(0, 6))

        # 전체 진동 세기 슬라이더
        slider_box = tk.Frame(ctrl_card, bg=self.colors["bg_card"])
        slider_box.pack(fill="x", pady=2)

        self.lbl_gain = tk.Label(slider_box, text="전체 진동 강도 (마스터 게인): 100%", font=("Malgun Gothic", 9, "bold"), fg=self.colors["text_primary"], bg=self.colors["bg_card"])
        self.lbl_gain.pack(anchor="w")

        self.slider = ttk.Scale(slider_box, from_=50, to=150, value=100, orient="horizontal", command=self._on_slider_change)
        self.slider.pack(fill="x", pady=(2, 0))

        # 카드 3: 원터치 진동 테스트 버튼
        test_card = tk.LabelFrame(
            left_col,
            text="  ⚡ 원터치 진동 테스트 (즉시 체험하기)  ",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["accent_orange"],
            bg=self.colors["bg_card"],
            padx=14,
            pady=6,
            bd=1,
            relief="solid"
        )
        test_card.pack(fill="x", pady=6)

        tests_grid = tk.Frame(test_card, bg=self.colors["bg_card"])
        tests_grid.pack(fill="x")

        tests = [
            ("가벼운 공격 (15%)", lambda: self.trigger_manual_test(0.15, False)),
            ("중간 공격 (35%)", lambda: self.trigger_manual_test(0.35, False)),
            ("강한 공격 (65%)", lambda: self.trigger_manual_test(0.65, False)),
            ("치명타 (90%)", lambda: self.trigger_manual_test(0.90, False)),
            ("기절/빈사 (0 HP)", lambda: self.trigger_manual_test(1.0, True)),
            ("심장 박동 펄스", lambda: self.trigger_manual_heartbeat()),
        ]

        for idx, (label, cmd) in enumerate(tests):
            r, c = idx // 3, idx % 3
            btn = tk.Button(
                tests_grid, text=label, font=("Malgun Gothic", 8, "bold"),
                bg=self.colors["btn_bg"], fg=self.colors["text_primary"],
                activebackground=self.colors["btn_hover"], activeforeground="#ffffff",
                relief="flat", pady=3, command=cmd
            )
            btn.grid(row=r, column=c, padx=2, pady=2, sticky="nsew")
        for i in range(3):
            tests_grid.columnconfigure(i, weight=1)

        # --- 우측 열 (실시간 배틀 상태 & 2D 조끼 모터 맵) ---
        # 카드 4: 실시간 포켓몬 배틀 상태 & 체력 게이지
        hp_card = tk.LabelFrame(
            right_col,
            text="  🎮 실시간 포켓몬 배틀 상태  ",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["accent_green"],
            bg=self.colors["bg_card"],
            padx=12,
            pady=8,
            bd=1,
            relief="solid"
        )
        hp_card.pack(fill="x", pady=(0, 6))

        self.lbl_battle_status = tk.Label(
            hp_card, text="🌿 현재 상태: 필드 탐색 중 / 배틀 대기 중...",
            font=("Malgun Gothic", 10, "bold"), fg=self.colors["text_secondary"], bg=self.colors["bg_card"]
        )
        self.lbl_battle_status.pack(anchor="w")

        self.lbl_hp_val = tk.Label(
            hp_card, text="포켓몬 체력: -- / -- (100%)",
            font=("Malgun Gothic", 12, "bold"), fg=self.colors["accent_green"], bg=self.colors["bg_card"]
        )
        self.lbl_hp_val.pack(anchor="w", pady=(2, 0))

        self.hp_canvas = tk.Canvas(hp_card, width=440, height=16, bg="#11131f", highlightthickness=0)
        self.hp_canvas.pack(fill="x", pady=4)
        self._draw_hp_bar(1.0)

        # 카드 5: 2D 촉각 조끼 실시간 모터 진동 맵
        suit_card = tk.LabelFrame(
            right_col,
            text="  🦺 촉각 조끼 실시간 모터 진동 화면 (40개 모터)  ",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["accent_blue"],
            bg=self.colors["bg_card"],
            padx=8,
            pady=6,
            bd=1,
            relief="solid"
        )
        suit_card.pack(fill="both", expand=True, pady=4)

        self.canvas = tk.Canvas(suit_card, width=440, height=220, bg="#11131f", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # 카드 6: 실시간 피격 이벤트 기록 로그
        log_card = tk.LabelFrame(
            right_col,
            text="  📋 실시간 피격 기록 로그  ",
            font=("Malgun Gothic", 9, "bold"),
            fg=self.colors["text_secondary"],
            bg=self.colors["bg_card"],
            padx=6,
            pady=4,
            bd=1,
            relief="solid"
        )
        log_card.pack(fill="x", pady=(4, 0))

        self.log_box = tk.Text(
            log_card, height=5, bg="#11131f", fg=self.colors["text_primary"],
            font=("Consolas", 8), bd=0, padx=4, pady=2
        )
        self.log_box.pack(fill="both", expand=True)
        self._log_event("제어 센터가 준비되었습니다. '햅틱 브릿지 시작' 버튼을 눌러주세요.")

    def _load_config_to_ui(self):
        sink = self.config.get("sink", {})
        mode = sink.get("kind", "bhaptics")
        self.var_mode.set(mode)
        self._on_mode_change()

        self.entry_app_id.delete(0, "end")
        self.entry_app_id.insert(0, sink.get("app_id", ""))

        self.entry_api_key.delete(0, "end")
        self.entry_api_key.insert(0, sink.get("api_key", ""))

        m_count = sink.get("motor_count", 32)
        if m_count == 40:
            self.combo_motors.current(1)
        else:
            self.combo_motors.current(0)

        self.spin_fgain.delete(0, "end")
        self.spin_fgain.insert(0, str(sink.get("front_gain", 1.0)))

        self.spin_bgain.delete(0, "end")
        self.spin_bgain.insert(0, str(sink.get("back_gain", 1.0)))

    def save_settings(self):
        m_val = 40 if "40" in self.combo_motors.get() else 32
        try:
            fg = float(self.spin_fgain.get())
            bg = float(self.spin_bgain.get())
        except ValueError:
            fg, bg = 1.0, 1.0

        new_cfg = {
            "sink": {
                "kind": self.var_mode.get(),
                "app_id": self.entry_app_id.get().strip(),
                "api_key": self.entry_api_key.get().strip(),
                "motor_count": m_val,
                "front_gain": fg,
                "back_gain": bg
            }
        }
        if save_config(new_cfg):
            self.config = new_cfg
            self.haptic_mgr = HapticOutputManager(self.config)
            self._log_event("✅ 설정이 config.json 파일에 성공적으로 저장되었습니다.")
            messagebox.showinfo("설정 저장 완료", "bHaptics 연동 설정이 성공적으로 저장되었습니다.")
        else:
            self._log_event("❌ 설정 파일(config.json) 저장에 실패했습니다.")

    def _on_mode_change(self):
        mode = self.var_mode.get()
        if mode == "bhaptics":
            self.lbl_mode_badge.config(text="● 모드: 공식 SDK", fg=self.colors["accent_purple"], bg="#2c1a3b")
        else:
            self.lbl_mode_badge.config(text="● 모드: 웹소켓", fg=self.colors["accent_blue"], bg="#192b3b")

    def _toggle_key_visibility(self):
        if self.entry_api_key.cget("show") == "*":
            self.entry_api_key.config(show="")
            self.btn_show_key.config(text="🔒")
        else:
            self.entry_api_key.config(show="*")
            self.btn_show_key.config(text="👁")

    def _draw_hp_bar(self, ratio):
        self.hp_canvas.delete("all")
        w = self.hp_canvas.winfo_width() or 440
        h = 16
        ratio = max(0.0, min(1.0, ratio))

        self.hp_canvas.create_rectangle(0, 0, w, h, fill="#222536", outline="")
        color = self.colors["accent_green"] if ratio > 0.5 else (self.colors["accent_orange"] if ratio > 0.2 else self.colors["accent_red"])
        if ratio > 0:
            self.hp_canvas.create_rectangle(0, 0, int(w * ratio), h, fill=color, outline="")

    def _on_slider_change(self, val):
        self.gain = float(val) / 100.0
        self.lbl_gain.config(text=f"전체 진동 강도 (마스터 게인): {int(float(val))}%")

    def _log_event(self, msg):
        timestamp = time.strftime("%H:%M:%S")
        self.log_box.insert("end", f"[{timestamp}] {msg}\n")
        self.log_box.see("end")

    def toggle_bridge(self):
        if not self.is_running:
            # 공식 SDK 모드일 때 키 검증
            if self.var_mode.get() == "bhaptics":
                app_id = self.entry_app_id.get().strip()
                api_key = self.entry_api_key.get().strip()
                if not app_id or not api_key:
                    messagebox.showerror(
                        "bHaptics 인증 정보 필요",
                        "공식 SDK 모드를 사용하려면 bHaptics Developer Portal에서 발급받은\n"
                        "App ID와 API Key를 입력하고 '설정 저장'을 눌러주세요.\n\n"
                        "(발급받은 키가 없으시다면 '일반 웹소켓 모드'를 선택하시면 바로 실행됩니다.)"
                    )
                    self._log_event("⚠️ 오류: 공식 SDK 연동에 필요한 App ID 또는 API Key가 비어있습니다.")
                    return

                self.save_settings()

            self.is_running = True
            self.btn_toggle.config(text="⏹ 햅틱 브릿지 중지 (진동 연동 끄기)", bg=self.colors["accent_red"], activebackground="#da3633")
            self._log_event(f"120Hz 초고속 메모리 브릿지 가동 시작 (연동 모드: {self.var_mode.get()})...")
            self.reader_thread = threading.Thread(target=self._bridge_worker, daemon=True)
            self.reader_thread.start()
        else:
            self.is_running = False
            self.btn_toggle.config(text="▶ 햅틱 브릿지 시작 (진동 연동 켜기)", bg=self.colors["accent_green"], activebackground="#2ea043")
            self.haptic_mgr.stop_all()
            self._log_event("햅틱 브릿지가 중지되었습니다.")
            self.lbl_battle_status.config(text="현재 상태: 브릿지 중지됨", fg=self.colors["text_secondary"])
            self._update_badge("ws", False, "대기 중")

    def _bridge_worker(self):
        """120Hz DeSmuME 메모리 스캔 및 햅틱 신호 전송 백그라운드 루프"""
        mode = self.var_mode.get()

        if mode == "bhaptics":
            # 공식 SDK 초기화
            ok, msg = self.haptic_mgr.initialize_sdk()
            if ok:
                self.after(0, lambda: self._update_badge("ws", True, "SDK 정상 연결"))
                self.after(0, lambda: self._log_event("🟢 공식 bhaptics-python SDK가 정상적으로 초기화되었습니다!"))
            else:
                self.after(0, lambda: self._update_badge("ws", False, "SDK 초기화 실패"))
                self.after(0, lambda m=msg: self._log_event(f"❌ {m}"))

            while self.is_running:
                try:
                    if not self.h_process:
                        if self._attach_desmume():
                            self.after(0, lambda: self._update_badge("emu", True, f"PID {self.pid}"))
                            self.after(0, lambda: self._log_event(f"DeSmuME 에뮬레이터 연결 성공 (PID {self.pid})!"))
                        else:
                            self.after(0, lambda: self._update_badge("emu", False, "탐색 중..."))
                            time.sleep(1)
                            continue

                    cur_hp, max_hp = self._scan_active_battler()

                    if cur_hp is not None and max_hp is not None:
                        if not self.in_battle:
                            self.in_battle = True
                            self.after(0, lambda c=cur_hp, m=max_hp: self._on_battle_start(c, m))

                        if self.last_hp != -1 and self.last_max_hp == max_hp:
                            if cur_hp < self.last_hp:
                                damage = self.last_hp - cur_hp
                                damage_ratio = damage / max_hp
                                is_fainted = (cur_hp == 0)

                                self.after(0, lambda d=damage, r=damage_ratio, c=cur_hp, m=max_hp: self._on_hit_detected(d, r, c, m))

                                # 공식 SDK를 통한 모터 진동 전송
                                frames = HapticPatternGenerator.get_pattern(damage_ratio, is_fainted)
                                self.haptic_mgr.play_haptic(frames, master_gain=self.gain)
                                self.after(0, lambda f=frames: self._animate_from_frames(f))

                        self.last_hp = cur_hp
                        self.last_max_hp = max_hp
                    else:
                        if self.in_battle:
                            self.in_battle = False
                            self.after(0, self._on_battle_end)
                        self.last_hp = -1
                        self.last_max_hp = -1

                    time.sleep(0.008)  # 120Hz (8ms)
                except Exception as e:
                    self.after(0, lambda err=str(e): self._log_event(f"SDK 실행 오류: {err}"))
                    time.sleep(1)

        else:
            # 일반 웹소켓 모드
            async def run_ws_loop():
                while self.is_running:
                    try:
                        self.after(0, lambda: self._update_badge("ws", False, "연결 시도 중..."))
                        async with websockets.connect(DEFAULT_WS_URL, max_size=None, ping_interval=None) as ws:
                            self.ws_client = ws
                            self.after(0, lambda: self._update_badge("ws", True, "웹소켓 정상 연결"))
                            self.after(0, lambda: self._log_event("bHaptics Player와 웹소켓(15881)으로 정상 연결되었습니다!"))

                            while self.is_running:
                                if not self.h_process:
                                    if self._attach_desmume():
                                        self.after(0, lambda: self._update_badge("emu", True, f"PID {self.pid}"))
                                        self.after(0, lambda: self._log_event(f"DeSmuME 에뮬레이터 연결 성공 (PID {self.pid})!"))
                                    else:
                                        self.after(0, lambda: self._update_badge("emu", False, "탐색 중..."))
                                        await asyncio.sleep(1)
                                        continue

                                cur_hp, max_hp = self._scan_active_battler()

                                if cur_hp is not None and max_hp is not None:
                                    if not self.in_battle:
                                        self.in_battle = True
                                        self.after(0, lambda c=cur_hp, m=max_hp: self._on_battle_start(c, m))

                                    if self.last_hp != -1 and self.last_max_hp == max_hp:
                                        if cur_hp < self.last_hp:
                                            damage = self.last_hp - cur_hp
                                            damage_ratio = damage / max_hp
                                            is_fainted = (cur_hp == 0)

                                            self.after(0, lambda d=damage, r=damage_ratio, c=cur_hp, m=max_hp: self._on_hit_detected(d, r, c, m))

                                            frames = HapticPatternGenerator.get_pattern(damage_ratio, is_fainted)
                                            submit_list = [{"Type": "turnOff", "Key": "PokemonDamage"}]
                                            for frame in frames:
                                                dots = frame.get("DotPoints", [])
                                                for dot in dots:
                                                    dot["Intensity"] = min(100, int(dot["Intensity"] * self.gain))
                                                submit_list.append({"Type": "frame", "Key": "PokemonDamage", "Frame": frame})

                                            await ws.send(json.dumps({"Submit": submit_list}))
                                            self.after(0, lambda f=frames: self._animate_from_frames(f))

                                    self.last_hp = cur_hp
                                    self.last_max_hp = max_hp
                                else:
                                    if self.in_battle:
                                        self.in_battle = False
                                        self.after(0, self._on_battle_end)
                                    self.last_hp = -1
                                    self.last_max_hp = -1

                                await asyncio.sleep(0.008)

                    except (ConnectionRefusedError, OSError):
                        self.after(0, lambda: self._update_badge("ws", False, "연결 끊김"))
                        await asyncio.sleep(2)
                    except Exception as e:
                        self.after(0, lambda err=str(e): self._log_event(f"웹소켓 통신 오류: {err}"))
                        await asyncio.sleep(2)

            asyncio.run(run_ws_loop())

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

    def _update_badge(self, target, connected, label_text):
        if target == "ws":
            color = self.colors["accent_green"] if connected else self.colors["accent_orange"]
            bg = "#192b20" if connected else "#2c221a"
            self.lbl_ws_badge.config(text=f"● 햅틱: {label_text}", fg=color, bg=bg)
        elif target == "emu":
            color = self.colors["accent_green"] if connected else self.colors["text_secondary"]
            bg = "#192b20" if connected else "#24283b"
            self.lbl_emu_badge.config(text=f"● 에뮬레이터: {label_text}", fg=color, bg=bg)

    def _on_battle_start(self, cur_hp, max_hp):
        self.lbl_battle_status.config(text="⚔️ 현재 상태: 포켓몬 배틀 진행 중 (실시간 연동 활성)", fg=self.colors["accent_green"])
        ratio = cur_hp / max_hp if max_hp > 0 else 1.0
        self.lbl_hp_val.config(text=f"포켓몬 체력: {cur_hp} / {max_hp} ({ratio*100:.0f}%)")
        self._draw_hp_bar(ratio)
        self._log_event(f"배틀 진입! 출전 포켓몬 감지 완료 (체력 {cur_hp}/{max_hp})")

    def _on_battle_end(self):
        self.lbl_battle_status.config(text="🌿 현재 상태: 필드 탐색 중 / 배틀 대기 중...", fg=self.colors["text_secondary"])
        self.lbl_hp_val.config(text="포켓몬 체력: -- / -- (100%)")
        self._draw_hp_bar(1.0)
        self._log_event("배틀 종료. 필드로 복귀합니다.")

    def _on_hit_detected(self, damage, ratio, cur_hp, max_hp):
        hp_pct = (cur_hp / max_hp) * 100 if max_hp > 0 else 0
        self.lbl_hp_val.config(text=f"포켓몬 체력: {cur_hp} / {max_hp} ({hp_pct:.0f}%)")
        self._draw_hp_bar(cur_hp / max_hp)
        self._log_event(f"💥 [피격 감지!] 데미지: -{damage} HP ({ratio*100:.1f}%) | 잔여 체력: {cur_hp}/{max_hp}")

    def _animate_from_frames(self, frames):
        for frame in frames:
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
        self._animate_from_frames(frames)
        self._log_event(f"원터치 테스트 발동: {int(damage_ratio*100)}% 데미지 진동 패턴")

        if self.var_mode.get() == "bhaptics":
            self.haptic_mgr.play_haptic(frames, master_gain=self.gain)
        elif self.ws_client:
            submit_list = [{"Type": "turnOff", "Key": "PokemonDamage"}]
            for frame in frames:
                dots = frame.get("DotPoints", [])
                for dot in dots:
                    dot["Intensity"] = min(100, int(dot["Intensity"] * self.gain))
                submit_list.append({"Type": "frame", "Key": "PokemonDamage", "Frame": frame})
            asyncio.run_coroutine_threadsafe(self.ws_client.send(json.dumps({"Submit": submit_list})), asyncio.get_event_loop())

    def trigger_manual_heartbeat(self):
        pattern = HapticPatternGenerator.get_heartbeat_pattern()
        self._animate_from_frames(pattern)
        self._log_event("원터치 테스트 발동: 저체력 심장 박동(쿵-쾅) 펄스")
        if self.var_mode.get() == "bhaptics":
            self.haptic_mgr.play_haptic(pattern, master_gain=self.gain)

    def _draw_motors_layout(self, offset_x, title, intensities):
        self.canvas.create_text(offset_x + 95, 14, text=title, fill=self.colors["text_primary"], font=("Malgun Gothic", 9, "bold"))

        self.canvas.create_rectangle(
            offset_x + 10, 28, offset_x + 180, 210,
            outline="#2b3044", width=2, fill="#181a26"
        )

        cols = 4
        start_x = offset_x + 36
        start_y = 48
        spacing_x = 38
        spacing_y = 33
        radius = 11

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
        self._draw_motors_layout(20, "조끼 앞면 (가슴/복부 20개)", self.front_intensity)
        self._draw_motors_layout(225, "조끼 뒷면 (등/허리 20개)", self.back_intensity)

        decay = 0.03
        for i in range(20):
            if self.front_intensity[i] > 0:
                self.front_intensity[i] = max(0.0, self.front_intensity[i] - decay)
            if self.back_intensity[i] > 0:
                self.back_intensity[i] = max(0.0, self.back_intensity[i] - decay)

        self.after(30, self._render)

    def _start_render_loop(self):
        self.after(30, self._render)

    def _on_close(self):
        self.is_running = False
        self.haptic_mgr.close()
        self.destroy()


if __name__ == "__main__":
    app = PokemonHapticApp()
    app.mainloop()
