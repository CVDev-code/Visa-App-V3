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


# Research prompts for each criterion type
RESEARCH_SYSTEM_PROMPT = """You are an expert immigration paralegal researcher specializing in O-1 visa petitions for performing artists.

Your task is to generate targeted web search queries to find evidence supporting specific O-1 criteria.

Rules:
- Return ONLY valid JSON
- Generate 3-5 specific search queries per criterion
- Queries should target primary sources and prestigious publications
- For awards: ONLY search for official announcements from award-granting bodies
- For reviews: Target major trade press and prestigious outlets (NOT blogs or fan sites)
- For distinguished organizations: Target major venues, orchestras, opera houses, festivals"""


SEARCH_QUERIES_PROMPT = """Generate web search queries to find evidence for the following artist and criteria.

Artist Name: {artist_name}
Name Variants: {name_variants}

Selected Criteria:
{criteria_list}

CRITERION-SPECIFIC GUIDANCE:

Criterion 1 (Awards):
- Search ONLY for official announcements from award-granting bodies
- Target: Grammy.com, Pulitzer.org, Kennedy-Center.org, official competition sites
- Example: "Jane Smith winner announcement site:grammy.com"

Criterion 3 (Reviews):
- Target prestigious publications and trade press
- Include: New York Times, Guardian, Financial Times, Gramophone, Opera News, Musical America, Bachtrack
- Example: "Jane Smith review site:nytimes.com OR site:theguardian.com"

Criteria 2 & 4 (Distinguished Performances/Organizations):
- Search for performance announcements from major venues
- Target: venue websites, OperaBase, major orchestra/opera house sites
- Example: "Jane Smith Metropolitan Opera announcement"
- Example: "Jane Smith site:operabase.com"

Return JSON format:
{{
  "queries_by_criterion": {{
    "1": ["query1", "query2", "query3"],
    "3": ["query1", "query2"]
  }}
}}"""


ORGANIZATION_VERIFICATION_PROMPT = """Determine if the following organization is "distinguished" for O-1 visa purposes.

Organization: {organization_name}
Context: {context}

A distinguished organization typically has:
- International reputation and recognition
- Long-established history (10+ years)
- Significant cultural impact
- Professional status (not amateur/community groups)
- Regular coverage in major publications

Examples of DISTINGUISHED organizations:
- Metropolitan Opera, Royal Opera House, Bavarian State Opera
- Berlin Philharmonic, London Symphony Orchestra, Vienna Philharmonic
- Salzburg Festival, Glyndebourne Festival, BBC Proms
- Carnegie Hall, Royal Albert Hall, Kennedy Center

Examples of NOT distinguished:
- Local community orchestras
- University ensembles (unless exceptionally prestigious)
- Amateur choirs
- Small regional festivals

Return JSON:
{{
  "is_distinguished": true/false,
  "confidence": "high/medium/low",
  "reasoning": "Brief explanation"
}}"""


PRIMARY_SOURCE_CHECK_PROMPT = """Analyze if this URL is a PRIMARY source for an award announcement.

URL: {url}
Page Title: {title}
Snippet: {snippet}

PRIMARY sources (acceptable):
- Official award organization websites
- Press releases from award-granting bodies
- Official competition result pages

SECONDARY sources (NOT acceptable):
- News articles ABOUT awards
- Artist biography pages mentioning awards
- Wikipedia or aggregator sites
- Social media posts

Return JSON:
{{
  "is_primary_source": true/false,
  "confidence": "high/medium/low",
  "reasoning": "Brief explanation"
}}"""


def generate_search_queries(
    artist_name: str,
    name_variants: List[str],
    selected_criteria: List[str],
    criteria_descriptions: Dict[str, str]
) -> Dict[str, List[str]]:
    """
    Generate targeted search queries for each selected criterion.
    
    Returns:
        {"1": ["query1", "query2"], "3": ["query1", "query2"]}
    """
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    
    model = _get_secret("OPENAI_MODEL") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key)
    
    # Build criteria list
    criteria_list_text = "\n".join([
        f"- ({cid}) {criteria_descriptions.get(cid, '')}"
        for cid in selected_criteria
    ])
    
    prompt = SEARCH_QUERIES_PROMPT.format(
        artist_name=artist_name,
        name_variants=", ".join(name_variants) if name_variants else "None",
        criteria_list=criteria_list_text
    )
    
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw = resp.choices[0].message.content or "{}"
        data = json.loads(raw)
        return data.get("queries_by_criterion", {})
    except Exception as e:
        print(f"[generate_search_queries] Error: {e}")
        return {}


def verify_organization_distinguished(
    organization_name: str,
    context: str = ""
) -> Dict:
    """
    Check if an organization is "distinguished" for O-1 purposes.
    
    Returns:
        {
          "is_distinguished": bool,
          "confidence": "high/medium/low",
          "reasoning": str
        }
    """
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    
    model = _get_secret("OPENAI_MODEL") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key)
    
    prompt = ORGANIZATION_VERIFICATION_PROMPT.format(
        organization_name=organization_name,
        context=context or "No additional context provided"
    )
    
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw = resp.choices[0].message.content or "{}"
        return json.loads(raw)
    except Exception as e:
        print(f"[verify_organization_distinguished] Error: {e}")
        return {
            "is_distinguished": False,
            "confidence": "low",
            "reasoning": f"Error during verification: {str(e)}"
        }


def check_primary_source(
    url: str,
    title: str = "",
    snippet: str = ""
) -> Dict:
    """
    Verify if a URL is a primary source for award announcements.
    
    Returns:
        {
          "is_primary_source": bool,
          "confidence": "high/medium/low",
          "reasoning": str
        }
    """
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    
    model = _get_secret("OPENAI_MODEL") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key)
    
    prompt = PRIMARY_SOURCE_CHECK_PROMPT.format(
        url=url,
        title=title or "Unknown",
        snippet=snippet or "No snippet available"
    )
    
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        raw = resp.choices[0].message.content or "{}"
        return json.loads(raw)
    except Exception as e:
        print(f"[check_primary_source] Error: {e}")
        return {
            "is_primary_source": False,
            "confidence": "low",
            "reasoning": f"Error during verification: {str(e)}"
        }
