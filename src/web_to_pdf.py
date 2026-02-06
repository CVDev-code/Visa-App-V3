"""
Web scraping and PDF conversion for O-1 Research Assistant.

This module fetches webpages and converts them to clean PDFs with consistent margins
suitable for PDF annotation.

IMPROVEMENTS v13:
- Publication logo/masthead extraction for authentic branding
- Image captions extraction and display
- Expanded junk image filtering (social widgets, navigation, etc.)
- Raised minimum image size from 50px to 100px
- Better editorial vs UI image detection
"""

import io
from typing import Dict, Optional, Tuple, List
from datetime import datetime


def fetch_webpage_content(url: str) -> Dict[str, str]:
    """
    Fetch and extract clean content from a webpage.
    
    Args:
        url: The URL to fetch
        
    Returns:
        {
            "title": "Article Title",
            "author": "Author Name",
            "date": "Publication Date",
            "content": "Full article text with <img> tags for images",
            "url": "Original URL",
            "publication_logo": "URL to publication logo/masthead (if found)",
            "raw_html": "Full HTML (for debugging)"
        }
    """
    # Try newspaper3k first (best for news/article sites)
    try:
        from newspaper import Article
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
        
        article = Article(url)
        article.download()
        article.parse()
        
        # Get HTML and extract paragraphs + images manually for better formatting
        soup = BeautifulSoup(article.html, 'html.parser')
        
        # Extract publication logo/masthead for branding
        publication_logo = _extract_publication_logo(soup, url)
        
        # Find article body
        main_content = (
            soup.find('article') or 
            soup.find('main') or 
            soup.find('div', class_=['content', 'article', 'post', 'entry-content', 'article-body']) or
            soup.find('body')
        )
        
        if main_content:
            # Extract images with captions (filter out junk)
            images = _extract_images_with_captions(main_content, url, limit=2)
            
            # Extract paragraphs maintaining structure
            paragraphs = main_content.find_all('p')
            if paragraphs and len(paragraphs) > 3:
                # Build content with images interspersed
                content_parts = []
                
                # Add first image at top if available
                if images:
                    img_html = f'<img src="{images[0]["src"]}" alt="Article image">'
                    if images[0].get('caption'):
                        img_html += f'\n<figcaption>{images[0]["caption"]}</figcaption>'
                    content_parts.append(img_html)
                
                # Add paragraphs
                for p in paragraphs:
                    p_text = p.get_text().strip()
                    if p_text:
                        content_parts.append(p_text)
                
                # Add second image in middle if available
                if len(images) > 1 and len(content_parts) > 3:
                    mid_point = len(content_parts) // 2
                    img_html = f'<img src="{images[1]["src"]}" alt="Article image">'
                    if images[1].get('caption'):
                        img_html += f'\n<figcaption>{images[1]["caption"]}</figcaption>'
                    content_parts.insert(mid_point, img_html)
                
                content = '\n\n'.join(content_parts)
            else:
                # Fallback to newspaper3k text
                content = article.text or ""
                # Add main image if found
                if images:
                    img_html = f'<img src="{images[0]["src"]}" alt="Article image">'
                    if images[0].get('caption'):
                        img_html += f'\n<figcaption>{images[0]["caption"]}</figcaption>'
                    content = img_html + '\n\n' + content
        else:
            content = article.text or ""
        
        return {
            "title": article.title or "Untitled",
            "author": ", ".join(article.authors) if article.authors else "",
            "date": article.publish_date.strftime("%B %d, %Y") if article.publish_date else "",
            "content": content,
            "url": url,
            "publication_logo": publication_logo,
            "raw_html": article.html
        }
    except Exception as e:
        print(f"[newspaper3k failed] {e}, trying BeautifulSoup...")
        # Fallback to BeautifulSoup with aggressive cleaning
        try:
            from bs4 import BeautifulSoup
            import requests
            from urllib.parse import urljoin
            
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; O1VisaBot/1.0)'
            })
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract publication logo
            publication_logo = _extract_publication_logo(soup, url)
            
            # Extract title
            title_tag = soup.find('title') or soup.find('h1')
            title = title_tag.get_text().strip() if title_tag else "Untitled"
            
            # Remove scripts, styles, navigation, ads, etc.
            for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'iframe', 'header']):
                tag.decompose()
            
            # Remove common junk classes/IDs
            junk_selectors = [
                {'class': ['nav', 'navigation', 'navbar', 'menu', 'sidebar', 'widget']},
                {'class': ['breadcrumb', 'breadcrumbs', 'tags', 'categories']},
                {'class': ['share', 'social', 'comments', 'related']},
                {'class': ['ad', 'ads', 'advertisement', 'promo']},
                {'class': ['meta', 'metadata', 'byline']},
                {'id': ['nav', 'navigation', 'sidebar', 'footer', 'header']},
            ]
            
            for selector in junk_selectors:
                for tag in soup.find_all(**selector):
                    tag.decompose()
            
            # Get main content
            main_content = (
                soup.find('article') or 
                soup.find('main') or 
                soup.find('div', class_=['content', 'article', 'post', 'entry-content']) or
                soup.find('body')
            )
            
            if main_content:
                # Extract images with captions
                images = _extract_images_with_captions(main_content, url, limit=2)
                
                # Extract paragraphs for proper structure
                paragraphs = main_content.find_all('p')
                if paragraphs:
                    content_parts = []
                    
                    # Add first image
                    if images:
                        img_html = f'<img src="{images[0]["src"]}" alt="Article image">'
                        if images[0].get('caption'):
                            img_html += f'\n<figcaption>{images[0]["caption"]}</figcaption>'
                        content_parts.append(img_html)
                    
                    # Add paragraphs
                    for p in paragraphs:
                        p_text = p.get_text().strip()
                        if p_text:
                            content_parts.append(p_text)
                    
                    content = '\n\n'.join(content_parts)
                else:
                    content = main_content.get_text(separator='\n\n').strip()
            else:
                content = ""
            
            # Clean up: remove multiple blank lines
            import re
            content = re.sub(r'\n{3,}', '\n\n', content)
            
            return {
                "title": title,
                "author": "",
                "date": "",
                "content": content,
                "url": url,
                "publication_logo": publication_logo,
                "raw_html": str(soup)
            }
        except Exception as e2:
            raise RuntimeError(f"Failed to fetch {url}: {e2}")


