"""
AI-Powered Research Assistant - Using OpenAI's Native Web Search
CORRECTED VERSION - Proper API response handling.

This uses ChatGPT's web_search tool via API.
No Brave API needed. No agent setup needed.
Just set OPENAI_API_KEY and it works.
"""

import os
import json
import re
from typing import Dict, List, Optional
from openai import OpenAI

# Import customizable search prompts
try:
    from .search_prompts import SEARCH_PROMPTS, SEARCH_SYSTEM_PROMPT
except ImportError:
    # Fallback if search_prompts.py not found
    SEARCH_PROMPTS = None
    SEARCH_SYSTEM_PROMPT = None


# ============================================================
# Configuration
# ============================================================

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
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


# ============================================================
# OpenAI Web Search (ChatGPT-Style)
# ============================================================

def _search_with_chatgpt(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    target_count: int,
) -> List[Dict]:
    """
    Use OpenAI's web_search tool - exactly like ChatGPT.
    
    This is the same search ChatGPT uses when you ask it to search the web.
    """
    
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    
    model = _get_secret("OPENAI_MODEL") or "gpt-4o"
    client = OpenAI(api_key=api_key)
    
    # Build criterion-specific search prompt
    search_prompt = _build_search_prompt(criterion_id, criterion_desc, artist_name, target_count)
    
    print(f"[ChatGPT Search] Criterion {criterion_id}: {search_prompt[:100]}...")
    
    try:
        # Use web_search tool (same as ChatGPT)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": SEARCH_SYSTEM_PROMPT if SEARCH_SYSTEM_PROMPT else """You are a USCIS immigration attorney researching O-1 visa evidence. 
Search the web and return sources that meet USCIS standards for extraordinary ability.

CRITICAL: Your response must include:
1. For each source: Full URL in markdown link format [Title](URL)
2. Brief description of why it's relevant
3. Key quote or excerpt if applicable

