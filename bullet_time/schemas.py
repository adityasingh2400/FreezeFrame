"""Pydantic schemas for Gemini structured output."""

from pydantic import BaseModel, Field
from typing import List


class Moment(BaseModel):
    timestamp_sec: float = Field(
        description="Timestamp in seconds from the start of the video"
    )
    frame_number: int = Field(
        description="Nearest frame number at 30fps (frame_number = round(timestamp_sec * 30))"
    )
    label: str = Field(
        description="Short human-readable label, e.g. 'the release', 'peak of jump', 'ball catch'"
    )
    description: str = Field(
        description="One-sentence description of what is happening at this moment"
    )
    action_type: str = Field(
        description="Category of the action: wind-up, release, peak, contact, follow-through, or celebration"
    )
    confidence: float = Field(
        description="Confidence score from 0.0 to 1.0 that this is a distinct, interesting moment"
    )


class MomentCatalog(BaseModel):
    scene_description: str = Field(
        description="Brief description of the overall scene and activity being captured"
    )
    moments: List[Moment] = Field(
        description="List of key moments detected in the video, ordered chronologically"
    )


class MomentSelection(BaseModel):
    selected_index: int = Field(
        description="Index into the moments list of the best matching moment, or -1 if no match"
    )
    reasoning: str = Field(
        description="Brief explanation of why this moment best matches the user's query"
    )
