import re
import random
from typing import Optional
from urllib.parse import urljoin, urlparse, unquote
import xml.etree.ElementTree as ET
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

XML_STYLESHEET_PATTERN = re.compile(r'<\?xml-stylesheet.*?\?>')
DOCTYPE_PATTERN = re.compile(r'<!DOCTYPE.*?>')
HTML_BODY_PATTERN = re.compile(r'</?(?:html|body).*?>')
HTML_END_PATTERN = re.compile(r'</html>')

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    # Add more user agents as needed
]

def clean_url(url: str) -> str:
    """Remove trailing colons, slashes, semicolons, and HTML tags from a URL."""
    url = re.sub(r'<[^>]+>', '', url)  
    url = url.strip()  
    url = re.sub(r'[:/;]+$', '', url) 
    return url

def is_same_domain(root_url, link):
    parsed_root = urlparse(root_url)
    parsed_link = urlparse(link)
    if not parsed_link.scheme and not parsed_link.netloc:
        return True

    root_domain = '.'.join(parsed_root.netloc.split('.')[-2:])
    link_domain = '.'.join(parsed_link.netloc.split('.')[-2:])
    return root_domain == link_domain

def is_html_or_text(url) -> bool:
    """
    Check if the URL is valid and doesn't contain excluded patterns.
    Returns True if the URL is valid, False otherwise.
    """
    excluded_patterns = [
        '.png', '.jpg', '.jpeg', '.gif', '.svg',
        '/cdn-cgi/', '.bib'
    ]
    url_lower = url.lower()
    return not any(pattern.lower() in url_lower for pattern in excluded_patterns)

async def fetch_content(url: str, browser) -> tuple[str, int]:
    """Fetch and return the content of a file and its size using Playwright."""
    url = clean_url(url)
    
    context = await browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={'width': 1920, 'height': 1080},
        extra_http_headers={
            'Accept': 'application/xml,text/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
    )
    
    try:
        page = await context.new_page()
        await page.wait_for_timeout(1000)
        
        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        if response and response.ok:
            body = await response.body()
            size = len(body)
            
            content = body.decode('utf-8', errors='ignore')
            
            if not content or '<html' in content:
                content = await page.evaluate('''() => {
                    const pre = document.querySelector('pre');
                    if (pre) return pre.textContent;
                    
                    const xmlViewer = document.querySelector('#webkit-xml-viewer-source-xml');
                    if (xmlViewer) return xmlViewer.innerHTML;
                    
                    const xmlContent = document.querySelector('body').innerText;
                    if (xmlContent.includes('<?xml') || xmlContent.includes('<urlset') || xmlContent.includes('<sitemapindex'))
                        return xmlContent;
                        
                    return document.documentElement.outerHTML;
                }''')
            
            return content, size
        else:
            print(f"Failed to fetch {url}: HTTP {response.status if response else 'No response'}")
            return "", 0
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return "", 0
    finally:
        await context.close()



