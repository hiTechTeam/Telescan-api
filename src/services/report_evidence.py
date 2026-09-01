import asyncio
import logging
import os
import stat
import weakref
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain.enums import ReportPhotoEvidenceStatus
from src.domain.ports import ReportRepositoryPort
from src.services.photos import PhotoService


logger = logging.getLogger(__name__)
EVIDENCE_WORKER_MARKER = Path("/run/telescan-api-singleton/evidence-worker.enabled")


class ReportEvidenceService:
    def __init__(
        self,
        reports: ReportRepositoryPort,
        photos: PhotoService,
        enabled_marker: Path | None = None,
    ) -> None:
        self._reports = reports
        self._photos = photos
        self._enabled_marker = enabled_marker
        self._report_locks: weakref.WeakValueDictionary[Any, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    def _report_lock(self, report_id: Any) -> asyncio.Lock:
        lock = self._report_locks.get(report_id)
        if lock is None:
            lock = asyncio.Lock()
            self._report_locks[report_id] = lock
        return lock

    def is_enabled(self) -> bool:
        if self._enabled_marker is None:
            return True
        try:
            metadata = self._enabled_marker.stat(follow_symlinks=False)
        except OSError:
            return False
        return (
            stat.S_ISREG(metadata.st_mode)
            and not self._enabled_marker.is_symlink()
            and stat.S_IMODE(metadata.st_mode) == 0o600
            and metadata.st_uid == os.geteuid()
            and metadata.st_nlink == 1
        )

    async def capture(self, report: Any) -> Any:
        if not self.is_enabled():
            return report
        report_id = getattr(report, "public_id")
        async with self._report_lock(report_id):
            current = await self._reports.get_by_public_id(report_id)
            if current is None:
                return report
            if (
                getattr(current, "target_photo_evidence_status", None)
                != ReportPhotoEvidenceStatus.COPY_FAILED
            ):
                return current
            source_url = getattr(current, "target_photo_source_url", None)
            if not source_url:
                return current
            now = datetime.now(UTC)
            evidence_url: str | None = None
            error: Exception | None = None
            try:
                evidence_url = await self._photos.copy_for_report(report_id, source_url)
                updated = await self._reports.update_photo_evidence(
                    report_id, evidence_url, now
                )
                if updated is not None:
                    return updated
            except Exception as exc:
                # Mongo write failures have an unknown outcome. Never blindly
                # delete the deterministic object: a concurrent/late CAS may
                # already have made it the report's durable evidence.
                error = exc

            latest = await self._reports.get_by_public_id(report_id)
            if latest is None:
                # No Mongo write can recreate a deleted report (the attach is
                # not an upsert), so the whole deterministic prefix is now
                # provably unreferenced.
                try:
                    await self._photos.delete_report_prefix(report_id)
                except Exception:
                    logger.exception(
                        "Deleted report evidence prefix cleanup remains pending "
                        "report_id=%s",
                        report_id,
                    )
                return report
            if (
                evidence_url is not None
                and getattr(latest, "target_photo_evidence_status", None)
                == ReportPhotoEvidenceStatus.AVAILABLE
                and getattr(latest, "target_photo_url", None) == evidence_url
            ):
                return latest
            try:
                await self._reports.record_photo_evidence_attempt(report_id, now)
            except Exception:
                logger.exception(
                    "Report evidence attempt recording failed report_id=%s", report_id
                )
            logger.warning(
                "Report photo evidence copy remains pending report_id=%s",
                report_id,
                exc_info=error,
            )
            return latest

    async def run_once(self, limit: int = 25) -> None:
        if not self.is_enabled():
            return
        for report in await self._reports.list_pending_photo_evidence(limit):
            await self.capture(report)

        now = datetime.now(UTC)
        for report in await self._reports.list_due_for_cleanup(now, limit):
            report_id = getattr(report, "public_id")
            async with self._report_lock(report_id):
                try:
                    current = await self._reports.get_by_public_id(report_id)
                    if current is None:
                        continue
                    retention_until = getattr(current, "retention_until", None)
                    if retention_until is None or retention_until > now:
                        continue
                    # Prefix deletion covers attached evidence and any object
                    # copied before an unknown/failed Mongo CAS. Only delete the
                    # durable DB retry record after S3 deletion succeeds.
                    await self._photos.delete_report_prefix(report_id)
                    evidence_url = getattr(current, "target_photo_url", None)
                    if evidence_url:
                        await self._photos.delete_by_url(evidence_url)
                    await self._reports.delete_by_public_id(report_id)
                except Exception:
                    logger.exception(
                        "Report retention cleanup remains pending report_id=%s",
                        report_id,
                    )


__all__ = ["EVIDENCE_WORKER_MARKER", "ReportEvidenceService"]
