"""Typed embedding transport results, independent of any inference library."""

import math
from typing import Annotated

from pydantic import Field

from .contracts import Contract


class EmbeddingBatch(Contract):
    model: Annotated[str, Field(min_length=1, max_length=300)]
    vectors: Annotated[list[list[Annotated[float, Field(strict=True)]]], Field(min_length=1, max_length=128)]
    usage: dict | None = None


def validate_embeddings(raw, count):
    result = EmbeddingBatch.model_validate(raw)
    if len(result.vectors) != count:
        raise ValueError('Embedding count differs from input count')
    dimension = len(result.vectors[0])
    if not 1 <= dimension <= 8192:
        raise ValueError('Embedding dimension must be between 1 and 8192')
    normalized = []
    for vector in result.vectors:
        if len(vector) != dimension or not all(math.isfinite(value) for value in vector):
            raise ValueError('Embedding dimensions and finite values must agree')
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise ValueError('Embedding vectors must have a finite nonzero norm')
        normalized.append([value / norm for value in vector])
    return {**result.model_dump(), 'vectors': normalized}
