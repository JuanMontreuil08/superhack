"""
Test: Save memories to Supermemory (localhost or cloud)
"""

import os
from dotenv import load_dotenv
from supermemory import Supermemory

load_dotenv(dotenv_path=".env.local")

base_url = os.environ.get("SUPERMEMORY_BASE_URL", "https://api.supermemory.ai")

client = Supermemory(
    api_key=os.environ.get("SUPERMEMORY_API_KEY"),
    base_url=base_url,
)

CONTAINER_TAG = "hackathon_test_user"

memories = [
    "Testing the save memory function. This is a test for the hackathon.",
    "I like using claude code and supermemory. I traveled to San Francisco on April 2026.",
]

print(f"Saving {len(memories)} memories to {base_url}...\n")

for i, content in enumerate(memories, start=1):
    result = client.add(
        content=content,
        container_tag=CONTAINER_TAG,
        custom_id=f"hackathon_test_{i}",  # evita duplicados si vuelves a correr el script
    )
    print(f"[{i}/{len(memories)}] saved -> id={result.id} status={result.status}")

print("\nDone.")