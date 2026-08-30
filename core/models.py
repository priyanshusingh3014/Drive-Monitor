from django.db import models
from django.utils import timezone


class EndpointDevice(models.Model):
    device_id = models.CharField(max_length=64, unique=True)
    hostname = models.CharField(max_length=255)
    username = models.CharField(max_length=255, blank=True)
    platform = models.CharField(max_length=255, blank=True)
    drives = models.JSONField(default=list, blank=True)
    total_files = models.PositiveIntegerField(default=0)
    total_size_bytes = models.BigIntegerField(default=0)
    c_drive_total_bytes = models.BigIntegerField(default=0)
    c_drive_used_bytes = models.BigIntegerField(default=0)
    secondary_total_bytes = models.BigIntegerField(default=0)
    secondary_used_bytes = models.BigIntegerField(default=0)
    storage_status = models.CharField(max_length=32, default='Optimal')
    last_seen = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['hostname']

    def __str__(self):
        return self.hostname


class ArchivedFile(models.Model):
    device = models.ForeignKey(EndpointDevice, related_name='files', on_delete=models.CASCADE)
    drive = models.CharField(max_length=8)
    path = models.TextField()
    name = models.CharField(max_length=512)
    extension = models.CharField(max_length=64, blank=True)
    size_bytes = models.BigIntegerField(default=0)
    content = models.BinaryField(null=True, blank=True)
    content_type = models.CharField(max_length=255, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    content_size_bytes = models.BigIntegerField(default=0)
    content_uploaded_at = models.DateTimeField(null=True, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    discovered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['drive', 'path']
        constraints = [
            models.UniqueConstraint(fields=['device', 'path'], name='unique_archived_file_per_device'),
        ]
        indexes = [
            models.Index(fields=['drive']),
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return self.path

    @property
    def has_download(self):
        return self.content_uploaded_at is not None
