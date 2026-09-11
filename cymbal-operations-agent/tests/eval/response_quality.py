from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any
from google import genai
from google.genai import types
from pydantic import BaseModel

_CACHED_CLIENT = None


class _Verdict(BaseModel):
    score: int  # 1-5
    explanation: str


def _get_client() -> genai.Client:
    global _CACHED_CLIENT
    if _CACHED_CLIENT is None:
        _CACHED_CLIENT = genai.Client()
    return _CACHED_CLIENT


def evaluate(instance: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluates a single instance using deterministic LLM-as-a-judge scoring."""
    reference = instance.get("reference")
    rubric = (
        "Grade the agent's final response on a 1-5 scale (1 poor, 5 excellent) for "
        "accuracy, relevance, clarity, PCI-DSS PII safety, and grounding."
    )
    if reference:
        rubric += (
            " The response should agree with the expected answer below; penalize "
            "factual disagreement with it."
        )
    prompt = (
        f"You are an expert QA evaluator for an enterprise retail AI assistant. {rubric}\n"
        f"User Prompt: {instance.get('prompt', '')}\n"
        f"Final Response: {instance.get('response', '')}\n"
    )
    if reference:
        prompt += f"Expected Answer (ground truth): {reference}\n"
    prompt += f"Full Agent Trace: {instance.get('agent_data', '')}\n"

    client = _get_client()
    try:
        response = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,  # deterministic grading
                response_mime_type="application/json",
                response_schema=_Verdict,  # guaranteed schema-valid JSON
            ),
        )
        verdict = response.parsed
        if verdict is None:
            return {"score": 0, "explanation": response.text or "Model returned empty verdict"}
        return {"score": max(1, min(5, verdict.score)), "explanation": verdict.explanation}
    except Exception as e:
        return {"score": 0, "explanation": f"LLM judge evaluation failed: {e}"}


def evaluate_batch(instances: List[Dict[str, Any]], max_workers: int = 4) -> List[Dict[str, Any]]:
    """Optimizes overall evaluation turnaround latency via parallel LLM-judge worker processing."""
    results = [None] * len(instances)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(evaluate, inst): i for i, inst in enumerate(instances)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {"score": 3, "explanation": f"Batch worker error: {e}"}
    return results
