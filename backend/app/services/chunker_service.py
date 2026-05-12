"""Format-aware document chunker for RAG ingestion."""
import logging
import re
from typing import List
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import tiktoken
    _ENCODER = tiktoken.get_encoding("cl100k_base")
except ImportError:
    _ENCODER = None
    logger.warning("tiktoken not installed — falling back to word-based token estimation")


@dataclass
class Chunk:
    content: str
    token_count: int
    metadata: dict = field(default_factory=dict)


def count_tokens(text: str) -> int:
    if _ENCODER:
        return len(_ENCODER.encode(text))
    return len(text.split())


def chunk_document(
    content: str,
    doc_type: str = "text",
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    file_path: str = "",
) -> List[Chunk]:
    """Split document content into chunks with metadata."""
    if not content or not content.strip():
        return []

    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

    if doc_type == "markdown" or ext in ("md", "rst"):
        return _chunk_markdown(content, chunk_size, chunk_overlap, file_path)
    elif ext in ("yaml", "yml"):
        return _chunk_yaml(content, chunk_size, chunk_overlap, file_path)
    elif ext in ("json",):
        return _chunk_json(content, chunk_size, chunk_overlap, file_path)
    elif ext in ("tf", "hcl"):
        return _chunk_iac(content, chunk_size, chunk_overlap, file_path)
    else:
        return _chunk_plain_text(content, chunk_size, chunk_overlap, file_path)


def _chunk_markdown(content: str, chunk_size: int, overlap: int, file_path: str) -> List[Chunk]:
    """Split markdown on heading boundaries, then by paragraphs if sections are large."""
    sections = re.split(r'^(#{1,4}\s+.+)$', content, flags=re.MULTILINE)
    chunks: List[Chunk] = []
    current_heading = ""
    heading_stack: List[str] = []

    i = 0
    while i < len(sections):
        section = sections[i]
        if re.match(r'^#{1,4}\s+', section):
            current_heading = section.strip()
            level = len(section) - len(section.lstrip('#'))
            heading_stack = [h for h in heading_stack if _heading_level(h) < level]
            heading_stack.append(current_heading)
            i += 1
            continue

        if section.strip():
            section_tokens = count_tokens(section)
            if section_tokens <= chunk_size:
                chunks.append(Chunk(
                    content=section.strip(),
                    token_count=section_tokens,
                    metadata={"headings": list(heading_stack), "file_path": file_path},
                ))
            else:
                sub_chunks = _split_by_size(section, chunk_size, overlap)
                for sc in sub_chunks:
                    chunks.append(Chunk(
                        content=sc,
                        token_count=count_tokens(sc),
                        metadata={"headings": list(heading_stack), "file_path": file_path},
                    ))
        i += 1

    return chunks if chunks else _chunk_plain_text(content, chunk_size, overlap, file_path)


def _heading_level(heading: str) -> int:
    return len(heading) - len(heading.lstrip('#'))


def _chunk_yaml(content: str, chunk_size: int, overlap: int, file_path: str) -> List[Chunk]:
    """Split YAML on top-level keys."""
    blocks = re.split(r'^(?=\S)', content, flags=re.MULTILINE)
    return _merge_blocks(blocks, chunk_size, overlap, file_path, "yaml")


def _chunk_json(content: str, chunk_size: int, overlap: int, file_path: str) -> List[Chunk]:
    """For JSON, treat as plain text (structure-aware splitting is complex)."""
    return _chunk_plain_text(content, chunk_size, overlap, file_path)


def _chunk_iac(content: str, chunk_size: int, overlap: int, file_path: str) -> List[Chunk]:
    """Split HCL/Terraform on resource/data/variable/output blocks."""
    blocks = re.split(r'^(?=(?:resource|data|variable|output|module|provider|terraform|locals)\s)', content, flags=re.MULTILINE)
    return _merge_blocks(blocks, chunk_size, overlap, file_path, "iac")


def _chunk_plain_text(content: str, chunk_size: int, overlap: int, file_path: str) -> List[Chunk]:
    """Split plain text by paragraphs, then by sentences if needed."""
    paragraphs = re.split(r'\n\s*\n', content)
    return _merge_blocks(paragraphs, chunk_size, overlap, file_path, "text")


def _merge_blocks(blocks: List[str], chunk_size: int, overlap: int, file_path: str, doc_type: str) -> List[Chunk]:
    """Merge small blocks into chunks up to chunk_size tokens, split large blocks."""
    chunks: List[Chunk] = []
    current = ""
    current_tokens = 0

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        block_tokens = count_tokens(block)

        if block_tokens > chunk_size:
            # Flush current buffer
            if current.strip():
                chunks.append(Chunk(
                    content=current.strip(),
                    token_count=current_tokens,
                    metadata={"file_path": file_path, "doc_type": doc_type},
                ))
                current = ""
                current_tokens = 0
            # Split large block
            for sub in _split_by_size(block, chunk_size, overlap):
                chunks.append(Chunk(
                    content=sub,
                    token_count=count_tokens(sub),
                    metadata={"file_path": file_path, "doc_type": doc_type},
                ))
        elif current_tokens + block_tokens > chunk_size:
            # Flush and start new chunk
            if current.strip():
                chunks.append(Chunk(
                    content=current.strip(),
                    token_count=current_tokens,
                    metadata={"file_path": file_path, "doc_type": doc_type},
                ))
            # Overlap: keep tail of previous chunk
            if overlap > 0 and current.strip():
                tail = _get_tail(current, overlap)
                current = tail + "\n\n" + block
                current_tokens = count_tokens(current)
            else:
                current = block
                current_tokens = block_tokens
        else:
            current = (current + "\n\n" + block).strip()
            current_tokens += block_tokens

    if current.strip():
        chunks.append(Chunk(
            content=current.strip(),
            token_count=count_tokens(current.strip()),
            metadata={"file_path": file_path, "doc_type": doc_type},
        ))

    return chunks


def _split_by_size(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Split text into chunks by sentence boundaries, respecting token limits."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    results: List[str] = []
    current = ""
    current_tokens = 0

    for sent in sentences:
        sent_tokens = count_tokens(sent)
        if current_tokens + sent_tokens > chunk_size and current:
            results.append(current.strip())
            if overlap > 0:
                tail = _get_tail(current, overlap)
                current = tail + " " + sent
                current_tokens = count_tokens(current)
            else:
                current = sent
                current_tokens = sent_tokens
        else:
            current = (current + " " + sent).strip()
            current_tokens += sent_tokens

    if current.strip():
        results.append(current.strip())

    # If no sentence splitting occurred (one giant sentence), split by words
    if not results and text.strip():
        results = _split_by_words(text, chunk_size, overlap)

    return results


def _split_by_words(text: str, chunk_size: int, overlap: int) -> List[str]:
    """Last-resort word-level splitting."""
    words = text.split()
    results: List[str] = []
    i = 0
    while i < len(words):
        chunk_words = []
        tokens = 0
        while i < len(words) and tokens < chunk_size:
            chunk_words.append(words[i])
            tokens = count_tokens(" ".join(chunk_words))
            i += 1
        results.append(" ".join(chunk_words))
        # Overlap: step back
        if overlap > 0:
            step_back = max(1, int(len(chunk_words) * (overlap / chunk_size)))
            i -= step_back
    return results


def _get_tail(text: str, overlap_tokens: int) -> str:
    """Get the last ~overlap_tokens worth of text."""
    words = text.split()
    tail: List[str] = []
    for w in reversed(words):
        tail.insert(0, w)
        if count_tokens(" ".join(tail)) >= overlap_tokens:
            break
    return " ".join(tail)
