from django.urls import path
from . import views


urlpatterns = [
    path('fetch-sitemap/', views.fetch_sitemap_urls, name='fetch_sitemap'),
    path('get-page-size/', views.get_page_size, name='get_page_size'),
    path('fetch-content/', views.fetch_page_content, name='fetch_content'),
] 