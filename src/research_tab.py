"""
OpenAI Assistant (AI Agent) Integration
Connects to OpenAI Assistant API for web research
"""

import json
import time
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


def search_with_ai_assistant(
    artist_name: str,
    criterion_id: str,
    criterion_description: str,
    name_variants: Optional[List[str]] = None,
    artist_field: Optional[str] = None,
    feedback: Optional[str] = None,
    max_results: int = 10
) -> List[Dict]:
    """
    Use OpenAI Assistant to search for evidence
    
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
    
    # Get credentials
    api_key = _get_secret("OPENAI_API_KEY")
    assistant_id = _get_secret("OPENAI_ASSISTANT_ID")
    
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set in Streamlit secrets")
    
    if not assistant_id:
        raise RuntimeError(
            "OPENAI_ASSISTANT_ID not set in Streamlit secrets.\n\n"
            "Please create an OpenAI Assistant at:\n"
            "https://platform.openai.com/assistants\n\n"
            "Then add the Assistant ID to your Streamlit secrets."
        )
    
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
    
    # Create a thread
    thread = client.beta.threads.create()
    
    # Add message to thread
    client.beta.threads.messages.create(
        thread_id=thread.id,
        role="user",
        content=prompt
    )
    
    # Run the assistant
    run = client.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant_id
    )
    
    # Wait for completion (with timeout)
    max_wait = 120  # 2 minutes max
    waited = 0
    poll_interval = 2  # seconds
    
    while waited < max_wait:
        run_status = client.beta.threads.runs.retrieve(
            thread_id=thread.id,
            run_id=run.id
        )
        
        if run_status.status == 'completed':
            break
        elif run_status.status in ['failed', 'cancelled', 'expired']:
            raise RuntimeError(f"Assistant run {run_status.status}: {run_status.last_error}")
        
        time.sleep(poll_interval)
        waited += poll_interval
    
    if waited >= max_wait:
        raise RuntimeError("Assistant timed out after 2 minutes")
    
    # Get the messages
    messages = client.beta.threads.messages.list(
        thread_id=thread.id
    )
    
    # Get the assistant's response (most recent message)
    assistant_messages = [m for m in messages.data if m.role == 'assistant']
    
    if not assistant_messages:
        raise RuntimeError("No response from assistant")
    
    # Extract the text content
    latest_message = assistant_messages[0]
    
    # Get text from message content
    content_text = ""
    for content_block in latest_message.content:
        if content_block.type == 'text':
            content_text += content_block.text.value
    
    if not content_text:
        raise RuntimeError("Assistant returned empty response")
    
    # Parse JSON response
    try:
        # Try to extract JSON array from response
        # Sometimes the assistant adds extra text, so we need to extract the JSON
        content_text = content_text.strip()
        
        # Find JSON array (starts with [ and ends with ])
        start = content_text.find('[')
        end = content_text.rfind(']') + 1
        
        if start == -1 or end == 0:
            raise ValueError("No JSON array found in response")
        
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
            f"Failed to parse assistant response as JSON: {str(e)}\n\n"
            f"Response was:\n{content_text[:500]}"
        )


# ============================================================
# Helper function for batch searching multiple criteria
# ============================================================

def batch_search_with_assistant(
    artist_name: str,
    criteria_ids: List[str],
    criteria_descriptions: Dict[str, str],
    name_variants: Optional[List[str]] = None,
    artist_field: Optional[str] = None,
    max_results_per_criterion: int = 10
) -> Dict[str, List[Dict]]:
    """
    Search multiple criteria in sequence
    
    Returns:
        {criterion_id: [results], ...}
    """
    
    all_results = {}
    
    for cid in criteria_ids:
        desc = criteria_descriptions.get(cid, "")
        
        try:
            results = search_with_ai_assistant(
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
