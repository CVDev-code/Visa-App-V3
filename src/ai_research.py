"""
AI-Powered Research Assistant - ChatGPT-Style Agentic Search
Uses LLM to orchestrate multi-query search, evaluate quality, and filter results.
Budget: ~$0.75-0.95 per application with deep analysis.
"""

import os
import json
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse, parse_qs, urlunparse


# ============================================================
# Configuration
# ============================================================

# Target results per criterion (what user sees)
TARGET_RESULTS = {
    "1": 5,           # Awards: 1-5 high-quality
    "2_past": 5,      # Past performances
    "2_future": 5,    # Future performances
    "3": 10,          # Reviews: most content-rich
    "4_past": 5,      # Past engagements
    "4_future": 5,    # Future engagements
    "5": 10,          # Success (expect duplicates)
    "6": 3,           # Recognition (expect duplicates)
    "7": 3,           # Salary (very specific)
}

# Search depth per criterion (URLs to fetch & analyze)
SEARCH_DEPTH = {
    "1": 100,    # Awards - find every credible one
    "3": 100,    # Reviews - critical for reputation
    "7": 100,    # Salary - rare but crucial
    "2_past": 50,
    "2_future": 50,
    "4_past": 50,
    "4_future": 50,
    "5": 30,     # Success - usually duplicates
    "6": 30,     # Recognition - usually duplicates
}

# Prestigious source exemplars (LLM learns from these)
PRESTIGIOUS_SOURCES = {
    "classical": [
        "Gramophone", "The Strad", "BBC Music Magazine", 
        "Classical Music Magazine", "Opera News"
    ],
    "general_prestige": [
        "New York Times", "Guardian", "Washington Post", 
        "Wall Street Journal", "Financial Times", "The Times",
        "NPR", "BBC", "Reuters", "Associated Press"
    ],
    "music_trade": [
        "Billboard", "Rolling Stone", "Pitchfork", "Variety",
        "Music Week", "NME", "Consequence"
    ],
    "arts_prestige": [
        "The New Yorker", "The Atlantic", "Harper's",
        "Art Forum", "Brooklyn Rail"
    ],
}

# Query templates (hybrid mode - LLM adapts these)
QUERY_TEMPLATES = {
    "1": [
        '"{artist}" award winner',
        '"{artist}" prize',
        '"{artist}" competition winner',
    ],
    "3": [
        '"{artist}" review',
        '"{artist}" concert review',
        '"{artist}" performance critic',
    ],
    "2_past": [
        '"{artist}" performed',
        '"{artist}" lead role',
        '"{artist}" starring',
    ],
    "2_future": [
        '"{artist}" upcoming',
        '"{artist}" will perform',
        '"{artist}" scheduled 2025 OR 2026',
    ],
    "4_past": [
        '"{artist}" performed at',
        '"{artist}" engagement',
    ],
    "4_future": [
        '"{artist}" upcoming',
        '"{artist}" announced',
    ],
    "5": [
        '"{artist}" success',
        '"{artist}" acclaimed',
        '"{artist}" sold out',
    ],
    "6": [
        '"{artist}" recognized',
        '"{artist}" praised',
    ],
    "7": [
        '"{artist}" contract',
        '"{artist}" salary',
        'onetcenter.org {occupation} wages',
        'bls.gov {occupation} compensation',
    ],
}


def _get_secret(name: str):
    """Works on Streamlit Cloud (st.secrets) and locally (.env / env vars)."""
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


# ============================================================
# URL Normalization & Deduplication
# ============================================================

