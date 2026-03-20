import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import hmac, hashlib, base64, json, ssl, urllib.request, os
import threading, time
from datetime import datetime
from pathlib import Path

# .env 파일에서 환경변수 로드
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# .env에서 로드 — 평문 fallback 없음
_b64 = os.environ.get("RINNAI_BASE_URL_B64", "")
_hex = os.environ.get("RINNAI_HMAC_KEY_HEX", "")
if not _b64 or not _hex:
    raise RuntimeError(
        ".env 파일에 RINNAI_BASE_URL_B64 / RINNAI_HMAC_KEY_HEX 가 필요합니다.\n"
        "프로젝트 루트의 .env 파일을 확인하세요."
    )
BASE_URL = base64.b64decode(_b64).decode()
HMAC_KEY = bytes.fromhex(_hex)
ETX = "7d"


def hash_password(pw):
    return base64.b64encode(
        hmac.new(HMAC_KEY, pw.encode(), hashlib.sha1).digest()
    ).decode().strip()


def ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


CTX = ssl_ctx()


def post_json(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, context=CTX, timeout=10) as res:
        return json.loads(res.read())


def post_plain(url, body, room_id, device_id):
    req = urllib.request.Request(
        url, data=body.encode(),
        headers={
            "Content-Type": "text/plain",
            "Accept": "text/plain",
            "RoomControlId": room_id,
            "DeviceId": device_id,
        }
    )
    with urllib.request.urlopen(req, context=CTX, timeout=10) as res:
        return res.read().decode()


def parse_status(raw):
    if not raw or len(raw) < 10:
        return None
    try:
        data_len = int(raw[8:10], 16)
        payload  = raw[10:10 + data_len]
        flags    = int(payload[0:2], 16)
        room_set = int(payload[2:4], 16)
        hw_set   = int(payload[4:6], 16)
        wt_raw   = int(payload[6:8], 16)
        room_cur = int(payload[8:10], 16)
        hw_raw   = int(payload[10:12], 16) if len(payload) >= 12 else 0
        go_out   = int(payload[14:16], 16) if len(payload) >= 16 else 0

        water_temp = (wt_raw - 128 + 0.5) if wt_raw >= 128 else float(wt_raw)
        hw_cur     = (hw_raw - 128 + 0.5) if hw_raw >= 128 else float(hw_raw)

        # CheckHeaterInfoRes.setDataFromBinary 정확한 로직:
        # returnBinary(0,2,6,payload) → hex→binary 6비트, reverse 없음
        # 예) flags=0x05 → "000101"
        # charAt(5) → isPwrOn     = flags & 0x01
        # charAt(4) → isHeatMode  = flags & 0x02  ← 온돌(True)/실내온도(False)
        # charAt(3) → isHeatOn    = flags & 0x04  ← 난방
        # charAt(2) → isHeatWater = flags & 0x08  ← 온수
        # charAt(1) → isPreHeat   = flags & 0x10
        # charAt(0) → isQuickHeat = flags & 0x20
        flags_6bit = bin(flags)[2:].zfill(6)  # 6비트, no reverse

        return {
            "power":         bool(flags & 0x01),   # charAt(5) isPwrOn
            "heat_mode":     bool(flags & 0x02),   # charAt(4) isHeatMode 온돌=True
            "heating":       bool(flags & 0x04),   # charAt(3) isHeatOn 난방
            "hot_water":     bool(flags & 0x08),   # charAt(2) isHeatWater 온수
            "pre_heat":      bool(flags & 0x10),   # charAt(1) isPreHeat
            "quick_heat":    bool(flags & 0x20),   # charAt(0) isQuickHeat
            "go_out":        go_out > 0,
            "room_temp_set": room_set,
            "room_temp_cur": room_cur,
            "hw_temp_set":   hw_set,
            "hw_temp_cur":   hw_cur,
            "water_temp":    water_temp,
            "raw":           raw,
            "payload":       payload,
            "flags_hex":     payload[0:2],
            "flags_6bit":    flags_6bit,
        }
    except Exception as e:
        return {"error": str(e), "raw": raw}


