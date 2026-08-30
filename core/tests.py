import json

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ArchivedFile, EndpointDevice


class HomePageTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Telemetry &amp; Overview')
        self.assertContains(response, 'No Devices Enrolled')
        self.assertContains(response, 'No devices enrolled yet.')
        self.assertContains(response, '0 GB / 0 GB')

    def test_devices_page_loads(self):
        response = self.client.get(reverse('devices'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Registered Endpoint Devices')
        self.assertContains(response, 'No devices enrolled yet.')

    def test_files_page_loads(self):
        response = self.client.get(reverse('files'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Drive Files &amp; Database Backups')
        self.assertContains(response, 'Archived Drive Files')
        self.assertContains(response, 'No secondary drive files found yet.')

    def test_storage_page_loads(self):
        response = self.client.get(reverse('storage'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Storage Vaults &amp; Locations')
        self.assertContains(response, 'No storage information yet.')

    def test_health_check_loads(self):
        response = self.client.get(reverse('healthz'))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {'ok': True})


class AgentSyncTests(TestCase):
    def test_agent_sync_registers_device_and_files(self):
        payload = {
            'device_id': 'test-device-1',
            'hostname': 'LAPTOP-TEST',
            'username': 'tester',
            'platform': 'Windows',
            'drives': ['D:'],
            'storage': {
                'c_drive': {
                    'drive': 'C:',
                    'total_bytes': 271656009728,
                    'used_bytes': 220117073920,
                    'free_bytes': 51538935808,
                },
                'secondary_drives': [
                    {
                        'drive': 'D:',
                        'total_bytes': 239444754432,
                        'used_bytes': 75082653696,
                        'free_bytes': 164362100736,
                    }
                ],
            },
            'files': [
                {
                    'drive': 'D:',
                    'path': 'D:\\Projects\\report.pdf',
                    'name': 'report.pdf',
                    'extension': '.pdf',
                    'size_bytes': 2048,
                    'modified_at': '2026-08-30T12:00:00+00:00',
                }
            ],
        }

        response = self.client.post(
            reverse('agent_sync'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(EndpointDevice.objects.count(), 1)
        self.assertEqual(ArchivedFile.objects.count(), 1)

        device = EndpointDevice.objects.get()
        self.assertEqual(device.c_drive_total_bytes, 271656009728)
        self.assertEqual(device.secondary_total_bytes, 239444754432)

        files_response = self.client.get(reverse('files'))
        self.assertContains(files_response, 'report.pdf')
        self.assertContains(files_response, 'LAPTOP-TEST')

        storage_response = self.client.get(reverse('storage'))
        self.assertContains(storage_response, 'LAPTOP-TEST')
        self.assertContains(storage_response, '205 GB / 253 GB')
        self.assertContains(storage_response, '69.9 GB / 223 GB')

        home_response = self.client.get(reverse('home'))
        self.assertContains(home_response, '1 Agent')
        self.assertContains(home_response, 'LAPTOP-TEST (tester)')
        self.assertContains(home_response, '274.9 GB / 476 GB')
        self.assertContains(home_response, 'Monitored Device Files')
        self.assertContains(home_response, 'report.pdf')
        self.assertContains(home_response, 'D:\\Projects\\report.pdf')

        heartbeat = payload | {
            'files': [],
            'replace_files': False,
        }

        heartbeat_response = self.client.post(
            reverse('agent_sync'),
            data=json.dumps(heartbeat),
            content_type='application/json',
        )

        self.assertEqual(heartbeat_response.status_code, 200)
        device.refresh_from_db()
        self.assertEqual(device.total_files, 1)
        self.assertEqual(ArchivedFile.objects.count(), 1)

    def test_dashboard_loads_files_for_selected_device(self):
        first_device = EndpointDevice.objects.create(
            device_id='first-device',
            hostname='FIRST-PC',
            username='one',
        )
        second_device = EndpointDevice.objects.create(
            device_id='second-device',
            hostname='SECOND-PC',
            username='two',
        )
        ArchivedFile.objects.create(
            device=first_device,
            drive='E:',
            path='E:\\first.txt',
            name='first.txt',
            size_bytes=1024,
        )
        ArchivedFile.objects.create(
            device=second_device,
            drive='F:',
            path='F:\\second.txt',
            name='second.txt',
            size_bytes=2048,
        )

        default_response = self.client.get(reverse('home'))
        self.assertContains(default_response, 'FIRST-PC (one)')
        self.assertContains(default_response, 'SECOND-PC (two)')
        self.assertContains(default_response, 'first.txt')
        self.assertNotContains(default_response, 'second.txt')

        selected_response = self.client.get(f"{reverse('home')}?device=second-device")
        self.assertContains(selected_response, 'SECOND-PC (two)')
        self.assertContains(selected_response, 'second.txt')
        self.assertContains(selected_response, 'F:\\second.txt')
        self.assertNotContains(selected_response, 'first.txt')

    def test_agent_sync_handles_bad_byte_values(self):
        payload = {
            'device_id': 'test-device-2',
            'hostname': 'LAPTOP-BAD-DATA',
            'username': 'tester',
            'platform': 'Windows',
            'drives': ['E:'],
            'storage': {
                'c_drive': {
                    'drive': 'C:',
                    'total_bytes': 'not-a-number',
                    'used_bytes': -100,
                },
                'secondary_drives': [
                    {
                        'drive': 'E:',
                        'total_bytes': '2048',
                        'used_bytes': '1024',
                    }
                ],
            },
            'files': [
                {
                    'drive': 'E:',
                    'path': 'E:\\bad-size.txt',
                    'size_bytes': 'not-a-number',
                }
            ],
        }

        response = self.client.post(
            reverse('agent_sync'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)

        device = EndpointDevice.objects.get(device_id='test-device-2')
        self.assertEqual(device.c_drive_total_bytes, 0)
        self.assertEqual(device.c_drive_used_bytes, 0)
        self.assertEqual(device.secondary_total_bytes, 2048)
        self.assertEqual(device.secondary_used_bytes, 1024)
        self.assertEqual(device.total_size_bytes, 0)

    @override_settings(AGENT_API_TOKEN='secret-token')
    def test_agent_sync_rejects_missing_token(self):
        payload = {
            'device_id': 'blocked-agent-1',
            'hostname': 'BLOCKED-LAPTOP',
            'files': [],
        }

        response = self.client.post(
            reverse('agent_sync'),
            data=json.dumps(payload),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 401)
