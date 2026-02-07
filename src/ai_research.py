"""
AI-Powered Research Assistant using Brave Search API.
NO AI filtering - returns all search results for manual review.
"""

import os
from typing import Dict, List, Optional
from urllib.parse import urlparse


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
    Search using Brave Search API - returns search results.
    
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
        import traceback
        traceback.print_exc()
        return []


def _extract_source_from_url(url: str) -> str:
    """Extract publication name from URL"""
    try:
        domain = urlparse(url).netloc
        # Remove www. and common TLDs
        domain = domain.replace("www.", "")
        parts = domain.split(".")
        if len(parts) > 1:
            # Capitalize first part (e.g., "nytimes" -> "Nytimes")
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
) -> Dict[str, List[Dict]]:
    """
    Search for evidence using Brave Search.
    
    NO AI FILTERING - returns all search results for manual review.
    
    Process:
    1. For each criterion, generate targeted search query
    2. Search with Brave
    3. Return ALL results (user filters manually in UI)
    
    Returns:
        {
            "1": [
                {
                    "url": "https://...",
                    "title": "...",
                    "source": "Publication Name",
                    "relevance": "Search result for criterion X",
                    "excerpt": "Description snippet from search"
                }
            ],
            "3": [...]
        }
    """
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
                user_feedback = feedback.get("user_feedback", "")
                if user_feedback:
                    search_query += f" {user_feedback}"
            
            print(f"[Criterion {cid}] Searching: {search_query}")
            
            # Search with Brave
            search_results = _search_with_brave(search_query, max_results=20)
            
            if not search_results:
                print(f"[Criterion {cid}] No results from Brave")
                continue
            
            print(f"[Criterion {cid}] Got {len(search_results)} results from Brave")
            
            # Convert to expected format (NO FILTERING - return everything)
            formatted_results = []
            for r in search_results:
                formatted_results.append({
                    "url": r.get("url", ""),
                    "title": r.get("title", ""),
                    "source": _extract_source_from_url(r.get("url", "")),
                    "relevance": f"Search result for {criterion_desc[:50]}...",
                    "excerpt": r.get("description", "")[:300]  # Limit excerpt length
                })
            
            results_by_criterion[cid] = formatted_results
            print(f"[Criterion {cid}] Returning {len(formatted_results)} results for manual review")
        
        except Exception as e:
            print(f"[Criterion {cid}] Error: {str(e)}")
            import traceback
            traceback.print_exc()
            continue
    
    if not results_by_criterion:
        raise RuntimeError(
            "No results found for any criterion. Possible causes:\n"
            "1. Brave Search API key is invalid or expired\n"
            "2. Artist name spelling may be incorrect\n"
            "3. Artist may have very limited online presence\n"
            "Check Streamlit logs for detailed error messages"
        )
    
    return results_by_criterion


def _generate_query_for_criterion(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    name_variants: List[str]
) -> str:
    """
    Generate search query for the criterion.
    
    Queries are broad to find all relevant content.
    User will filter manually in the UI.
    """
    
    # Use primary name or first variant
    search_name = artist_name or (name_variants[0] if name_variants else "")
    
    if not search_name:
        return ""
    
    # BROAD QUERIES - Find everything, let user filter
    
    if criterion_id == "1":
        # Criterion 1: Awards and Prizes
        return f'"{search_name}" award OR prize OR competition OR winner'
    
    elif criterion_id == "3":
        # Criterion 3: Reviews
        return f'"{search_name}" review OR performance OR concert'
    
    elif criterion_id == "2_past":
        # Criterion 2 Past: Past performances
        return f'"{search_name}" performed OR performance OR role'
    
    elif criterion_id == "2_future":
        # Criterion 2 Future: Future performances
        return f'"{search_name}" upcoming OR "will perform" OR announced 2025 OR 2026'
    
    elif criterion_id == "4_past":
        # Criterion 4 Past
        return f'"{search_name}" performed OR appeared OR engagement'
    
    elif criterion_id == "4_future":
        # Criterion 4 Future
        return f'"{search_name}" upcoming OR future OR "will perform"'
    
    elif criterion_id == "5":
        # Criterion 5: Success
        return f'"{search_name}" success OR acclaimed OR "sold out"'
    
    elif criterion_id == "6":
        # Criterion 6: Recognition
        return f'"{search_name}" recognized OR praised OR acclaimed'
    
    elif criterion_id == "7":
        # Criterion 7: Salary
        return f'"{search_name}" contract OR fee OR engagement'
    
    else:
        # Generic fallback
        return f'"{search_name}" performance OR concert'
