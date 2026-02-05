"""
AI-Powered Research Assistant using Tavily for high-quality web search.
Tavily provides: full article content, English results, prestigious sources.
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


def _search_with_tavily(query: str, max_results: int = 5) -> List[Dict]:
    """
    Search using Tavily API - returns high-quality sources with full content.
    
    Returns:
        [
            {
                "url": "https://...",
                "title": "Article title",
                "content": "Full article text...",
                "score": 0.95
            }
        ]
    """
    try:
        from tavily import TavilyClient
    except ImportError:
        raise RuntimeError("Tavily not installed. Add 'tavily-python' to requirements.txt")
    
    api_key = _get_secret("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set. Get free key at https://tavily.com")
    
    client = TavilyClient(api_key=api_key)
    
    try:
        # Search with Tavily
        response = client.search(
            query=query,
            search_depth="advanced",  # Get more comprehensive results
            max_results=max_results,
            include_raw_content=True  # Get full article text
            # Removed strict domain filters - too restrictive
            # Let Tavily use its own quality ranking
        )
        
        # Check response is valid
        if not response or not isinstance(response, dict):
            print(f"[Tavily] Invalid response: {response}")
            return []
        
        results = []
        raw_results = response.get("results")
        
        # Check results exist and are a list
        if not raw_results or not isinstance(raw_results, list):
            print(f"[Tavily] No results or invalid results format")
            return []
        
        for item in raw_results:
            if not item or not isinstance(item, dict):
                continue
            results.append({
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "content": item.get("raw_content", item.get("content", "")),
                "score": item.get("score", 0.0)
            })
        
        return results
        
    except Exception as e:
        print(f"[_search_with_tavily] Error: {e}")
        return []


# System prompt for analyzing search results
ANALYSIS_SYSTEM_PROMPT = """You are an expert immigration paralegal for O-1 visa petitions.

Analyze search results and determine which URLs are most relevant for the specified criterion.

For each relevant URL, extract:
- Why it supports the criterion
- A brief excerpt (1-2 sentences) that shows the evidence

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
2. Does it clearly mention the artist by name?
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
      "excerpt": "Quote 1-2 sentences that show the artist's prominence or venue's prestige"
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
    Search for evidence using Tavily + OpenAI analysis.
    
    Process:
    1. For each criterion, generate targeted search query
    2. Search with Tavily (gets high-quality results)
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
            
            # Search with Tavily - get MORE results (10-15)
            search_results = _search_with_tavily(search_query, max_results=15)
            
            if not search_results:
                print(f"[Criterion {cid}] No results from Tavily")
                continue
            
            # Use OpenAI to analyze which results are most relevant
            search_results_text = "\n\n".join([
                f"URL: {r.get('url', 'N/A')}\nTitle: {r.get('title', 'N/A')}\nContent Preview: {r.get('content', '')[:500]}..."
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
            
            # Add full content from Tavily results
            for item in relevant:
                if not isinstance(item, dict):
                    continue
                url = item.get("url", "")
                if not url:
                    continue
                # Find matching Tavily result to get full content
                for tavily_result in search_results:
                    if tavily_result and isinstance(tavily_result, dict) and tavily_result.get("url") == url:
                        item["full_content"] = tavily_result.get("content", "")
                        break
            
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
        return f'{search_name} award winner OR prize recipient OR competition winner OR laureate announcement'
    
    elif criterion_id == "3":
        # Criterion 3: National/International Recognition via Critical Reviews
        # PRIORITY: Trade press + major news outlets covering internationally recognized performances
        # Your exact approach: reviews where artist is in prestigious/lead role OR performing at distinguished venues
        return f'{search_name} review OR critique performance lead role OR principal OR soloist distinguished venue OR prestigious production major opera house OR philharmonic OR symphony'
    
    elif criterion_id == "2_past":
        # Criterion 2 Past: Lead/Starring role in PAST productions with distinguished reputation
        # Search for past performances where they had a lead role at distinguished venues
        return f'{search_name} performed lead role OR principal OR soloist OR starring Metropolitan Opera OR Royal Opera OR Berlin Philharmonic OR Vienna State Opera OR Salzburg Festival OR Glyndebourne'
    
    elif criterion_id == "2_future":
        # Criterion 2 Future: Lead/Starring role in FUTURE productions with distinguished reputation
        # Search for announcements of upcoming performances in lead roles
        return f'{search_name} upcoming OR will perform OR announced OR season 2025 OR 2026 lead role OR principal OR soloist Metropolitan Opera OR Royal Opera OR major venue'
    
    elif criterion_id == "4_past":
        # Criterion 4 Past: Lead/critical role for PAST distinguished organizations
        # Search for documented past work with distinguished organizations
        return f'{search_name} performed with OR appeared at distinguished organization OR prestigious ensemble OR major opera company OR symphony orchestra'
    
    elif criterion_id == "4_future":
        # Criterion 4 Future: Lead/critical role for FUTURE distinguished organizations
        # Search for future engagements with distinguished organizations
        return f'{search_name} will perform OR upcoming engagement OR announced season distinguished venue OR prestigious company OR major festival'
    
    elif criterion_id == "5":
        # Criterion 5: Record of commercial or critically acclaimed successes
        # Search for evidence of major success, sold-out performances, recordings
        return f'{search_name} sold out OR box office success OR critically acclaimed OR chart-topping OR bestselling recording OR major success'
    
    elif criterion_id == "6":
        # Criterion 6: Recognition from organizations, critics, and experts
        # Search for praise and recognition from credible sources
        return f'{search_name} praised by OR recognized by OR acclaimed by critic OR expert OR organization award OR honor OR recognition'
    
    elif criterion_id == "7":
        # Criterion 7: High salary or substantial remuneration
        # Search for evidence of high-level contracts and engagements
        return f'{search_name} contract OR engagement fee OR appearance OR residency major venue OR international tour'
    
    else:
        # Generic fallback
        return f'{search_name} opera OR performance OR concert review'