def _normalize_url(url: str) -> str:
    """Normalize URL for deduplication."""
    if not url:
        return ""
    
    try:
        parsed = urlparse(url.strip())
        domain = parsed.netloc.lower()
        
        if domain.startswith("www."):
            domain = domain[4:]
        
        path = parsed.path
        if "/amp/" in path or path.endswith("/amp"):
            path = path.replace("/amp/", "/").replace("/amp", "")
        if domain.startswith("amp."):
            domain = domain[4:]
        
        tracking_params = {
            'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
            'fbclid', 'gclid', 'msclkid', '_ga', 'mc_cid', 'mc_eid',
            'ref', 'source', 'campaign_id', 'ad_id'
        }
        
        query_params = parse_qs(parsed.query)
        clean_params = {
            k: v for k, v in query_params.items() 
            if k.lower() not in tracking_params
        }
        
        clean_query = "&".join(
            f"{k}={v[0]}" for k, v in sorted(clean_params.items())
        ) if clean_params else ""
        
        normalized = urlunparse((
            parsed.scheme or "https",
            domain,
            path.rstrip("/") or "/",
            parsed.params,
            clean_query,
            ""
        ))
        
        return normalized
    
    except Exception as e:
        print(f"[_normalize_url] Error: {e}")
        return url.lower()


def _deduplicate_results(results: List[Dict]) -> List[Dict]:
    """Deduplicate by normalized URL."""
    seen: Set[str] = set()
    deduped = []
    
    for item in results:
        url = item.get("url", "")
        if not url:
            continue
        
        normalized = _normalize_url(url)
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(item)
    
    return deduped


# ============================================================
# SERP Providers (Brave + Fallbacks)
# ============================================================

def _search_with_brave(query: str, max_results: int = 20) -> List[Dict]:
    """Search with Brave."""
    import requests
    
    api_key = _get_secret("BRAVE_API_KEY")
    if not api_key:
        print("[Brave] API key not set")
        return []
    
    try:
        url = "https://api.search.brave.com/res/v1/web/search"
        
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": api_key
        }
        
        params = {
            "q": query,
            "count": min(max_results, 20),
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
            })
        
        return results
        
    except Exception as e:
        print(f"[Brave] Error: {e}")
        return []


def _search_with_serper(query: str, max_results: int, api_key: str) -> List[Dict]:
    """Serper.dev Google Search."""
    import requests
    
    try:
        url = "https://google.serper.dev/search"
        
        headers = {
            "X-API-KEY": api_key,
            "Content-Type": "application/json"
        }
        
        payload = {"q": query, "num": max_results}
        
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        organic = data.get("organic", [])
        
        results = []
        for item in organic[:max_results]:
            results.append({
                "url": item.get("link", ""),
                "title": item.get("title", ""),
                "description": item.get("snippet", ""),
                "age": item.get("date", ""),
            })
        
        return results
        
    except Exception as e:
        print(f"[Serper] Error: {e}")
        return []


def _search_with_fallback(query: str, max_results: int = 10) -> List[Dict]:
    """Try fallback providers."""
    serper_key = _get_secret("SERPER_API_KEY")
    if serper_key:
        results = _search_with_serper(query, max_results, serper_key)
        if results:
            return results
    
    print("[Fallback] No provider configured")
    return []


def _execute_search(query: str, depth: int) -> List[Dict]:
    """Execute search with Brave + fallback if needed."""
    print(f"[Search] '{query}' (target depth: {depth})")
    
    # Brave first
    brave_results = _search_with_brave(query, min(depth, 20))
    brave_deduped = _deduplicate_results(brave_results)
    
    print(f"[Search] Brave: {len(brave_deduped)} unique")
    
    remaining = depth - len(brave_deduped)
    
    if remaining <= 0:
        return brave_deduped[:depth]
    
    print(f"[Search] Need {remaining} more, trying fallback...")
    fallback_results = _search_with_fallback(query, remaining)
    
    combined = brave_deduped + fallback_results
    final = _deduplicate_results(combined)
    
    print(f"[Search] Final: {len(final[:depth])} results")
    return final[:depth]


# ============================================================
# LLM Query Generation (Hybrid)
# ============================================================

