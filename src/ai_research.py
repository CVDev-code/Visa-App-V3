"""
AI-Powered Research Assistant - Using Vertex AI Gemini with Google Search
This works with PAID Google Cloud accounts with Vertex AI enabled.

Setup Required:
1. Create Google Cloud project: https://console.cloud.google.com
2. Enable Vertex AI API
3. Set up billing
4. Create service account and download JSON key
5. Set GOOGLE_APPLICATION_CREDENTIALS environment variable
"""

import os
import re
import json
from typing import Dict, List, Optional

# Import customizable search prompts
try:
    from .search_prompts import SEARCH_PROMPTS
except ImportError:
    SEARCH_PROMPTS = None


TARGET_RESULTS = {
    "1": 5,
    "2_past": 5,
    "2_future": 5,
    "3": 10,
    "4_past": 5,
    "4_future": 5,
    "5": 10,
    "6": 3,
    "7": 3,
}


def _get_secret(name: str):
    """Get secret from Streamlit or environment."""
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


def _search_with_vertex_ai(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    target_count: int,
) -> List[Dict]:
    """
    Use Vertex AI Gemini with Google Search grounding.
    This is the PAID version that actually works.
    """
    
    try:
        import vertexai
        from vertexai.generative_models import GenerativeModel, Tool
        from vertexai.preview.generative_models import grounding
    except ImportError:
        raise RuntimeError(
            "Vertex AI library not installed.\n"
            "Install with: pip install google-cloud-aiplatform"
        )
    
    # Get configuration
    project_id = _get_secret("GOOGLE_CLOUD_PROJECT")
    location = _get_secret("GOOGLE_CLOUD_LOCATION") or "us-central1"
    
    if not project_id:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT not found.\n"
            "Add your Google Cloud project ID to Streamlit secrets."
        )
    
    # Initialize Vertex AI
    try:
        vertexai.init(project=project_id, location=location)
    except Exception as e:
        raise RuntimeError(
            f"Failed to initialize Vertex AI: {e}\n\n"
            "Make sure:\n"
            "1. Vertex AI API is enabled in your Google Cloud project\n"
            "2. Service account credentials are configured\n"
            "3. GOOGLE_APPLICATION_CREDENTIALS is set (or use Streamlit secrets)"
        )
    
    # Build search prompt
    search_prompt = _build_search_prompt(criterion_id, criterion_desc, artist_name, target_count)
    
    print(f"\n{'='*60}")
    print(f"[Vertex AI] Criterion {criterion_id}: {criterion_desc[:50]}...")
    print(f"{'='*60}")
    
    try:
        print("[Vertex AI] Searching with Google Search grounding...")
        
        # Create model with Google Search grounding
        model = GenerativeModel("gemini-1.5-flash-002")
        
        # Configure Google Search as grounding source
        google_search_tool = Tool.from_google_search_retrieval(
            grounding.GoogleSearchRetrieval()
        )
        
        # Generate content with grounding
        response = model.generate_content(
            search_prompt,
            tools=[google_search_tool],
        )
        
        # Extract text
        text = response.text
        
        print(f"[Vertex AI] Response length: {len(text)} chars")
        
        # Extract grounding metadata if available
        grounding_metadata = None
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'grounding_metadata'):
                grounding_metadata = candidate.grounding_metadata
        
        # Extract URLs from response
        results = _extract_search_results(text, criterion_desc, grounding_metadata)
        
        print(f"[Vertex AI] Found {len(results)} results")
        
        return results
        
    except Exception as e:
        print(f"[Vertex AI] Error: {e}")
        import traceback
        traceback.print_exc()
        return []


def _build_search_prompt(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    target_count: int,
) -> str:
    """
    Build criterion-specific search prompts.
    """
    
    # Try external prompts first
    if SEARCH_PROMPTS and criterion_id in SEARCH_PROMPTS:
        template = SEARCH_PROMPTS[criterion_id]
        base_prompt = template.format(
            artist_name=artist_name,
            target_count=target_count
        )
    else:
        # Fallback to built-in prompts
        base_prompt = _get_default_prompt(criterion_id, criterion_desc, artist_name, target_count)
    
    # Add grounding-specific instructions
    grounding_instructions = f"""

CRITICAL: Use Google Search to find {target_count} actual sources.

For each source you find, provide:
1. Full article title
2. Complete URL
3. Publication name
4. Brief excerpt showing relevance

FORMAT:
---
TITLE: [Exact article title from the source]
URL: [Complete URL]
SOURCE: [Publication name]
EXCERPT: [Key quote from the article]
---

Find EXACTLY {target_count} real sources using Google Search."""
    
    return base_prompt + grounding_instructions


