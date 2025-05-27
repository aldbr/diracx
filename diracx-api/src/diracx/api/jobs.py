from __future__ import annotations

import re

from diracx.client._generated.models._models import InsertedJob

__all__ = ("create_sandbox", "download_sandbox")

import hashlib
import logging
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Literal

import httpx

from diracx.client.aio import AsyncDiracClient
from diracx.client.models import SandboxInfo
from diracx.core.models import SearchSpec

from .utils import with_client

logger = logging.getLogger(__name__)

SANDBOX_CHECKSUM_ALGORITHM = "sha256"
SANDBOX_COMPRESSION: Literal["bz2"] = "bz2"
SANDBOX_OPEN_MODE: Literal["w|bz2"] = "w|bz2"


class ContentRange:
    unit: str | None = None
    start: int | None = None
    end: int | None = None
    total: int | None = None

    def __init__(self, header: str):
        if match := re.fullmatch(r"(\w+) (\d+-\d+|\*)/(\d+|\*)", header):
            self.unit, range, total = match.groups()
            self.total = int(total)
            if range != "*":
                self.start, self.end = map(int, range.split("-"))
        elif match := re.fullmatch(r"\w+", header):
            self.unit = match.group()

    @property
    def caption(self):
        if self.start is None and self.end is None:
            range_str = "all"
        else:
            range_str = (
                f"{self.start if self.start is not None else 'unknown'}-"
                f"{self.end if self.end is not None else 'unknown'} "
                f"of {self.total or 'unknown'}"
            )
        return f"Showing {range_str} {self.unit}"


@with_client
async def search(
    parameter: list[str],
    search_specs: list[SearchSpec],
    all: bool,
    page: int,
    per_page: int,
    *,
    client: AsyncDiracClient,
) -> tuple[list[dict], ContentRange]:
    """Search for jobs with the given parameters and conditions.
    If `all` is True, all parameters will be used, otherwise only the ones
    specified in the `parameter` list.
    The `condition` list should contain strings in the format:
    "ParameterName Operator Value" or "ParameterName Operator [Value1, Value2, ...]".

    """
    jobs, content_range = await client.jobs.search(
        parameters=None if all else parameter,
        search=search_specs if search_specs else None,
        page=page,
        per_page=per_page,
        cls=lambda _, jobs, headers: (
            jobs,
            ContentRange(headers.get("Content-Range", "jobs")),
        ),
    )
    return jobs, content_range


@with_client
async def submit(jdls: list[str], *, client: AsyncDiracClient) -> list[InsertedJob]:
    # TODO: call create_sandbox to upload the sandbox if needed but we would need DIRAC ClassAd
    return await client.jobs.submit_jdl_jobs(jdls)


@with_client
async def create_sandbox(paths: list[Path], *, client: AsyncDiracClient) -> str:
    """Create a sandbox from the given paths and upload it to the storage backend.

    Any paths that are directories will be added recursively.
    The returned value is the PFN of the sandbox in the storage backend and can
    be used to submit jobs.
    """
    with tempfile.TemporaryFile(mode="w+b") as tar_fh:
        with tarfile.open(fileobj=tar_fh, mode=SANDBOX_OPEN_MODE) as tf:
            for path in paths:
                logger.debug("Adding %s to sandbox as %s", path.resolve(), path.name)
                tf.add(path.resolve(), path.name, recursive=True)
        tar_fh.seek(0)

        hasher = getattr(hashlib, SANDBOX_CHECKSUM_ALGORITHM)()
        while data := tar_fh.read(512 * 1024):
            hasher.update(data)
        checksum = hasher.hexdigest()
        tar_fh.seek(0)
        logger.debug("Sandbox checksum is %s", checksum)

        sandbox_info = SandboxInfo(
            checksum_algorithm=SANDBOX_CHECKSUM_ALGORITHM,
            checksum=checksum,
            size=os.stat(tar_fh.fileno()).st_size,
            format=f"tar.{SANDBOX_COMPRESSION}",
        )

        res = await client.jobs.initiate_sandbox_upload(sandbox_info)
        if res.url:
            logger.debug("Uploading sandbox for %s", res.pfn)
            files = {"file": ("file", tar_fh)}
            async with httpx.AsyncClient() as httpx_client:
                response = await httpx_client.post(
                    res.url, data=res.fields, files=files
                )
                # TODO: Handle this error better
                response.raise_for_status()

            logger.debug(
                "Sandbox uploaded for %s with status code %s",
                res.pfn,
                response.status_code,
            )
        else:
            logger.debug("%s already exists in storage backend", res.pfn)
        return res.pfn


async def download_job_sandbox(
    job_id: int,
    sandbox_type: str,
    destination: Path,
    *,
    client: AsyncDiracClient,
) -> list[tuple[str, str]]:
    """Download the input or output sandbox for a job."""
    sandboxes = await get_job_sandbox(job_id, sandbox_type, client=client)
    if not sandboxes:
        logger.info("No sandboxes found for job %s", job_id)
        return sandboxes

    logger.info("Downloading %s sandboxes for job %s", len(sandboxes), job_id)
    downloaded_sandboxes = []
    for s_type, pfn in sandboxes:
        subdir = destination / s_type
        subdir.mkdir(parents=True, exist_ok=True)
        await download_sandbox(pfn, subdir, client=client)
        downloaded_sandboxes.append((s_type, pfn))

    return downloaded_sandboxes


@with_client
async def get_job_sandbox(
    job_id: int,
    sandbox_type: str,
    *,
    client: AsyncDiracClient,
) -> list[tuple[str, str]]:
    """Get the input or output sandbox for a job."""
    sandboxes: list[tuple[str, str]] = []
    if sandbox_type in ("input", "all"):
        input_sandboxes = await client.jobs.get_job_sandbox(job_id, "input")
        sandboxes.extend(("input", pfn) for pfn in input_sandboxes)
    if sandbox_type in ("output", "all"):
        output_sandboxes = await client.jobs.get_job_sandbox(job_id, "output")
        sandboxes.extend(("output", pfn) for pfn in output_sandboxes)
    return sandboxes


@with_client
async def download_sandbox(pfn: str, destination: Path, *, client: AsyncDiracClient):
    """Download a sandbox from the storage backend to the given destination."""
    res = await client.jobs.get_sandbox_file(pfn=pfn)
    logger.debug("Downloading sandbox for %s", pfn)
    with tempfile.TemporaryFile(mode="w+b") as fh:
        async with httpx.AsyncClient() as http_client:
            response = await http_client.get(res.url)
            # TODO: Handle this error better
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                fh.write(chunk)
        fh.seek(0)
        logger.debug("Sandbox downloaded for %s", pfn)

        with tarfile.open(fileobj=fh) as tf:
            tf.extractall(path=destination, filter="data")
        logger.debug("Extracted %s to %s", pfn, destination)
