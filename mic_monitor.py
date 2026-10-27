#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mic-monitor — маленький оверлей: текущая громкость микрофона и история её изменений.

Что показывает:
  * громкость устройства записи (тот же ползунок, что «Уровень» в настройках Windows);
  * живой уровень сигнала (peak) с устройства;
  * кто менял громкость: Windows не сообщает автора изменения, поэтому приложение
    показывает кандидатов, собранных в момент изменения (активное окно, программы,
    которые в этот момент держат микрофон, только что запущенные процессы).

Запуск GUI:      python mic_monitor.py
Диагностика:     python mic_monitor.py --probe
Лог без окна:    python mic_monitor.py --watch 30
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import json
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

APP_NAME = "MicMonitor"
__version__ = "1.2.0"
APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_NAME
HISTORY_FILE = APP_DIR / "history.jsonl"
CONFIG_FILE = APP_DIR / "config.json"
LOG_FILE = APP_DIR / "mic-monitor.log"

POLL_INTERVAL = 0.12        # секунд между опросами громкости/пика
SLOW_INTERVAL = 1.5         # как часто перечитывать список устройств и аудио-сессии
VOLUME_EPS = 0.005          # 0.5% — меньше считаем шумом
NEW_SESSION_WINDOW = 4.0    # «программа только что открыла микрофон»
RECENT_PROC_WINDOW = 8.0    # «программа только что запустилась»
CLSCTX_ALL = 23

# Панели и утилиты, которые умеют менять громкость записи сами по себе.
# Совпадение по подстроке в имени процесса (нижний регистр).
KNOWN_CONTROL_APPS = (
    "realtek", "nahimic", "sonicstudio", "sonar", "steelseries",
    "voicemeeter", "voicemod", "equalizerapo", "peace", "waves",
    "soundvolumeview", "nircmd", "audioswitcher", "soundswitch",
    "razer", "corsair", "logitech", "hyperx", "ngenuity", "icue",
    "armoury", "msi", "dragon", "asus", "creative", "sbc",
)
OWN_EXE = Path(sys.argv[0]).stem.lower()


# ----------------------------------------------------------------------------
# Модель данных
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    title: str = ""


@dataclass(frozen=True)
class SessionInfo:
    pid: int
    name: str
    state: int  # 0 = неактивна, 1 = активна, 2 = просрочена

    @property
    def active(self) -> bool:
        return self.state == 1


@dataclass
class Snapshot:
    device_id: str
    device_name: str
    volume: float                 # 0..1
    muted: bool
    peak: float                   # 0..1
    sessions: tuple[SessionInfo, ...] = ()
    ts: float = field(default_factory=time.time)


@dataclass
class Candidate:
    name: str
    pid: int
    reason: str
    score: float
    title: str = ""
    exe: str = ""
    parent: str = ""


@dataclass
class Change:
    ts: float
    kind: str                     # volume | mute | device | session_start | session_stop
    device: str
    device_id: str
    old: Any
    new: Any
    candidates: list[Candidate] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        top = primary_suspect(self.candidates)
        return {
            "ts": self.ts,
            "time": datetime.fromtimestamp(self.ts).strftime("%d.%m.%Y %H:%M:%S"),
            "kind": self.kind,
            "device": self.device,
            "device_id": self.device_id,
            "old": self.old,
            "new": self.new,
            "suspect": {
                "name": top.name, "pid": top.pid, "reason": top.reason,
                "confidence": confidence(self.candidates),
            } if top else None,
            "candidates": [
                {"name": c.name, "pid": c.pid, "reason": c.reason,
                 "score": round(c.score, 2), "exe": c.exe, "parent": c.parent}
                for c in self.candidates
            ],
            "context": self.context,
        }


# ----------------------------------------------------------------------------
# Чистая логика (тестируется без Windows/звуковых устройств)
# ----------------------------------------------------------------------------

def detect_changes(prev: Snapshot | None, cur: Snapshot, eps: float = VOLUME_EPS) -> list[tuple[str, Any, Any]]:
    """Сравнить два снимка и вернуть список изменений (kind, было, стало)."""
    if prev is None:
        return []
    if prev.device_id != cur.device_id:
        return [("device", prev.device_name, cur.device_name)]

    result: list[tuple[str, Any, Any]] = []
    if abs(prev.volume - cur.volume) > eps:
        result.append(("volume", prev.volume, cur.volume))
    if prev.muted != cur.muted:
        result.append(("mute", prev.muted, cur.muted))

    before = {s.pid: s for s in prev.sessions}
    after = {s.pid: s for s in cur.sessions}
    for pid, s in after.items():
        if pid not in before and s.active:
            result.append(("session_start", None, s.name))
        elif pid in before and not before[pid].active and s.active:
            result.append(("session_start", None, s.name))
    for pid, s in before.items():
        if (pid not in after or not after[pid].active) and s.active:
            result.append(("session_stop", s.name, None))
    return result


