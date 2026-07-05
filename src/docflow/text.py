"""Module for processing the text extracted from documents, regardless of the document
source (PDF, GitHub, Azure DevOps or Confluence).
"""

import requests
from langchain_text_splitters import MarkdownTextSplitter


def split_text(
    text: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """Split a Markdown text into chunks of a specified size with overlap.

    LangChain's MarkdownTextSplitter is used, which respects Markdown structure.

    Args:
        text: Markdown text to split.
        chunk_size: Maximum size of each chunk.
        chunk_overlap: Number of overlapping characters between chunks.

    Returns:
        List of text chunks.
    """
    if chunk_size <= 0:
        raise ValueError("Chunk size must be greater than 0")

    if chunk_overlap < 0:
        raise ValueError("Chunk overlap must be 0 or greater")

    splitter = MarkdownTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    return splitter.split_text(text)


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
