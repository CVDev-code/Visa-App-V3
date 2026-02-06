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
    # Implementation will use:
    # - requests to fetch the page
    # - newspaper3k or readability-lxml to extract clean article content
    # - BeautifulSoup as fallback
    
    # Try newspaper3k first (best for news/article sites)
    try:
        from newspaper import Article
        
        article = Article(url)
        article.download()
        article.parse()
        
        return {
            "title": article.title or "Untitled",
            "author": ", ".join(article.authors) if article.authors else "",
            "date": article.publish_date.strftime("%B %d, %Y") if article.publish_date else "",
            "content": article.text or "",
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
                {'class': ['meta', 'metadata', 'byline']},  # We'll extract author separately
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
                # Extract just paragraphs for cleaner content
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
    
    Args:
        webpage_data: Dictionary from fetch_webpage_content()
        left_margin_mm: Left margin in millimeters
        right_margin_mm: Right margin in millimeters
        top_margin_mm: Top margin in millimeters
        bottom_margin_mm: Bottom margin in millimeters
        
    Returns:
        PDF bytes
    """
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except ImportError:
        # Fallback: use reportlab (more basic but works)
        return _convert_with_reportlab(webpage_data, left_margin_mm, right_margin_mm, 
                                        top_margin_mm, bottom_margin_mm)
    
    # Extract data
    title = webpage_data.get('title', 'Untitled')
    author = webpage_data.get('author', '')
    date = webpage_data.get('date', '')
    url = webpage_data.get('url', '')
    content = webpage_data.get('content', '')
    
    # Get current timestamp for footer (like browser print)
    from datetime import datetime
    timestamp = datetime.now().strftime("%m/%d/%Y, %H:%M")
    
    # Shorten URL for display (remove https://)
    display_url = url.replace('https://', '').replace('http://', '')
    
    # Create HTML with Opera Today exact styling
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            @page {{
                size: letter;
                margin: {top_margin_mm}mm {right_margin_mm}mm {bottom_margin_mm}mm {left_margin_mm}mm;
                
                @bottom-left {{
                    content: "{timestamp}  {title[:40]}{'...' if len(title) > 40 else ''}";
                    font-family: 'Times New Roman', Times, serif;
                    font-size: 8pt;
                    color: #000;
                    white-space: pre;
                }}
                
                @bottom-right {{
                    content: counter(page) "/" counter(pages);
                    font-family: 'Times New Roman', Times, serif;
                    font-size: 8pt;
                    color: #000;
                }}
            }}
            
            body {{
                font-family: Georgia, 'Times New Roman', Times, serif;
                font-size: 11pt;
                line-height: 1.4;
                color: #000;
                text-align: left;
                hyphens: none;
                margin: 0;
                padding: 0;
            }}
            
            h1 {{
                font-size: 22pt;
                font-weight: bold;
                margin: 0 0 10pt 0;
                padding: 0;
                color: #000;
                line-height: 1.2;
            }}
            
            .url-display {{
                font-size: 9pt;
                color: #666;
                margin: 0 0 15pt 0;
                text-decoration: none;
                word-wrap: break-word;
            }}
            
            .url-display::before {{
                content: "🔗 ";
                color: #999;
            }}
            
            p {{
                margin: 0 0 10pt 0;
                padding: 0;
            }}
            
            /* Remove images */
            img, iframe {{ display: none; }}
        </style>
    </head>
    <body>
        <h1>{title}</h1>
        
        <div class="url-display">{display_url}</div>
        
        <div class="content">
            {_format_content_to_html(content)}
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
    """Convert plain text to HTML paragraphs."""
    paragraphs = text.split('\n\n')
    html_paragraphs = [f"<p>{p.strip()}</p>" for p in paragraphs if p.strip()]
    return '\n'.join(html_paragraphs)


def _convert_with_reportlab(
    webpage_data: Dict[str, str],
    left_margin_mm: float,
    right_margin_mm: float,
    top_margin_mm: float,
    bottom_margin_mm: float
) -> bytes:
    """
    Fallback PDF converter using ReportLab (already in your requirements).
    Simpler but works reliably.
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.enums import TA_JUSTIFY
    
    buffer = io.BytesIO()
    
    # Create PDF with specified margins
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=left_margin_mm * mm,
        rightMargin=right_margin_mm * mm,
        topMargin=top_margin_mm * mm,
        bottomMargin=bottom_margin_mm * mm
    )
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=12
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=11,
        alignment=TA_JUSTIFY,
        spaceAfter=10
    )
    
    metadata_style = ParagraphStyle(
        'Metadata',
        parent=styles['Normal'],
        fontSize=9,
        textColor='#666666',
        spaceAfter=15
    )
    
    # Build document
    story = []
    
    # Title
    story.append(Paragraph(webpage_data.get('title', 'Untitled'), title_style))
    story.append(Spacer(1, 6))
    
    # Metadata
    metadata_parts = []
    if webpage_data.get('author'):
        metadata_parts.append(f"<b>Author:</b> {webpage_data['author']}")
    if webpage_data.get('date'):
        metadata_parts.append(f"<b>Date:</b> {webpage_data['date']}")
    metadata_parts.append(f"<b>URL:</b> {webpage_data.get('url', '')}")
    
    story.append(Paragraph('<br/>'.join(metadata_parts), metadata_style))
    story.append(Spacer(1, 12))
    
    # Content paragraphs
    content = webpage_data.get('content', '')
    for para in content.split('\n\n'):
        para = para.strip()
        if para:
            # Escape HTML entities
            para = para.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            story.append(Paragraph(para, body_style))
    
    # Generate PDF
    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


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
                if progress_callback:
                    progress_callback(processed, total_urls, f"Error: {title} - {str(e)}")
                processed += 1
                continue
    
    return result


# For organization verification evidence
def fetch_organization_evidence(organization_name: str) -> Tuple[Dict, list]:
    """
    Fetch evidence documents about an organization's prestige.
    
    Returns:
        (verification_result, evidence_urls)
        
        evidence_urls = [
            {"url": "...", "title": "...", "snippet": "..."},
            ...
        ]
    """
    # This would:
    # 1. Search for the organization
    # 2. Find official website, Wikipedia, news coverage
    # 3. Return URLs of evidence used in verification
    
    # Placeholder implementation
    return {
        "is_distinguished": True,
        "confidence": "high",
        "reasoning": "International opera house with 100+ year history"
    }, [
        {
            "url": f"https://en.wikipedia.org/wiki/{organization_name.replace(' ', '_')}",
            "title": f"{organization_name} - Wikipedia",
            "snippet": "Official encyclopedia entry"
        }
    ]
