#!/usr/bin/env python3
"""Тесты чистых функций трея и модуля намерения (без устройства и окон).

Запуск:  .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app' / 'scripts' / 'meetings'))

import plug_control as pc  # noqa: E402
import tray_plug as tray  # noqa: E402

NOW = datetime(2026, 11, 20, 12, 0, 0)
STAMP = '%Y-%m-%d %H:%M:%S'


class HumanDurationTests(unittest.TestCase):
    def test_less_than_minute(self):
        self.assertEqual(tray.human_duration(0), 'меньше минуты')
        self.assertEqual(tray.human_duration(59.9), 'меньше минуты')

    def test_minutes_and_hours(self):
        self.assertEqual(tray.human_duration(60), '1 мин')
        self.assertEqual(tray.human_duration(2520), '42 мин')
        self.assertEqual(tray.human_duration(3660), '1 ч 01 мин')
        self.assertEqual(tray.human_duration(7200), '2 ч')

    def test_negative_is_clamped(self):
        self.assertEqual(tray.human_duration(-5), 'меньше минуты')


class RemainingSuffixTests(unittest.TestCase):
    def test_remaining(self):
        until = NOW + timedelta(minutes=37)
        self.assertEqual(tray.remaining_suffix(until, NOW), ' · осталось 37 мин')

    def test_expired_and_absent(self):
        self.assertEqual(tray.remaining_suffix(NOW - timedelta(seconds=1), NOW), '')
        self.assertEqual(tray.remaining_suffix(None, NOW), '')


class MeetingSummaryTests(unittest.TestCase):
    def test_two_meetings_use_earliest_start(self):
        state = {'apps': {
            'talk': {'app': 'Talk', 'state': 'meeting',
                     'since': '2026-11-20 11:18:00'},
            'zoom': {'app': 'Zoom', 'state': 'meeting',
                     'since': '2026-11-20 11:30:00'},
            'telemost': {'app': 'Telemost', 'state': 'none', 'since': None},
        }}
        names, seconds = tray.meeting_summary(state, NOW)
        self.assertEqual(names, ['Talk', 'Zoom'])
        self.assertEqual(seconds, 2520)

    def test_no_meeting_and_broken_shapes(self):
        self.assertEqual(tray.meeting_summary(None, NOW), ([], None))
        self.assertEqual(tray.meeting_summary({'apps': []}, NOW), ([], None))
        state = {'apps': {'talk': {'state': 'none'}, 'bad': 'oops'}}
        self.assertEqual(tray.meeting_summary(state, NOW), ([], None))

    def test_missing_since_gives_names_without_duration(self):
        state = {'apps': {'talk': {'app': 'Talk', 'state': 'meeting'}}}
        names, seconds = tray.meeting_summary(state, NOW)
        self.assertEqual(names, ['Talk'])
        self.assertIsNone(seconds)


class MeetingsAgeTests(unittest.TestCase):
    def test_age_and_stale_shapes(self):
        state = {'updated': (NOW - timedelta(seconds=12)).strftime(STAMP)}
        self.assertAlmostEqual(tray.meetings_age(state, NOW), 12.0)
        self.assertIsNone(tray.meetings_age(None, NOW))
        self.assertIsNone(tray.meetings_age({'updated': 'bad'}, NOW))


class ControlTests(unittest.TestCase):
    def test_describe_manual_with_deadline(self):
        self.assertEqual(pc.describe(pc.MODE_OFF, NOW + timedelta(minutes=30)),
                         'выключена вручную до 12:30')
        self.assertEqual(pc.describe(pc.MODE_PAUSED, None),
                         'автоматика снята, до ручного возврата')

    def test_expired_until_resolves_to_auto(self):
        control = {'mode': pc.MODE_ON, 'until': (NOW - timedelta(seconds=1)).strftime(STAMP)}
        mode, until, expired = pc.resolve(control, NOW)
        self.assertEqual(mode, pc.MODE_AUTO)
        self.assertIsNone(until)
        self.assertTrue(expired)


if __name__ == '__main__':
    unittest.main()
