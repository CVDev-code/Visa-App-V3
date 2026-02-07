"""
AI-Powered Research Assistant - Using Gemini's Google Search Grounding
FIXED VERSION - Uses new google.genai library and fixes NameError
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


def _search_with_gemini(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    target_count: int,
) -> List[Dict]:
    """
    Use Gemini's Google Search grounding to find sources.
    """
    
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise RuntimeError(
            "Google GenAI library not installed.\n"
            "Install with: pip install google-genai"
        )
    
    # Get API key
    api_key = _get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not found.\n"
            "Get one at: https://aistudio.google.com/app/apikey\n"
            "Add to Streamlit secrets or environment variables."
        )
    
    # Configure client
    client = genai.Client(api_key=api_key)
    
    # Build search prompt
    search_prompt = _build_search_prompt(criterion_id, criterion_desc, artist_name, target_count)
    
    print(f"\n{'='*60}")
    print(f"[Gemini Search] Criterion {criterion_id}: {criterion_desc[:50]}...")
    print(f"{'='*60}")
    
    try:
        print("[Gemini Search] Searching with Google Search grounding...")
        
        # Generate content with Google Search grounding
        response = client.models.generate_content(
            model='gemini-1.5-pro',  # Stable model with grounding support
            contents=search_prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                response_modalities=['TEXT'],
            )
        )
        
        # Extract text
        text = response.text
        
        print(f"[Gemini Search] Response length: {len(text)} chars")
        
        # Extract URLs from response
        results = _extract_search_results(text, criterion_desc, response)
        
        print(f"[Gemini Search] Found {len(results)} results")
        
        return results
        
    except Exception as e:
        print(f"[Gemini Search] Error: {e}")
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
    Build criterion-specific search prompts for Gemini.
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
    
    # Add Gemini-specific instructions
    gemini_instructions = f"""

