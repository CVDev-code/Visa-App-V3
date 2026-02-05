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
            include_raw_content=True,  # Get full article text
            include_domains=[
                # Prestigious publications for reviews
                "nytimes.com", "theguardian.com", "ft.com", 
                "gramophone.co.uk", "operanews.com", "musicalamerica.com",
                "bachtrack.com", "seen-and-heard-international.com",
                # Major venues/opera houses
                "metopera.org", "roh.org.uk", "wiener-staatsoper.at",
                "operadeparis.fr", "berliner-philharmoniker.de",
                # Performance databases
                "operabase.com", "operawire.com"
            ],
            exclude_domains=[
                # Exclude low-quality sources
                "wikipedia.org", "facebook.com", "twitter.com", 
                "instagram.com", "youtube.com"
            ]
        )
        
        results = []
        for item in response.get("results", []):
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

For each result, determine:
1. Is it relevant to this criterion?
2. Does it mention the artist?
3. Is it from a credible/prestigious source?
4. What specific evidence does it provide?

Return JSON:
{{
  "relevant_sources": [
    {{
      "url": "https://...",
      "title": "...",
      "source": "Publication name",
      "relevance": "Why this supports the criterion",
      "excerpt": "Brief quote showing evidence"
    }}
  ]
}}

Only include sources that are:
- Clearly relevant to the criterion
- From prestigious/credible sources
- Actually mention the artist (or their performances/work)"""


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
        criterion_desc = criteria_descriptions.get(cid, "")
        
        # Generate search query for this criterion
        search_query = _generate_query_for_criterion(
            cid, criterion_desc, artist_name, name_variants
        )
        
        # Apply feedback if regenerating
        if feedback:
            rejected = feedback.get("rejected_urls", [])
            user_feedback = feedback.get("user_feedback", "")
            if user_feedback:
                search_query += f" {user_feedback}"
        
        print(f"[Criterion {cid}] Searching: {search_query}")
        
        # Search with Tavily
        search_results = _search_with_tavily(search_query, max_results=8)
        
        if not search_results:
            print(f"[Criterion {cid}] No results from Tavily")
            continue
        
        # Use OpenAI to analyze which results are most relevant
        search_results_text = "\n\n".join([
            f"URL: {r['url']}\nTitle: {r['title']}\nContent Preview: {r['content'][:500]}..."
            for r in search_results
        ])
        
        prompt = ANALYSIS_PROMPT_TEMPLATE.format(
            criterion_id=cid,
            criterion_description=criterion_desc,
            artist_name=artist_name,
            name_variants=", ".join(name_variants) if name_variants else "None",
            search_results=search_results_text
        )
        
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
            
            relevant = data.get("relevant_sources", [])
            if relevant:
                # Add full content from Tavily results
                for item in relevant:
                    url = item.get("url", "")
                    # Find matching Tavily result to get full content
                    for tavily_result in search_results:
                        if tavily_result["url"] == url:
                            item["full_content"] = tavily_result["content"]
                            break
                
                results_by_criterion[cid] = relevant[:5]  # Top 5
                print(f"[Criterion {cid}] Found {len(relevant)} relevant sources")
        
        except Exception as e:
            print(f"[Criterion {cid}] Analysis error: {e}")
            continue
    
    return results_by_criterion


def _generate_query_for_criterion(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    name_variants: List[str]
) -> str:
    """Generate an optimized search query for the criterion."""
    
    # Use primary name or first variant
    search_name = artist_name or (name_variants[0] if name_variants else "")
    
    # Criterion-specific query templates
    if criterion_id == "1":
        # Awards - search official sources
        return f'"{search_name}" award winner announcement'
    
    elif criterion_id == "3":
        # Reviews - search major publications
        return f'"{search_name}" review opera OR concert site:nytimes.com OR site:theguardian.com OR site:gramophone.co.uk OR site:bachtrack.com'
    
    elif criterion_id in ["2_past", "4_past"]:
        # Past performances at distinguished venues
        return f'"{search_name}" performed at Metropolitan Opera OR Royal Opera OR Berlin Philharmonic OR Vienna State Opera'
    
    elif criterion_id in ["2_future", "4_future"]:
        # Future performances at distinguished venues
        return f'"{search_name}" upcoming performance OR season announcement site:metopera.org OR site:roh.org.uk OR site:operabase.com'
    
    elif criterion_id == "5":
        # Commercial/critical success
        return f'"{search_name}" acclaimed OR success OR bestselling OR award-winning'
    
    elif criterion_id == "6":
        # Recognition from experts
        return f'"{search_name}" praised by OR recognized by OR expert opinion'
    
    elif criterion_id == "7":
        # High salary/compensation
        return f'"{search_name}" contract OR fee OR salary OR compensation'
    
    else:
        # Generic fallback
        return f'"{search_name}" {criterion_desc[:50]}'
