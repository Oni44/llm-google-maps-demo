# LLM → Google Maps Demo (Local Ollama + FastAPI + Google Places)

A small demo that runs a **local LLM (Ollama)** and exposes a **FastAPI backend** to:
1) parse a user's natural-language request into a structured search plan (LLM),
2) query **Google Places Text Search**,
3) return results with **Google Maps embed URLs** (place + directions) and **open links**,
4) provide a simple web UI at `/ui`.

---

## Architecture (High level)

User (UI) → `POST /chat` → Ollama (local LLM) extracts:
- `search_query`
- `city`
- `count`
- `mode`

Backend then calls Google Places API and returns:
- place results (name, address, rating, lat/lng)
- `embed_place_url` and `embed_directions_url`
- `open_in_maps_url` and `directions_url`

---

## Requirements

- Python **3.9+**
- Ollama installed & running locally
- Google Cloud project with billing enabled (free trial credit is OK)
- Enabled APIs:
  - **Places API (or Places API New)**
  - **Maps Embed API**
  - (Optional) Directions API / Geocoding API if you expand features

---

## Security Notes (important)

- The Google Maps API key is stored in `.env` and **never committed to git**.
- In Google Cloud Console, the API key should be restricted:
  - **API Restrictions**: allow only required APIs (Places + Maps Embed).
  - **Application Restrictions** (recommended for production):
    - Use **IP address restriction** to your backend server’s public IP.
    - This prevents key theft abuse from other sources.
- Backend includes **rate limiting** using SlowAPI to reduce abuse and control usage.

---

## Setup

### 1) Create virtual environment

mkdir maps-llm-demo
cd maps-llm-demo

python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
# source venv/bin/activate


### 2) Install dependencies

pip install -r requirements.txt


### 3) Set up environment variables

Create a `.env` file in the root directory with the following variables:

GOOGLE_MAPS_API_KEY=your_api_key_here


### 4) Run Ollama

Make sure Ollama is running and your model is available, for example:

ollama run llama3.1:8b

This project calls Ollama Chat API at:

http://localhost:11434/api/chat

### 5) Start the backend

uvicorn main:app --reload --port 8000

Open:

API docs: http://127.0.0.1:8000/docs

UI: http://127.0.0.1:8000/ui/

API Endpoints
    Health Check

        GET /health

        Extract query only

        POST /ask

        Body: 
            { "question": "best ramen under 100k near Blok M" }

    Places search (direct)

        POST /places

        Body: 
            { "search_query": "best ramen under 100k", "city": "Jakarta", "count": 5, "origin": "Blok M", "mode": "driving" }

    Full pipeline (LLM → Places)

        POST /chat

        Body: 
            {
                "question": "find cheap ramen near Blok M under 100k",
                "origin": "Lebak Bulus",
                "city": "Jakarta",
                "count": 5,
                "mode": "driving"
            }

        Response includes:

            plan (LLM extracted JSON)

            results.places[] with embed + open links

Rate Limiting (SlowAPI)

    Example limits (can be changed in main.py):

    /chat: 10 requests/minute

    /places: 30 requests/minute

Assumptions

    Default city is "Jakarta" when not specified.

    Default mode is "driving".

    The LLM is instructed to return strict JSON; backend also includes a JSON-extraction fallback.