def _get_default_prompt(criterion_id: str, criterion_desc: str, artist_name: str, target_count: int) -> str:
    """Default search prompts."""
    
    prompts = {
        "1": f"""Search Google for evidence that {artist_name} has won significant national or international awards.

USCIS O-1 Requirements:
- Named, prestigious awards (Grammy, Pulitzer, MacArthur, major competitions)
- Official announcements from award organizations
- Coverage in major publications

Find {target_count} sources showing award wins.""",

        "3": f"""Search Google for critical reviews and feature articles about {artist_name}.

USCIS O-1 Requirements:
- Reviews from prestigious publications (NYT, Guardian, Gramophone, BBC, NPR)
- Feature articles demonstrating distinguished reputation
- Critical analysis, not just event listings

Find {target_count} reviews from major publications.""",

        "2_past": f"""Search Google for {artist_name}'s PAST lead or starring roles in productions/events.

Look for:
- Past performances at major venues (Carnegie Hall, Royal Opera House, etc.)
- Lead roles in distinguished productions

Find {target_count} sources about past performances.""",

        "2_future": f"""Search Google for {artist_name}'s UPCOMING (2025-2026) lead or starring roles.

Look for:
- Announced performances at major venues
- Future engagements

Find {target_count} sources about future performances.""",

        "4_past": f"""Search Google for {artist_name}'s PAST roles with distinguished organizations.

Look for:
- Past engagements with major orchestras, opera companies, festivals
- Critical roles with prestigious organizations

Find {target_count} sources.""",

        "4_future": f"""Search Google for {artist_name}'s FUTURE engagements with distinguished organizations.

Look for:
- Announced engagements with major organizations
- Future performances

Find {target_count} sources.""",

        "5": f"""Search Google for {artist_name}'s major commercial or critically acclaimed successes.

Look for:
- Sold-out performances
- Chart success or sales records
- Critical acclaim

Find {target_count} sources.""",

        "6": f"""Search Google for {artist_name} receiving significant recognition.

Look for:
- Critical praise from recognized experts
- Recognition from industry organizations
- Expert testimonials

Find {target_count} sources.""",

        "7": f"""Search Google for {artist_name}'s salary/remuneration and industry wage data.

CRITICAL: Need both artist salary AND industry comparison.

Search for:
1. Artist's salary/fees (if available)
2. Bureau of Labor Statistics: "onetcenter.org musicians wages"
3. BLS data: "bls.gov occupational employment musicians"
4. Union scales for comparison

Find {target_count} sources including BLS data.""",
    }
    
    return prompts.get(criterion_id, f"Search for {target_count} sources about {artist_name} for: {criterion_desc}")


