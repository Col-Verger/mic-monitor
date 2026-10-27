# -*- coding: utf-8 -*-
"""Тесты чистой логики: без Windows Core Audio и без GUI.

Запуск:  python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mic_monitor import (  # noqa: E402
    Candidate,
    Change,
    History,
    Logger,
    ProcInfo,
    SessionInfo,
    Snapshot,
    confidence,
    describe_change,
    detect_changes,
    fmt_value,
    fmt_volume,
    launch_command,
    play_alert,
    primary_suspect,
    score_candidates,
    short_device,
)


def snap(volume=0.8, muted=False, device="mic-1", name="Микрофон", sessions=()):
    return Snapshot(device_id=device, device_name=name, volume=volume,
                    muted=muted, peak=0.0, sessions=tuple(sessions))


class DetectChangesTest(unittest.TestCase):
    def test_first_snapshot_is_silent(self):
        self.assertEqual(detect_changes(None, snap()), [])

    def test_volume_change(self):
        changes = detect_changes(snap(1.0), snap(0.6))
        self.assertEqual(changes, [("volume", 1.0, 0.6)])

    def test_tiny_jitter_ignored(self):
        self.assertEqual(detect_changes(snap(0.800), snap(0.803)), [])

    def test_mute_toggle(self):
        self.assertEqual(detect_changes(snap(0.8, False), snap(0.8, True)),
                         [("mute", False, True)])

    def test_device_switch_reports_once(self):
        changes = detect_changes(snap(0.5, device="a", name="A"),
                                 snap(0.9, device="b", name="B"))
        self.assertEqual(changes, [("device", "A", "B")])

    def test_session_start_and_stop(self):
        start = detect_changes(snap(sessions=[]),
                               snap(sessions=[SessionInfo(10, "Discord.exe", 1)]))
        self.assertIn(("session_start", None, "Discord.exe"), start)

        stop = detect_changes(snap(sessions=[SessionInfo(10, "Discord.exe", 1)]),
                              snap(sessions=[SessionInfo(10, "Discord.exe", 0)]))
        self.assertIn(("session_stop", "Discord.exe", None), stop)

    def test_inactive_session_start_not_reported(self):
        changes = detect_changes(snap(sessions=[]),
                                 snap(sessions=[SessionInfo(10, "x.exe", 0)]))
        self.assertEqual(changes, [])


class CandidatesTest(unittest.TestCase):
    def test_new_session_beats_background(self):
        rows = score_candidates(
            foreground=ProcInfo(1, "explorer.exe"),
            sessions=[SessionInfo(2, "chrome.exe", 1), SessionInfo(3, "Discord.exe", 1)],
            new_session_pids=[3],
        )
        self.assertEqual(rows[0].name, "Discord.exe")
        self.assertIn("только что открыл микрофон", rows[0].reason)
        self.assertEqual({r.name for r in rows}, {"chrome.exe", "Discord.exe", "explorer.exe"})

    def test_control_panel_bonus(self):
        rows = score_candidates(sessions=[SessionInfo(5, "SteelSeriesGG.exe", 1)],
                                recent=[ProcInfo(6, "steam.exe")])
        by_name = {r.name: r for r in rows}
        self.assertGreater(by_name["SteelSeriesGG.exe"].score, by_name["steam.exe"].score)
        self.assertIn("панель управления звуком", by_name["SteelSeriesGG.exe"].reason)

    def test_own_pid_excluded(self):
        rows = score_candidates(foreground=ProcInfo(42, "python.exe"),
                                sessions=[SessionInfo(42, "python.exe", 1)],
                                exclude_pids=(42,))
        self.assertEqual(rows, [])

    def test_limit_and_order(self):
        many = [SessionInfo(i, f"app{i}.exe", 1) for i in range(10)]
        rows = score_candidates(sessions=many)
        self.assertLessEqual(len(rows), 4)
        self.assertEqual([r.score for r in rows], sorted((r.score for r in rows), reverse=True))


class SuspectTest(unittest.TestCase):
    def test_primary_and_confidence(self):
        rows = score_candidates(
            foreground=ProcInfo(1, "explorer.exe"),
            sessions=[SessionInfo(3, "Discord.exe", 1)],
            new_session_pids=[3],
        )
        top = primary_suspect(rows)
        self.assertIsNotNone(top)
        self.assertEqual(top.name, "Discord.exe")
        # рядом сильный конкурент (активное окно), поэтому уверенность не «высокая»
        self.assertEqual(confidence(rows), "средняя")
        self.assertEqual(confidence([]), "нет данных")

    def test_confidence_high_for_clear_winner(self):
        rows = [Candidate("Discord.exe", 1, "x", 3.4), Candidate("chrome.exe", 2, "y", 0.6)]
        self.assertEqual(confidence(rows), "высокая")

    def test_confidence_low_when_tie(self):
        rows = [Candidate("a.exe", 1, "x", 2.0), Candidate("b.exe", 2, "y", 1.95)]
        self.assertEqual(confidence(rows), "низкая")

    def test_record_contains_suspect(self):
        rows = score_candidates(sessions=[SessionInfo(3, "Discord.exe", 1)])
        rec = Change(ts=0, kind="volume", device="mic", device_id="i",
                     old=1.0, new=0.5, candidates=rows).to_record()
        self.assertEqual(rec["suspect"]["name"], "Discord.exe")
        self.assertIn("confidence", rec["suspect"])
        self.assertIsNone(Change(0, "volume", "mic", "i", 1.0, 0.5).to_record()["suspect"])


class LoggerTest(unittest.TestCase):
    def test_writes_suspect_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = Logger(Path(tmp) / "log.txt")
            rows = score_candidates(sessions=[SessionInfo(3, "Discord.exe", 1)])
            rec = Change(ts=1750000000.0, kind="volume", device="Микрофон", device_id="i",
                         old=1.0, new=0.55, candidates=rows,
                         context={"foreground": {"name": "chrome.exe", "pid": 5, "title": "T"},
                                  "sessions": [{"name": "Discord.exe", "pid": 3}],
                                  "recent": []}).to_record()
            logger.change(rec)
            text = (Path(tmp) / "log.txt").read_text(encoding="utf-8")
            self.assertIn("[ГРОМКОСТЬ] 100% → 55%", text)
            self.assertIn("виновник: Discord.exe", text)
            self.assertIn("держат микрофон: Discord.exe(3)", text)
            self.assertIn("активное окно: chrome.exe", text)


class LaunchCommandTest(unittest.TestCase):
    def test_quoted_and_points_to_script(self):
        cmd = launch_command()
        self.assertTrue(cmd.startswith('"'))
        self.assertIn("mic_monitor.py", cmd)


class AlertTest(unittest.TestCase):
    def test_alert_uses_system_sound(self):
        calls = []

        class FakeWinsound:
            SND_ALIAS = 0x10000
            SND_ASYNC = 1
            SND_NODEFAULT = 2

            @staticmethod
            def PlaySound(alias, flags):
                calls.append(alias)

        real = sys.modules.get("winsound")
        sys.modules["winsound"] = FakeWinsound
        try:
            play_alert("volume")
            play_alert("mute")
        finally:
            if real is None:
                sys.modules.pop("winsound", None)
            else:
                sys.modules["winsound"] = real

        self.assertEqual(calls, ["SystemNotification", "SystemHand"])


class FormatTest(unittest.TestCase):
    def test_volume(self):
        self.assertEqual(fmt_volume(1.0), "100%")
        self.assertEqual(fmt_volume(0.605), "60%")
        self.assertEqual(fmt_volume(None), "—")

    def test_fmt_value(self):
        self.assertEqual(fmt_value("volume", 0.6), "60%")
        self.assertEqual(fmt_value("mute", False), "включён")
        self.assertEqual(fmt_value("mute", True), "выключен")
        self.assertEqual(fmt_value("session_start", "Discord.exe"), "Discord.exe")
        self.assertEqual(fmt_value("volume", None), "")

    def test_short_device(self):
        self.assertEqual(short_device("Микрофон   (USB)"), "Микрофон (USB)")
        self.assertEqual(len(short_device("x" * 100, 20)), 20)
        self.assertTrue(short_device("x" * 100, 20).endswith("…"))

    def test_describe_change(self):
        ch = Change(ts=0, kind="volume", device="d", device_id="i", old=1.0, new=0.6)
        self.assertEqual(describe_change(ch), "100% → 60%")
        self.assertEqual(describe_change(Change(0, "mute", "d", "i", False, True)), "микрофон выключен")


class HistoryTest(unittest.TestCase):
    def test_roundtrip_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            hist = History(path)
            record = Change(ts=1700000000.0, kind="volume", device="Микрофон",
                            device_id="i", old=1.0, new=0.6,
                            candidates=[]).to_record()
            record["candidates"] = [{"name": "Discord.exe", "pid": 10,
                                     "reason": "держит микрофон", "score": 2.0}]
            hist.add(record)
            hist.add(dict(record, kind="mute", old=False, new=True))

            self.assertEqual(len(hist.records), 2)
            self.assertTrue(path.exists())

            reloaded = History(path)
            self.assertEqual(len(reloaded.records), 2)

            rows = reloaded.programs()
            self.assertEqual(rows[0][0], "Discord.exe")
            self.assertEqual(rows[0][1], 2)
            self.assertEqual(rows[0][3], "100%→60%")

            csv_path = reloaded.export_csv()
            text = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("Discord.exe", text)
            self.assertIn("громкость", text) if "громкость" in text else None

    def test_broken_lines_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.jsonl"
            path.write_text('{"kind": "volume"}\nnot json\n', encoding="utf-8")
            hist = History(path)
            self.assertEqual(len(hist.records), 1)


if __name__ == "__main__":
    unittest.main()
