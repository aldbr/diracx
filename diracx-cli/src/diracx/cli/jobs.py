# Can't using PEP-604 with typer: https://github.com/tiangolo/typer/issues/348
# from __future__ import annotations
from __future__ import annotations

__all__ = ("app",)

import json
from pathlib import Path
from typing import Annotated

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress
from rich.table import Table
from rich.text import Text
from typer import FileText, Option

from diracx.api.jobs import ContentRange, get_job_sandbox
from diracx.api.jobs import download_sandbox as api_download_sandbox
from diracx.api.jobs import search as api_search
from diracx.api.jobs import submit as api_submit
from diracx.core.models import ScalarSearchOperator, SearchSpec, VectorSearchOperator
from diracx.core.preferences import OutputFormats, get_diracx_preferences

from .utils import AsyncTyper

app = AsyncTyper()


available_operators = (
    f"Scalar operators: {', '.join([op.value for op in ScalarSearchOperator])}. "
    f"Vector operators: {', '.join([op.value for op in VectorSearchOperator])}."
)


def parse_condition(value: str) -> SearchSpec:
    parameter, operator, rest = value.split(" ", 2)
    if operator in set(ScalarSearchOperator):
        return {
            "parameter": parameter,
            "operator": ScalarSearchOperator(operator),
            "value": rest,
        }
    elif operator in set(VectorSearchOperator):
        return {
            "parameter": parameter,
            "operator": VectorSearchOperator(operator),
            "values": json.loads(rest),
        }
    else:
        raise ValueError(f"Unknown operator {operator}")


@app.async_command()
async def search(
    parameter: list[str] = [
        "JobID",
        "Status",
        "MinorStatus",
        "ApplicationStatus",
        "JobGroup",
        "Site",
        "JobName",
        "Owner",
        "LastUpdateTime",
    ],
    condition: Annotated[
        list[str], Option(help=f'Example: "JobID eq 1000". {available_operators}')
    ] = [],
    all: bool = False,
    page: int = 1,
    per_page: int = 10,
):
    search_specs = [parse_condition(cond) for cond in condition]

    jobs, content_range = await api_search(
        parameter=parameter,
        search_specs=search_specs,
        all=all,
        page=page,
        per_page=per_page,
    )

    display(jobs, content_range)


@app.async_command()
async def submit(jdls: list[FileText]):
    console = Console()

    if not jdls:
        console.print(
            Panel(
                "[yellow]No JDL files provided. Please specify at least one JDL file.[/yellow]",
                title="Submission Error",
            )
        )
        return

    jobs = await api_submit([f.read() for f in jdls])

    if not jobs:
        console.print(
            Panel("[yellow]No jobs were submitted.[/yellow]", title="Submission Result")
        )
        return

    job_ids = []
    for job in jobs:
        job_id = (
            job.get("job_id") if isinstance(job, dict) else getattr(job, "job_id", None)
        )
        if job_id is not None:
            job_ids.append(str(job_id))
    if job_ids:
        console.print(
            Panel(
                Text(
                    f"Inserted {len(job_ids)} jobs with ids: {', '.join(job_ids)}",
                    style="green",
                ),
                title="Submission Result",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                "[red]No job IDs returned from submission.[/red]",
                title="Submission Result",
            )
        )


@app.async_command()
async def download_sandbox(
    job_id: int,
    sandbox_type: Annotated[
        str, Option(help="Type of sandbox to download: 'input', 'output', or 'all'")
    ] = "all",
    destination: Annotated[str, Option(help="Directory to save the sandboxes")] = ".",
):
    dest_path = Path(destination)
    dest_path.mkdir(parents=True, exist_ok=True)

    sandboxes = get_job_sandbox(job_id=job_id, sandbox_type=sandbox_type)

    if not sandboxes:
        Console().print(
            Panel(
                f"[yellow]No sandboxes found for job {job_id}.[/yellow]",
                title="Download Sandboxes",
            )
        )
        return

    with Progress() as progress:
        task = progress.add_task("Downloading sandboxes...", total=len(sandboxes))
        for s_type, pfn in sandboxes:
            subdir = dest_path / s_type
            subdir.mkdir(parents=True, exist_ok=True)
            try:
                await api_download_sandbox(pfn, subdir)
                progress.console.print(
                    f"[green]Downloaded {s_type} sandbox to {subdir}[/green]"
                )
            except Exception as e:
                progress.console.print(
                    f"[red]Failed to download {s_type} sandbox: {e}[/red]"
                )
            progress.advance(task)


def display(data, content_range: ContentRange):
    output_format = get_diracx_preferences().output_format
    match output_format:
        case OutputFormats.JSON:
            print(json.dumps(data, indent=2))
        case OutputFormats.RICH:
            display_rich(data, content_range)
        case _:
            raise NotImplementedError(output_format)


def display_rich(data, content_range: ContentRange) -> None:
    if not data:
        print(f"No {content_range.unit} found")
        return

    console = Console()
    columns = [str(c) for c in data[0].keys()]
    if sum(map(len, columns)) > 0.75 * console.width:
        table = Table(
            "Parameter",
            "Value",
            caption=content_range.caption,
            caption_justify="right",
        )
        for job in data:
            for k, v in job.items():
                table.add_row(k, str(v))
            table.add_section()
    else:
        table = Table(
            *columns,
            caption=content_range.caption,
            caption_justify="right",
        )
        for job in data:
            table.add_row(*map(str, job.values()))
    console.print(table)
