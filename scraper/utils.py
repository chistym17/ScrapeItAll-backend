import re
import random
from typing import Optional
from urllib.parse import urljoin, urlparse, unquote
import xml.etree.ElementTree as ET
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import requests
from collections import deque
from langchain_text_splitters import MarkdownTextSplitter
import tiktoken

tokenizer = tiktoken.get_encoding("cl100k_base")

XML_STYLESHEET_PATTERN = re.compile(r'<\?xml-stylesheet.*?\?>')
DOCTYPE_PATTERN = re.compile(r'<!DOCTYPE.*?>')
HTML_BODY_PATTERN = re.compile(r'</?(?:html|body).*?>')
HTML_END_PATTERN = re.compile(r'</html>')

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
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
        
        response = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
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

            content = clean_html_content(content)

            return content, size
        else:
            print(f"Failed to fetch {url}: HTTP {response.status if response else 'No response'}")
            return "", 0
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return "", 0
    finally:
        await context.close()

def crawl_website(root_url, max_pages=100):
    """Crawl website to find URLs."""
    visited_urls = set()
    urls_to_visit = deque([root_url])
    url_info = []

    while urls_to_visit and len(visited_urls) < max_pages:
        url = urls_to_visit.popleft()
        if url in visited_urls:
            continue
        visited_urls.add(url)

        try:
            response = requests.get(url)
            soup = BeautifulSoup(response.content, 'html.parser')
            if is_same_domain(root_url, url):
                size = len(soup.get_text()) if is_html_or_text(url) else 0
                url_info.append({
                    'url': url,
                    'selected': True,
                    'processed': bool(size),
                    'size': size
                })

                for link_tag in soup.find_all('a', href=True):
                    link = link_tag['href']
                    absolute_url = urljoin(url, link)
                    if urlparse(absolute_url).scheme in ['http', 'https'] and is_same_domain(root_url, absolute_url):
                        urls_to_visit.append(absolute_url)

        except requests.RequestException:
            url_info.append({
                'url': url,
                'selected': False,
                'processed': False,
                'size': 0
            })

    return url_info

def extract_page_name(url):
    """Extract a readable name from URL."""
    parsed_url = urlparse(url)
    path = parsed_url.path.rstrip('/')
    
    if not path:
        return parsed_url.netloc.split(':')[0]
    
    leaf = unquote(path).split('/')[-1]
    leaf = leaf.split(';')[0]
    leaf = leaf.split('?')[0].split('#')[0]
    
    if not leaf and len(path.split('/')) > 1:
        leaf = unquote(path).split('/')[-2]
    leaf = re.sub(r'\.[^.]+$', '', leaf)
    
    return leaf if leaf else parsed_url.netloc.split(':')[0]

def split_markdown(markdown_text, header_metadata, max_chunk_size, chunk_overlap_size):
    """Split markdown text into chunks."""
    splitter = MarkdownTextSplitter(chunk_size=max_chunk_size, chunk_overlap=chunk_overlap_size)
    chunks = splitter.split_text(markdown_text)
    final_chunks = [
        f"{header_metadata}\n\n{chunk}" for chunk in chunks
    ]
    chunk_token_counts = [len(tokenizer.encode(chunk)) for chunk in final_chunks]
    return list(zip(final_chunks, chunk_token_counts))

def get_header_metadata(soup, url):
    """Get metadata from page header."""
    title = soup.title.string if soup.title else extract_page_name(url)
    return f"Document Title: {title}. Document URL: {url}\n"

