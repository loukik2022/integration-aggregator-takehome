from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    GITHUB = "github"
    GOOGLE = "google"
    GITLAB = "gitlab"
    OIDC = "oidc"


class ProviderRegisterRequest(BaseModel):
    name: str
    provider: str
    client_id: str
    client_secret: str
    provider_options: Optional[Dict[str, str]] = None
    scopes: Optional[List[str]] = None


class ProviderRegisterResponse(BaseModel):
    name: str
    status: str = "registered"


class ConnectResponse(BaseModel):
    auth_url: str
    state: str


class CallbackResponse(BaseModel):
    status: str = "connected"
    provider: str
    user: str


class RequestStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class AsyncAcceptedResponse(BaseModel):
    request_id: str
    status: str = RequestStatus.PENDING.value
    location: str


class AsyncStatusResponse(BaseModel):
    request_id: str
    status: RequestStatus
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None


class OAuthStateRecord(BaseModel):
    state: str
    provider: str
    user: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AsyncRequestRecord(BaseModel):
    request_id: str
    provider: str
    user: str
    status: RequestStatus = RequestStatus.PENDING
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