def _extract_publication_logo(soup, url: str) -> Optional[str]:
    """
    Extract publication logo/masthead for PDF header branding.
    
    Args:
        soup: BeautifulSoup object
        url: Original URL (for converting relative paths)
        
    Returns:
        URL to logo image, or None if not found
    """
    from urllib.parse import urljoin
    
    publication_logo = None
    
    # Method 1: Find images with 'logo' or 'masthead' in class
    logo_candidates = soup.find_all('img', class_=lambda x: x and (
        'logo' in str(x).lower() or 
        'masthead' in str(x).lower() or
        'brand' in str(x).lower()
    ))
    
    # Method 2: Check header/masthead containers
    if not logo_candidates:
        header = soup.find(['header', 'div'], class_=lambda x: x and (
            'header' in str(x).lower() or 
            'masthead' in str(x).lower() or
            'branding' in str(x).lower()
        ))
        if header:
            logo_candidates = header.find_all('img', limit=5)
    
    # Select best logo (must be reasonably sized)
    for logo_img in logo_candidates:
        logo_src = logo_img.get('src') or logo_img.get('data-src')
        if not logo_src:
            continue
            
        logo_url = urljoin(url, logo_src)
        
        # Logo should be at least 100px wide (not tiny icon)
        width = logo_img.get('width')
        if width:
            try:
                if int(width) >= 100:
                    publication_logo = logo_url
                    break
            except (ValueError, TypeError):
                pass
        else:
            # No width specified - assume it might be good
            # Check if URL suggests it's a logo
            if any(x in logo_url.lower() for x in ['logo', 'masthead', 'brand']):
                publication_logo = logo_url
                break
    
    return publication_logo


