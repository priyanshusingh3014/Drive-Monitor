from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('healthz/', views.healthz, name='healthz'),
    path('devices/', views.devices, name='devices'),
    path('storage/', views.storage, name='storage'),
    path('files/', views.files, name='files'),
    path('files/<int:file_id>/', views.file_detail, name='file_detail'),
    path('files/<int:file_id>/download/', views.download_file, name='download_file'),
    path('api/agent/sync/', views.agent_sync, name='agent_sync'),
]