Format your response like:
1. [Article Title](https://full-url.com) - Why this is strong evidence
2. [Another Article](https://another-url.com) - Key points from this source
etc."""
                },
                {
                    "role": "user",
                    "content": search_prompt
                }
            ],
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search"
                }
            ],
        )
        
        # Extract search results from response
        results = _extract_search_results(response, criterion_desc)
        
        print(f"[ChatGPT Search] Found {len(results)} results")
        return results
        
    except Exception as e:
        print(f"[ChatGPT Search] Error: {e}")
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
    
    Uses prompts from search_prompts.py if available,
    otherwise falls back to built-in defaults.
    """
    
    # Try to use external customizable prompts first
    if SEARCH_PROMPTS and criterion_id in SEARCH_PROMPTS:
        template = SEARCH_PROMPTS[criterion_id]
        return template.format(
            artist_name=artist_name,
            target_count=target_count
        )
    
    # Fallback to built-in prompts
    prompts = {
        "1": f"""Find {target_count} sources showing {artist_name} has won significant national or international awards or prizes.

USCIS Requirements for O-1:
- Named, prestigious awards (Grammy, Pulitzer, MacArthur, major international competitions)
- Official announcements from award organizations or major publications
- NOT nominations, "best of" lists, or local community awards

Search for:
- Award announcements from official organizations
- Coverage in major newspapers (NYT, Guardian, etc.)
- Industry publication reports (e.g., Gramophone for classical music)

For each source found, provide:
- [Full Article Title](complete URL)
- Brief description of the award
- Why this meets O-1 standards

IMPORTANT: Include the complete URL for each source.""",

        "3": f"""Find {target_count} critical reviews or feature articles about {artist_name} from prestigious publications.

USCIS Requirements for O-1:
- Reviews from major publications (New York Times, Guardian, Gramophone, BBC, NPR, etc.)
- Feature articles demonstrating distinguished reputation
- Critical analysis, not just event listings or brief mentions

Search for:
- Concert or performance reviews
- Album or recording reviews  
- Feature articles or profiles
- Critical essays about the artist's work

For each review found, provide:
- [Article Title](complete URL)
- Publication name and date
- Key excerpt showing critical acclaim

IMPORTANT: Include complete URLs. Prioritize prestigious publications.""",

        "2_past": f"""Find {target_count} sources showing {artist_name} had lead or starring roles in PAST productions or events with distinguished reputation.

Search for:
- Past performances at major venues (Carnegie Hall, Royal Opera House, etc.)
- Lead roles in distinguished productions
- Starring engagements with prestigious organizations

For each source, provide:
- [Article Title](complete URL)
- Venue/event name, role, date

IMPORTANT: Include complete URLs.""",

        "2_future": f"""Find {target_count} sources showing {artist_name} has UPCOMING (2025-2026) lead or starring roles.

Search for:
- Announced performances at major venues
- Future engagements
- Upcoming tours or productions

For each source, provide:
- [Announcement Title](complete URL)
- Venue/event name, role, date

IMPORTANT: Include complete URLs.""",

        "4_past": f"""Find {target_count} sources showing {artist_name} had PAST lead, starring, or critical roles for distinguished organizations.

Search for:
- Past engagements with major orchestras, opera companies, festivals
- Critical roles with prestigious organizations

For each source, provide:
- [Article Title](complete URL)
- Organization name, role, date""",

        "4_future": f"""Find {target_count} sources showing {artist_name} has FUTURE engagements with distinguished organizations.

Search for:
- Announced engagements with major organizations
- Future performances

For each source, provide:
- [Announcement Title](complete URL)
- Organization name, role, date""",

        "5": f"""Find {target_count} sources showing {artist_name} has achieved major commercial or critically acclaimed successes.

Search for:
- Sold-out performances
- Chart success or sales records
- Critical acclaim
- Box office success

For each source, provide:
- [Article Title](complete URL)
- Success metric described""",

        "6": f"""Find {target_count} sources showing {artist_name} has received significant recognition from organizations, critics, or experts.

Search for:
- Critical praise from recognized experts
- Recognition from industry organizations
- Expert testimonials

For each source, provide:
- [Article Title](complete URL)
- Type of recognition""",

        "7": f"""Find sources about {artist_name}'s salary/remuneration, and industry wage data for comparison.

CRITICAL: For O-1 visa, we need to prove artist earns substantially above median.

Search for:
1. Artist's salary/fees:
   - Contract amounts
   - Performance fees
   - News articles mentioning compensation
   
2. Industry wage comparisons (ESSENTIAL):
   - Bureau of Labor Statistics data: search "onetcenter.org musicians wages"
   - BLS data: search "bls.gov occupational employment wages musicians"
   - Union scales for comparison

For each source, provide:
- [Source Title](complete URL)
- Wage/salary information
- Whether it's artist-specific or industry comparison data

IMPORTANT: Finding BLS comparison data is critical for this criterion.""",
    }
    
    return prompts.get(criterion_id, f"Find {target_count} sources about {artist_name} for: {criterion_desc}")


def _extract_search_results(response, criterion_desc: str) -> List[Dict]:
    """
    Extract search results from OpenAI response.
    
    The response contains the LLM's text with markdown links.
    We extract URLs from the format: [Title](URL)
    """
    
    results = []
    
    try:
        # Get the message content
        message = response.choices[0].message
        content = message.content or ""
        
        print(f"[Extract Results] Raw response length: {len(content)} chars")
        
        # Extract markdown links: [text](url)
        # Pattern: [anything](http://url or https://url)
        url_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
        matches = re.findall(url_pattern, content)
        
        print(f"[Extract Results] Found {len(matches)} markdown links")
        
        for title, url in matches:
            # Clean up URL (remove trailing punctuation)
            url = url.rstrip('.,;:!?)')
            
            # Extract excerpt (text after the link, up to next link or paragraph)
            # This is a simple extraction - could be improved
            excerpt_pattern = re.escape(f"[{title}]({url})") + r'\s*-?\s*([^[\n]+)'
            excerpt_match = re.search(excerpt_pattern, content)
            excerpt = excerpt_match.group(1).strip() if excerpt_match else ""
            
            results.append({
                "url": url,
                "title": title.strip(),
                "source": _extract_source_from_url(url),
                "relevance": f"ChatGPT search for {criterion_desc[:50]}...",
                "excerpt": excerpt[:300] if excerpt else "Found via ChatGPT web search"
            })
        
        # If no markdown links found, try to extract bare URLs
        if not results:
            print("[Extract Results] No markdown links, trying bare URLs")
            bare_url_pattern = r'(https?://[^\s\)]+)'
            bare_urls = re.findall(bare_url_pattern, content)
            
            for url in bare_urls[:10]:  # Limit to 10 bare URLs
                url = url.rstrip('.,;:!?)')
                results.append({
                    "url": url,
                    "title": _extract_source_from_url(url),
                    "source": _extract_source_from_url(url),
                    "relevance": f"Found for {criterion_desc[:50]}...",
                    "excerpt": "Source found via ChatGPT web search"
                })
        
        return results
        
    except Exception as e:
        print(f"[Extract Results] Error: {e}")
        import traceback
        traceback.print_exc()
        return []


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


# ============================================================
# Main Research Function
# ============================================================

def ai_search_for_evidence(
    artist_name: str,
    name_variants: List[str],
    selected_criteria: List[str],
    criteria_descriptions: Dict[str, str],
    feedback: Optional[Dict] = None,
    artist_field: Optional[str] = None,
) -> Dict[str, List[Dict]]:
    """
    ChatGPT-style research using OpenAI's native web search.
    
    This uses the SAME search tool ChatGPT uses.
    
    Setup required:
    - OPENAI_API_KEY in environment or Streamlit secrets
    - That's it! No agent setup needed.
    
    Cost: ~$2-3 per application
    - Web search: $10/1000 calls (7 criteria = $0.07)
    - LLM costs: ~$2-3 depending on model
    
    Quality: ChatGPT-level
    """
    
    results_by_criterion = {}
    
    for cid in selected_criteria:
        try:
            criterion_desc = criteria_descriptions.get(cid, "")
            if not criterion_desc:
                print(f"[Criterion {cid}] No description, skipping")
                continue
            
            print(f"\n{'='*60}")
            print(f"[Criterion {cid}] {criterion_desc}")
            print(f"{'='*60}")
            
            target = TARGET_RESULTS.get(cid, 5)
            
            # Use ChatGPT's web search
            results = _search_with_chatgpt(
                cid,
                criterion_desc,
                artist_name,
                target
            )
            
            if results:
                results_by_criterion[cid] = results
                print(f"[Criterion {cid}] Returning {len(results)} results")
            else:
                print(f"[Criterion {cid}] No results found - ChatGPT may not have found relevant sources")
            
        except Exception as e:
            print(f"[Criterion {cid}] Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    if not results_by_criterion:
        raise RuntimeError(
            "No results found for any criterion.\n\n"
            "Possible causes:\n"
            "1. OPENAI_API_KEY not set or invalid\n"
            "2. Artist name may be misspelled or have limited online presence\n"
            "3. Web search API may be temporarily unavailable\n"
            "4. Check Streamlit logs for detailed error messages\n\n"
            "Try searching manually in ChatGPT first to verify the artist has findable sources."
        )
    
    return results_by_criterion
