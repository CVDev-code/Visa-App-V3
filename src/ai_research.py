"""
AI-Powered Research Assistant using Brave Search API for high-quality web search.
Brave provides: comprehensive results, clean data, no tracking.
"""

import json
import os
from typing import Dict, List, Optional

from openai import OpenAI


def _get_secret(name: str):
    """Works on Streamlit Cloud (st.secrets) and locally (.env / env vars)."""
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


def _search_with_brave(query: str, max_results: int = 10) -> List[Dict]:
    """
    Search using Brave Search API - returns high-quality sources with snippets.
    
    Returns:
        [
            {
                "url": "https://...",
                "title": "Article title",
                "description": "Snippet/description",
                "age": "Published date (if available)"
            }
        ]
    """
    import requests
    
    api_key = _get_secret("BRAVE_API_KEY")
    if not api_key:
        raise RuntimeError("BRAVE_API_KEY not set. Get free key at https://brave.com/search/api/")
    
    try:
        # Brave Search API endpoint
        url = "https://api.search.brave.com/res/v1/web/search"
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key
        }
        
        params = {
            "q": query,
            "count": min(max_results, 20),  # Brave allows up to 20
            "search_lang": "en",
            "country": "us",
            "safesearch": "off",
            "freshness": "all",
            "text_decorations": False,
            "spellcheck": True
        }
        
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        # Extract web results
        web_results = data.get("web", {}).get("results", [])
        
        results = []
        for item in web_results[:max_results]:
            if not item or not isinstance(item, dict):
                continue
            
            results.append({
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "description": item.get("description", ""),
                "age": item.get("age", ""),
                "page_age": item.get("page_age", ""),
                "language": item.get("language", ""),
                "family_friendly": item.get("family_friendly", True)
            })
        
        return results
        
    except Exception as e:
        print(f"[_search_with_brave] Error: {e}")
        return []


# System prompt for analyzing search results
ANALYSIS_SYSTEM_PROMPT = """You are an expert immigration paralegal for O-1 visa petitions.

Analyze search results and determine which URLs are most relevant for the specified criterion.

For each relevant URL, extract:
- Why it supports the criterion
- A brief excerpt from the description that shows the evidence

Return ONLY valid JSON."""


ANALYSIS_PROMPT_TEMPLATE = """Analyze these search results for O-1 Criterion {criterion_id}.

Criterion: {criterion_description}

Artist: {artist_name}
Variants: {name_variants}

Search Results:
{search_results}

CRITICAL O-1 VISA REQUIREMENTS:
You must identify sources that will satisfy USCIS adjudicators under 8 CFR 214.4.

For Criterion 3 (Reviews):
- PRIORITIZE: Notable trade press (Gramophone, Opera News, Musical America, Bachtrack, Seen and Heard International)
- PRIORITIZE: Major reputable news (New York Times, Guardian, Financial Times, Washington Post)
- The review must describe the artist in a PRESTIGIOUS or LEAD role (principal, soloist, leading role)
- OR the review must be about a performance at a DISTINGUISHED venue (Met Opera, Royal Opera, Berlin Phil, major festivals)
- REJECT: Local papers, blogs, amateur reviews, minor venues

For Criteria 2 & 4 (Distinguished Performances/Organizations):
- Must document performances at venues known to be internationally distinguished
- Must show the artist had a lead/critical/prominent role
- Examples of distinguished: Metropolitan Opera, Royal Opera House, Berlin Philharmonic, Vienna State Opera, Salzburg Festival, Glyndebourne
- REJECT: Community theaters, student performances, small local venues

For Criterion 1 (Awards):
- Must be from the OFFICIAL award-granting body (not news about awards)
- Must be nationally or internationally recognized competitions/awards

For each result, determine:
1. Is the source credible and prestigious enough for O-1 purposes?
2. Does it clearly mention the artist by name (check the description)?
3. Does it show the artist in a lead/prominent role OR at a distinguished venue?
4. What SPECIFIC evidence does it provide that USCIS would find compelling?

Return JSON:
{{
  "relevant_sources": [
    {{
      "url": "https://...",
      "title": "...",
      "source": "Publication name (e.g., 'The Guardian', 'Gramophone')",
      "relevance": "Explain WHY this satisfies the O-1 criterion - be specific about role/venue/recognition",
      "excerpt": "Quote from the description that shows the artist's prominence or venue's prestige"
    }}
  ]
}}

IMPORTANT: Only include sources that would genuinely satisfy USCIS under 8 CFR 214.4. Quality over quantity.
If a source is from a minor publication or doesn't show distinguished achievement, EXCLUDE it."""


