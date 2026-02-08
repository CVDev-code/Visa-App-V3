"""
OpenAI Responses API Integration (New System)
Replaces deprecated Assistants API with Responses API
Uses web_search tool for evidence research
"""

import json
import os
from typing import List, Dict, Optional
from openai import OpenAI


def _get_secret(name: str):
    """Get secret from Streamlit or environment"""
    try:
        import streamlit as st
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


# System prompt with USCIS guidance
RESEARCH_SYSTEM_PROMPT = """You are a visa paralegal assistant researching O-1 visa evidence for artists.

CRITICAL OUTPUT REQUIREMENT:
You MUST return ONLY a valid JSON array. No explanations, no markdown, no code blocks, no preamble, no postamble.
Just the raw JSON array starting with [ and ending with ].

USCIS Regulatory Standards

According to 8 CFR 214.2(o)(3)(iv), evidence must demonstrate extraordinary ability.

Key USCIS Standards:
✅ Evidence must be credible, relevant, substantial, and documented
❌ Avoid self-serving sources, unverified claims, listings-only pages

Special Rules by Evidence Type:

AWARDS (Criterion 1):
- Grammy Awards: Automatically satisfy (no prestige proof needed)
- Other awards: MUST include independent prestige evidence
- Required: Award selection criteria, international scope

REVIEWS (Criterion 3):
- Must be substantial articles (not one-line mentions)
- Must focus on beneficiary's work
- Preferred: Major newspapers, established arts magazines

DISTINGUISHED ORGANIZATIONS (Criterion 4):
- Must prove BOTH role AND organization prestige
- Examples: Carnegie Hall, Met Opera, major orchestras
- Supporting evidence: Organization awards, media coverage

Source Quality Hierarchy:

TIER 1 (Always prioritize):
- Official award websites (grammy.com, kennedy-center.org)
- Major newspapers (NYT, Guardian, Telegraph)
- Prestigious venues (Carnegie Hall, Met Opera)
- Government cultural institutions

TIER 2 (Good):
- Regional newspapers
- Industry publications (Variety, Billboard)
- Major festival websites

NEVER USE:
- Artist personal websites/social media
- Wikipedia (cite its sources instead)
- Unverified blogs
- Generic "top artists" lists

Your Task:

Search the web for 8-10 high-quality sources that support the given O-1 criterion.

OUTPUT FORMAT - CRITICAL:
Return ONLY a JSON array. No other text whatsoever.

Example of CORRECT output:
[{"url":"https://example.com","title":"Title","source":"Source","excerpt":"Excerpt","relevance":"Why relevant"}]

Example of WRONG output:
Here are the results:
[...]

Example of WRONG output:
```json
[...]
```

ONLY return the raw JSON array. Nothing else.
"""


