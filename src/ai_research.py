"""
AI-Powered Research Assistant
Automatically searches the web and finds evidence for O-1 criteria.

IMPORTANT:
- Web search is supported via the OpenAI **Responses API** with tools=[{"type": "web_search"}]
- Chat Completions does NOT accept tools[].type like "web_search_20250305" (only "function"/"custom")
"""

import json
import os
from typing import Dict, List, Optional

from openai import OpenAI


def _get_secret(name: str):
    """Works on Streamlit Cloud (st.secrets) and locally (.env / env vars)."""
    try:
        import streamlit as st  # type: ignore
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)


# System prompt for AI research
RESEARCH_SYSTEM_PROMPT = """You are an expert immigration paralegal researcher for O-1 visa petitions.

Your task is to search the web and find actual evidence (URLs to articles, announcements, reviews) that support specific O-1 criteria for a performing artist.

You have access to web search. Use it to find real, verifiable evidence.

For each criterion, find 3-5 high-quality sources. Prioritize:
- Primary sources (official announcements, award websites)
- Prestigious publications (NYT, Guardian, major trade press)
- Recent content (within last 5 years)
- Content that clearly mentions the artist

Return results as JSON."""


RESEARCH_PROMPT_TEMPLATE = """Find evidence to support O-1 criteria for this artist.

Artist: {artist_name}
Name variants: {name_variants}

Selected criteria:
{criteria_list}

For EACH criterion, search the web and find 3-5 actual URLs with evidence.

CRITERION-SPECIFIC GUIDANCE:

Criterion 1 (Awards):
- Find official announcements from award-granting bodies
- Look for: Grammy.com, Pulitzer.org, Kennedy-Center.org, competition sites
- PRIMARY SOURCES ONLY (not news articles about awards)

Criterion 3 (Reviews):
- Find critical reviews from major publications
- Look for: NYT, Guardian, FT, Gramophone, Opera News, Bachtrack, Musical America
- Must be actual reviews (not just mentions)

Criteria 2 & 4 (Distinguished Performances/Organizations):
- Find performance announcements from major venues
- Look for: Metropolitan Opera, Berlin Phil, Royal Opera, etc.
- Also search OperaBase for documented performances

For each URL you find:
1. Verify it exists and is relevant
2. Extract the title
3. Note why it's relevant

Return JSON:
{{
  "results_by_criterion": {{
    "3": [
      {{
        "url": "https://...",
        "title": "Article title",
        "source": "Publication name",
        "relevance": "Why this supports the criterion",
        "excerpt": "Brief relevant quote from article"
      }}
    ]
  }}
}}"""


def ai_search_for_evidence(
    artist_name: str,
    name_variants: List[str],
    selected_criteria: List[str],
    criteria_descriptions: Dict[str, str],
    feedback: Optional[Dict] = None,
) -> Dict[str, List[Dict]]:
    """
    AI automatically searches the web and finds evidence for O-1 criteria.

    Returns:
        {
          "3": [
            {"url": "...", "title": "...", "source": "...", "relevance": "...", "excerpt": "..."},
            ...
          ],
          ...
        }
    """
    api_key = _get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    # NOTE: Web search tool is supported via Responses API; model availability can vary.
    # If you run into model/tool issues, set OPENAI_MODEL="gpt-5" in Streamlit Cloud secrets.
    model = _get_secret("OPENAI_MODEL") or "gpt-5"

    client = OpenAI(api_key=api_key)

    # Build criteria list
    criteria_list = "\n".join(
        [f"({cid}) {criteria_descriptions.get(cid, '')}" for cid in selected_criteria]
    )

    # Add feedback if regenerating
    feedback_text = ""
    if feedback:
        approved = feedback.get("approved_urls", [])
        rejected = feedback.get("rejected_urls", [])
        user_feedback = feedback.get("user_feedback", "")

        if approved or rejected or user_feedback:
            feedback_text = f"""

IMPORTANT - Regeneration Context:
- Keep these approved URLs (don't search for these again): {', '.join(approved[:5]) if approved else 'None'}
- Find DIFFERENT sources to replace these rejected ones: {', '.join(rejected[:5]) if rejected else 'None'}
- User feedback: {user_feedback if user_feedback else 'None'}

Focus on finding NEW, DIFFERENT sources that address the user's feedback.
"""

    prompt = (
        RESEARCH_PROMPT_TEMPLATE.format(
            artist_name=artist_name,
            name_variants=", ".join(name_variants) if name_variants else "None",
            criteria_list=criteria_list,
        )
        + feedback_text
    )

    try:
        # ✅ Responses API + web_search tool (this fixes your 400 invalid tools[].type error)
        resp = client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            response_format={"type": "json_object"},
            input=[
                {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

        # Extract response text
        raw = (resp.output_text or "").strip() or "{}"

        # Parse JSON (with a fallback if the model returns extra text)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Best-effort extraction of the first JSON object
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                data = json.loads(raw[start : end + 1])
            else:
                raise

        results = data.get("results_by_criterion", {})

        # Validate structure
        cleaned: Dict[str, List[Dict]] = {}
        for cid in selected_criteria:
            items = results.get(cid, [])
            if not isinstance(items, list):
                items = []

            valid_items: List[Dict] = []
            for item in items:
                if isinstance(item, dict) and item.get("url") and item.get("title"):
                    valid_items.append(
                        {
                            "url": item.get("url", ""),
                            "title": item.get("title", ""),
                            "source": item.get("source", "Unknown"),
                            "relevance": item.get("relevance", ""),
                            "excerpt": item.get("excerpt", ""),
                        }
                    )

            if valid_items:
                cleaned[cid] = valid_items

        return cleaned

    except Exception as e:
        print(f"[ai_search_for_evidence] Error: {e}")
        raise RuntimeError(f"AI search failed: {str(e)}")