def ai_search_for_evidence(
    artist_name: str,
    name_variants: List[str],
    selected_criteria: List[str],
    criteria_descriptions: Dict[str, str],
    feedback: Optional[Dict] = None,
) -> Dict[str, List[Dict]]:
    """
    Search for evidence using Brave Search + OpenAI analysis.
    
    Process:
    1. For each criterion, generate targeted search query
    2. Search with Brave (gets high-quality results)
    3. Use OpenAI to analyze and rank results
    4. Return best sources with relevance explanations
    """
    openai_key = _get_secret("OPENAI_API_KEY")
    if not openai_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    
    model = _get_secret("OPENAI_MODEL") or "gpt-4o-mini"
    client = OpenAI(api_key=openai_key)
    
    results_by_criterion = {}
    
    for cid in selected_criteria:
        try:
            criterion_desc = criteria_descriptions.get(cid, "")
            if not criterion_desc:
                print(f"[Criterion {cid}] No description found, skipping")
                continue
            
            # Generate search query for this criterion
            search_query = _generate_query_for_criterion(
                cid, criterion_desc, artist_name, name_variants
            )
            
            if not search_query:
                print(f"[Criterion {cid}] Could not generate query, skipping")
                continue
            
            # Apply feedback if regenerating
            if feedback:
                rejected = feedback.get("rejected_urls", [])
                user_feedback = feedback.get("user_feedback", "")
                if user_feedback:
                    search_query += f" {user_feedback}"
            
            print(f"[Criterion {cid}] Searching: {search_query}")
            
            # Search with Brave - get MORE results (15-20)
            search_results = _search_with_brave(search_query, max_results=20)
            
            if not search_results:
                print(f"[Criterion {cid}] No results from Brave")
                continue
            
            # Use OpenAI to analyze which results are most relevant
            search_results_text = "\n\n".join([
                f"URL: {r.get('url', 'N/A')}\nTitle: {r.get('title', 'N/A')}\nDescription: {r.get('description', 'N/A')}\nAge: {r.get('age', 'N/A')}"
                for r in search_results
                if r and isinstance(r, dict)
            ])
            
            if not search_results_text:
                print(f"[Criterion {cid}] Could not format search results")
                continue
            
            prompt = ANALYSIS_PROMPT_TEMPLATE.format(
                criterion_id=cid,
                criterion_description=criterion_desc,
                artist_name=artist_name,
                name_variants=", ".join(name_variants) if name_variants else "None",
                search_results=search_results_text
            )
            
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            raw = resp.choices[0].message.content
            if not raw:
                print(f"[Criterion {cid}] No content in OpenAI response")
                continue
                
            data = json.loads(raw)
            
            relevant = data.get("relevant_sources", [])
            if not relevant or not isinstance(relevant, list):
                print(f"[Criterion {cid}] No relevant sources found")
                continue
            
            results_by_criterion[cid] = relevant[:10]  # Top 10
            print(f"[Criterion {cid}] Found {len(relevant)} relevant sources")
        
        except Exception as e:
            print(f"[Criterion {cid}] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            continue
    
    if not results_by_criterion:
        raise RuntimeError("No results found for any criterion. Check that artist name is correct and has online presence.")
    
    return results_by_criterion


def _generate_query_for_criterion(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    name_variants: List[str]
) -> str:
    """
    Generate an optimized search query for the criterion.
    
    Uses detailed O-1 visa specific search strategies based on 8 CFR 214.4 requirements.
    """
    
    # Use primary name or first variant
    search_name = artist_name or (name_variants[0] if name_variants else "")
    
    if not search_name:
        return ""
    
    # O-1 VISA SPECIFIC CRITERION SEARCHES
    
    if criterion_id == "1":
        # Criterion 1: Awards and Prizes
        # Search for official announcements from award-granting bodies
        return f'"{search_name}" award winner OR prize recipient OR competition winner OR laureate announcement'
    
    elif criterion_id == "3":
        # Criterion 3: National/International Recognition via Critical Reviews
        # PRIORITY: Trade press + major news outlets covering internationally recognized performances
        return f'"{search_name}" review OR critique performance lead role OR principal OR soloist distinguished venue OR prestigious production'
    
    elif criterion_id == "2_past":
        # Criterion 2 Past: Lead/Starring role in PAST productions with distinguished reputation
        return f'"{search_name}" performed lead role OR principal OR soloist Metropolitan Opera OR Royal Opera OR Berlin Philharmonic OR Vienna State Opera'
    
    elif criterion_id == "2_future":
        # Criterion 2 Future: Lead/Starring role in FUTURE productions with distinguished reputation
        return f'"{search_name}" upcoming OR will perform OR announced lead role OR principal OR soloist 2025 OR 2026'
    
    elif criterion_id == "4_past":
        # Criterion 4 Past: Lead/critical role for PAST distinguished organizations
        return f'"{search_name}" performed with OR appeared at distinguished organization OR prestigious ensemble'
    
    elif criterion_id == "4_future":
        # Criterion 4 Future: Lead/critical role for FUTURE distinguished organizations
        return f'"{search_name}" will perform OR upcoming engagement OR announced season distinguished venue OR prestigious company'
    
    elif criterion_id == "5":
        # Criterion 5: Record of commercial or critically acclaimed successes
        return f'"{search_name}" sold out OR box office success OR critically acclaimed OR bestselling recording'
    
    elif criterion_id == "6":
        # Criterion 6: Recognition from organizations, critics, and experts
        return f'"{search_name}" praised by OR recognized by OR acclaimed by critic OR expert OR organization'
    
    elif criterion_id == "7":
        # Criterion 7: High salary or substantial remuneration
        return f'"{search_name}" contract OR engagement fee OR appearance major venue OR international tour'
    
    else:
        # Generic fallback
        return f'"{search_name}" opera OR performance OR concert review'
