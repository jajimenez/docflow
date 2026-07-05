"""Module for generating text embeddings."""

import requests


def get_embedding(api_url: str, api_timeout: int, model: str, text: str) -> list[float]:
    """Get the embedding of a text.

    The Ollama embedding API is used to generate the embedding.

    Args:
        api_url: Ollama embedding API URL (e.g.
            "http://localhost:11434/api/embeddings").
        api_timeout: API requests timeout in seconds.
        model: Embedding model to use.
        text: Text to get the embedding for.

    Returns:
        Text embedding.
    """
    data = {"model": model, "prompt": text}
    res = requests.post(api_url, json=data, timeout=api_timeout)

    # Raise an exception if status code is 400-599 (error status)
    res.raise_for_status()

    return res.json()["embedding"]
