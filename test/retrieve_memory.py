"""
Test: Retrieve memories from Supermemory (localhost or cloud)
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

queries = [
    "Have I traveled to San Francisco before?",
    "favorite coding assistants"
]

print(f"Searching memories at {base_url}...\n")
print("=" * 60)

for query in queries:
    print(f"\nQuery: '{query}'")
    print("-" * 40)

    response = client.search.memories(
        q=query,
        container_tag=CONTAINER_TAG,
        search_mode="hybrid",
        limit=5,
    )

    if not response.results:
        print("  No results found.")
    else:
        for j, result in enumerate(response.results, 1):
            text = result.memory or result.chunk
            print(f"  [{j}] ({result.similarity:.2f}) {text}")

print("\n" + "=" * 60)
print("Retrieval test complete.")
