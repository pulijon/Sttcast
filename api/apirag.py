"""
API models for RAG Service
Defines Pydantic models for request/response objects used in sttcast_rag_service.py
"""

from pydantic import BaseModel
from typing import List, Optional


# Models for /summarize endpoint
class EpisodeInput(BaseModel):
    ep_id: str
    transcription: str


class EpisodeOutput(BaseModel):
    ep_id: str
    summary: str
    tokens_prompt: int
    tokens_completion: int
    tokens_total: int
    estimated_cost_usd: float


# Models for embeddings
class EmbeddingInput(BaseModel):
    tag: str
    epname: str
    epdate: str
    start: float
    end: float
    content: str


# Models for /relsearch endpoint
class MultiLangText(BaseModel):
    es: str
    en: str


class References(BaseModel):
    label: MultiLangText
    file: str
    time: float
    tag: str


class RelSearchRequest(BaseModel):
    query: str
    embeddings: List[EmbeddingInput]
    requester: str = "unknown"  # IP del cliente final


class RelSearchResponse(BaseModel):
    tokens_prompt: int
    tokens_completion: int
    tokens_total: int
    estimated_cost_usd: float
    search: MultiLangText
    refs: List[References]


# Models for /getembeddings endpoint
class GetEmbeddingsResponse(BaseModel):
    embeddings: List[List[float]]  # List of byte arrays for embeddings
    tokens_prompt: int
    tokens_total: int


# Models for /getoneembedding endpoint
class GetOneEmbeddingRequest(BaseModel):
    query: str


class GetOneEmbeddingResponse(BaseModel):
    embedding: List[float]  # List of floats for the vector