def score_candidates(
    *,
    foreground: ProcInfo | None = None,
    sessions: Iterable[SessionInfo] = (),
    new_session_pids: Iterable[int] = (),
    recent: Iterable[ProcInfo] = (),
    exclude_pids: Iterable[int] = (),
) -> list[Candidate]:
    """Собрать и упорядочить подозреваемых: кто мог поменять громкость.

    Windows не отдаёт автора изменения. Это не доказательство, а набор улик:
    чем выше score, тем вероятнее, что программа причастна.
    """
    exclude = set(exclude_pids)
    scored: dict[int, Candidate] = {}

    def push(info: ProcInfo, score: float, reason: str) -> None:
        if info.pid in exclude or info.pid == 0 or not info.name:
            return
        cur = scored.get(info.pid)
        if cur is None:
            scored[info.pid] = Candidate(info.name, info.pid, reason, score, info.title)
        else:
            reasons = [] if reason in cur.reason else [reason]
            cur.reason = "; ".join([cur.reason] + reasons)
            if score > cur.score:
                cur.score = score
                cur.name = info.name or cur.name

    for s in sessions:
        if s.pid in set(new_session_pids):
            push(ProcInfo(s.pid, s.name), 3.2, "только что открыл микрофон")
        elif s.active:
            push(ProcInfo(s.pid, s.name), 2.0, "держит микрофон")
        else:
            push(ProcInfo(s.pid, s.name), 0.6, "микрофон открыт в фоне")

    for p in recent:
        push(p, 2.2, "запущен только что")

    if foreground is not None:
        push(foreground, 3.0, "активное окно")

    for info in list(scored.values()):
        low = info.name.lower()
        if any(key in low for key in KNOWN_CONTROL_APPS):
            info.score += 1.2
            info.reason += "; панель управления звуком"

    rows = sorted(scored.values(), key=lambda c: (-c.score, c.name.lower()))[:4]
    for row in rows:
        row.exe, row.parent = _process_details(row.pid)
    return rows


def _process_details(pid: int) -> tuple[str, str]:
    """Путь к exe и имя родительского процесса — чтобы в логе было видно, кто это."""
    if pid <= 0:
        return "", ""
    try:
        import psutil
        proc = psutil.Process(pid)
        exe = ""
        try:
            exe = proc.exe()
        except Exception:
            exe = ""
        parent = ""
        try:
            parent = proc.parent().name()
        except Exception:
            parent = ""
        return exe, parent
    except Exception:
        return "", ""


def primary_suspect(candidates: Iterable[Candidate]) -> Candidate | None:
    rows = sorted(candidates, key=lambda c: -c.score)
    return rows[0] if rows else None


def confidence(candidates: Iterable[Candidate]) -> str:
    """Насколько уверенно можно назвать виновника (эвристика, не факт)."""
    rows = sorted(candidates, key=lambda c: -c.score)
    if not rows:
        return "нет данных"
    top = rows[0].score
    gap = top - (rows[1].score if len(rows) > 1 else 0.0)
    if top >= 3.0 and gap >= 0.8:
        return "высокая"
    if top >= 2.5 or (top >= 2.0 and gap >= 0.3):
        return "средняя"
    return "низкая"


def fmt_volume(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{round(value * 100):d}%"


def fmt_value(kind: str, value: Any) -> str:
    """Значение для таблицы/CSV: громкость в процентах, mute словами."""
    if value is None:
        return ""
    if kind == "mute":
        return "выключен" if value else "включён"
    if isinstance(value, float):
        return fmt_volume(value)
    return str(value)


def short_device(name: str, limit: int = 34) -> str:
    name = " ".join((name or "Устройство записи").split())
    return name if len(name) <= limit else name[: limit - 1] + "…"


def describe_change(change: Change) -> str:
    """Человекочитаемая строка для оверлея."""
    if change.kind == "volume":
        return f"{fmt_volume(change.old)} → {fmt_volume(change.new)}"
    if change.kind == "mute":
        return "микрофон выключен" if change.new else "микрофон включён"
    if change.kind == "device":
        return f"другое устройство: {short_device(str(change.new), 22)}"
    if change.kind == "session_start":
        return f"{change.new} открыл микрофон"
    if change.kind == "session_stop":
        return f"{change.old} отпустил микрофон"
    return change.kind


# ----------------------------------------------------------------------------
# Windows-хелперы
# ----------------------------------------------------------------------------

def foreground_process() -> ProcInfo | None:
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        title_buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title_buf, 256)

        import psutil
        proc = psutil.Process(pid.value)
        return ProcInfo(pid.value, proc.name(), title_buf.value)
    except Exception:
        return None


def recent_processes(window: float = RECENT_PROC_WINDOW) -> list[ProcInfo]:
    try:
        import psutil
        now = time.time()
        found: list[ProcInfo] = []
        for proc in psutil.process_iter(["pid", "name", "create_time"]):
            try:
                created = proc.info.get("create_time") or 0
                if now - created <= window:
                    found.append(ProcInfo(proc.info["pid"], proc.info.get("name") or ""))
            except Exception:
                continue
        return found
    except Exception:
        return []


# ----------------------------------------------------------------------------
# Аудио через Core Audio (pycaw)
# ----------------------------------------------------------------------------

class DeviceHandle:
    """Обёртка над устройством записи: громкость, mute, пик, сессии."""

    def __init__(self, device, meter=None):
        from pycaw.pycaw import IAudioSessionControl2

        self.device = device
        self.id: str = device.id
        self.name: str = device.FriendlyName or "Устройство записи"
        self._meter = meter
        self._session_ctl = IAudioSessionControl2

    # --- чтение -------------------------------------------------------
    def volume(self) -> float:
        return float(self.device.EndpointVolume.GetMasterVolumeLevelScalar())

    def muted(self) -> bool:
        return bool(self.device.EndpointVolume.GetMute())

    def peak(self) -> float:
        if self._meter is None:
            return 0.0
        try:
            return max(0.0, min(1.0, float(self._meter.GetPeakValue())))
        except Exception:
            return 0.0

    def sessions(self) -> tuple[SessionInfo, ...]:
        try:
            enumerator = self.device.AudioSessionManager.GetSessionEnumerator()
            count = enumerator.GetCount()
        except Exception:
            return ()
        out: list[SessionInfo] = []
        for i in range(count):
            try:
                ctl = enumerator.GetSession(i).QueryInterface(self._session_ctl)
                pid = ctl.GetProcessId()
                state = ctl.GetState()
                name = ""
                if pid:
                    try:
                        import psutil
                        name = psutil.Process(pid).name()
                    except Exception:
                        name = f"pid {pid}"
                if name and pid:
                    out.append(SessionInfo(pid, name, int(state)))
            except Exception:
                continue
        return tuple(out)


