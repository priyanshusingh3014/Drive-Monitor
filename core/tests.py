import json

from django.test import TestCase
from django.urls import reverse

from .models import ArchivedFile, EndpointDevice


class HomePageTests(TestCase):
    def test_home_page_loads(self):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'System Telemetry &amp; Overview')

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

        files_response = self.client.get(reverse('files'))
        self.assertContains(files_response, 'report.pdf')
        self.assertContains(files_response, 'LAPTOP-TEST')