IMPORTANT FORMATTING INSTRUCTIONS:
For each source you find, provide:
1. Full article title
2. Complete URL (starting with https://)
3. Publication name
4. Brief excerpt or reason it's relevant

Format each result like this:
---
TITLE: [Article Title]
URL: https://complete-url.com
SOURCE: [Publication Name]
EXCERPT: [Key quote or why it's relevant]
---

Find exactly {target_count} high-quality sources that meet USCIS O-1 standards."""
    
    return base_prompt + gemini_instructions


def _get_default_prompt(criterion_id: str, criterion_desc: str, artist_name: str, target_count: int) -> str:
    """Default search prompts if search_prompts.py not available."""
    
    prompts = {
        "1": f"""Search Google for evidence that {artist_name} has won significant national or international awards or prizes.

USCIS O-1 Requirements:
- Named, prestigious awards (Grammy, Pulitzer, MacArthur, major international competitions)
- Official announcements from award organizations
- Coverage in major publications (New York Times, Guardian, etc.)
- NOT nominations or local awards

Find {target_count} sources showing award wins.""",

        "3": f"""Search Google for critical reviews and feature articles about {artist_name}.

USCIS O-1 Requirements:
- Reviews from prestigious publications (NYT, Guardian, Gramophone, BBC, NPR)
- Feature articles demonstrating distinguished reputation
- Critical analysis, not just event listings

Search for:
- Concert/performance reviews
- Album/recording reviews
- Feature articles and profiles
- Critical essays

Find {target_count} reviews from major publications.""",

        "2_past": f"""Search Google for evidence of {artist_name}'s PAST lead or starring roles in productions/events with distinguished reputation.

Look for:
- Past performances at major venues (Carnegie Hall, Royal Opera House, etc.)
- Lead roles in distinguished productions
- Starring engagements with prestigious organizations

Find {target_count} sources about past performances.""",

        "2_future": f"""Search Google for {artist_name}'s UPCOMING (2025-2026) lead or starring roles.

Look for:
- Announced performances at major venues
- Future engagements with prestigious organizations
- Upcoming tours or productions

Find {target_count} sources about future performances.""",

        "4_past": f"""Search Google for {artist_name}'s PAST lead, starring, or critical roles for distinguished organizations.

Look for:
- Past engagements with major orchestras, opera companies, festivals
- Critical roles with prestigious organizations

Find {target_count} sources.""",

        "4_future": f"""Search Google for {artist_name}'s FUTURE engagements with distinguished organizations.

Look for:
- Announced engagements with major organizations
- Future performances with prestigious ensembles

Find {target_count} sources.""",

        "5": f"""Search Google for evidence of {artist_name}'s major commercial or critically acclaimed successes.

Look for:
- Sold-out performances
- Chart success or sales records
- Critical acclaim
- Box office success

Find {target_count} sources.""",

        "6": f"""Search Google for evidence of {artist_name} receiving significant recognition from organizations, critics, or experts.

Look for:
- Critical praise from recognized experts
- Recognition from industry organizations
- Expert testimonials

Find {target_count} sources.""",

        "7": f"""Search Google for information about {artist_name}'s salary/remuneration and industry wage data.

CRITICAL: Need both artist salary AND industry comparison data.

Search for:
1. Artist's salary/fees (if available)
2. Bureau of Labor Statistics data:
   - "onetcenter.org musicians wages"
   - "bls.gov occupational employment musicians"
3. Union scales for comparison

Find {target_count} sources including BLS data.""",
    }
    
    return prompts.get(criterion_id, f"Search for {target_count} sources about {artist_name} related to: {criterion_desc}")


def _extract_search_results(text: str, criterion_desc: str, response=None) -> List[Dict]:
    """
    Extract URLs and metadata from Gemini's response.
    """
    
    results = []
    
    # Try structured format first (---\nTITLE: ...\nURL: ...\n---)
    structured_pattern = r'---\s*TITLE:\s*(.+?)\s*URL:\s*(https?://[^\s]+)\s*SOURCE:\s*(.+?)\s*EXCERPT:\s*(.+?)\s*---'
    structured_matches = re.findall(structured_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if structured_matches:
        print(f"[Extract] Found {len(structured_matches)} structured results")
        for title, url, source, excerpt in structured_matches:
            results.append({
                "url": url.strip(),
                "title": title.strip(),
                "source": source.strip(),
                "relevance": f"Google Search for {criterion_desc[:50]}...",
                "excerpt": excerpt.strip()[:300]
            })
    
    # Fallback: Extract any URLs mentioned
    if not results:
        print("[Extract] No structured format, trying URL extraction...")
        
        # Find all URLs
        url_pattern = r'https?://[^\s\)\]<>"]+'
        urls = re.findall(url_pattern, text)
        
        print(f"[Extract] Found {len(urls)} URLs in text")
        
        # For each URL, try to find context
        for url in urls[:20]:  # Limit to 20 URLs
            # Look for title near URL (within 200 chars before)
            title_context = ""
            url_index = text.find(url)
            if url_index > 0:
                context_start = max(0, url_index - 200)
                context = text[context_start:url_index]
                
                # Try to extract title from context
                title_match = re.search(r'["""]([^"""]+)["""]', context)
                if title_match:
                    title_context = title_match.group(1)
                else:
                    # Look for the last sentence before URL
                    sentences = re.split(r'[.!?]\s+', context)
                    if sentences:
                        title_context = sentences[-1].strip()
            
            results.append({
                "url": url.strip(),
                "title": title_context[:100] if title_context else _extract_source_from_url(url),
                "source": _extract_source_from_url(url),
                "relevance": f"Found via Google Search for {criterion_desc[:50]}...",
                "excerpt": "Source found via Gemini's Google Search grounding"
            })
    
    # Try to extract grounding metadata if available
    if response and hasattr(response, 'candidates'):
        try:
            for candidate in response.candidates:
                if hasattr(candidate, 'grounding_metadata'):
                    metadata = candidate.grounding_metadata
                    if hasattr(metadata, 'grounding_chunks'):
                        print(f"[Extract] Found {len(metadata.grounding_chunks)} grounding chunks")
                        for chunk in metadata.grounding_chunks:
                            if hasattr(chunk, 'web') and hasattr(chunk.web, 'uri'):
                                # Check if we already have this URL
                                if not any(r['url'] == chunk.web.uri for r in results):
                                    results.append({
                                        "url": chunk.web.uri,
                                        "title": getattr(chunk.web, 'title', _extract_source_from_url(chunk.web.uri)),
                                        "source": _extract_source_from_url(chunk.web.uri),
                                        "relevance": f"Grounding source for {criterion_desc[:50]}...",
                                        "excerpt": "Source from Gemini's grounding metadata"
                                    })
        except Exception as e:
            print(f"[Extract] Error extracting grounding metadata: {e}")
    
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
    Research using Gemini's Google Search grounding.
    
    Setup:
    - Get API key: https://aistudio.google.com/app/apikey
    - Add to secrets: GEMINI_API_KEY = "your-key-here"
    - Install library: pip install google-genai
    
    Cost: ~$0.40/app (cheaper than OpenAI)
    Quality: Google Search level (excellent)
    """
    
    print(f"\n{'='*60}")
    print("GEMINI GOOGLE SEARCH - AI RESEARCH")
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
            
            # Search with Gemini
            results = _search_with_gemini(
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
            "1. GEMINI_API_KEY not set or invalid\n"
            "   Get one at: https://aistudio.google.com/app/apikey\n"
            "2. Artist name may be misspelled or have limited online presence\n"
            "3. Try searching manually in Google first to verify sources exist\n"
            "4. Check Streamlit logs for detailed error messages"
        )
    
    return results_by_criterion
