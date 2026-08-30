from django.urls import path

from . import views


urlpatterns = [
    path('', views.home, name='home'),
    path('healthz/', views.healthz, name='healthz'),
    path('devices/', views.devices, name='devices'),
    path('files/', views.files, name='files'),
    path('api/agent/sync/', views.agent_sync, name='agent_sync'),
]
