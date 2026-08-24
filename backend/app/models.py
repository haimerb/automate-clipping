from __future__ import annotations

from pydantic import BaseModel


class Job(BaseModel):
    id: str
    filename: str
    owner_id: str | None = None
    source: str = "upload"
    source_url: str | None = None
    status: str = "queued"
    progress: int = 0
    error: str | None = None
    duration: float | None = None
    transcriber: str | None = None
    scorer: str | None = None
    clip_count: int = 0
    post_count: int = 0
    auto_publish: bool = False
    auto_publish_platform: str = "youtube_shorts"
    auto_publish_account: str | None = None
    created_at: str


class Clip(BaseModel):
    id: str
    index: int
    start: float
    end: float
    duration: float
    title: str
    line: str
    script: str
    score: float
    description: str = ""
    tags: list[str] = []
    thumbnail: str | None = None
    exported: bool = False
    export_name: str | None = None
    publish: bool = False


PLATFORMS = [
    "youtube_shorts",
    "tiktok",
    "facebook_reels",
    "instagram_reels",
    "otros",
]


class PlatformPost(BaseModel):
    id: str
    clip_id: str
    platform: str = "otros"
    status: str = "no_publicado"
    url: str | None = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    earnings: float = 0.0
    currency: str = "USD"
    account: str | None = None
    method: str = "manual"
    updated_at: str


class PlatformTotals(BaseModel):
    posts: int = 0
    views: int = 0
    likes: int = 0
    earnings: float = 0.0


class RecentPost(BaseModel):
    post_id: str
    job_id: str
    clip_id: str
    title: str
    platform: str
    status: str
    url: str | None = None
    views: int = 0
    likes: int = 0
    earnings: float = 0.0
    currency: str = "USD"


class DashboardStats(BaseModel):
    jobs: int = 0
    clips: int = 0
    posts: int = 0
    publicados: int = 0
    total_views: int = 0
    total_likes: int = 0
    total_earnings: float = 0.0
    by_platform: dict[str, PlatformTotals] = {}
    recent_posts: list[RecentPost] = []
    accounts: int = 0


class UserOut(BaseModel):
    id: str
    email: str
    name: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class LinkedAccountOut(BaseModel):
    id: str
    platform: str
    name: str
    handle: str
    token: str | None = None
    client_id: str | None = None
    has_client_secret: bool = False
    redirect_uri: str | None = None
    created_at: str


class LinkedAccountCreate(BaseModel):
    platform: str
    name: str
    handle: str = ""
    token: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None


class ClipPublish(BaseModel):
    publish: bool


class JobSettings(BaseModel):
    auto_publish: bool = False
    auto_publish_platform: str = "youtube_shorts"
    auto_publish_account: str | None = None


class PublishAllRequest(BaseModel):
    platform: str = "youtube_shorts"
    account: str | None = None


class PublishClipRequest(BaseModel):
    platform: str = "youtube_shorts"
    account: str | None = None


class PostCreate(BaseModel):
    platform: str = "otros"
    status: str = "no_publicado"
    url: str | None = None
    views: int = 0
    likes: int = 0
    comments: int = 0
    earnings: float = 0.0
    currency: str = "USD"
    account: str | None = None
    method: str = "manual"


class GenerateRequest(BaseModel):
    prompt: str
    duration: int = 30
    style: str = "professional"
    platform: str = "youtube_shorts"
    voice: str = "es_mx_female"
    auto_publish: bool = False
    account_id: str | None = None
