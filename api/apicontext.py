"""
API models for Context Server
Defines Pydantic models for request/response objects used in context_server.py
"""

from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime


# Models for /addsegments endpoint
class AddSegmentsRequest(BaseModel):
    epname: str
    epdate: datetime
    epfile: str
    segments: List[dict]


# Models for /getcontext endpoint
class GetContextRequest(BaseModel):
    query: str
    n_fragments: int = 20
    only_embedding: bool = False
    query_embedding: Optional[List[float]] = None


class GetContextResponse(BaseModel):
    context: List[dict]
    query_embedding: Optional[List[float]] = None


# Models for /api/gen_stats endpoint
class GenStatsRequest(BaseModel):
    fromdate: Optional[str] = None
    todate: Optional[str] = None


class GetGeneralStatsResponse(BaseModel):
    total_episodes: int
    total_duration: float
    speakers: List[dict]


# Models for /api/speaker_stats endpoint
class SpeakerStat(BaseModel):
    tag: str
    episodes: List[dict]
    total_interventions: int
    total_duration: float
    total_episodes_in_period: int


class GetSpeakerStatsResponse(BaseModel):
    tags: List[str]
    stats: List[SpeakerStat]


class SpeakerStatsRequest(BaseModel):
    tags: List[str]
    fromdate: Optional[str] = None
    todate: Optional[str] = None
