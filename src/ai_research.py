"""
AI-Powered Research Assistant - Using Gemini (Free Tier - WORKING)
Uses the stable google-generativeai library that works with free API keys.
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
    Use Gemini to suggest sources (works with free API key).
    """
    
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError(
            "Google Generative AI library not installed.\n"
            "Install with: pip install google-generativeai"
        )
    
    # Get API key
    api_key = _get_secret("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not found.\n"
            "Get one at: https://aistudio.google.com/app/apikey\n"
            "Add to Streamlit secrets or environment variables."
        )
    
    # Configure Gemini
    genai.configure(api_key=api_key)
    
    # Build search prompt
    search_prompt = _build_search_prompt(criterion_id, criterion_desc, artist_name, target_count)
    
    print(f"\n{'='*60}")
    print(f"[Gemini] Criterion {criterion_id}: {criterion_desc[:50]}...")
    print(f"{'='*60}")
    
    try:
        print("[Gemini] Generating source suggestions...")
        
        # Use free tier model
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        response = model.generate_content(search_prompt)
        
        # Extract text
        text = response.text
        
        print(f"[Gemini] Response length: {len(text)} chars")
        
        # Extract URLs from response
        results = _extract_search_results(text, criterion_desc)
        
        print(f"[Gemini] Found {len(results)} results")
        
        return results
        
    except Exception as e:
        print(f"[Gemini] Error: {e}")
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

CRITICAL INSTRUCTIONS:
Based on your knowledge of {artist_name}, suggest {target_count} likely sources where evidence for this criterion would be found.

For each source, provide:
1. A likely article title or description
2. A realistic URL where such content would be published
3. The publication name
4. Why this source would be relevant

FORMAT EXACTLY LIKE THIS (use this exact structure):
---
TITLE: Grammy Award Winner {artist_name} Announced
URL: https://www.grammy.com/news/{artist_name.lower().replace(' ', '-')}-wins-award
SOURCE: Grammy.com
EXCERPT: {artist_name} received the Grammy Award for Best Performance
---

TITLE: {artist_name} Review - New York Times
URL: https://www.nytimes.com/music/reviews/{artist_name.lower().replace(' ', '-')}-concert-review
SOURCE: New York Times
EXCERPT: Critic praises {artist_name}'s virtuoso performance
---

YOU MUST:
- Provide EXACTLY {target_count} sources in this format
- Use realistic publication names (NYT, Guardian, Gramophone, NPR, BBC, etc.)
- Create plausible URLs based on how that publication structures URLs
- Make titles and excerpts relevant to the criterion
- Use the --- separators between each source

DO NOT:
- Make up fake sources that wouldn't exist
- Use URLs from suspicious or unreliable sources
- Provide fewer than {target_count} sources
- Break the formatting structure"""
    
    return base_prompt + gemini_instructions


def _get_default_prompt(criterion_id: str, criterion_desc: str, artist_name: str, target_count: int) -> str:
    """Default search prompts."""
    
    prompts = {
        "1": f"""Based on your knowledge, suggest {target_count} likely sources showing awards won by {artist_name}.

Focus on:
- Major music awards (Grammy, classical competitions, international prizes)
- Official award announcements
- Major publication coverage of awards""",

        "3": f"""Based on your knowledge, suggest {target_count} likely reviews of {artist_name}.

Focus on:
- Major publications (NYT, Guardian, Gramophone, BBC, NPR)
- Concert/performance reviews
- Album/recording reviews
- Feature articles""",

        "2_past": f"""Based on your knowledge, suggest {target_count} likely sources about {artist_name}'s past performances.

Focus on:
- Major venues (Carnegie Hall, Royal Opera House, etc.)
- Lead roles
- Distinguished productions""",

        "2_future": f"""Based on your knowledge, suggest {target_count} likely sources about {artist_name}'s upcoming (2025-2026) performances.

Focus on:
- Announced performances at major venues
- Future tours
- Scheduled engagements""",

        "4_past": f"""Based on your knowledge, suggest {target_count} likely sources about {artist_name}'s past roles with distinguished organizations.

Focus on:
- Major orchestras, opera companies, festivals
- Critical roles with prestigious organizations""",

        "4_future": f"""Based on your knowledge, suggest {target_count} likely sources about {artist_name}'s future engagements with distinguished organizations.

Focus on:
- Announced engagements
- Future performances with prestigious ensembles""",

        "5": f"""Based on your knowledge, suggest {target_count} likely sources about {artist_name}'s commercial or critical successes.

Focus on:
- Sold-out performances
- Chart success or sales records
- Critical acclaim""",

        "6": f"""Based on your knowledge, suggest {target_count} likely sources about recognition {artist_name} has received.

Focus on:
- Critical praise from experts
- Recognition from industry organizations
- Expert testimonials""",

        "7": f"""Based on your knowledge, suggest {target_count} likely sources about {artist_name}'s salary and industry wage data.

Focus on:
- BLS data (onetcenter.org, bls.gov)
- Union scales
- Industry salary surveys""",
    }
    
    return prompts.get(criterion_id, f"Suggest {target_count} sources about {artist_name} for: {criterion_desc}")


def _extract_search_results(text: str, criterion_desc: str) -> List[Dict]:
    """
    Extract URLs and metadata from Gemini's response.
    """
    
    results = []
    
    # Try structured format (---\nTITLE: ...\nURL: ...\n---)
    structured_pattern = r'---\s*TITLE:\s*(.+?)\s*URL:\s*(https?://[^\s]+)\s*SOURCE:\s*(.+?)\s*EXCERPT:\s*(.+?)\s*---'
    structured_matches = re.findall(structured_pattern, text, re.DOTALL | re.IGNORECASE)
    
    if structured_matches:
        print(f"[Extract] Found {len(structured_matches)} structured results")
        for title, url, source, excerpt in structured_matches:
            results.append({
                "url": url.strip(),
                "title": title.strip(),
                "source": source.strip(),
                "relevance": f"Suggested source for {criterion_desc[:50]}...",
                "excerpt": excerpt.strip()[:300]
            })
    
    # Fallback: Extract any URLs
    if not results:
        print("[Extract] No structured format, trying URL extraction...")
        
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
                "relevance": f"Suggested source for {criterion_desc[:50]}...",
                "excerpt": "Source suggested by Gemini"
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
    Research using Gemini (free tier compatible).
    
    Setup:
    - Get API key: https://aistudio.google.com/app/apikey
    - Add to secrets: GEMINI_API_KEY = "your-key-here"
    - Install library: pip install google-generativeai
    
    Note: Uses Gemini's knowledge to suggest likely sources.
    Not real-time search, but works with free API keys.
    """
    
    print(f"\n{'='*60}")
    print("GEMINI AI RESEARCH (Free Tier)")
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
            "2. Artist name may have limited information in Gemini's knowledge\n"
            "3. Check Streamlit logs for detailed error messages"
        )
    
    return results_by_criterion
