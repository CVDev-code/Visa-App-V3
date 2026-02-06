"""
Web scraping and PDF conversion for O-1 Research Assistant.

This module fetches webpages and converts them to clean PDFs with consistent margins
suitable for PDF annotation.
"""

import io
from typing import Dict, Optional, Tuple
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
            "content": "Full article text",
            "url": "Original URL",
            "raw_html": "Full HTML (for debugging)"
        }
    """
    # Try newspaper3k first (best for news/article sites)
    try:
        from newspaper import Article
        
        article = Article(url)
        article.download()
        article.parse()
        
        # CRITICAL FIX: newspaper3k loses paragraph structure
        # Get HTML and extract paragraphs manually for better formatting
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(article.html, 'html.parser')
        
        # Find article body and extract paragraphs
        main_content = (
            soup.find('article') or 
            soup.find('main') or 
            soup.find('div', class_=['content', 'article', 'post', 'entry-content', 'article-body']) or
            soup.find('body')
        )
        
        if main_content:
            # Extract paragraphs maintaining structure
            paragraphs = main_content.find_all('p')
            if paragraphs and len(paragraphs) > 3:
                # Use HTML paragraph structure (MUCH better than newspaper3k text)
                content = '\n\n'.join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
            else:
                # Fallback to newspaper3k text
                content = article.text or ""
        else:
            content = article.text or ""
        
        return {
            "title": article.title or "Untitled",
            "author": ", ".join(article.authors) if article.authors else "",
            "date": article.publish_date.strftime("%B %d, %Y") if article.publish_date else "",
            "content": content,
            "url": url,
            "raw_html": article.html
        }
    except Exception as e:
        print(f"[newspaper3k failed] {e}, trying BeautifulSoup...")
        # Fallback to BeautifulSoup with aggressive cleaning
        try:
            from bs4 import BeautifulSoup
            import requests
            
            response = requests.get(url, timeout=10, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; O1VisaBot/1.0)'
            })
            soup = BeautifulSoup(response.content, 'html.parser')
            
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
                # Extract paragraphs for proper structure
                paragraphs = main_content.find_all('p')
                if paragraphs:
                    content = '\n\n'.join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
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
                "raw_html": str(soup)
            }
        except Exception as e2:
            raise RuntimeError(f"Failed to fetch {url}: {e2}")


def convert_webpage_to_pdf_with_margins(
    webpage_data: Dict[str, str],
    left_margin_mm: float = 30,
    right_margin_mm: float = 30,
    top_margin_mm: float = 30,
    bottom_margin_mm: float = 30
) -> bytes:
    """
    Convert webpage content to PDF matching Opera Today print style.
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
    
    # Get current timestamp for footer (like browser print)
    timestamp = datetime.now().strftime("%m/%d/%Y, %H:%M")
    
    # Shorten URL for display (remove https://)
    display_url = url.replace('https://', '').replace('http://', '')
    
    # Extract publication name from URL
    from urllib.parse import urlparse
    parsed_url = urlparse(url)
    publication_name = parsed_url.netloc.replace('www.', '').split('.')[0].title()
    
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
                content: "🔗 ";
                color: #ccc;
            }}
            
            p {{
                margin: 0 0 12pt 0;
                padding: 0;
                text-indent: 0;
                orphans: 2;
                widows: 2;
            }}
            
            /* Preserve formatting from original */
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
                margin: 15pt auto;
            }}
            
            /* Remove navigation images and ads */
            img[src*="logo"], img[src*="ad"], img[src*="banner"], 
            img[src*="thumb"], img[width="1"], img[height="1"] {{
                display: none;
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
        <div class="publication">{publication_name}</div>
        
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
    Preserves structure for authentic look.
    """
    if not text:
        return ""
    
    # Split into paragraphs
    paragraphs = text.split('\n\n')
    
    html_parts = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        # Escape HTML but preserve structure
        para = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Preserve common formatting patterns from original text
        # (newspaper3k strips HTML but sometimes leaves formatting clues)
        
        html_parts.append(f"<p>{para}</p>")
    
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
