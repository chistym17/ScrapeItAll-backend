from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
from .utils import fetch_sitemap, fetch_sitemap_with_custom_location, get_page_content_size
from .models import SitemapURL


@csrf_exempt
@require_http_methods(["POST"])
async def fetch_sitemap_urls(request):
    try:
        data = json.loads(request.body)
        domain = data.get('domain')
        custom_location = data.get('custom_location')

        if custom_location:
            urls = await fetch_sitemap_with_custom_location(custom_location)
        else:
            urls = await fetch_sitemap(domain)

        for url_data in urls:
            SitemapURL.objects.create(
                url=url_data['url'],
                size=url_data['size'],
                selected=url_data['selected'],
                processed=url_data['processed']
            )

        return JsonResponse({
            'status': 'success',
            'urls': urls
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
async def get_page_size(request):
    try:
        data = json.loads(request.body)
        url = data.get('url')
        
        if not url:
            return JsonResponse({
                'status': 'error',
                'message': 'URL is required'
            }, status=400)

        size = await get_page_content_size(url)
        
        return JsonResponse({
            'status': 'success',
            'size': size
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
