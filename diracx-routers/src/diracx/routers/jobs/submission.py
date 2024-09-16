from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated

from fastapi import Body, Depends, HTTPException
from pydantic import BaseModel
from typing_extensions import TypedDict

from diracx.core.models import (
    JobStatus,
)
from diracx.core.properties import JOB_ADMINISTRATOR, NORMAL_USER

from ..auth import has_properties
from ..dependencies import (
    JobDB,
    JobLoggingDB,
)
from ..fastapi_classes import DiracxRouter
from ..utils.users import AuthorizedUserInfo, verify_dirac_access_token
from .access_policies import ActionType, CheckWMSPolicyCallable

logger = logging.getLogger(__name__)

router = DiracxRouter(dependencies=[has_properties(NORMAL_USER | JOB_ADMINISTRATOR)])


class InsertedJob(TypedDict):
    JobID: int
    Status: str
    MinorStatus: str
    TimeStamp: datetime


class JobID(BaseModel):
    job_id: int


MAX_PARAMETRIC_JOBS = 20

EXAMPLE_JDLS = {
    "Simple JDL": {
        "value": [
            """Arguments = "jobDescription.xml -o LogLevel=INFO";
Executable = "dirac-jobexec";
JobGroup = jobGroup;
JobName = jobName;
JobType = User;
LogLevel = INFO;
OutputSandbox =
    {
        Script1_CodeOutput.log,
        std.err,
        std.out
    };
Priority = 1;
Site = ANY;
StdError = std.err;
StdOutput = std.out;"""
        ]
    },
    "Parametric JDL": {
        "value": ["""Arguments = "jobDescription.xml -o LogLevel=INFO"""]
    },
}


@router.post("/")
async def submit_bulk_jobs(
    job_definitions: Annotated[list[str], Body(openapi_examples=EXAMPLE_JDLS)],
    job_db: JobDB,
    job_logging_db: JobLoggingDB,
    user_info: Annotated[AuthorizedUserInfo, Depends(verify_dirac_access_token)],
    check_permissions: CheckWMSPolicyCallable,
) -> list[InsertedJob]:
    await check_permissions(action=ActionType.CREATE, job_db=job_db)

    from DIRAC.Core.Utilities.ClassAd.ClassAdLight import ClassAd
    from DIRAC.Core.Utilities.ReturnValues import returnValueOrRaise
    from DIRAC.WorkloadManagementSystem.Service.JobPolicy import RIGHT_SUBMIT, JobPolicy
    from DIRAC.WorkloadManagementSystem.Utilities.ParametricJob import (
        generateParametricJobs,
        getParameterVectorLength,
    )

    class DiracxJobPolicy(JobPolicy):
        def __init__(self, user_info: AuthorizedUserInfo, allInfo: bool = True):
            self.userName = user_info.preferred_username
            self.userGroup = user_info.dirac_group
            self.userProperties = user_info.properties
            self.jobDB = None
            self.allInfo = allInfo
            self._permissions: dict[str, bool] = {}
            self._getUserJobPolicy()

    # Check job submission permission
    policyDict = returnValueOrRaise(DiracxJobPolicy(user_info).getJobPolicy())
    if not policyDict[RIGHT_SUBMIT]:
        raise HTTPException(HTTPStatus.FORBIDDEN, "You are not allowed to submit jobs")

    # TODO: that needs to go in the legacy adapter (Does it ? Because bulk submission is not supported there)
    for i in range(len(job_definitions)):
        job_definition = job_definitions[i].strip()
        if not (job_definition.startswith("[") and job_definition.endswith("]")):
            job_definition = f"[{job_definition}]"
        job_definitions[i] = job_definition

    if len(job_definitions) == 1:
        # Check if the job is a parametric one
        jobClassAd = ClassAd(job_definitions[0])
        result = getParameterVectorLength(jobClassAd)
        if not result["OK"]:
            print("Issue with getParameterVectorLength", result["Message"])
            return result
        nJobs = result["Value"]
        parametricJob = False
        if nJobs is not None and nJobs > 0:
            # if we are here, then jobDesc was the description of a parametric job. So we start unpacking
            parametricJob = True
            result = generateParametricJobs(jobClassAd)
            if not result["OK"]:
                return result
            jobDescList = result["Value"]
        else:
            # if we are here, then jobDesc was the description of a single job.
            jobDescList = job_definitions
    else:
        # if we are here, then jobDesc is a list of JDLs
        # we need to check that none of them is a parametric
        for job_definition in job_definitions:
            res = getParameterVectorLength(ClassAd(job_definition))
            if not res["OK"]:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST, detail=res["Message"]
                )
            if res["Value"]:
                raise HTTPException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    detail="You cannot submit parametric jobs in a bulk fashion",
                )

        jobDescList = job_definitions
        parametricJob = True

    # TODO: make the max number of jobs configurable in the CS
    if len(jobDescList) > MAX_PARAMETRIC_JOBS:
        raise HTTPException(
            status_code=HTTPStatus.BAD_REQUEST,
            detail=f"Normal user cannot submit more than {MAX_PARAMETRIC_JOBS} jobs at once",
        )

    result = []

    if parametricJob:
        initialStatus = JobStatus.SUBMITTING
        initialMinorStatus = "Bulk transaction confirmation"
    else:
        initialStatus = JobStatus.RECEIVED
        initialMinorStatus = "Job accepted"

    for (
        jobDescription
    ) in (
        jobDescList
    ):  # jobDescList because there might be a list generated by a parametric job
        res = await job_db.insert(
            jobDescription,
            user_info.preferred_username,
            user_info.dirac_group,
            initialStatus,
            initialMinorStatus,
            user_info.vo,
        )

        job_id = res["JobID"]
        logging.debug(
            f'Job added to the JobDB", "{job_id} for {user_info.preferred_username}/{user_info.dirac_group}'
        )

        await job_logging_db.insert_record(
            int(job_id),
            initialStatus,
            initialMinorStatus,
            "Unknown",
            datetime.now(timezone.utc),
            "JobManager",
        )

        result.append(res)

    return result

    # TODO: is this needed ?
    # if not parametricJob:
    #     self.__sendJobsToOptimizationMind(jobIDList)
    # return result

    return await asyncio.gather(
        *(job_db.insert(j.owner, j.group, j.vo) for j in job_definitions)
    )