def _extract_images_with_captions(soup, url: str, limit: int = 2) -> List[Dict[str, str]]:
    """
    Extract editorial images with their captions/credits.
    Filters out UI chrome, ads, social widgets, etc.
    
    Args:
        soup: BeautifulSoup object (article body)
        url: Original URL (for converting relative paths)
        limit: Maximum number of images to extract
        
    Returns:
        [
            {"src": "https://...", "caption": "Photo credit"},
            ...
        ]
    """
    from urllib.parse import urljoin
    
    images = []
    
    # Comprehensive junk image filter
    junk_patterns = [
        # Logos/branding
        'logo', 'icon', 'brand', 'masthead',
        
        # Ads
        'ad', 'banner', 'sponsor', 'promo',
        
        # UI elements
        'button', 'nav', 'menu', 'header', 'footer', 'sidebar',
        'arrow', 'chevron', 'caret', 'hamburger',
        
        # Social
        'facebook', 'twitter', 'instagram', 'linkedin', 'social', 'share',
        
        # User elements
        'avatar', 'profile', 'user', 'author-photo',
        
        # Junk
        'pixel', 'tracking', 'beacon', 'analytics', 'widget',
        'thumbnail', 'badge', 'tag',
        
        # Subscription widgets
        'newsletter', 'subscribe', 'donate', 'support',
        
        # Placeholder/loading
        'placeholder', 'loading', 'spinner', 'loader'
    ]
    
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-original')
        if not src:
            continue
        
        # Convert relative URLs to absolute
        img_src = urljoin(url, src)
        src_lower = img_src.lower()
        
        # Filter out junk images by URL
        if any(pattern in src_lower for pattern in junk_patterns):
            continue
        
        # Filter out junk images by CSS class
        img_classes = ' '.join(img.get('class', [])).lower()
        if any(pattern in img_classes for pattern in junk_patterns):
            continue
        
        # Skip tiny images (raised from 50px to 100px minimum)
        width = img.get('width')
        height = img.get('height')
        if width and height:
            try:
                if int(width) < 100 or int(height) < 100:
                    continue
            except (ValueError, TypeError):
                pass
        
        # Check if this is editorial content (not UI chrome)
        if not _is_editorial_image(img):
            continue
        
        # Extract caption (multiple methods)
        caption = _extract_image_caption(img)
        
        images.append({
            'src': img_src,
            'caption': caption
        })
        
        if len(images) >= limit:
            break
    
    return images


def _is_editorial_image(img) -> bool:
    """
    Distinguish editorial images (keep) from UI chrome (remove).
    
    Args:
        img: BeautifulSoup img tag
        
    Returns:
        True if this appears to be editorial content
    """
    src = img.get('src', '').lower()
    
    # Definite editorial content indicators
    editorial_indicators = [
        'photo', 'image', 'picture', 'gallery', 'media',
        'album', 'cover', 'artist', 'performer', 'concert'
    ]
    if any(ind in src for ind in editorial_indicators):
        return True
    
    # Check if inside article content areas
    parent = img.find_parent()
    if parent:
        parent_classes = ' '.join(parent.get('class', [])).lower()
        content_indicators = ['article', 'content', 'body', 'post', 'entry', 'main']
        if any(ind in parent_classes for ind in content_indicators):
            return True
    
    # Check if in header/footer/nav (definitely NOT editorial)
    chrome_parents = ['header', 'footer', 'nav', 'aside', 'sidebar']
    if any(img.find_parent(tag) for tag in chrome_parents):
        return False
    
    return True  # Default: keep it


def _extract_image_caption(img) -> Optional[str]:
    """
    Extract caption/credit for an image.
    
    Args:
        img: BeautifulSoup img tag
        
    Returns:
        Caption text, or None if not found
    """
    caption = None
    
    # Method 1: <figcaption> inside parent <figure>
    fig = img.find_parent('figure')
    if fig:
        figcaption = fig.find('figcaption')
        if figcaption:
            caption = figcaption.get_text(strip=True)
    
    # Method 2: <p class="caption"> nearby
    if not caption:
        caption_elem = img.find_next('p', class_=lambda x: x and 'caption' in str(x).lower())
        if caption_elem:
            caption = caption_elem.get_text(strip=True)
    
    # Method 3: <div class="credit"> or similar
    if not caption:
        credit_elem = img.find_next(['div', 'span'], class_=lambda x: x and (
            'credit' in str(x).lower() or 
            'photo-credit' in str(x).lower()
        ))
        if credit_elem:
            caption = credit_elem.get_text(strip=True)
    
    # Method 4: title or alt attribute
    if not caption:
        caption = img.get('title') or img.get('alt')
        # Skip generic alt text
        if caption and caption.lower() in ['image', 'photo', 'picture']:
            caption = None
    
    return caption


