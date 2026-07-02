"""Module for splitting text into chunks."""

from langchain_text_splitters import MarkdownTextSplitter


def split_text(
    text: str,
    chunk_size: int = 1500,
    chunk_overlap: int = 200,
) -> list[str]:
    """Split a Markdown text into chunks of a specified size with overlap.

    This function uses LangChain's MarkdownTextSplitter, which respects Markdown
    structure.

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
