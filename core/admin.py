from django.contrib import admin

from .models import ArchivedFile, EndpointDevice


@admin.register(EndpointDevice)
class EndpointDeviceAdmin(admin.ModelAdmin):
    list_display = ('hostname', 'device_id', 'ip_address', 'mac_address', 'username', 'total_files', 'last_seen')
    search_fields = ('hostname', 'username', 'device_id', 'ip_address', 'mac_address')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ArchivedFile)
class ArchivedFileAdmin(admin.ModelAdmin):
    list_display = ('name', 'drive', 'device', 'size_bytes', 'modified_at')
    list_filter = ('drive', 'device')
    search_fields = ('name', 'path')
    readonly_fields = ('discovered_at', 'updated_at')
