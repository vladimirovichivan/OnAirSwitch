#!/usr/bin/env python3
"""Тесты проверки обновлений: версии, контрольные суммы, выбор файлов.

Запуск:  .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'app' / 'scripts' / 'meetings'))

import updater  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_parse_version(self):
        self.assertEqual(updater.parse_version('v1.2.3'), (1, 2, 3))
        self.assertEqual(updater.parse_version('1.1.0-beta'), (1, 1, 0))
        self.assertEqual(updater.parse_version(''), (0,))
        self.assertEqual(updater.parse_version('dev'), (0,))

    def test_is_newer(self):
        self.assertTrue(updater.is_newer('1.1.0', '1.0.2'))
        self.assertTrue(updater.is_newer('1.1.1', '1.1'))
        self.assertFalse(updater.is_newer('1.1.0', '1.1.0'))
        self.assertFalse(updater.is_newer('1.0.9', '1.1.0'))
        self.assertFalse(updater.is_newer('1.1', '1.1.0'))


class ChecksumTests(unittest.TestCase):
    def test_parse_checksums(self):
        digest = 'a' * 64
        text = f'{digest}  OnAirLamp-Setup-1.1.0.exe\r\n' \
               f'{digest.upper()} *other.zip\r\n' \
               'bad line\r\n# comment\r\n'
        sums = updater.parse_checksums(text)
        self.assertEqual(sums['OnAirLamp-Setup-1.1.0.exe'], digest)
        self.assertEqual(sums['other.zip'], digest)
        self.assertEqual(len(sums), 2)

    def test_verify_checksum(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'file.bin'
            path.write_bytes(b'onair-lamp')
            expected = hashlib.sha256(b'onair-lamp').hexdigest()
            updater.verify_checksum(path, expected)
            with self.assertRaises(updater.UpdateError):
                updater.verify_checksum(path, '0' * 64)


class AssetTests(unittest.TestCase):
    def test_pick_assets_ignores_other_files(self):
        release = {'assets': [
            {'name': 'README.txt', 'browser_download_url': 'https://x/readme'},
            {'name': 'OnAirLamp-Setup-1.1.0.exe',
             'browser_download_url': 'https://x/setup.exe'},
            {'name': 'SHA256SUMS.txt',
             'browser_download_url': 'https://x/sums'},
            {'name': 'OnAirLamp-1.1.0-win64.zip',
             'browser_download_url': 'https://x/zip'},
        ]}
        installer, sums = updater.pick_assets(release)
        self.assertEqual(installer['name'], 'OnAirLamp-Setup-1.1.0.exe')
        self.assertEqual(sums['name'], 'SHA256SUMS.txt')

    def test_pick_assets_missing(self):
        self.assertEqual(updater.pick_assets({'assets': []}), (None, None))


class CheckTests(unittest.TestCase):
    def release(self, version='1.2.0'):
        return {
            'tag_name': f'v{version}',
            'body': 'changes',
            'html_url': 'https://example/release',
            'assets': [
                {'name': f'OnAirLamp-Setup-{version}.exe',
                 'browser_download_url': 'https://example/setup.exe'},
                {'name': 'SHA256SUMS.txt',
                 'browser_download_url': 'https://example/sums.txt'},
            ],
        }

    def test_new_release_is_available(self):
        with mock.patch.object(updater, 'fetch_release',
                               return_value=self.release()):
            check = updater.check_for_update(current='1.1.0')
        self.assertTrue(check.available)
        self.assertEqual(check.version, '1.2.0')
        self.assertEqual(check.installer_name, 'OnAirLamp-Setup-1.2.0.exe')
        self.assertEqual(check.error, '')

    def test_same_or_older_release_is_not_available(self):
        with mock.patch.object(updater, 'fetch_release',
                               return_value=self.release('1.1.0')):
            check = updater.check_for_update(current='1.1.0')
        self.assertFalse(check.available)

    def test_missing_installer_is_an_error(self):
        release = self.release()
        release['assets'] = release['assets'][1:]
        with mock.patch.object(updater, 'fetch_release', return_value=release):
            check = updater.check_for_update(current='1.1.0')
        self.assertFalse(check.available)
        self.assertIn('installer', check.error)

    def test_network_error_is_returned_without_raising(self):
        with mock.patch.object(updater, 'fetch_release',
                               side_effect=updater.UpdateError('HTTP 404')):
            check = updater.check_for_update(current='1.1.0')
        self.assertFalse(check.available)
        self.assertEqual(check.error, 'HTTP 404')

    def test_current_version_from_build_file(self):
        with tempfile.TemporaryDirectory() as temp:
            build = Path(temp) / 'build.json'
            build.write_text('{"version": "1.1.0"}', encoding='utf-8')
            self.assertEqual(updater.current_version(build), '1.1.0')
            build.write_text('not json', encoding='utf-8')
            self.assertEqual(updater.current_version(build), '0.0.0')


class DownloadTests(unittest.TestCase):
    def make_check(self):
        return updater.UpdateCheck(
            current='1.1.0', available=True, version='1.2.0',
            installer_url='https://example/setup.exe',
            installer_name='OnAirLamp-Setup-1.2.0.exe',
            sums_url='https://example/sums.txt')

    def test_download_update_checks_sha256(self):
        payload = b'installer-bytes'
        digest = hashlib.sha256(payload).hexdigest()
        sums_text = f'{digest}  OnAirLamp-Setup-1.2.0.exe\n'

        def fake_download(url, destination, timeout=0):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload if 'setup' in url
                                    else sums_text.encode())
            return destination

        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(updater, 'download', side_effect=fake_download):
            path = updater.download_update(self.make_check(), Path(temp))
            self.assertEqual(path.read_bytes(), payload)

    def test_download_update_rejects_bad_checksum(self):
        sums_text = f'{"0" * 64}  OnAirLamp-Setup-1.2.0.exe\n'

        def fake_download(url, destination, timeout=0):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b'installer' if 'setup' in url
                                    else sums_text.encode())
            return destination

        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(updater, 'download', side_effect=fake_download):
            with self.assertRaises(updater.UpdateError):
                updater.download_update(self.make_check(), Path(temp))


class HelperTests(unittest.TestCase):
    def test_helper_waits_installs_and_restarts(self):
        text = updater.build_helper(Path(r'C:\Temp\setup.exe'),
                                    Path(r'C:\Apps\OnAirLamp'), 'autostart')
        self.assertIn(r'C:\Temp\setup.exe', text)
        self.assertIn(r'C:\Apps\OnAirLamp\start.vbs', text)
        self.assertIn('/SILENT', text)
        self.assertIn('/MERGETASKS=autostart', text)
        self.assertIn('sh.Run', text)

    def test_helper_disables_tasks_when_none_selected(self):
        text = updater.build_helper(Path(r'C:\Temp\setup.exe'),
                                    Path(r'C:\Apps\OnAirLamp'), '')
        self.assertIn('/MERGETASKS=!autostart,!desktopicon', text)


if __name__ == '__main__':
    unittest.main()