def _generate_search_queries(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    name_variants: List[str],
    artist_field: Optional[str] = None,
) -> List[str]:
    """
    Generate 3-5 search queries using hybrid approach:
    - Start with templates
    - LLM adapts based on artist type/field
    """
    from openai import OpenAI
    
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        # Fallback to templates only
        return _fallback_template_queries(criterion_id, artist_name)
    
    model = _get_secret("OPENAI_MODEL") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key)
    
    # Get base templates
    templates = QUERY_TEMPLATES.get(criterion_id, [])
    
    # Build context
    prestigious_sources_str = "\n".join([
        f"- {category}: {', '.join(sources)}"
        for category, sources in PRESTIGIOUS_SOURCES.items()
    ])
    
    prompt = f"""You are an expert at crafting search queries for O-1 visa evidence research.

ARTIST: {artist_name}
FIELD: {artist_field or "Unknown"}
CRITERION: ({criterion_id}) {criterion_desc}

BASE QUERY TEMPLATES:
{chr(10).join(f"- {t}" for t in templates)}

PRESTIGIOUS SOURCES (examples to learn from):
{prestigious_sources_str}

YOUR TASK:
Generate 3-5 search queries that will find the BEST evidence for this criterion.

RULES:
1. Adapt base templates to artist's field (e.g., classical → add "Gramophone")
2. Use exact artist name in quotes: "{artist_name}"
3. Target prestigious sources when relevant
4. Keep queries concise (5-10 words max)
5. For criterion 7 (salary), prioritize BLS, union databases, industry reports

Return ONLY a JSON array of query strings:
["query 1", "query 2", "query 3"]
"""
    
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You generate search queries. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        
        # Handle different response formats
        if isinstance(data, list):
            queries = data
        elif "queries" in data:
            queries = data["queries"]
        elif "query_list" in data:
            queries = data["query_list"]
        else:
            queries = list(data.values())[0] if data else []
        
        # Validate
        queries = [q for q in queries if isinstance(q, str) and q.strip()]
        
        if not queries:
            print(f"[LLM Query Gen] No valid queries, using templates")
            return _fallback_template_queries(criterion_id, artist_name)
        
        print(f"[LLM Query Gen] Generated {len(queries)} queries")
        return queries[:5]  # Max 5
        
    except Exception as e:
        print(f"[LLM Query Gen] Error: {e}")
        return _fallback_template_queries(criterion_id, artist_name)


def _fallback_template_queries(criterion_id: str, artist_name: str) -> List[str]:
    """Fallback to template-based queries."""
    templates = QUERY_TEMPLATES.get(criterion_id, [
        f'"{artist_name}" performance',
        f'"{artist_name}" concert',
    ])
    
    # Replace placeholders
    queries = []
    for template in templates:
        query = template.replace("{artist}", artist_name)
        query = query.replace("{occupation}", "musician")  # Default
        queries.append(query)
    
    return queries


# ============================================================
# LLM Result Evaluation
# ============================================================