async def fetch_sitemap(root_domain):
    async def parse_sitemap(sitemap_url, browser):
        try:
            content, size = await fetch_content(sitemap_url, browser)
            if not content:
                return []

            if not any(marker in content for marker in ('<?xml', '<urlset', '<sitemapindex')):
                return []

            content = content[content.find('<?xml'):]
            content = XML_STYLESHEET_PATTERN.sub('', content)
            content = DOCTYPE_PATTERN.sub('', content)
            content = HTML_BODY_PATTERN.sub('', content)
            content = HTML_END_PATTERN.sub('', content)
            content = content.strip()

            root = ET.fromstring(content)
            urls = []
            if root.tag.endswith('sitemapindex'):
                for sitemap in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                    urls.extend(await parse_sitemap(sitemap.text, browser))
            else:
                for url in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                    urls.append({'url': url.text, 'size': size})

            return urls
        except Exception as e:
            print(f"Parse sitemap error: {str(e)}")
            return []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            if not root_domain.startswith(('http://', 'https://')):
                root_domain = 'https://' + root_domain

            sitemap_locations = [
                '/sitemap.xml',
                '/sitemap_index.xml',
                '/sitemap.php',
                '/sitemap.txt'
            ]

            url_with_size = []

            for location in sitemap_locations:
                sitemap_url = urljoin(root_domain, location)
                urls = await parse_sitemap(sitemap_url, browser)
                if urls:
                    url_with_size.extend(urls)
                    break

            filtered_urls = [
                url for url in url_with_size
                if is_same_domain(url.get('url'), root_domain) and is_html_or_text(url.get('url'))
            ]

            processed_urls = []
            for url in filtered_urls:
                size = url.get('size', 0)
                processed_urls.append({
                    'url': url.get('url'),
                    'selected': True,
                    'processed': False,
                    'size': size
                })

            return processed_urls
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            return []
        finally:
            await browser.close()

async def fetch_sitemap_with_custom_location(sitemap_custom_location):
    async def parse_sitemap(sitemap_url, browser):
        try:
            content, size = await fetch_content(sitemap_url, browser)
            if not content:
                return []

            if not any(marker in content for marker in ('<?xml', '<urlset', '<sitemapindex')):
                return []

            content = content[content.find('<?xml'):]
            content = XML_STYLESHEET_PATTERN.sub('', content)
            content = DOCTYPE_PATTERN.sub('', content)
            content = HTML_BODY_PATTERN.sub('', content)
            content = HTML_END_PATTERN.sub('', content)
            content = content.strip()

            root = ET.fromstring(content)
            urls = []
            if root.tag.endswith('sitemapindex'):
                for sitemap in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                    urls.extend(await parse_sitemap(sitemap.text, browser))
            else:
                for url in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc'):
                    urls.append({'url': url.text, 'size': size})

            return urls
        except Exception as e:
            print(f"Parse sitemap error: {str(e)}")
            return []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            if not sitemap_custom_location.startswith(('http://', 'https://')):
                sitemap_custom_location = 'https://' + sitemap_custom_location

            url_with_size = []
            urls = await parse_sitemap(sitemap_custom_location, browser)
            if urls:
                url_with_size.extend(urls)

            filtered_urls = [
                url for url in url_with_size
                if is_same_domain(url.get('url'), sitemap_custom_location) and is_html_or_text(url.get('url'))
            ]

            processed_urls = []
            for url in filtered_urls:
                size = url.get('size', 0)
                processed_urls.append({
                    'url': url.get('url'),
                    'selected': True,
                    'processed': False,
                    'size': size
                })

            return processed_urls
        except Exception as e:
            print(f"An error occurred: {str(e)}")
            return []
        finally:
            await browser.close()

async def get_page_content_size(url: str) -> Optional[int]:
    """
    Fetch the content size of the given URL.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width": 1920, "height": 1080}
            )
            page = await context.new_page()

            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if not response or not response.ok:
                return None

            text_content = await page.evaluate('''() => {
                const elementsToRemove = document.querySelectorAll('script, style, nav, header, footer');
                elementsToRemove.forEach(el => el.remove());
                const mainContent = document.querySelector('main, article, [role="main"], .content') || document.body;
                return mainContent.innerText;
            }''')

            return len(text_content) if text_content else 0

        except Exception as e:
            print(f"Error fetching page size for {url}: {e}")
            return None

        finally:
            await browser.close()

def clean_html_content(html_content: str) -> str:
    """Clean HTML content and extract readable text.
    
    Args:
        html_content: Raw HTML string
    Returns:
        Cleaned text content with preserved line breaks
    """
    try:
        html_content = XML_STYLESHEET_PATTERN.sub('', html_content)
        html_content = DOCTYPE_PATTERN.sub('', html_content)
        html_content = HTML_BODY_PATTERN.sub('', html_content)
        html_content = HTML_END_PATTERN.sub('', html_content)
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        for element in soup(['script', 'style', 'meta', 'link', 'noscript']):
            element.decompose()
            
        text = soup.get_text(separator=' ', strip=True)
        
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = text.strip()
        
        return text
        
    except Exception as e:
        print(f"Error cleaning HTML content: {e}")
        return ""