def search_with_responses_api(
    artist_name: str,
    criterion_id: str,
    criterion_description: str,
    name_variants: Optional[List[str]] = None,
    artist_field: Optional[str] = None,
    feedback: Optional[str] = None,
    max_results: int = 10
) -> List[Dict]:
    """
    Use OpenAI Responses API with web_search tool for evidence research
    
    Args:
        artist_name: Beneficiary name
        criterion_id: Which criterion (e.g., "1", "3", "2_past")
        criterion_description: Full description of the criterion
        name_variants: Alternative spellings of artist name
        artist_field: Field of work (e.g., "Classical Music")
        feedback: User feedback for regeneration
        max_results: Maximum number of results to return
    
    Returns:
        List of evidence sources with url, title, source, excerpt, relevance
    """
    
    # Get API key
    api_key = _get_secret("OPENAI_API_KEY")
    
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in Streamlit secrets")
    
    client = OpenAI(api_key=api_key)
    
    # Build the research prompt
    prompt = f"""Search the web for evidence that {artist_name} meets this O-1 visa criterion:

Criterion ({criterion_id}): {criterion_description}

Artist: {artist_name}
"""
    
    if name_variants:
        prompt += f"Also known as: {', '.join(name_variants)}\n"
    
    if artist_field:
        prompt += f"Field: {artist_field}\n"
    
    prompt += f"\nFind {max_results} high-quality sources (major publications, industry magazines, official websites).\n"
    
    if feedback:
        prompt += f"\nUser feedback: {feedback}\n"
    
    prompt += """
Return ONLY a JSON array in this format:
[
  {
    "url": "https://example.com/article",
    "title": "Article Title",
    "source": "Publication Name",
    "excerpt": "Brief relevant excerpt",
    "relevance": "Why this supports the criterion"
  }
]

DO NOT include any other text. ONLY the JSON array.
"""
    
    try:
        # Call Responses API with web_search tool
        response = client.responses.create(
            model="gpt-4o",  # Use gpt-4o for web search support
            input=[
                {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            tools=[
                {
                    "type": "web_search_20250305",
                    "name": "web_search"
                }
            ]
            # Note: response_format not supported in Responses API yet
        )
        
        # Extract text from response
        content_text = response.output_text
        
        if not content_text:
            raise RuntimeError("API returned empty response")
        
        # Parse JSON response
        try:
            # Try to extract JSON array from response
            # The response might include extra text since we can't force JSON format
            content_text = content_text.strip()
            
            # Try to find JSON array markers
            # Look for [ and ] that likely contain our JSON
            start = content_text.find('[')
            end = content_text.rfind(']') + 1
            
            if start == -1 or end == 0:
                # No JSON array found - try to parse the whole thing
                # Maybe it's just the JSON without extra text
                try:
                    results = json.loads(content_text)
                    if isinstance(results, list):
                        # Great, it was just a JSON array
                        pass
                    else:
                        raise ValueError("Response is not a JSON array")
                except json.JSONDecodeError:
                    raise ValueError(
                        f"No JSON array found in response. "
                        f"Response was: {content_text[:200]}..."
                    )
            else:
                # Found array markers - extract JSON
                json_str = content_text[start:end]
                results = json.loads(json_str)
                
                if not isinstance(results, list):
                    raise ValueError("Response is not a JSON array")
            
            # Validate and normalize results
            normalized_results = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                
                # Ensure required fields
                if 'url' not in item or not item['url']:
                    continue
                
                normalized_results.append({
                    'url': item.get('url', ''),
                    'title': item.get('title', 'Untitled'),
                    'source': item.get('source', 'Unknown'),
                    'excerpt': item.get('excerpt', ''),
                    'relevance': item.get('relevance', '')
                })
            
            return normalized_results[:max_results]
        
        except (json.JSONDecodeError, ValueError) as e:
            raise RuntimeError(
                f"Failed to parse API response as JSON: {str(e)}\n\n"
                f"Response was:\n{content_text[:500]}"
            )
    
    except Exception as e:
        raise RuntimeError(f"OpenAI Responses API error: {str(e)}")


# ============================================================
# Helper function for batch searching multiple criteria
# ============================================================

def batch_search_with_responses(
    artist_name: str,
    criteria_ids: List[str],
    criteria_descriptions: Dict[str, str],
    name_variants: Optional[List[str]] = None,
    artist_field: Optional[str] = None,
    max_results_per_criterion: int = 10
) -> Dict[str, List[Dict]]:
    """
    Search multiple criteria in sequence using Responses API
    
    Returns:
        {criterion_id: [results], ...}
    """
    
    all_results = {}
    
    for cid in criteria_ids:
        desc = criteria_descriptions.get(cid, "")
        
        try:
            results = search_with_responses_api(
                artist_name=artist_name,
                criterion_id=cid,
                criterion_description=desc,
                name_variants=name_variants,
                artist_field=artist_field,
                max_results=max_results_per_criterion
            )
            all_results[cid] = results
        
        except Exception as e:
            # Log error but continue with other criteria
            print(f"Error searching criterion {cid}: {str(e)}")
            all_results[cid] = []
    
    return all_results