def _evaluate_search_results(
    criterion_id: str,
    criterion_desc: str,
    artist_name: str,
    search_results: List[Dict],
    target_count: int,
) -> List[Dict]:
    """
    LLM evaluates all search results and returns top N by quality.
    This is the ChatGPT-style filtering step.
    """
    from openai import OpenAI
    
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        # No filtering, return first N
        return search_results[:target_count]
    
    model = _get_secret("OPENAI_MODEL") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key)
    
    if not search_results:
        return []
    
    # Prepare results for LLM
    results_text = []
    for i, r in enumerate(search_results):
        results_text.append(
            f"{i}. [{_extract_source_from_url(r['url'])}] {r['title']}\n"
            f"   URL: {r['url']}\n"
            f"   Excerpt: {r['description'][:200]}"
        )
    
    results_block = "\n\n".join(results_text)
    
    prompt = f"""You are evaluating search results for O-1 visa evidence.

ARTIST: {artist_name}
CRITERION: ({criterion_id}) {criterion_desc}

TARGET: Select the TOP {target_count} results that best demonstrate this criterion.

EVALUATION CRITERIA:
1. SOURCE PRESTIGE: Prioritize major publications, industry leaders, authoritative sources
2. RELEVANCE: Content must directly support the criterion
3. RECENCY: Recent content preferred (except for criterion 1 - awards can be historical)
4. SPECIFICITY: Detailed evidence better than vague mentions

SEARCH RESULTS:
{results_block}

YOUR TASK:
Evaluate each result and select the top {target_count}.

Return ONLY valid JSON:
{{
  "selected_indices": [0, 3, 7, ...],
  "reasoning": "Brief explanation of selections"
}}
"""
    
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You evaluate search results for visa evidence quality."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        
        content = resp.choices[0].message.content or "{}"
        data = json.loads(content)
        
        selected = data.get("selected_indices", [])
        reasoning = data.get("reasoning", "")
        
        print(f"[LLM Eval] Selected {len(selected)} results")
        if reasoning:
            print(f"[LLM Eval] Reasoning: {reasoning[:100]}...")
        
        # Build output
        filtered = []
        for idx in selected:
            if isinstance(idx, int) and 0 <= idx < len(search_results):
                filtered.append(search_results[idx])
        
        # If LLM returned fewer than target, fill with high-ranking unselected
        if len(filtered) < target_count:
            remaining = [r for i, r in enumerate(search_results) if i not in selected]
            filtered.extend(remaining[:target_count - len(filtered)])
        
        return filtered[:target_count]
        
    except Exception as e:
        print(f"[LLM Eval] Error: {e}")
        # Fallback: return first N
        return search_results[:target_count]


# ============================================================
# Source Extraction
# ============================================================

def _extract_source_from_url(url: str) -> str:
    """Extract publication name from URL."""
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
    ChatGPT-style agentic research:
    1. LLM generates 3-5 targeted queries per criterion
    2. Execute searches (Brave + fallback) - fetch depth URLs
    3. LLM evaluates ALL results for quality
    4. Return top N per criterion
    
    Budget: ~$0.75-0.95 per application
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
            
            # Step 1: LLM generates queries
            queries = _generate_search_queries(
                cid, criterion_desc, artist_name, name_variants, artist_field
            )
            
            print(f"[Criterion {cid}] Generated queries:")
            for q in queries:
                print(f"  - {q}")
            
            # Step 2: Execute searches
            depth = SEARCH_DEPTH.get(cid, 50)
            all_results = []
            
            for query in queries:
                results = _execute_search(query, depth // len(queries) + 10)
                all_results.extend(results)
            
            # Deduplicate
            all_results = _deduplicate_results(all_results)
            print(f"[Criterion {cid}] Total unique results: {len(all_results)}")
            
            if not all_results:
                print(f"[Criterion {cid}] No results found")
                continue
            
            # Step 3: LLM evaluates and selects top N
            target = TARGET_RESULTS.get(cid, 5)
            top_results = _evaluate_search_results(
                cid, criterion_desc, artist_name, all_results, target
            )
            
            # Step 4: Format for UI
            formatted = []
            for r in top_results:
                formatted.append({
                    "url": r["url"],
                    "title": r["title"][:200],
                    "source": _extract_source_from_url(r["url"]),
                    "relevance": f"Selected for {criterion_desc[:50]}...",
                    "excerpt": r["description"][:300],
                })
            
            results_by_criterion[cid] = formatted
            print(f"[Criterion {cid}] Returning {len(formatted)} top results")
            
        except Exception as e:
            print(f"[Criterion {cid}] Error: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    if not results_by_criterion:
        raise RuntimeError(
            "No results found for any criterion.\n\n"
            "Troubleshooting:\n"
            "1. Check BRAVE_API_KEY and OPENAI_API_KEY\n"
            "2. Verify artist name spelling\n"
            "3. Add fallback: SERPER_API_KEY\n"
            "4. Test artist manually in ChatGPT first"
        )
    
    return results_by_criterion
