from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional

from .storage import JobStore
from .users import LinkedAccount


class AccountStatus(Enum):
    HEALTHY = "healthy"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    ERROR = "error"


@dataclass
class UploadTask:
    job_id: str
    clip_id: str
    platform: str
    account_name: str
    priority: int = 0
    retries: int = 0
    created_at: float = field(default_factory=time.time)
    next_retry_at: float = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "UploadTask":
        return cls(**data)


@dataclass
class AccountQuota:
    account_name: str
    platform: str
    uploads_today: int = 0
    last_upload: float = 0
    status: AccountStatus = AccountStatus.HEALTHY
    quota_reset_at: float = 0
    consecutive_429: int = 0
    consecutive_403: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "AccountQuota":
        data = data.copy()
        data["status"] = AccountStatus(data["status"])
        return cls(**data)


class PublishQueueManager:
    """
    Cola persistente de publicaciones con:
    - Rate limiting adaptativo por cuenta
    - Rotación automática entre cuentas vinculadas
    - Backoff exponencial en 429
    - Pausa 24h en 403 (quota exceeded)
    - Fallback a Studio link si API falla
    """

    MAX_UPLOADS_PER_DAY = 6
    MIN_DELAY_BETWEEN_UPLOADS = 600
    MAX_RETRIES_429 = 5
    BASE_BACKOFF_429 = 300
    MAX_BACKOFF_429 = 86400
    QUOTA_RESET_HOUR = 0

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.queue_file = store.root / "publish_queue.json"
        self.quota_file = store.root / "account_quotas.json"
        self._queue: list[UploadTask] = []
        self._quotas: dict[str, AccountQuota] = {}
        self._processing = False
        self._load_state()

    def _load_state(self) -> None:
        if self.queue_file.exists():
            try:
                data = json.loads(self.queue_file.read_text())
                self._queue = [UploadTask.from_dict(t) for t in data]
            except Exception:
                self._queue = []
        if self.quota_file.exists():
            try:
                data = json.loads(self.quota_file.read_text())
                self._quotas = {k: AccountQuota.from_dict(v) for k, v in data.items()}
            except Exception:
                self._quotas = {}
        self._reset_daily_quotas()

    def _save_state(self) -> None:
        self.queue_file.write_text(json.dumps([t.to_dict() for t in self._queue]))
        self.quota_file.write_text(json.dumps({k: v.to_dict() for k, v in self._quotas.items()}))

    def _get_quota_key(self, platform: str, account: str) -> str:
        return f"{platform}:{account}"

    def _next_midnight_utc(self) -> float:
        now = time.time()
        local = time.gmtime(now)
        midnight = time.mktime((
            local.tm_year, local.tm_mon, local.tm_mday + 1,
            self.QUOTA_RESET_HOUR, 0, 0, 0, 0, 0
        ))
        return midnight

    def _reset_daily_quotas(self) -> None:
        now = time.time()
        for quota in self._quotas.values():
            if quota.quota_reset_at and now >= quota.quota_reset_at:
                if quota.status == AccountStatus.QUOTA_EXCEEDED:
                    quota.status = AccountStatus.HEALTHY
                quota.uploads_today = 0
                quota.consecutive_403 = 0
                quota.quota_reset_at = self._next_midnight_utc()

    def can_upload(self, platform: str, account: str) -> tuple[bool, str]:
        self._reset_daily_quotas()
        key = self._get_quota_key(platform, account)
        quota = self._quotas.get(key)
        now = time.time()

        if not quota:
            return True, "new_account"

        if quota.status == AccountStatus.QUOTA_EXCEEDED:
            if now >= quota.quota_reset_at:
                quota.status = AccountStatus.HEALTHY
                quota.uploads_today = 0
                quota.consecutive_403 = 0
                quota.quota_reset_at = self._next_midnight_utc()
                self._save_state()
                return True, "quota_reset"
            return False, f"quota_exceeded_until_{int(quota.quota_reset_at)}"

        if quota.status == AccountStatus.RATE_LIMITED:
            if now >= quota.next_retry_at:
                quota.status = AccountStatus.HEALTHY
                quota.consecutive_429 = 0
                self._save_state()
                return True, "backoff_complete"
            return False, f"rate_limited_until_{int(quota.next_retry_at)}"

        if quota.uploads_today >= self.MAX_UPLOADS_PER_DAY:
            quota.status = AccountStatus.QUOTA_EXCEEDED
            quota.quota_reset_at = self._next_midnight_utc()
            self._save_state()
            return False, "daily_limit_reached"

        if now - quota.last_upload < self.MIN_DELAY_BETWEEN_UPLOADS:
            return False, f"min_delay_not_met_{self.MIN_DELAY_BETWEEN_UPLOADS}s"

        return True, "ok"

    def get_best_account(self, platform: str, accounts: list[LinkedAccount]) -> Optional[LinkedAccount]:
        platform_key = self._platform_to_account_platform(platform)
        platform_accounts = [a for a in accounts if a.platform == platform_key]
        if not platform_accounts:
            return None

        candidates = []
        for acc in platform_accounts:
            can, _ = self.can_upload(platform, acc.name)
            if can:
                quota = self._quotas.get(self._get_quota_key(platform, acc.name))
                uploads = quota.uploads_today if quota else 0
                candidates.append((uploads, acc))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def _platform_to_account_platform(self, platform: str) -> str:
        mapping = {
            "youtube_shorts": "youtube",
            "youtube": "youtube",
            "tiktok": "tiktok",
            "facebook_reels": "facebook",
            "instagram_reels": "instagram",
            "otros": "otros",
        }
        return mapping.get(platform, "otros")

    def record_upload(self, platform: str, account: str, success: bool, error_code: int = 0) -> None:
        key = self._get_quota_key(platform, account)
        quota = self._quotas.get(key) or AccountQuota(account_name=account, platform=platform)
        now = time.time()

        if success:
            quota.uploads_today += 1
            quota.last_upload = now
            quota.status = AccountStatus.HEALTHY
            quota.consecutive_429 = 0
            quota.consecutive_403 = 0
        elif error_code == 429:
            quota.consecutive_429 += 1
            quota.status = AccountStatus.RATE_LIMITED
            backoff = min(
                self.BASE_BACKOFF_429 * (2 ** (quota.consecutive_429 - 1)),
                self.MAX_BACKOFF_429
            )
            quota.next_retry_at = now + backoff
        elif error_code == 403:
            quota.consecutive_403 += 1
            if quota.consecutive_403 >= 2:
                quota.status = AccountStatus.QUOTA_EXCEEDED
                quota.quota_reset_at = self._next_midnight_utc()

        self._quotas[key] = quota
        self._save_state()

    def enqueue(self, task: UploadTask) -> None:
        self._queue.append(task)
        self._queue.sort(key=lambda t: (t.priority, t.created_at))
        self._save_state()

    def enqueue_many(self, tasks: list[UploadTask]) -> None:
        self._queue.extend(tasks)
        self._queue.sort(key=lambda t: (t.priority, t.created_at))
        self._save_state()

    def get_pending_for_job(self, job_id: str) -> list[UploadTask]:
        return [t for t in self._queue if t.job_id == job_id]

    async def process_queue(self, store: JobStore, publish_fn, get_accounts_fn) -> None:
        if self._processing:
            return
        self._processing = True

        try:
            while self._queue:
                task = self._queue[0]
                now = time.time()

                if task.next_retry_at > now:
                    await asyncio.sleep(min(task.next_retry_at - now, 60))
                    continue

                can, reason = self.can_upload(task.platform, task.account_name)
                if not can:
                    accounts = get_accounts_fn()
                    best = self.get_best_account(task.platform, accounts)
                    if best and best.name != task.account_name:
                        task.account_name = best.name
                        self._save_state()
                        continue
                    task.next_retry_at = now + 300
                    self._save_state()
                    await asyncio.sleep(60)
                    continue

                self._queue.pop(0)
                try:
                    job = store.get_job(task.job_id)
                    clip = next((c for c in store.get_clips(task.job_id) if c.id == task.clip_id), None)
                    if job and clip:
                        result = await publish_fn(store, job, clip, task.platform, task.account_name)
                        success = result is not None and result.status == "publicado"
                        error_code = 0
                        if not success and hasattr(result, "error"):
                            error_code = getattr(result.error, "status_code", 0) if hasattr(result.error, "status_code") else 0
                        self.record_upload(task.platform, task.account_name, success, error_code)
                except Exception as e:
                    error_code = getattr(e, "response", {}).get("status_code", 0) if hasattr(e, "response") else 0
                    if hasattr(e, "status_code"):
                        error_code = e.status_code
                    self.record_upload(task.platform, task.account_name, False, error_code)
                    task.retries += 1
                    if task.retries <= self.MAX_RETRIES_429:
                        task.next_retry_at = time.time() + (60 * task.retries)
                        self._queue.insert(0, task)

                self._save_state()
                await asyncio.sleep(10)

        finally:
            self._processing = False

    def get_status_summary(self) -> dict:
        self._reset_daily_quotas()
        return {
            "pending_tasks": len(self._queue),
            "account_quotas": {
                k: {
                    "uploads_today": v.uploads_today,
                    "status": v.status.value,
                    "next_retry": v.next_retry_at if v.status == AccountStatus.RATE_LIMITED else None,
                    "quota_reset": v.quota_reset_at if v.status == AccountStatus.QUOTA_EXCEEDED else None,
                }
                for k, v in self._quotas.items()
            }
        }


_queue_manager_instance: Optional[PublishQueueManager] = None


def get_queue_manager(store: JobStore) -> PublishQueueManager:
    global _queue_manager_instance
    if _queue_manager_instance is None:
        _queue_manager_instance = PublishQueueManager(store)
    return _queue_manager_instance