def _extract_search_results(text: str, criterion_desc: str, grounding_metadata=None) -> List[Dict]:
    """
    Extract URLs and metadata from Vertex AI response.
    """
    
    results = []
    
    # First try to extract from grounding metadata (most reliable)
    if grounding_metadata:
        try:
            if hasattr(grounding_metadata, 'grounding_chunks'):
                print(f"[Extract] Found {len(grounding_metadata.grounding_chunks)} grounding chunks")
                for chunk in grounding_metadata.grounding_chunks:
                    if hasattr(chunk, 'web') and hasattr(chunk.web, 'uri'):
                        results.append({
                            "url": chunk.web.uri,
                            "title": getattr(chunk.web, 'title', _extract_source_from_url(chunk.web.uri)),
                            "source": _extract_source_from_url(chunk.web.uri),
                            "relevance": f"Google Search for {criterion_desc[:50]}...",
                            "excerpt": "Source from Google Search grounding"
                        })
        except Exception as e:
            print(f"[Extract] Error extracting grounding metadata: {e}")
    
    # Also try structured format from text
    structured_pattern = r'---\s*TITLE:\s*(.+?)\s*URL:\s*(https?://[^\s]+)\s*SOURCE:\s*(.+?)\s*EXCERPT:\s*(.+?)\s*---'
    structured_matches = re.findall(structured_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if structured_matches:
        print(f"[Extract] Found {len(structured_matches)} structured results in text")
        for title, url, source, excerpt in structured_matches:
            # Avoid duplicates from grounding metadata
            if not any(r['url'] == url.strip() for r in results):
                results.append({
                    "url": url.strip(),
                    "title": title.strip(),
                    "source": source.strip(),
                    "relevance": f"Google Search for {criterion_desc[:50]}...",
                    "excerpt": excerpt.strip()[:300]
                })
    
    # Fallback: Extract any URLs from text
    if not results:
        print("[Extract] No grounding metadata or structured format, trying URL extraction...")
        
        url_pattern = r'https?://[^\s\)\]<>"]+'
        urls = re.findall(url_pattern, text)
        
        print(f"[Extract] Found {len(urls)} URLs in text")
        
        for url in urls[:20]:
            title_context = ""
            url_index = text.find(url)
            if url_index > 0:
                context_start = max(0, url_index - 200)
                context = text[context_start:url_index]
                
                title_match = re.search(r'["""]([^"""]+)["""]', context)
                if title_match:
                    title_context = title_match.group(1)
                else:
                    sentences = re.split(r'[.!?]\s+', context)
                    if sentences:
                        title_context = sentences[-1].strip()
            
            results.append({
                "url": url.strip(),
                "title": title_context[:100] if title_context else _extract_source_from_url(url),
                "source": _extract_source_from_url(url),
                "relevance": f"Google Search for {criterion_desc[:50]}...",
                "excerpt": "Source from Google Search"
            })
    
    # Remove duplicates
    seen_urls = set()
    unique_results = []
    for r in results:
        if r['url'] not in seen_urls:
            seen_urls.add(r['url'])
            unique_results.append(r)
    
    return unique_results


def _extract_source_from_url(url: str) -> str:
    """Extract publication name from URL."""
    from urllib.parse import urlparse
    try:
        domain = urlparse(url).netloc
        domain = domain.replace("www.", "")
        parts = domain.split(".")
        if len(parts) > 1:
            return parts[0].capitalize()
        return domain.capitalize()
    except:
        return "Unknown Source"


def ai_search_for_evidence(
    artist_name: str,
    name_variants: List[str],
    selected_criteria: List[str],
    criteria_descriptions: Dict[str, str],
    feedback: Optional[Dict] = None,
    artist_field: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    """
    Research using Vertex AI Gemini with Google Search grounding.
    
    Setup:
    1. Create Google Cloud project
    2. Enable Vertex AI API
    3. Set up billing
    4. Add to Streamlit secrets:
       - GOOGLE_CLOUD_PROJECT = "your-project-id"
       - GOOGLE_CLOUD_LOCATION = "us-central1" (optional)
       - GOOGLE_APPLICATION_CREDENTIALS_JSON = {...} (service account key)
    
    Cost: ~$0.26 per application
    Quality: Excellent - real Google Search results
    """
    
    print(f"\n{'='*60}")
    print("VERTEX AI GEMINI + GOOGLE SEARCH")
    print(f"{'='*60}")
    print(f"Artist: {artist_name}")
    print(f"Variants: {name_variants}")
    print(f"Criteria: {selected_criteria}")
    print(f"Field: {artist_field}")
    print(f"{'='*60}\n")
    
    results_by_criterion = {}
    
    for cid in selected_criteria:
        try:
            criterion_desc = criteria_descriptions.get(cid, "")
            if not criterion_desc:
                print(f"[Warning] No description for criterion {cid}, skipping")
                continue
            
            print(f"\n{'='*60}")
            print(f"Searching: Criterion {cid} - {criterion_desc}")
            print(f"{'='*60}")
            
            target = TARGET_RESULTS.get(cid, 5)
            
            # Search with Vertex AI
            results = _search_with_vertex_ai(
                cid,
                criterion_desc,
                artist_name,
                target
            )
            
            if results:
                results_by_criterion[cid] = results
                print(f"[Success] Criterion {cid}: {len(results)} results")
            else:
                print(f"[Warning] Criterion {cid}: No results found")
            
        except Exception as e:
            print(f"[Error] Criterion {cid} failed: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    print(f"\n{'='*60}")
    print("SEARCH COMPLETE")
    print(f"Criteria searched: {len(selected_criteria)}")
    print(f"Criteria with results: {len(results_by_criterion)}")
    print(f"{'='*60}\n")
    
    if not results_by_criterion:
        raise RuntimeError(
            "No results found for any criterion.\n\n"
            "Possible causes:\n"
            "1. Vertex AI not properly configured\n"
            "2. GOOGLE_CLOUD_PROJECT not set\n"
            "3. Service account credentials missing\n"
            "4. Vertex AI API not enabled\n"
            "5. Check Streamlit logs for detailed error messages"
        )
    
    return results_by_criterion