def convert_webpage_to_pdf_with_margins(
    webpage_data: Dict[str, str],
    left_margin_mm: float = 30,
    right_margin_mm: float = 30,
    top_margin_mm: float = 30,
    bottom_margin_mm: float = 30
) -> bytes:
    """
    Convert webpage content to PDF with authentic publication styling.
    Uses 30mm margins for annotation space.
    
    REQUIRES WeasyPrint - will fail if not installed.
    
    Args:
        webpage_data: Dictionary from fetch_webpage_content()
        left_margin_mm: Left margin in millimeters
        right_margin_mm: Right margin in millimeters
        top_margin_mm: Top margin in millimeters
        bottom_margin_mm: Bottom margin in millimeters
        
    Returns:
        PDF bytes
    """
    from weasyprint import HTML, CSS
    from weasyprint.text.fonts import FontConfiguration
    
    # Extract data
    title = webpage_data.get('title', 'Untitled')
    author = webpage_data.get('author', '')
    date = webpage_data.get('date', '')
    url = webpage_data.get('url', '')
    content = webpage_data.get('content', '')
    publication_logo = webpage_data.get('publication_logo')
    
    # Get current timestamp for footer (like browser print)
    timestamp = datetime.now().strftime("%m/%d/%Y, %H:%M")
    
    # Shorten URL for display (remove https://)
    display_url = url.replace('https://', '').replace('http://', '')
    
    # Extract publication name from URL
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    publication_name = parsed_url.netloc.replace('www.', '').split('.')[0].title()
    
    # Build publication header HTML
    publication_header = ''
    if publication_logo:
        publication_header = f'<div class="publication-header"><img src="{publication_logo}" class="publication-logo" alt="{publication_name}"></div>'
    else:
        publication_header = f'<div class="publication">{publication_name}</div>'
    
    # Create HTML with authentic article styling
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: letter;
                margin: 20mm 30mm 20mm 30mm;
                
                @bottom-left {{
                    content: "{timestamp}";
                    font-family: Arial, Helvetica, sans-serif;
                    font-size: 8pt;
                    color: #666;
                }}
                
                @bottom-center {{
                    content: "{publication_name}";
                    font-family: Arial, Helvetica, sans-serif;
                    font-size: 8pt;
                    color: #666;
                    text-transform: uppercase;
                }}
                
                @bottom-right {{
                    content: counter(page) "/" counter(pages);
                    font-family: Arial, Helvetica, sans-serif;
                    font-size: 8pt;
                    color: #666;
                }}
            }}
            
            body {{
                font-family: Arial, Helvetica, sans-serif;
                font-size: 10pt;
                line-height: 1.5;
                color: #333;
                text-align: left;
                hyphens: none;
                margin: 0;
                padding: 0;
            }}
            
            .publication-header {{
                margin: 0 0 15pt 0;
            }}
            
            .publication-logo {{
                max-width: 200px;
                height: auto;
                display: block;
            }}
            
            .publication {{
                font-size: 9pt;
                color: #999;
                text-transform: uppercase;
                letter-spacing: 1px;
                margin: 0 0 15pt 0;
                font-weight: bold;
            }}
            
            h1 {{
                font-size: 18pt;
                font-weight: bold;
                margin: 0 0 12pt 0;
                padding: 0;
                color: #000;
                line-height: 1.2;
            }}
            
            .byline {{
                font-size: 9pt;
                color: #666;
                margin: 0 0 8pt 0;
                font-style: italic;
            }}
            
            .divider {{
                border-bottom: 1px solid #ddd;
                margin: 8pt 0 15pt 0;
            }}
            
            .url-display {{
                font-size: 8pt;
                color: #999;
                margin: 0 0 20pt 0;
                text-decoration: none;
                word-wrap: break-word;
                font-family: 'Courier New', monospace;
            }}
            
            .url-display::before {{
                content: "↗ ";
                color: #999;
                font-weight: bold;
            }}
            
            p {{
                margin: 0 0 12pt 0;
                padding: 0;
                text-indent: 0;
                orphans: 2;
                widows: 2;
            }}
            
            em, i {{
                font-style: italic;
            }}
            
            strong, b {{
                font-weight: bold;
            }}
            
            img {{
                max-width: 100%;
                height: auto;
                display: block;
                margin: 20pt auto;
                border: 1px solid #eee;
                padding: 5pt;
            }}
            
            figcaption {{
                font-size: 8pt;
                color: #666;
                font-style: italic;
                text-align: center;
                margin: 5pt 0 15pt 0;
            }}
            
            .footer {{
                margin-top: 30pt;
                padding-top: 15pt;
                border-top: 1px solid #ddd;
                font-size: 8pt;
                color: #999;
                line-height: 1.4;
            }}
        </style>
    </head>
    <body>
        {publication_header}
        
        <h1>{title}</h1>
        
        {f'<div class="byline">By {author}{", " + date if date else ""}</div>' if author or date else ''}
        
        <div class="divider"></div>
        
        <div class="url-display">{display_url}</div>
        
        <div class="content">
            {_format_content_to_html(content)}
        </div>
        
        <div class="footer">
            © {datetime.now().year} {publication_name}. All rights reserved.<br>
            Original article: {display_url}<br>
            Retrieved: {timestamp}
        </div>
    </body>
    </html>
    """
    
    # Convert to PDF
    font_config = FontConfiguration()
    html = HTML(string=html_template)
    pdf_bytes = html.write_pdf(font_config=font_config)
    
    return pdf_bytes


def _format_content_to_html(text: str) -> str:
    """
    Convert plain text to HTML paragraphs.
    Handles embedded <img> and <figcaption> tags.
    """
    if not text:
        return ""
    
    # Split into paragraphs
    parts = text.split('\n\n')
    
    html_parts = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        # Check if this is an image tag
        if part.startswith('<img'):
            # Already HTML, keep as-is
            html_parts.append(part)
        elif part.startswith('<figcaption'):
            # Caption tag, keep as-is
            html_parts.append(part)
        else:
            # Text paragraph - escape HTML
            part = part.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_parts.append(f"<p>{part}</p>")
    
    return '\n'.join(html_parts)


def batch_convert_urls_to_pdfs(
    urls_by_criterion: Dict[str, list],
    progress_callback=None
) -> Dict[str, Dict[str, bytes]]:
    """
    Convert multiple approved URLs to PDFs, organized by criterion.
    
    Args:
        urls_by_criterion: {"1": [{"url": "...", "title": "..."}], ...}
        progress_callback: Optional function to call with progress updates
        
    Returns:
        {
            "1": {
                "Title_1.pdf": pdf_bytes,
                "Title_2.pdf": pdf_bytes
            },
            "3": {...}
        }
    """
    result = {}
    errors = []  # Collect errors to show later
    total_urls = sum(len(urls) for urls in urls_by_criterion.values())
    processed = 0
    
    for criterion_id, urls in urls_by_criterion.items():
        result[criterion_id] = {}
        
        for url_data in urls:
            url = url_data.get('url')
            title = url_data.get('title', 'Untitled')
            
            try:
                if progress_callback:
                    progress_callback(processed, total_urls, f"Fetching: {title}")
                
                # Fetch webpage
                webpage_data = fetch_webpage_content(url)
                
                if progress_callback:
                    progress_callback(processed, total_urls, f"Converting: {title}")
                
                # Convert to PDF with 30mm margins
                pdf_bytes = convert_webpage_to_pdf_with_margins(
                    webpage_data,
                    left_margin_mm=30,
                    right_margin_mm=30,
                    top_margin_mm=30,
                    bottom_margin_mm=30
                )
                
                # Create safe filename
                safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_'))[:50]
                filename = f"{safe_title}.pdf"
                
                result[criterion_id][filename] = pdf_bytes
                processed += 1
                
            except Exception as e:
                error_msg = f"❌ {title}: {str(e)}"
                errors.append(error_msg)
                if progress_callback:
                    progress_callback(processed, total_urls, error_msg)
                processed += 1
                continue
    
    # Print errors so they show in Streamlit
    if errors:
        print("\n=== CONVERSION ERRORS ===")
        for err in errors:
            print(err)
        print("========================\n")
    
    return result
