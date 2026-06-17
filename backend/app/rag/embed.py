"""Turn text into embedding vectors via OpenAI `text-embedding-3-small`.

The rest of the RAG layer calls `embed()` — it doesn't care which provider is
behind it.  The client is built once and reused (like the Groq client in
`app.llm.client`), and the API key is read from the environment so it never
appears in code.
"""

from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI


@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    """Build the OpenAI client once and reuse it on every later call.

    `load_dotenv()` makes `OPENAI_API_KEY` available before `OpenAI()`
    reads it.  `@lru_cache` makes this a singleton — the client is created
    on the first call and returned from cache on every subsequent call.
    """
    load_dotenv()
    return OpenAI()


def embed(texts: list[str]) -> list[list[float]]:
    """Return an embedding vector for each input string.

    Each vector is a list of floats (the `text-embedding-3-small` model
    produces 1536-dimensional vectors).  Callers get back plain lists so they
    don't depend on any provider-specific type.
    """
    client = _get_client()
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    return [item.embedding for item in response.data]
