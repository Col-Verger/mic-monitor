# -*- coding: utf-8 -*-
"""Локализация mic-monitor: плоские ключи, английский — база и fallback, русский — перевод.

Правила:
  * любой видимый пользователю текст берётся через :func:`t`;
  * ключи плоские (`ui.volume`, `log.suspect`), без вложенности;
  * в `en` и `ru` одинаковый набор ключей и одинаковые `{placeholders}`;
  * язык определяется по системе (русская Windows → ru), переключается в меню и хранится в конфиге.
"""

from __future__ import annotations

import ctypes

LANGUAGES = ("en", "ru")
_current = "en"


TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # --- причины, по которым процесс попал в подозреваемые ---
        "cand.just_opened_mic": "just opened the mic",
        "cand.holds_mic": "holds the mic",
        "cand.mic_idle": "mic is open in background",
        "cand.just_started": "just started",
        "cand.foreground": "active window",
        "cand.control_panel_suffix": "; audio control panel",
        # --- уверенность ---
        "conf.high": "high",
        "conf.medium": "medium",
        "conf.low": "low",
        "conf.none": "no data",
        # --- значения в таблицах ---
        "value.muted_yes": "muted",
        "value.muted_no": "unmuted",
        # --- строка изменения ---
        "change.device": "another device: {name}",
        "change.muted_on": "microphone muted",
        "change.muted_off": "microphone unmuted",
        "change.session_start": "{name} opened the mic",
        "change.session_stop": "{name} released the mic",
        # --- CSV ---
        "csv.time": "time",
        "csv.kind": "type",
        "csv.device": "device",
        "csv.old": "before",
        "csv.new": "after",
        "csv.programs": "programs",
        # --- заголовки событий в логе ---
        "kind.volume": "VOLUME",
        "kind.mute": "MUTE",
        "kind.device": "DEVICE",
        "kind.session_start": "MIC OPENED",
        "kind.session_stop": "MIC CLOSED",
        # --- лог ---
        "log.startup": "=== started ({source}) · device: {device}",
        "log.suspect": "    suspect: {name} (pid {pid}) — confidence {confidence}",
        "log.reason": "      reason: {reason}",
        "log.file": "      file: {exe}",
        "log.parent": "      parent: {parent}",
        "log.others": "    also suspected: {names}",
        "log.no_suspect": "    suspect: not determined",
        "log.foreground": "    active window: {name} (pid {pid}){title}",
        "log.holding": "    holding the mic: {names}",
        "log.recent": "    recent processes: {names}",
        "log.source_watcher": "watcher",
        # --- оверлей ---
        "ui.device_placeholder": "recording device",
        "ui.signal": "signal",
        "ui.signal_free": "signal · microphone is free",
        "ui.signal_listen": "signal · {names}",
        "ui.signal_more": " +{count}",
        "ui.no_changes": "no changes yet",
        "ui.muted_badge": "MUTED",
        "ui.suspect": "{name} · {reason} ({confidence})",
        "ui.no_suspect": "suspect not determined",
        "ui.window_title": "mic-monitor",
        # --- меню ---
        "menu.history": "Change history",
        "menu.compact": "Compact view",
        "menu.full": "Full view",
        "menu.topmost": "Always on top",
        "menu.sound": "Sound on change",
        "menu.autostart": "Start with Windows",
        "menu.open_log": "Open log",
        "menu.open_folder": "Open data folder",
        "menu.default_device": "Use default device",
        "menu.language": "Language",
        "menu.quit": "Quit",
        # --- окно истории ---
        "hist.title": "mic-monitor — history",
        "hist.tab_changes": "Changes",
        "hist.tab_programs": "Programs",
        "hist.col_time": "Time",
        "hist.col_kind": "Event",
        "hist.col_old": "Before",
        "hist.col_new": "After",
        "hist.col_who": "Suspects",
        "hist.col_program": "Program",
        "hist.col_count": "Matches",
        "hist.col_last": "Last time",
        "hist.col_values": "Changed to",
        "hist.close": "Close",
        "hist.records": "records: {count} · file: {path}",
        "hist.export_ok": "CSV: {path}",
        "hist.export_fail": "could not save: {error}",
        "hist.kind.volume": "volume",
        "hist.kind.mute": "mute",
        "hist.kind.device": "device",
        "hist.kind.session_start": "mic opened",
        "hist.kind.session_stop": "mic closed",
        # --- ошибки наблюдателя ---
        "watch.audio_unavailable": "Core Audio is unavailable: {error}",
        "watch.poll_failed": "polling failed: {error}",
        "watch.no_devices": "no recording devices available",
        # --- командная строка ---
        "cli.description": "Microphone volume overlay with a change history",
        "cli.probe_help": "list recording devices and current values",
        "cli.watch_help": "print changes to the console without a window",
        "cli.device_help": "recording device id (see --probe)",
        "cli.probe_devices": "recording devices:",
        "cli.no_device": "no recording device available",
        "cli.current": "current: {name}",
        "cli.volume": "  volume: {value}  mute={muted}",
        "cli.peak": "  signal peak: {value}",
        "cli.sessions": "  audio sessions: {count}",
        "cli.session_line": "    pid {pid:>6}  {name:<24} {state}",
        "cli.session_active": "active",
        "cli.session_inactive": "inactive",
        "cli.foreground": "  active window: {name}",
        "cli.watch_status": "\rvolume {volume}  signal {peak}  ",
        "cli.watch_done": "\nchanges logged: {count}\nlog: {path}\nhistory: {history}",
        # --- прочее ---
        "msg.already_running_title": "mic-monitor",
        "msg.already_running": "mic-monitor is already running — look for the overlay on your screen.",
        "msg.already_running_console": "mic-monitor is already running",
    },
    "ru": {
        "cand.just_opened_mic": "только что открыл микрофон",
        "cand.holds_mic": "держит микрофон",
        "cand.mic_idle": "микрофон открыт в фоне",
        "cand.just_started": "запущен только что",
        "cand.foreground": "активное окно",
        "cand.control_panel_suffix": "; панель управления звуком",
        "conf.high": "высокая",
        "conf.medium": "средняя",
        "conf.low": "низкая",
        "conf.none": "нет данных",
        "value.muted_yes": "выключен",
        "value.muted_no": "включён",
        "change.device": "другое устройство: {name}",
        "change.muted_on": "микрофон выключен",
        "change.muted_off": "микрофон включён",
        "change.session_start": "{name} открыл микрофон",
        "change.session_stop": "{name} отпустил микрофон",
        "csv.time": "время",
        "csv.kind": "тип",
        "csv.device": "устройство",
        "csv.old": "было",
        "csv.new": "стало",
        "csv.programs": "программы",
        "kind.volume": "ГРОМКОСТЬ",
        "kind.mute": "MUTE",
        "kind.device": "УСТРОЙСТВО",
        "kind.session_start": "ОТКРЫЛ МИКРОФОН",
        "kind.session_stop": "ЗАКРЫЛ МИКРОФОН",
        "log.startup": "=== запуск ({source}) · устройство: {device}",
        "log.suspect": "    виновник: {name} (pid {pid}) — уверенность {confidence}",
        "log.reason": "      причина: {reason}",
        "log.file": "      файл: {exe}",
        "log.parent": "      родитель: {parent}",
        "log.others": "    ещё под подозрением: {names}",
        "log.no_suspect": "    виновник: не определён",
        "log.foreground": "    активное окно: {name} (pid {pid}){title}",
        "log.holding": "    держат микрофон: {names}",
        "log.recent": "    свежие процессы: {names}",
        "log.source_watcher": "наблюдатель",
        "ui.device_placeholder": "устройство записи",
        "ui.signal": "сигнал",
        "ui.signal_free": "сигнал · микрофон свободен",
        "ui.signal_listen": "сигнал · {names}",
        "ui.signal_more": " +{count}",
        "ui.no_changes": "изменений пока не было",
        "ui.muted_badge": "ВЫКЛ",
        "ui.suspect": "{name} · {reason} ({confidence})",
        "ui.no_suspect": "виновник не определён",
        "ui.window_title": "mic-monitor",
        "menu.history": "История изменений",
        "menu.compact": "Компактный вид",
        "menu.full": "Полный вид",
        "menu.topmost": "Поверх всех окон",
        "menu.sound": "Звук при изменении",
        "menu.autostart": "Запускать с Windows",
        "menu.open_log": "Открыть лог",
        "menu.open_folder": "Открыть историю (папка)",
        "menu.default_device": "Сбросить на устройство по умолчанию",
        "menu.language": "Язык",
        "menu.quit": "Выход",
        "hist.title": "mic-monitor — история",
        "hist.tab_changes": "Изменения",
        "hist.tab_programs": "Программы",
        "hist.col_time": "Время",
        "hist.col_kind": "Событие",
        "hist.col_old": "Было",
        "hist.col_new": "Стало",
        "hist.col_who": "Кандидаты",
        "hist.col_program": "Программа",
        "hist.col_count": "Совпадений",
        "hist.col_last": "Последний раз",
        "hist.col_values": "Меняла",
        "hist.close": "Закрыть",
        "hist.records": "записей: {count} · файл: {path}",
        "hist.export_ok": "CSV: {path}",
        "hist.export_fail": "не удалось сохранить: {error}",
        "hist.kind.volume": "громкость",
        "hist.kind.mute": "mute",
        "hist.kind.device": "устройство",
        "hist.kind.session_start": "открыл микрофон",
        "hist.kind.session_stop": "закрыл микрофон",
        "watch.audio_unavailable": "Core Audio недоступен: {error}",
        "watch.poll_failed": "сбой опроса: {error}",
        "watch.no_devices": "нет доступных устройств записи",
        "cli.description": "Оверлей с громкостью микрофона и историей изменений",
        "cli.probe_help": "показать устройства и текущие значения",
        "cli.watch_help": "лог изменений в консоль без окна",
        "cli.device_help": "id устройства записи (см. --probe)",
        "cli.probe_devices": "устройства записи:",
        "cli.no_device": "нет доступного устройства записи",
        "cli.current": "текущее: {name}",
        "cli.volume": "  громкость: {value}  mute={muted}",
        "cli.peak": "  пик сигнала: {value}",
        "cli.sessions": "  аудио-сессий: {count}",
        "cli.session_line": "    pid {pid:>6}  {name:<24} {state}",
        "cli.session_active": "активна",
        "cli.session_inactive": "inactive",
        "cli.foreground": "  активное окно: {name}",
        "cli.watch_status": "\rгромкость {volume}  сигнал {peak}  ",
        "cli.watch_done": "\nизменений записано: {count}\nлог: {path}\nистория: {history}",
        "msg.already_running_title": "mic-monitor",
        "msg.already_running": "mic-monitor уже запущен — смотрите оверлей в углу экрана.",
        "msg.already_running_console": "mic-monitor уже запущен",
    },
}


def available_languages() -> tuple[str, ...]:
    return LANGUAGES


def current_language() -> str:
    return _current


def set_language(language: str) -> str:
    """Переключить язык. Неизвестный код игнорируется."""
    global _current
    if language and language.lower()[:2] in LANGUAGES:
        _current = language.lower()[:2]
    return _current


def detect_language() -> str:
    """Язык системы: русская Windows → ru, всё остальное → en."""
    try:
        langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (langid & 0x3FF) == 0x19:  # LANG_RUSSIAN
            return "ru"
        if langid:
            return "en"
    except Exception:
        pass
    try:
        import locale
        name = (locale.getlocale()[0] or "").lower()
        if name.startswith("ru"):
            return "ru"
    except Exception:
        pass
    return "en"


def t(key: str, **kwargs: object) -> str:
    """Перевод по ключу с fallback на английский и на сам ключ."""
    text = TRANSLATIONS.get(_current, {}).get(key) or TRANSLATIONS["en"].get(key) or key
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError):
        return text


def variants(key: str) -> set[str]:
    """Все варианты строки на всех языках — чтобы узнавать значения из старых записей."""
    return {table[key] for table in TRANSLATIONS.values() if key in table}