class AudioBackend:
    def __init__(self) -> None:
        import comtypes  # noqa: F401  (инициализирует COM в этом потоке)
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation, IAudioSessionControl2
        from pycaw.constants import AudioDeviceState, EDataFlow, ERole

        self._AudioUtilities = AudioUtilities
        self._Meter = IAudioMeterInformation
        self._SessionCtl = IAudioSessionControl2
        self._State = AudioDeviceState
        self._Flow = EDataFlow
        self._Role = ERole

    def capture_devices(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        try:
            for dev in self._AudioUtilities.GetAllDevices(
                data_flow=self._Flow.eCapture.value,
                device_state=self._State.Active.value,
            ):
                out.append((dev.id, dev.FriendlyName or "Устройство записи"))
        except Exception:
            pass
        return out

    def default_id(self) -> str | None:
        try:
            enum = self._AudioUtilities.GetDeviceEnumerator()
            dev = enum.GetDefaultAudioEndpoint(
                self._Flow.eCapture.value, self._Role.eMultimedia.value
            )
            return dev.GetId()
        except Exception:
            return None

    def open(self, device_id: str | None) -> DeviceHandle | None:
        devices = self._AudioUtilities.GetAllDevices(
            data_flow=self._Flow.eCapture.value,
            device_state=self._State.Active.value,
        )
        chosen = None
        for dev in devices:
            if device_id is None:
                break
            if dev.id == device_id:
                chosen = dev
                break
        if chosen is None:
            target_id = device_id or self.default_id()
            for dev in devices:
                if dev.id == target_id:
                    chosen = dev
                    break
        if chosen is None and devices:
            chosen = devices[0]
        if chosen is None:
            return None

        meter = None
        try:
            raw = chosen._dev.Activate(self._Meter._iid_, CLSCTX_ALL, None)
            meter = raw.QueryInterface(self._Meter)
        except Exception:
            meter = None
        return DeviceHandle(chosen, meter)


# ----------------------------------------------------------------------------
# История изменений
# ----------------------------------------------------------------------------

class History:
    def __init__(self, path: Path = HISTORY_FILE, limit: int = 500) -> None:
        self.path = path
        self.limit = limit
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                lines = fh.readlines()[-self.limit:]
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            pass

    def add(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.records.append(record)
            if len(self.records) > self.limit:
                self.records = self.records[-self.limit:]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError:
                pass

    def programs(self) -> list[tuple[str, int, str, str]]:
        """Сводка: программа → сколько раз совпала с изменением, последний раз, что меняла."""
        stats: dict[str, dict[str, Any]] = {}
        for rec in self.records:
            for cand in rec.get("candidates", []):
                name = cand.get("name") or "?"
                item = stats.setdefault(name, {"count": 0, "last": "", "values": []})
                item["count"] += 1
                item["last"] = rec.get("time", "")
                if rec.get("kind") == "volume":
                    values = f"{fmt_volume(rec.get('old'))}→{fmt_volume(rec.get('new'))}"
                    if len(item["values"]) < 6 and values not in item["values"]:
                        item["values"].append(values)
        rows = []
        for name, item in stats.items():
            rows.append((name, item["count"], item["last"], ", ".join(item["values"])))
        rows.sort(key=lambda r: (-r[1], r[0].lower()))
        return rows

    def export_csv(self) -> Path:
        out = self.path.parent / f"mic-history-{datetime.now():%Y%m%d-%H%M%S}.csv"
        with out.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow(["время", "тип", "устройство", "было", "стало", "программы"])
            for rec in self.records:
                names = ", ".join(c.get("name", "?") for c in rec.get("candidates", []))
                old, new = rec.get("old"), rec.get("new")
                writer.writerow([
                    rec.get("time", ""),
                    rec.get("kind", ""),
                    rec.get("device", ""),
                    fmt_value(rec.get("kind", ""), old),
                    fmt_value(rec.get("kind", ""), new),
                    names,
                ])
        return out


# ----------------------------------------------------------------------------
# Текстовый лог «кто это сделал»
# ----------------------------------------------------------------------------

KIND_TITLES = {
    "volume": "ГРОМКОСТЬ",
    "mute": "MUTE",
    "device": "УСТРОЙСТВО",
    "session_start": "ОТКРЫЛ МИКРОФОН",
    "session_stop": "ЗАКРЫЛ МИКРОФОН",
}


class Logger:
    """Пишет подробный текстовый лог: что изменилось и кто был рядом в этот момент."""

    def __init__(self, path: Path = LOG_FILE, max_bytes: int = 1_000_000) -> None:
        self.path = path
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                        self.path.replace(self.path.with_name(self.path.name + ".1"))
                except OSError:
                    pass
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(text.rstrip() + "\n")
            except OSError:
                pass

    # ------------------------------------------------------------------
    def startup(self, device: str, source: str) -> None:
        self.write(f"=== запуск ({source}) · устройство: {device}")

    def change(self, record: dict[str, Any], echo: bool = False) -> str:
        kind = record.get("kind", "")
        title = KIND_TITLES.get(kind, kind.upper())
        old, new = fmt_value(kind, record.get("old")), fmt_value(kind, record.get("new"))
        if kind in ("volume", "mute"):
            what = f"{old} → {new}"
        elif kind == "device":
            what = f"{old} → {new}"
        else:
            what = new or old

        lines = [f"[{title}] {what}  ·  {record.get('device', '')}"]

        suspect = record.get("suspect")
        if suspect:
            lines.append(f"    виновник: {suspect['name']} (pid {suspect['pid']}) — "
                         f"уверенность {suspect['confidence']}")
            lines.append(f"      причина: {suspect['reason']}")
            for cand in record.get("candidates", []):
                if cand.get("pid") == suspect["pid"]:
                    if cand.get("exe"):
                        lines.append(f"      файл: {cand['exe']}")
                    if cand.get("parent"):
                        lines.append(f"      родитель: {cand['parent']}")
                    break
            others = [c["name"] for c in record.get("candidates", [])
                      if c.get("pid") != suspect["pid"]]
            if others:
                lines.append(f"    ещё под подозрением: {', '.join(others)}")
        elif kind in ("volume", "mute", "device"):
            lines.append("    виновник: не определён")

        ctx = record.get("context") or {}
        fg = ctx.get("foreground")
        if fg:
            title_txt = f" «{fg.get('title')}»" if fg.get("title") else ""
            lines.append(f"    активное окно: {fg.get('name')} (pid {fg.get('pid')}){title_txt}")
        sessions = ctx.get("sessions") or []
        if sessions:
            lines.append("    держат микрофон: " + ", ".join(
                f"{s['name']}({s['pid']})" for s in sessions[:6]))
        recent = ctx.get("recent") or []
        if recent:
            lines.append("    свежие процессы: " + ", ".join(
                f"{p['name']}({p['pid']})" for p in recent[:6]))

        text = f"{record.get('time', '')}  " + "\n".join(lines)
        self.write(text)
        if echo:
            print(text, flush=True)
        return text


def play_alert(kind: str) -> None:
    """Звук на изменение. Системный, без внешних файлов."""
    try:
        import winsound
        if kind == "mute":
            winsound.PlaySound("SystemHand",
                               winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        else:
            winsound.PlaySound("SystemNotification",
                               winsound.SND_ALIAS | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        try:
            import winsound
            winsound.MessageBeep(0x30)
        except Exception:
            pass


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "mic-monitor"


def launch_command() -> str:
    """Команда автозапуска: для собранного exe — он сам, для исходников — pythonw + скрипт."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    if not pyw.exists():
        pyw = exe
    return f'"{pyw}" "{Path(__file__).resolve()}"'


def autostart_enabled() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_VALUE)
        return bool(value)
    except OSError:
        return False
    except Exception:
        return False


def set_autostart(enable: bool) -> bool:
    """Включить/выключить запуск с Windows. Возвращает новое состояние."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, RUN_VALUE, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE)
                except FileNotFoundError:
                    pass
        return autostart_enabled()
    except Exception:
        return autostart_enabled()


# ----------------------------------------------------------------------------
# Фоновый наблюдатель
# ----------------------------------------------------------------------------
class Watcher(threading.Thread):
    """Опрашивает устройство, определяет изменения и складывает их в очередь."""

    def __init__(self, out: queue.Queue, history: History,
                 device_id: str | None = None, logger: Logger | None = None) -> None:
        super().__init__(daemon=True, name="mic-watcher")
        self.out = out
        self.history = history
        self.logger = logger or Logger()
        self.device_id = device_id
        self._stop = threading.Event()
        self._prev: Snapshot | None = None
        self._handle: DeviceHandle | None = None
        self._session_seen: dict[int, float] = {}
        self._first_sessions = True
        self._last_slow = 0.0

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    def run(self) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        backend = None
        try:
            backend = AudioBackend()
        except Exception as exc:
            self.out.put({"type": "error", "text": f"Core Audio недоступен: {exc}"})
            return

        try:
            while not self._stop.is_set():
                try:
                    self._tick(backend)
                except Exception as exc:  # устройство выдернули, COM упал и т.п.
                    self.out.put({"type": "warning", "text": f"сбой опроса: {exc}"})
                    self._handle = None
                    time.sleep(0.5)
                time.sleep(POLL_INTERVAL)
        finally:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass

    # ------------------------------------------------------------------
    def _tick(self, backend: AudioBackend) -> None:
        now = time.time()
        slow = (now - self._last_slow) >= SLOW_INTERVAL

        if self._handle is None or slow:
            default_id = backend.default_id()
            wanted = self.device_id or default_id
            if self._handle is None or self._handle.id != wanted:
                handle = backend.open(wanted)
                if handle is None:
                    self.out.put({"type": "warning", "text": "нет доступных устройств записи"})
                    return
                self._handle = handle
                self._prev = None
                self.logger.startup(handle.name, "наблюдатель")
            self._last_slow = now

        handle = self._handle
        assert handle is not None

        sessions = handle.sessions() if slow else (self._prev.sessions if self._prev else ())
        snap = Snapshot(
            device_id=handle.id,
            device_name=handle.name,
            volume=handle.volume(),
            muted=handle.muted(),
            peak=handle.peak(),
            sessions=sessions,
            ts=now,
        )

        # запомнить, когда каждая сессия появилась
        active_pids = {s.pid for s in snap.sessions if s.active}
        for pid in active_pids:
            if pid not in self._session_seen:
                # на старте уже открытые микрофоны не считаем «только что открытыми»
                self._session_seen[pid] = (now if not self._first_sessions
                                           else now - NEW_SESSION_WINDOW - 5)
        if snap.sessions:
            self._first_sessions = False
        for pid in list(self._session_seen):
            if pid not in active_pids:
                self._session_seen.pop(pid, None)

        changes = detect_changes(self._prev, snap)
        self._prev = snap

        self.out.put({
            "type": "state",
            "device": snap.device_name,
            "device_id": snap.device_id,
            "volume": snap.volume,
            "muted": snap.muted,
            "peak": snap.peak,
            "sessions": [(s.pid, s.name, s.active) for s in snap.sessions],
            "devices": backend.capture_devices() if slow else None,
        })

        for kind, old, new in changes:
            change = Change(
                ts=now,
                kind=kind,
                device=snap.device_name,
                device_id=snap.device_id,
                old=round(old, 3) if isinstance(old, float) else old,
                new=round(new, 3) if isinstance(new, float) else new,
            )
            if kind in ("volume", "mute", "device"):
                freshest = handle.sessions()
                if freshest:
                    snap.sessions = freshest
                new_pids = [pid for pid, seen in self._session_seen.items()
                            if now - seen <= NEW_SESSION_WINDOW]
                fg = foreground_process()
                recent = recent_processes()
                change.candidates = score_candidates(
                    foreground=fg,
                    sessions=snap.sessions,
                    new_session_pids=new_pids,
                    recent=recent,
                    exclude_pids=(os.getpid(),),
                )
                change.context = {
                    "foreground": (
                        {"name": fg.name, "pid": fg.pid, "title": fg.title} if fg else None
                    ),
                    "sessions": [{"name": s.name, "pid": s.pid} for s in snap.sessions if s.active],
                    "recent": [{"name": p.name, "pid": p.pid} for p in recent[:8]],
                }
            record = change.to_record()
            self.history.add(record)
            self.logger.change(record)
            self.out.put({"type": "change", "change": record})


# ----------------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------------

BG = "#12141a"
BAR_BG = "#232936"
FG = "#e9eef7"
DIM = "#8b93a6"
OK = "#3ddc84"
BAD = "#ff5d5d"
SIG = "#4aa3ff"
ACCENT = "#7c8cff"

FONT_MAIN = ("Segoe UI", 9)
FONT_SMALL = ("Segoe UI", 8)
FONT_VALUE = ("Segoe UI Semibold", 20)


class Overlay:
    """Маленькое окно поверх всех: громкость, сигнал, последнее изменение."""

    def __init__(self, app: "App") -> None:
        import tkinter as tk
        from tkinter import ttk  # noqa: F401

        self.tk = tk
        self.app = app
        self.cfg = app.config
        self.compact = bool(self.cfg.get("compact", False))
        self._drag = (0, 0)
        self._peak_disp = 0.0
        self._history_win: HistoryWindow | None = None

        root = tk.Tk()
        self.root = root
        root.title("mic-monitor")
        root.configure(bg=BG)
        root.overrideredirect(True)
        root.attributes("-topmost", bool(self.cfg.get("topmost", True)))
        root.attributes("-alpha", float(self.cfg.get("opacity", 0.97)))

        self._build()
        self._place_window()
        self._bind_drag()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(120, self._pump)

    # ------------------------------------------------------------------
    def _build(self) -> None:
        tk = self.tk
        root = self.root

        outer = tk.Frame(root, bg=BG, highlightthickness=1,
                         highlightbackground="#2c3342")
        outer.pack(fill="both", expand=True)
        self.outer = outer

        # верхняя полоса: имя устройства + кнопки
        top = tk.Frame(outer, bg=BG)
        top.pack(fill="x", padx=8, pady=(6, 0))
        self.device_lbl = tk.Label(top, text="устройство записи", bg=BG, fg=DIM,
                                   font=FONT_SMALL, anchor="w")
        self.device_lbl.pack(side="left", fill="x", expand=True)

        self.btn_close = self._mini_button(top, "✕", self.close)
        self.btn_menu = self._mini_button(top, "☰", self._popup_menu)
        self.btn_expand = self._mini_button(top, "▤", self.toggle_history)

        # громкость
        vol_row = tk.Frame(outer, bg=BG)
        vol_row.pack(fill="x", padx=8, pady=(2, 0))
        self.vol_lbl = tk.Label(vol_row, text="—", bg=BG, fg=FG, font=FONT_VALUE)
        self.vol_lbl.pack(side="left")
        self.state_lbl = tk.Label(vol_row, text="", bg=BG, fg=DIM, font=FONT_SMALL)
        self.state_lbl.pack(side="left", padx=(6, 0), pady=(8, 0))

        self.vol_canvas = tk.Canvas(outer, height=12, bg=BAR_BG, highlightthickness=0)
        self.vol_canvas.pack(fill="x", padx=8, pady=(1, 0))
        self.vol_fill = self.vol_canvas.create_rectangle(0, 0, 0, 12, fill=OK, width=0)
        self.vol_canvas.bind("<Configure>", lambda _e: self._redraw_bars())

        # сигнал
        self.sig_frame = tk.Frame(outer, bg=BG)
        self.sig_frame.pack(fill="x", padx=8, pady=(6, 0))
        self.sig_lbl = tk.Label(self.sig_frame, text="сигнал", bg=BG, fg=DIM, font=FONT_SMALL,
                                anchor="w")
        self.sig_lbl.pack(side="left")
        self.sig_val = tk.Label(self.sig_frame, text="0%", bg=BG, fg=DIM, font=FONT_SMALL)
        self.sig_val.pack(side="right")
        self.sig_canvas = tk.Canvas(outer, height=5, bg=BAR_BG, highlightthickness=0)
        self.sig_canvas.pack(fill="x", padx=8, pady=(1, 0))
        self.sig_fill = self.sig_canvas.create_rectangle(0, 0, 0, 5, fill=SIG, width=0)
        self.sig_canvas.bind("<Configure>", lambda _e: self._redraw_bars())

        # последнее изменение
        self.last_frame = tk.Frame(outer, bg=BG)
        self.last_frame.pack(fill="x", padx=8, pady=(6, 0))
        self.last_lbl = tk.Label(self.last_frame, text="изменений пока не было", bg=BG,
                                 fg=DIM, font=FONT_SMALL, anchor="w", justify="left")
        self.last_lbl.pack(fill="x")

        self.who_lbl = tk.Label(outer, text="", bg=BG, fg=ACCENT, font=FONT_SMALL,
                                anchor="w", justify="left")
        self.who_lbl.pack(fill="x", padx=8, pady=(1, 6))

        self._apply_compact()

    def _mini_button(self, parent, text: str, command) -> Any:
        lbl = self.tk.Label(parent, text=text, bg=BG, fg=DIM, font=("Segoe UI", 10),
                            cursor="hand2", padx=3)
        lbl.pack(side="right")
        lbl.bind("<Button-1>", lambda _e: command())
        lbl.bind("<Enter>", lambda _e: lbl.configure(fg=FG))
        lbl.bind("<Leave>", lambda _e: lbl.configure(fg=DIM))
        return lbl

    # ------------------------------------------------------------------
    def _geometry(self) -> tuple[int, int]:
        return (300, 96) if self.compact else (332, 168)

    def _place_window(self) -> None:
        w, h = self._geometry()
        x = int(self.cfg.get("x", 40))
        y = int(self.cfg.get("y", 40))
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _apply_compact(self) -> None:
        if self.compact:
            self.sig_frame.pack_forget()
            self.sig_canvas.pack_forget()
            self.last_frame.pack_forget()
            self.who_lbl.pack_forget()
        else:
            self.sig_frame.pack(fill="x", padx=8, pady=(6, 0), after=self.vol_canvas)
            self.sig_canvas.pack(fill="x", padx=8, pady=(1, 0), after=self.sig_frame)
            self.last_frame.pack(fill="x", padx=8, pady=(6, 0))
            self.who_lbl.pack(fill="x", padx=8, pady=(1, 6))
        self._place_window()

    def toggle_compact(self) -> None:
        self.compact = not self.compact
        self.cfg["compact"] = self.compact
        self._apply_compact()

    # ------------------------------------------------------------------
    def _bind_drag(self) -> None:
        for widget in (self.outer, self.vol_canvas, self.sig_canvas, self.last_frame,
                       self.last_lbl, self.device_lbl, self.vol_lbl, self.state_lbl,
                       self.sig_lbl, self.sig_val, self.who_lbl):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<Double-Button-1>", lambda _e: self.toggle_history())
            widget.bind("<Button-3>", self._popup_menu)

    def _drag_start(self, event) -> None:
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event) -> None:
        x = event.x_root - self._drag[0]
        y = event.y_root - self._drag[1]
        self.root.geometry(f"+{x}+{y}")
        self.cfg["x"], self.cfg["y"] = x, y

    # ------------------------------------------------------------------
    def _popup_menu(self, event=None) -> None:
        tk = self.tk
        menu = tk.Menu(self.root, tearoff=0, bg="#1b202b", fg=FG,
                       activebackground="#2a3242", activeforeground=FG, bd=0)
        menu.add_command(label="История изменений", command=self.toggle_history)
        menu.add_command(label="Компактный вид" if not self.compact else "Полный вид",
                         command=self.toggle_compact)
        menu.add_checkbutton(label="Поверх всех окон", command=self.toggle_topmost,
                             variable=tk.BooleanVar(value=bool(self.root.attributes("-topmost"))))
        menu.add_checkbutton(label="Звук при изменении", command=self.toggle_sound,
                             variable=tk.BooleanVar(value=bool(self.cfg.get("sound", True))))
        menu.add_checkbutton(label="Запускать с Windows", command=self.toggle_autostart,
                             variable=tk.BooleanVar(value=autostart_enabled()))
        menu.add_separator()
        menu.add_command(label="Открыть лог", command=self._open_log)
        menu.add_command(label="Открыть историю (папка)", command=self._open_folder)
        if self.app.current:
            menu.add_separator()
            for dev_id, dev_name in self.app.devices:
                mark = "● " if dev_id == self.app.device_id else "   "
                menu.add_command(label=mark + short_device(dev_name, 40),
                                 command=lambda d=dev_id: self.app.select_device(d))
        menu.add_separator()
        menu.add_command(label="Сбросить на устройство по умолчанию",
                         command=lambda: self.app.select_device(None))
        menu.add_command(label="Выход", command=self.close)
        try:
            menu.tk_popup(event.x_root if event else self.root.winfo_pointerx(),
                          event.y_root if event else self.root.winfo_pointery())
        finally:
            menu.grab_release()

    def toggle_topmost(self) -> None:
        value = not bool(self.root.attributes("-topmost"))
        self.root.attributes("-topmost", value)
        self.cfg["topmost"] = value

    def toggle_sound(self) -> None:
        self.cfg["sound"] = not bool(self.cfg.get("sound", True))
        if self.cfg["sound"]:
            play_alert("volume")

    def toggle_autostart(self) -> None:
        self.cfg["autostart"] = set_autostart(not autostart_enabled())

    def _open_log(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            LOG_FILE.touch(exist_ok=True)
            os.startfile(str(LOG_FILE))  # noqa: S606  (Windows shell)
        except Exception:
            pass

    def _open_folder(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(str(APP_DIR))  # noqa: S606
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _pump(self) -> None:
        """Забрать события наблюдателя из очереди и обновить картинку."""
        try:
            while True:
                event = self.app.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.root.after(110, self._pump)

    def _handle_event(self, event: dict[str, Any]) -> None:
        kind = event["type"]
        if kind == "state":
            self.app.current = event
            if event.get("devices"):
                self.app.devices = event["devices"]
            self.app.device_id = event["device_id"]
            self._render_state(event)
        elif kind == "change":
            change = event["change"]
            if self.cfg.get("sound", True):
                play_alert(change.get("kind", ""))
            self._render_change(change)
            if self._history_win is not None:
                self._history_win.refresh()
        elif kind in ("error", "warning"):
            self.device_lbl.configure(text=event.get("text", ""), fg=BAD)

    def _render_state(self, st: dict[str, Any]) -> None:
        self.device_lbl.configure(text=short_device(st["device"], 40), fg=DIM)
        self.vol_lbl.configure(text=fmt_volume(st["volume"]),
                               fg=BAD if st["muted"] else FG)
        self.state_lbl.configure(text="ВЫКЛ" if st["muted"] else "", fg=BAD)

        self._peak_disp = max(st["peak"], self._peak_disp * 0.80)
        self.sig_val.configure(text=fmt_volume(self._peak_disp))
        self._redraw_bars()

        active = sorted({name for _pid, name, is_active in st.get("sessions", ()) if is_active})
        if active:
            extra = f" +{len(active) - 2}" if len(active) > 2 else ""
            self.sig_lbl.configure(text=short_device("сигнал · " + ", ".join(active[:2]) + extra, 46))
        else:
            self.sig_lbl.configure(text="сигнал · микрофон свободен")

    def _redraw_bars(self) -> None:
        st = self.app.current
        if not st:
            return
        width = max(1, self.vol_canvas.winfo_width())
        value = 0.0 if st["muted"] else float(st["volume"])
        self.vol_canvas.coords(self.vol_fill, 0, 0, int(width * value), 12)
        self.vol_canvas.itemconfigure(self.vol_fill, fill=BAD if st["muted"] else OK)

        sig_w = max(1, self.sig_canvas.winfo_width())
        self.sig_canvas.coords(self.sig_fill, 0, 0, int(sig_w * self._peak_disp), 5)

    def _render_change(self, change: dict[str, Any]) -> None:
        when = datetime.fromtimestamp(change["ts"]).strftime("%H:%M:%S")
        text = describe_change(Change(**{k: change[k] for k in
                                         ("ts", "kind", "device", "device_id", "old", "new")},
                                     candidates=[]))
        self.last_lbl.configure(text=f"{when}  {text}", fg=FG)

        suspect = change.get("suspect")
        if suspect:
            conf = suspect.get("confidence", "")
            color = OK if conf == "высокая" else (ACCENT if conf == "средняя" else DIM)
            self.who_lbl.configure(
                text=short_device(f"{suspect['name']} · {suspect['reason']} ({conf})", 52),
                fg=color,
            )
        else:
            self.who_lbl.configure(text="виновник не определён", fg=DIM)

    # ------------------------------------------------------------------
    def toggle_history(self) -> None:
        if self._history_win is not None and self._history_win.alive():
            self._history_win.focus()
            return
        self._history_win = HistoryWindow(self)

    def close(self) -> None:
        self.app.save_config()
        try:
            self.root.destroy()
        finally:
            self.app.shutdown()


class HistoryWindow:
    """Окно с историей изменений и сводкой по программам."""

    def __init__(self, overlay: Overlay) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.overlay = overlay
        self.app = overlay.app
        self.win = tk.Toplevel(overlay.root)
        self.win.title("mic-monitor — история")
        self.win.configure(bg=BG)
        self.win.geometry("760x420")
        self.win.attributes("-topmost", bool(overlay.cfg.get("topmost", True)))

        style = ttk.Style(self.win)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#1b202b", foreground=DIM, padding=(10, 5))
        style.map("TNotebook.Tab", background=[("selected", "#2a3242")],
                  foreground=[("selected", FG)])
        style.configure("Treeview", background="#161a22", fieldbackground="#161a22",
                        foreground=FG, rowheight=22, borderwidth=0)
        style.configure("Treeview.Heading", background="#1b202b", foreground=DIM,
                        relief="flat")
        style.map("Treeview", background=[("selected", "#33405c")])

        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.nb = nb

        changes_tab = tk.Frame(nb, bg="#161a22")
        programs_tab = tk.Frame(nb, bg="#161a22")
        nb.add(changes_tab, text="Изменения")
        nb.add(programs_tab, text="Программы")

        self.tree = ttk.Treeview(
            changes_tab, columns=("time", "kind", "was", "now", "who"),
            show="headings", selectmode="browse",
        )
        for col, title, width in (
            ("time", "Время", 130), ("kind", "Событие", 90),
            ("was", "Было", 70), ("now", "Стало", 70), ("who", "Кандидаты", 340),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="w", stretch=(col == "who"))
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(changes_tab, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        self.prog_tree = ttk.Treeview(
            programs_tab, columns=("name", "count", "last", "values"),
            show="headings", selectmode="browse",
        )
        for col, title, width in (
            ("name", "Программа", 200), ("count", "Совпадений", 90),
            ("last", "Последний раз", 130), ("values", "Меняла", 300),
        ):
            self.prog_tree.heading(col, text=title)
            self.prog_tree.column(col, width=width, anchor="w", stretch=(col == "values"))
        self.prog_tree.pack(side="left", fill="both", expand=True)
        scroll2 = ttk.Scrollbar(programs_tab, orient="vertical", command=self.prog_tree.yview)
        scroll2.pack(side="right", fill="y")
        self.prog_tree.configure(yscrollcommand=scroll2.set)

        bottom = tk.Frame(self.win, bg=BG)
        bottom.pack(fill="x", padx=8, pady=(0, 8))
        self.status = tk.Label(bottom, text="", bg=BG, fg=DIM, font=FONT_SMALL, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        tk.Button(bottom, text="CSV", command=self._export, bg="#1b202b", fg=FG,
                  relief="flat", font=FONT_SMALL, padx=10, cursor="hand2").pack(side="right")
        tk.Button(bottom, text="Закрыть", command=self.win.destroy, bg="#1b202b", fg=FG,
                  relief="flat", font=FONT_SMALL, padx=10, cursor="hand2").pack(side="right", padx=6)

        self.win.protocol("WM_DELETE_WINDOW", self.win.destroy)
        self.refresh()

    def alive(self) -> bool:
        try:
            return bool(self.win.winfo_exists())
        except Exception:
            return False

    def focus(self) -> None:
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def refresh(self) -> None:
        if not self.alive():
            return
        self.tree.delete(*self.tree.get_children())
        for rec in reversed(self.app.history.records[-300:]):
            kind = {"volume": "громкость", "mute": "mute", "device": "устройство",
                    "session_start": "открыл микрофон", "session_stop": "закрыл микрофон"}.get(
                        rec.get("kind"), rec.get("kind", ""))
            was = rec.get("old")
            now = rec.get("new")
            suspect = rec.get("suspect")
            if suspect:
                others = [c["name"] for c in rec.get("candidates", [])
                          if c.get("pid") != suspect["pid"]]
                who = f"{suspect['name']} · {suspect['confidence']}"
                if others:
                    who += " + " + ", ".join(others)
            else:
                who = "—"
            kind_raw = rec.get("kind", "")
            self.tree.insert("", 0, values=(
                rec.get("time", ""), kind,
                fmt_value(kind_raw, was),
                fmt_value(kind_raw, now),
                who,
            ))

        self.prog_tree.delete(*self.prog_tree.get_children())
        for name, count, last, values in self.app.history.programs():
            self.prog_tree.insert("", "end", values=(name, count, last, values or "—"))

        self.status.configure(text=f"записей: {len(self.app.history.records)} · "
                                   f"файл: {self.app.history.path}")

    def _export(self) -> None:
        try:
            path = self.app.history.export_csv()
            self.status.configure(text=f"CSV: {path}", fg=OK)
        except OSError as exc:
            self.status.configure(text=f"не удалось сохранить: {exc}", fg=BAD)


# ----------------------------------------------------------------------------
# Приложение
# ----------------------------------------------------------------------------

class App:
    def __init__(self) -> None:
        self.config = self._load_config()
        self.history = History()
        self.logger = Logger()
        self.events: queue.Queue = queue.Queue()
        self.current: dict[str, Any] | None = None
        self.devices: list[tuple[str, str]] = []
        self.device_id: str | None = self.config.get("device_id")
        self.watcher: Watcher | None = None
        self.overlay: Overlay | None = None

    # ------------------------------------------------------------------
    @staticmethod
    def _load_config() -> dict[str, Any]:
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_config(self) -> None:
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self.config, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        except OSError:
            pass

    def select_device(self, device_id: str | None) -> None:
        self.device_id = device_id
        self.config["device_id"] = device_id
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        self.start_watcher()

    def start_watcher(self) -> None:
        if self.watcher is not None:
            return
        self.watcher = Watcher(self.events, self.history, self.device_id, self.logger)
        self.watcher.start()

    def shutdown(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()

    def run(self) -> None:
        self.start_watcher()
        self.overlay = Overlay(self)
        try:
            self.overlay.root.mainloop()
        finally:
            self.shutdown()


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def acquire_single_instance() -> bool:
    """Не даём запустить две копии: иначе дублируются окно, лог и звук."""
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\MicMonitor-SingleInstance")
        if not handle:
            return True
        return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True


def cli_probe() -> int:
    try:
        import comtypes
        comtypes.CoInitialize()
    except Exception:
        pass
    backend = AudioBackend()
    default_id = backend.default_id()
    print("устройства записи:")
    for dev_id, name in backend.capture_devices():
        mark = "*" if dev_id == default_id else " "
        print(f" {mark} {name}\n     {dev_id}")
    handle = backend.open(default_id)
    if handle is None:
        print("нет доступного устройства записи")
        return 1
    print(f"\nтекущее: {handle.name}")
    print(f"  громкость: {fmt_volume(handle.volume())}  mute={handle.muted()}")
    peaks = []
    for _ in range(10):
        peaks.append(handle.peak())
        time.sleep(0.05)
    print(f"  пик сигнала: {fmt_volume(max(peaks))}")
    sessions = handle.sessions()
    print(f"  аудио-сессий: {len(sessions)}")
    for s in sessions:
        print(f"    pid {s.pid:>6}  {s.name:<24} {'активна' if s.active else 'inactive'}")
    fg = foreground_process()
    print(f"  активное окно: {fg.name if fg else '—'}")
    return 0


def cli_watch(seconds: float) -> int:
    history = History()
    logger = Logger()
    events: queue.Queue = queue.Queue()
    watcher = Watcher(events, history, logger=logger)
    watcher.start()
    deadline = time.time() + seconds
    seen = 0
    try:
        while time.time() < deadline:
            try:
                event = events.get(timeout=0.3)
            except queue.Empty:
                continue
            if event["type"] == "state":
                print(f"\rгромкость {fmt_volume(event['volume'])}  "
                      f"сигнал {fmt_volume(event['peak'])}  ", end="")
            elif event["type"] == "change":
                seen += 1
                print()
                logger.change(event["change"], echo=True)
            elif event["type"] in ("error", "warning"):
                print(f"\n{event['type']}: {event['text']}")
    finally:
        watcher.stop()
    print(f"\nизменений записано: {seen}\nлог: {Logger().path}\nистория: {history.path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Оверлей с громкостью микрофона и историей изменений")
    parser.add_argument("--probe", action="store_true", help="показать устройства и текущие значения")
    parser.add_argument("--watch", type=float, metavar="SEC", help="лог изменений в консоль без окна")
    parser.add_argument("--device", metavar="ID", help="id устройства записи (см. --probe)")
    parser.add_argument("--version", action="version", version=f"mic-monitor {__version__}")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if args.probe:
        return cli_probe()
    if args.watch:
        return cli_watch(args.watch)

    if not acquire_single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                None, "mic-monitor уже запущен — смотрите оверлей в углу экрана.",
                "mic-monitor", 0x40,
            )
        except Exception:
            print("mic-monitor уже запущен")
        return 0

    app = App()
    if args.device:
        app.device_id = args.device
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
