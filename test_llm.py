import requests

url = "http://localhost:11434/api/chat"

payload = {
    "model": "llama3.1:8b",
    "messages": [
        {
            "role": "user",
            "content": "Recommend ramen places in Jakarta. Return JSON."
        }
    ],
    "stream": False
}

response = requests.post(url, json=payload)

print(response.json())