class RinnaiDebugger(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("린나이 보일러 디버거")
        self.geometry("960x720")
        self.configure(bg="#1e1e1e")
        self.resizable(True, True)

        self.room_id   = tk.StringVar()
        self.device_id = tk.StringVar()
        self.email     = tk.StringVar()
        self.password  = tk.StringVar()
        self.auto_var  = tk.BooleanVar(value=False)
        self.status    = {}
        self._auto_job = None

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background="#1e1e1e", borderwidth=0)
        style.configure("TNotebook.Tab", background="#2d2d2d", foreground="#aaa",
                        padding=[12, 6], font=("Helvetica", 11))
        style.map("TNotebook.Tab", background=[("selected", "#3a3a3a")],
                  foreground=[("selected", "#fff")])
        style.configure("TFrame", background="#1e1e1e")
        style.configure("TLabel", background="#1e1e1e", foreground="#ccc", font=("Helvetica", 11))
        style.configure("TEntry", fieldbackground="#2d2d2d", foreground="#fff",
                        insertcolor="#fff", font=("Helvetica", 11))
        style.configure("TButton", background="#3a3a3a", foreground="#fff",
                        font=("Helvetica", 11), padding=[8, 4])
        style.map("TButton", background=[("active", "#505050")])
        style.configure("Accent.TButton", background="#1a73e8", foreground="#fff",
                        font=("Helvetica", 11, "bold"), padding=[10, 5])
        style.map("Accent.TButton", background=[("active", "#1557b0")])
        style.configure("Red.TButton", background="#c0392b", foreground="#fff",
                        font=("Helvetica", 11, "bold"), padding=[10, 5])
        style.configure("Green.TButton", background="#27ae60", foreground="#fff",
                        font=("Helvetica", 11, "bold"), padding=[10, 5])
        style.configure("Orange.TButton", background="#e67e22", foreground="#fff",
                        font=("Helvetica", 11, "bold"), padding=[10, 5])

        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        self._tab_login(nb)
        self._tab_status(nb)
        self._tab_control(nb)
        self._tab_raw(nb)

        self._statusbar()

    def _label(self, parent, text, **kw):
        return ttk.Label(parent, text=text, **kw)

    def _entry(self, parent, var, show=None, width=30):
        return ttk.Entry(parent, textvariable=var, show=show, width=width)

    def _btn(self, parent, text, cmd, style="TButton", **kw):
        return ttk.Button(parent, text=text, command=cmd, style=style, **kw)

    # ── 탭 1: 로그인 ──────────────────────────────────────────
    def _tab_login(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  로그인  ")
        pad = dict(padx=12, pady=6)

        ttk.Label(f, text="린나이 계정 로그인", font=("Helvetica", 14, "bold"),
                  foreground="#fff").grid(row=0, column=0, columnspan=2, pady=(20, 10))

        for i, (lbl, var, show) in enumerate([
            ("이메일",  self.email,    None),
            ("비밀번호", self.password, "*"),
        ], 1):
            self._label(f, lbl).grid(row=i, column=0, sticky="e", **pad)
            self._entry(f, var, show=show, width=35).grid(row=i, column=1, sticky="w", **pad)

        self._btn(f, "로그인", self._do_login, "Accent.TButton").grid(
            row=3, column=0, columnspan=2, pady=12)

        ttk.Separator(f, orient="horizontal").grid(
            row=4, column=0, columnspan=2, sticky="ew", padx=12, pady=8)
        ttk.Label(f, text="또는 직접 입력", foreground="#888").grid(row=5, column=0, columnspan=2)

        self._label(f, "Room Control ID").grid(row=6, column=0, sticky="e", **pad)
        self._entry(f, self.room_id, width=35).grid(row=6, column=1, sticky="w", **pad)

        self._label(f, "Device ID").grid(row=7, column=0, sticky="e", **pad)
        self._entry(f, self.device_id, width=35).grid(row=7, column=1, sticky="w", **pad)

        self._btn(f, "직접 연결 테스트", self._do_direct, "Accent.TButton").grid(
            row=8, column=0, columnspan=2, pady=12)

        self.login_log = scrolledtext.ScrolledText(
            f, height=10, bg="#0d1117", fg="#58a6ff",
            font=("Courier", 11), state="disabled", relief="flat"
        )
        self.login_log.grid(row=9, column=0, columnspan=2, sticky="nsew", padx=12, pady=8)
        f.rowconfigure(9, weight=1)
        f.columnconfigure(1, weight=1)

    # ── 탭 2: 상태 ──────────────────────────────────────────
    def _tab_status(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  상태 조회  ")

        ctrl = ttk.Frame(f)
        ctrl.pack(fill=tk.X, padx=12, pady=10)
        self._btn(ctrl, "상태 조회", self._do_status, "Accent.TButton").pack(side=tk.LEFT, padx=4)
        self._btn(ctrl, "자동 갱신 ON/OFF", self._toggle_auto).pack(side=tk.LEFT, padx=4)
        self.auto_label = ttk.Label(ctrl, text="자동 갱신: OFF", foreground="#888")
        self.auto_label.pack(side=tk.LEFT, padx=8)

        cards = ttk.Frame(f)
        cards.pack(fill=tk.X, padx=12, pady=4)

        self.sv = {}
        items = [
            ("전원",       "power"),
            ("난방",       "heating"),
            ("온수",       "hot_water"),
            ("외출",       "go_out"),
            ("난방모드",    "heat_mode"),   # 온돌/실내온도
            ("예열",       "pre_heat"),
            ("실내 설정",   "room_temp_set"),
            ("실내 현재",   "room_temp_cur"),
            ("온수 설정",   "hw_temp_set"),
            ("온수 현재",   "hw_temp_cur"),
            ("온수사용온도", "water_temp"),
            ("flags hex",  "flags_hex"),
        ]
        for i, (lbl, key) in enumerate(items):
            c = tk.Frame(cards, bg="#2d2d2d", bd=0, relief="flat",
                         highlightbackground="#3a3a3a", highlightthickness=1)
            c.grid(row=i//4, column=i%4, padx=5, pady=5, sticky="nsew", ipadx=10, ipady=6)
            tk.Label(c, text=lbl, bg="#2d2d2d", fg="#888",
                     font=("Helvetica", 9)).pack()
            v = tk.StringVar(value="—")
            self.sv[key] = v
            fg = "#ffa657" if key == "heat_mode" else "#fff"
            tk.Label(c, textvariable=v, bg="#2d2d2d", fg=fg,
                     font=("Helvetica", 14, "bold")).pack()
            cards.columnconfigure(i%4, weight=1)

        ttk.Label(f, text="RAW 응답 파싱", foreground="#888").pack(
            anchor="w", padx=14, pady=(10, 2))
        self.raw_display = scrolledtext.ScrolledText(
            f, height=10, bg="#0d1117", fg="#7ee787",
            font=("Courier", 11), state="disabled", relief="flat"
        )
        self.raw_display.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

    # ── 탭 3: 제어 ──────────────────────────────────────────
    def _tab_control(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  제어  ")

        def section(title):
            ttk.Label(f, text=title, font=("Helvetica", 12, "bold"),
                      foreground="#ccc").pack(anchor="w", padx=14, pady=(14, 4))

        section("전원 제어")
        row = ttk.Frame(f); row.pack(fill=tk.X, padx=14, pady=4)
        self._btn(row, "전원 ON + 난방 ON",
                  lambda: self._ctrl_power(True, True, False),  "Green.TButton").pack(side=tk.LEFT, padx=4)
        self._btn(row, "전원 OFF",
                  lambda: self._ctrl_power(False, False, False), "Red.TButton").pack(side=tk.LEFT, padx=4)
        self._btn(row, "난방 + 온수 ON",
                  lambda: self._ctrl_power(True, True, True)).pack(side=tk.LEFT, padx=4)
        self._btn(row, "온수만 ON",
                  lambda: self._ctrl_power(True, False, True)).pack(side=tk.LEFT, padx=4)

        section("온돌/실내온도 모드 전환")
        row_mode = ttk.Frame(f); row_mode.pack(fill=tk.X, padx=14, pady=4)
        self._btn(row_mode, "온돌 모드로 전환",
                  lambda: self._ctrl_heat_mode(True), "Orange.TButton").pack(side=tk.LEFT, padx=4)
        self._btn(row_mode, "실내온도 모드로 전환",
                  lambda: self._ctrl_heat_mode(False), "Accent.TButton").pack(side=tk.LEFT, padx=4)

        section("온도 설정 (실내온도 모드 — CMD 02)")
        row2 = ttk.Frame(f); row2.pack(fill=tk.X, padx=14, pady=4)
        self.temp_var = tk.IntVar(value=22)
        ttk.Label(row2, text="실내온도:").pack(side=tk.LEFT, padx=4)
        tk.Scale(row2, from_=10, to=40, orient=tk.HORIZONTAL,
                 variable=self.temp_var, length=180,
                 bg="#2d2d2d", fg="#fff", troughcolor="#444",
                 highlightbackground="#1e1e1e").pack(side=tk.LEFT, padx=4)
        ttk.Label(row2, textvariable=self.temp_var).pack(side=tk.LEFT)
        ttk.Label(row2, text="°C").pack(side=tk.LEFT)
        self._btn(row2, "설정 (CMD 02)", self._ctrl_temp_room,
                  "Accent.TButton").pack(side=tk.LEFT, padx=8)

        section("온도 설정 (온돌 모드 — CMD 03)")
        row3 = ttk.Frame(f); row3.pack(fill=tk.X, padx=14, pady=4)
        self.ondol_var = tk.IntVar(value=40)
        ttk.Label(row3, text="온돌온도:").pack(side=tk.LEFT, padx=4)
        tk.Scale(row3, from_=20, to=80, orient=tk.HORIZONTAL,
                 variable=self.ondol_var, length=180,
                 bg="#2d2d2d", fg="#fff", troughcolor="#444",
                 highlightbackground="#1e1e1e").pack(side=tk.LEFT, padx=4)
        ttk.Label(row3, textvariable=self.ondol_var).pack(side=tk.LEFT)
        ttk.Label(row3, text="°C").pack(side=tk.LEFT)
        self._btn(row3, "설정 (CMD 03)", self._ctrl_temp_ondol,
                  "Orange.TButton").pack(side=tk.LEFT, padx=8)

        section("모드")
        row4 = ttk.Frame(f); row4.pack(fill=tk.X, padx=14, pady=4)
        self._btn(row4, "외출 ON",  lambda: self._ctrl_goout(True),  "Accent.TButton").pack(side=tk.LEFT, padx=4)
        self._btn(row4, "외출 OFF", lambda: self._ctrl_goout(False)).pack(side=tk.LEFT, padx=4)
        self._btn(row4, "절약 ON",  lambda: self._ctrl_save(True),   "Accent.TButton").pack(side=tk.LEFT, padx=8)
        self._btn(row4, "절약 OFF", lambda: self._ctrl_save(False)).pack(side=tk.LEFT, padx=4)
        self._btn(row4, "취침 ON",  lambda: self._ctrl_sleep(True),  "Accent.TButton").pack(side=tk.LEFT, padx=8)
        self._btn(row4, "취침 OFF", lambda: self._ctrl_sleep(False)).pack(side=tk.LEFT, padx=4)

        section("커스텀 패킷")
        row5 = ttk.Frame(f); row5.pack(fill=tk.X, padx=14, pady=4)
        self.custom_var = tk.StringVar(value=f"sm00020100007d")
        ttk.Label(row5, text="패킷:").pack(side=tk.LEFT, padx=4)
        ttk.Entry(row5, textvariable=self.custom_var, width=42).pack(side=tk.LEFT, padx=4)
        self._btn(row5, "쿼리 전송",   lambda: self._ctrl_custom("query"),   "Accent.TButton").pack(side=tk.LEFT, padx=4)
        self._btn(row5, "컨트롤 전송", lambda: self._ctrl_custom("control")).pack(side=tk.LEFT, padx=4)

        ttk.Label(f, text="제어 로그", foreground="#888").pack(anchor="w", padx=14, pady=(12, 2))
        self.ctrl_log = scrolledtext.ScrolledText(
            f, height=9, bg="#0d1117", fg="#ffa657",
            font=("Courier", 11), state="disabled", relief="flat"
        )
        self.ctrl_log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

    # ── 탭 4: 전체 로그 ──────────────────────────────────────────
    def _tab_raw(self, nb):
        f = ttk.Frame(nb)
        nb.add(f, text="  전체 로그  ")

        row = ttk.Frame(f); row.pack(fill=tk.X, padx=12, pady=8)
        self._btn(row, "로그 지우기", self._clear_log).pack(side=tk.LEFT, padx=4)

        self.full_log = scrolledtext.ScrolledText(
            f, bg="#0d1117", fg="#ccc",
            font=("Courier", 10), state="disabled", relief="flat"
        )
        self.full_log.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))
        self.full_log.tag_config("req",  foreground="#58a6ff")
        self.full_log.tag_config("res",  foreground="#7ee787")
        self.full_log.tag_config("err",  foreground="#f85149")
        self.full_log.tag_config("info", foreground="#ffa657")

    def _statusbar(self):
        bar = tk.Frame(self, bg="#252525", height=24)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.sb_var = tk.StringVar(value="준비")
        tk.Label(bar, textvariable=self.sb_var, bg="#252525",
                 fg="#888", font=("Helvetica", 10)).pack(side=tk.LEFT, padx=10)
        self.conn_var = tk.StringVar(value="미연결")
        self.conn_label = tk.Label(bar, textvariable=self.conn_var, bg="#252525",
                                   fg="#f85149", font=("Helvetica", 10, "bold"))
        self.conn_label.pack(side=tk.RIGHT, padx=10)

    # ── 로깅 ──────────────────────────────────────────
    def _log(self, msg, tag="info", widget=None):
        ts   = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        for w in ([self.full_log] + ([widget] if widget else [])):
            w.configure(state="normal")
            w.insert(tk.END, line, tag)
            w.see(tk.END)
            w.configure(state="disabled")

    def _set_status(self, msg):
        self.sb_var.set(msg)

    # ── 로그인 ──────────────────────────────────────────
    def _do_login(self):
        def run():
            try:
                self._log("로그인 시도...", "req", self.login_log)
                r1 = post_json(f"{BASE_URL}/user", {
                    "query": "search", "target": "user_check_v2",
                    "deviceId": self.device_id.get() or "homeassistant"
                })
                self._log(f"user_check_v2: {r1}", "res", self.login_log)

                r2 = post_json(f"{BASE_URL}/user", {
                    "query": "search", "target": "id_login",
                    "email": self.email.get(),
                    "password": hash_password(self.password.get()),
                    "deviceId": self.device_id.get() or "homeassistant",
                    "deviceToken": "debugger", "language": "KOR",
                    "appVersion": "1.8.8", "agreementVersion": ""
                })
                self._log(
                    f"id_login: {json.dumps(r2, ensure_ascii=False, indent=2)}",
                    "res", self.login_log
                )

                if r2.get("result") == "OK":
                    boilers = r2.get("boilerData", [])
                    users   = r2.get("userData", [])
                    if boilers:
                        self.room_id.set(boilers[0]["roomControlId"])
                    if users:
                        self.device_id.set(users[0].get("deviceId", ""))
                    self._log(
                        f"로그인 성공! roomControlId={self.room_id.get()}",
                        "info", self.login_log
                    )
                    self.conn_var.set(f"연결됨: {self.room_id.get()}")
                    self.conn_label.config(fg="#7ee787")
                else:
                    self._log(f"로그인 실패: {r2}", "err", self.login_log)
            except Exception as e:
                self._log(f"에러: {e}", "err", self.login_log)
        threading.Thread(target=run, daemon=True).start()

    def _do_direct(self):
        if not self.room_id.get() or not self.device_id.get():
            messagebox.showwarning("입력 필요", "Room Control ID와 Device ID를 입력하세요")
            return
        self._do_status()

    # ── 상태 조회 ──────────────────────────────────────────
    def _do_status(self):
        def run():
            try:
                rid = self.room_id.get()
                did = self.device_id.get()
                if not rid or not did:
                    self._log("Room ID / Device ID 없음 — 먼저 로그인하세요", "err")
                    return
                packet = f"sm00020100007d"   # 올바른 쿼리 패킷
                self._log(f"쿼리 → {packet}", "req")
                raw = post_plain(f"{BASE_URL}/query", packet, rid, did)
                self._log(f"응답 ← {raw}", "res")
                self._update_raw_display(raw)
                st = parse_status(raw)
                if st:
                    self.status = st
                    self._update_cards(st)
                self._set_status(f"마지막 조회: {datetime.now().strftime('%H:%M:%S')}")
            except Exception as e:
                self._log(f"에러: {e}", "err")
        threading.Thread(target=run, daemon=True).start()

    def _update_cards(self, st):
        def fmt_bool(v): return "ON" if v else "OFF"
        def fmt_temp(v): return f"{v}°C" if v is not None else "—"

        self.sv["power"].set(fmt_bool(st.get("power")))
        self.sv["heating"].set(fmt_bool(st.get("heating")))
        self.sv["hot_water"].set(fmt_bool(st.get("hot_water")))
        self.sv["go_out"].set(fmt_bool(st.get("go_out")))
        self.sv["pre_heat"].set(fmt_bool(st.get("pre_heat")))
        self.sv["heat_mode"].set("온돌" if st.get("heat_mode") else "실내온도")
        self.sv["room_temp_set"].set(fmt_temp(st.get("room_temp_set")))
        self.sv["room_temp_cur"].set(fmt_temp(st.get("room_temp_cur")))
        self.sv["hw_temp_set"].set(fmt_temp(st.get("hw_temp_set")))
        self.sv["hw_temp_cur"].set(fmt_temp(st.get("hw_temp_cur")))
        self.sv["water_temp"].set(fmt_temp(st.get("water_temp")))
        self.sv["flags_hex"].set(
            f"{st.get('flags_hex','—')} = {st.get('flags_6bit','')}"
        )

    def _update_raw_display(self, raw):
        self.raw_display.configure(state="normal")
        self.raw_display.delete("1.0", tk.END)
        self.raw_display.insert(tk.END, f"RAW:  {raw}\n\n")

        if len(raw) >= 10 and raw[8:10] != "ff":
            try:
                data_len = int(raw[8:10], 16)
                payload  = raw[10:10 + data_len]
                flags    = int(payload[0:2], 16)
                # 정확한 파싱: hex→binary 6비트, reverse 없음
                # returnBinary(0,2,6,payload) in RinnaiResponseController
                f6 = bin(flags)[2:].zfill(6)

                def b(v): return "ON" if v else "OFF"

                self.raw_display.insert(tk.END,
                    f"헤더:        {raw[0:8]}\n"
                    f"데이터길이:  {raw[8:10]} = {data_len}바이트\n"
                    f"페이로드:    {payload}\n\n"
                    f"flags hex:   {payload[0:2]}\n"
                    f"flags 6bit:  {f6}  (no-reverse)\n"
                    f"  charAt(5): {f6[5]} → isPwrOn     전원  = {b(flags & 0x01)}\n"
                    f"  charAt(4): {f6[4]} → isHeatMode  난방모드 = {'온돌' if flags & 0x02 else '실내온도'}  ← 핵심!\n"
                    f"  charAt(3): {f6[3]} → isHeatOn    난방  = {b(flags & 0x04)}\n"
                    f"  charAt(2): {f6[2]} → isHeatWater 온수  = {b(flags & 0x08)}\n"
                    f"  charAt(1): {f6[1]} → isPreHeat   예열  = {b(flags & 0x10)}\n"
                    f"  charAt(0): {f6[0]} → isQuickHeat 빠른예열 = {b(flags & 0x20)}\n\n"
                    f"실내온도 설정: {payload[2:4]} = {int(payload[2:4],16)}°C  → CMD 02\n"
                    f"온수온도 설정: {payload[4:6]} = {int(payload[4:6],16)}°C  → CMD 03 (온돌)\n"
                    f"온수사용온도:  {payload[6:8]} = raw {int(payload[6:8],16)}\n"
                    f"실내온도 현재: {payload[8:10]} = {int(payload[8:10],16)}°C\n"
                    f"온수온도 현재: {payload[10:12] if len(payload)>=12 else '?'}\n"
                )
            except Exception as e:
                self.raw_display.insert(tk.END, f"파싱 오류: {e}\n")
        elif raw[8:10] == "ff":
            sub = raw[10:12] if len(raw) >= 12 else "?"
            msgs = {"08": "기기 연결 해제", "10": "기기 삭제됨",
                    "11": "에러 상태", "12": "에러+삭제"}
            self.raw_display.insert(tk.END,
                f"DATA_LENGTH_ERROR (ff)\n"
                f"서브코드: {sub} → {msgs.get(sub, '알 수 없음')}\n"
            )
        self.raw_display.configure(state="disabled")

    # ── 자동 갱신 ──────────────────────────────────────────
    def _toggle_auto(self):
        self.auto_var.set(not self.auto_var.get())
        if self.auto_var.get():
            self.auto_label.config(text="자동 갱신: ON (30초)", foreground="#7ee787")
            self._auto_loop()
        else:
            self.auto_label.config(text="자동 갱신: OFF", foreground="#888")
            if self._auto_job:
                self.after_cancel(self._auto_job)

    def _auto_loop(self):
        if self.auto_var.get():
            self._do_status()
            self._auto_job = self.after(30000, self._auto_loop)

    # ── 제어 ──────────────────────────────────────────
    def _send_control(self, packet):
        def run():
            try:
                rid = self.room_id.get()
                did = self.device_id.get()
                self._log(f"제어 → {packet}", "req", self.ctrl_log)
                raw = post_plain(f"{BASE_URL}/control", packet, rid, did)
                self._log(f"응답 ← {raw}", "res", self.ctrl_log)
                ok = raw[8:10] != "ff" if len(raw) >= 10 else False
                self._log(f"결과: {'성공' if ok else '실패'}", "info" if ok else "err", self.ctrl_log)
                time.sleep(1)
                self._do_status()
            except Exception as e:
                self._log(f"에러: {e}", "err", self.ctrl_log)
        threading.Thread(target=run, daemon=True).start()

    def _ctrl_power(self, power, heating, hot_water):
        # 프로토콜 가이드 §6: bit0=전원, bit1=온돌, bit2=난방, bit3=온수
        heat_mode = self.status.get("heat_mode", False)  # 현재 온돌/실내 유지
        flags = (
            (0x01 if power     else 0) |
            (0x02 if heat_mode else 0) |
            (0x04 if heating   else 0) |
            (0x08 if hot_water else 0)
        )
        f_hex = format(flags, "02x")
        # CMD 01: sm0003 01 04 [FLAGS] [TEMP] 00 00 7d
        temp = self.status.get("room_temp_set", 22) if not heat_mode else self.status.get("hw_temp_set", 40)
        t_hex = format(temp, "02x")
        self._send_control(f"sm00030104{f_hex}{t_hex}0000{ETX}")

    def _ctrl_heat_mode(self, ondol):
        """온돌/실내온도 모드 전환 — CMD 01 flags bit1"""
        # ondol=True  → 0x07 (전원+온돌+난방)
        # ondol=False → 0x05 (전원+난방)
        flags = 0x01 | 0x04 | (0x02 if ondol else 0x00)
        temp = self.status.get("hw_temp_set", 40) if ondol else self.status.get("room_temp_set", 22)
        f_hex = format(flags, "02x")
        t_hex = format(temp, "02x")
        self._send_control(f"sm00030104{f_hex}{t_hex}0000{ETX}")

    def _ctrl_temp_room(self):
        """실내온도 모드 — CMD 02"""
        temp = self.temp_var.get()
        data = format(temp, "02x")
        self._send_control(f"sm000302 02 {data} 00 7d".replace(" ", ""))

    def _ctrl_temp_ondol(self):
        """온돌 모드 — CMD 03"""
        temp = self.ondol_var.get()
        data = format(temp, "02x")
        self._send_control(f"sm000303 02 {data} 00 7d".replace(" ", ""))

    def _ctrl_goout(self, on):
        data = "80" if on else "00"
        self._send_control(f"sm000305 02 {data} 00 7d".replace(" ", ""))

    def _ctrl_save(self, on):
        data = "80" if on else "00"
        self._send_control(f"sm000307 02 {data} 00 7d".replace(" ", ""))

    def _ctrl_sleep(self, on):
        data = "80" if on else "00"
        self._send_control(f"sm000308 02 {data} 00 7d".replace(" ", ""))

    def _ctrl_custom(self, endpoint):
        packet = self.custom_var.get().strip()
        def run():
            try:
                rid = self.room_id.get()
                did = self.device_id.get()
                self._log(f"커스텀 [{endpoint}] → {packet}", "req", self.ctrl_log)
                raw = post_plain(f"{BASE_URL}/{endpoint}", packet, rid, did)
                self._log(f"응답 ← {raw}", "res", self.ctrl_log)
                self._update_raw_display(raw)
            except Exception as e:
                self._log(f"에러: {e}", "err", self.ctrl_log)
        threading.Thread(target=run, daemon=True).start()

    def _clear_log(self):
        self.full_log.configure(state="normal")
        self.full_log.delete("1.0", tk.END)
        self.full_log.configure(state="disabled")


if __name__ == "__main__":
    app = RinnaiDebugger()
    app.mainloop()