"""Async image upload compression: stream to per-novel temp dir, compress in ProcessPoolExecutor."""

from __future__ import annotations

import asyncio
import os
import uuid
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from loguru import logger
from utils.paths import novel_attachment_upload_temp_dir

from engine.setup_chat.image_preprocess import ImagePreprocessError, compress_image_file_worker


class ImageUploadStatus(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ImageUploadJob:
    attachment_id: str
    novel_id: str
    filename: str
    input_path: str
    output_path: str
    status: ImageUploadStatus = ImageUploadStatus.PROCESSING
    error: str | None = None


_pool: ProcessPoolExecutor | None = None
_jobs: dict[str, ImageUploadJob] = {}


def _job_name(attachment_id: str) -> str:
    return f"img_compress:{attachment_id}"


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.replace("\\", "_").replace("/", "_").strip()
    return name or "attachment"


def _temp_paths(novel_id: str, attachment_id: str, filename: str) -> tuple[str, str]:
    root = novel_attachment_upload_temp_dir(novel_id)
    safe = _safe_filename(filename)
    input_path = os.path.join(root, f"{attachment_id}_in_{safe}")
    output_path = os.path.join(root, f"{attachment_id}_out.jpg")
    return input_path, output_path


def get_image_process_pool() -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        workers = min(8, (os.cpu_count() or 4))
        _pool = ProcessPoolExecutor(max_workers=workers)
    return _pool


async def shutdown_image_process_pool(*, wait: bool = True) -> None:
    global _pool
    if _pool is None:
        return
    pool = _pool
    _pool = None
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: pool.shutdown(wait=wait, cancel_futures=True))


def get_image_upload_status(attachment_id: str) -> ImageUploadStatus | None:
    job = _jobs.get(attachment_id)
    return job.status if job is not None else None


def get_image_upload_error(attachment_id: str) -> str | None:
    job = _jobs.get(attachment_id)
    if job is None or job.status != ImageUploadStatus.ERROR:
        return None
    return job.error


def _set_job(job: ImageUploadJob) -> None:
    _jobs[job.attachment_id] = job


def _remove_temp_files(*paths: str) -> None:
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def _cleanup_job_files(job: ImageUploadJob) -> None:
    _remove_temp_files(job.input_path, job.output_path)


def cancel_image_upload(attachment_id: str) -> None:
    from api.services.scheduler import SCHEDULER

    job = _jobs.get(attachment_id)
    if job is None:
        return
    if job.status != ImageUploadStatus.PROCESSING:
        return
    SCHEDULER.cancel_once(_job_name(attachment_id))
    _set_job(
        ImageUploadJob(
            attachment_id=job.attachment_id,
            novel_id=job.novel_id,
            filename=job.filename,
            input_path=job.input_path,
            output_path=job.output_path,
            status=ImageUploadStatus.CANCELLED,
        )
    )
    _cleanup_job_files(job)
    _jobs.pop(attachment_id, None)


async def stream_upload_to_temp(upload_file, dest_path: str) -> None:
    """Write UploadFile chunks to disk without loading the whole payload into memory."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as f:
        while True:
            chunk = await upload_file.read(65536)
            if not chunk:
                break
            f.write(chunk)


def begin_image_upload(novel_id: str, filename: str) -> tuple[str, str]:
    """Reserve attachment id + input temp path for a streamed upload."""
    from engine.setup_chat.attachment_persistence import (
        clear_image_description,
        find_persisted_attachment_id_by_filename,
    )

    existing_id = find_persisted_attachment_id_by_filename(novel_id, filename)
    attachment_id = existing_id or uuid.uuid4().hex
    if existing_id:
        cancel_image_upload(attachment_id)
        clear_image_description(novel_id, attachment_id)
        from engine.setup_chat.attachments import evict_attachment_memory

        evict_attachment_memory(attachment_id)
    input_path, output_path = _temp_paths(novel_id, attachment_id, filename)
    _set_job(
        ImageUploadJob(
            attachment_id=attachment_id,
            novel_id=novel_id,
            filename=filename,
            input_path=input_path,
            output_path=output_path,
        )
    )
    return attachment_id, input_path


def schedule_image_compression(attachment_id: str) -> None:
    from api.services.scheduler import SCHEDULER

    job = _jobs.get(attachment_id)
    if job is None or job.status != ImageUploadStatus.PROCESSING:
        return
    SCHEDULER.schedule_once(_job_name(attachment_id), 0.0, lambda: _run_compression(job))


async def _run_compression(job: ImageUploadJob) -> None:
    current = _jobs.get(job.attachment_id)
    if current is None or current.status != ImageUploadStatus.PROCESSING:
        return

    loop = asyncio.get_running_loop()
    pool = get_image_process_pool()
    try:
        await loop.run_in_executor(
            pool,
            compress_image_file_worker,
            job.input_path,
            job.output_path,
        )
    except asyncio.CancelledError:
        _cleanup_job_files(job)
        _jobs.pop(job.attachment_id, None)
        raise
    except ImagePreprocessError as exc:
        _set_job(
            ImageUploadJob(
                attachment_id=job.attachment_id,
                novel_id=job.novel_id,
                filename=job.filename,
                input_path=job.input_path,
                output_path=job.output_path,
                status=ImageUploadStatus.ERROR,
                error=str(exc),
            )
        )
        _cleanup_job_files(job)
        return
    except Exception:
        logger.exception("[image_upload] compression failed for {}", job.attachment_id)
        _set_job(
            ImageUploadJob(
                attachment_id=job.attachment_id,
                novel_id=job.novel_id,
                filename=job.filename,
                input_path=job.input_path,
                output_path=job.output_path,
                status=ImageUploadStatus.ERROR,
                error="图片压缩失败",
            )
        )
        _cleanup_job_files(job)
        return

    if _jobs.get(job.attachment_id) is None:
        _cleanup_job_files(job)
        return
    if _jobs[job.attachment_id].status == ImageUploadStatus.CANCELLED:
        _cleanup_job_files(job)
        _jobs.pop(job.attachment_id, None)
        return

    try:
        with open(job.output_path, "rb") as f:
            jpeg_bytes = f.read()
    except OSError:
        _set_job(
            ImageUploadJob(
                attachment_id=job.attachment_id,
                novel_id=job.novel_id,
                filename=job.filename,
                input_path=job.input_path,
                output_path=job.output_path,
                status=ImageUploadStatus.ERROR,
                error="图片压缩失败",
            )
        )
        _cleanup_job_files(job)
        return

    from engine.setup_chat.attachments import finalize_image_attachment

    finalize_image_attachment(job.novel_id, job.attachment_id, job.filename, jpeg_bytes)
    _cleanup_job_files(job)
    _jobs.pop(job.attachment_id, None)


async def cancel_all_image_uploads() -> None:
    from api.services.scheduler import SCHEDULER

    for attachment_id in list(_jobs):
        SCHEDULER.cancel_once(_job_name(attachment_id))
    for job in list(_jobs.values()):
        _cleanup_job_files(job)
    _jobs.clear()
