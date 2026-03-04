from __future__ import annotations

import json
import os
import re
import urllib.parse
from typing import Optional, Tuple, Any, Dict

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# -----------------------
# Config / App bootstrap
# -----------------------
load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

app = FastAPI(title="LLM → Google Maps Demo", version="1.0.0")

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

if not GOOGLE_MAPS_API_KEY:
    # keep running for demo, but endpoints will fail with clear message
    print("WARNING: GOOGLE_MAPS_API_KEY is not set in .env")

# -----------------------
# Schemas
# -----------------------
class AskRequest(BaseModel):
    question: str = Field(..., min_length=1)


class PlacesRequest(BaseModel):
    search_query: str = Field(..., min_length=1)
    city: Optional[str] = "Jakarta"
    count: Optional[int] = Field(5, ge=1, le=20)  # cap for safety
    origin: Optional[str] = None
    mode: Optional[str] = "driving"


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1)
    origin: Optional[str] = None
    city: Optional[str] = None
    count: Optional[int] = Field(5, ge=1, le=20)
    mode: Optional[str] = "driving"


# -----------------------
# Helpers
# -----------------------
def http_post_json(url: str, payload: dict, timeout: int = 120) -> dict:
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"HTTP POST failed: {str(e)}")


def http_get_json(url: str, params: dict, timeout: int = 30) -> dict:
    try:
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"HTTP GET failed: {str(e)}")


def call_ollama_json_only(prompt: str) -> str:
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    resp = http_post_json(OLLAMA_URL, payload, timeout=120)
    content = (resp.get("message") or {}).get("content", "")
    return (content or "").strip()


def extract_json_object(text: str) -> Tuple[Optional[dict], Optional[str]]:
    """
    Extract first JSON object from text and make it JSON-parseable.
    Handles:
    - markdown fences
    - // comments
    - trailing commas before } or ]
    """
    # Try direct parse first
    try:
        return json.loads(text), None
    except Exception:
        pass

    # Extract first {...} block (DOTALL)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None, "No JSON object found"

    s = m.group(0)

    # Remove markdown fences if any leaked
    s = s.replace("```json", "").replace("```", "").strip()

    # Remove // comments
    s = re.sub(r"//.*?$", "", s, flags=re.MULTILINE)

    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)

    s = s.strip()

    try:
        return json.loads(s), None
    except Exception as e:
        return None, f"JSON parse failed after cleanup: {str(e)}"


def require_maps_key() -> None:
    if not GOOGLE_MAPS_API_KEY:
        raise HTTPException(status_code=500, detail="GOOGLE_MAPS_API_KEY is missing. Set it in .env")


def build_embed_place_url(place_id: str) -> str:
    q = urllib.parse.urlencode({"key": GOOGLE_MAPS_API_KEY, "q": f"place_id:{place_id}"})
    return f"https://www.google.com/maps/embed/v1/place?{q}"


def build_open_place_url(place_id: str) -> str:
    # Google example uses query=Google; we keep same pattern but only place_id matters
    qs = urllib.parse.urlencode({"api": "1", "query_place_id": place_id, "query": "Google"})
    return f"https://www.google.com/maps/search/?{qs}"


def build_open_directions_url(origin: str, dest_place_id: str, mode: str) -> str:
    destination = f"place_id:{dest_place_id}"
    qs = urllib.parse.urlencode(
        {"api": "1", "origin": origin, "destination": destination, "travelmode": mode}
    )
    return f"https://www.google.com/maps/dir/?{qs}"


def build_embed_directions_url(origin: str, dest_place_id: str, mode: str) -> str:
    q = urllib.parse.urlencode(
        {"key": GOOGLE_MAPS_API_KEY, "origin": origin, "destination": f"place_id:{dest_place_id}", "mode": mode}
    )
    return f"https://www.google.com/maps/embed/v1/directions?{q}"


def places_text_search(query: str, count: int) -> list[dict]:
    require_maps_key()
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {"query": query, "key": GOOGLE_MAPS_API_KEY}
    payload = http_get_json(url, params, timeout=30)
    return (payload.get("results") or [])[:count]


# -----------------------
# Routes
# -----------------------
@app.get("/")
def root():
    return {"message": "Maps LLM backend running"}


@app.get("/health")
@limiter.limit("100/day")
def health(request: Request):
    # Don't call external services here; keep it fast & safe
    return {
        "status": "ok",
        "ollama_url": OLLAMA_URL,
        "model": MODEL,
        "maps_api_key_loaded": bool(GOOGLE_MAPS_API_KEY),
    }


@app.post("/ask")
@limiter.limit("30/minute")
def ask_llm(data: AskRequest, request: Request):
    prompt = f"""
You are a strict JSON generator.

Return ONLY a raw JSON object. No markdown, no code fences, no comments, no extra text.
Schema: {{ "search_query": "..." }}

User question:
{data.question}
""".strip()

    content = call_ollama_json_only(prompt)
    parsed, err = extract_json_object(content)
    if err:
        return {"raw_llm": content, "error": err}

    return {"search_query": parsed.get("search_query"), "raw_llm": content}


@app.post("/places")
@limiter.limit("30/minute")
def places_search(data: PlacesRequest, request: Request):
    require_maps_key()

    query = data.search_query.strip()
    if data.city and data.city.strip():
        query = f"{query} in {data.city.strip()}"

    count = int(data.count or 5)
    mode = (data.mode or "driving").strip()
    origin = (data.origin or "").strip() if data.origin else None

    results = places_text_search(query, count)

    places: list[dict] = []
    for it in results:
        place_id = it.get("place_id")
        if not place_id:
            continue

        geom = (it.get("geometry") or {}).get("location") or {}
        lat = geom.get("lat")
        lng = geom.get("lng")

        item = {
            "name": it.get("name"),
            "formatted_address": it.get("formatted_address"),
            "rating": it.get("rating"),
            "user_ratings_total": it.get("user_ratings_total"),
            "place_id": place_id,
            "lat": lat,
            "lng": lng,
            "embed_place_url": build_embed_place_url(place_id),
            "open_in_maps_url": build_open_place_url(place_id),
        }

        if origin:
            item["directions_url"] = build_open_directions_url(origin, place_id, mode)
            item["embed_directions_url"] = build_embed_directions_url(origin, place_id, mode)

        places.append(item)

    return {"query": query, "count": len(places), "places": places}


@app.post("/chat")
@limiter.limit("10/minute")
def chat(data: ChatRequest, request: Request):
    prompt = f"""
You are a strict JSON generator.

Return ONLY a raw JSON object. No markdown, no code fences, no comments, no extra text.

Schema:
{{ "search_query": "...", "city": "Jakarta", "count": 5, "mode": "driving" }}

User request:
{data.question}
""".strip()

    content = call_ollama_json_only(prompt)
    plan, err = extract_json_object(content)
    if err:
        return {"raw_llm": content, "error": err}

    # Merge fallbacks
    search_query = (plan.get("search_query") or data.question).strip()
    city = (plan.get("city") or data.city or "Jakarta").strip()
    count = int(plan.get("count") or data.count or 5)
    mode = (plan.get("mode") or data.mode or "driving").strip()

    # Reuse /places logic
    places_req = PlacesRequest(
        search_query=search_query,
        city=city,
        count=count,
        origin=data.origin,
        mode=mode,
    )
    results = places_search(places_req, request)

    return {"plan": plan, "results": results}


# UI static
app.mount("/ui", StaticFiles(directory="static", html=True), name="static")