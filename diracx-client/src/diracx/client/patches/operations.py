import io
import json
from typing import Any, Dict, List

from azure.core.rest import HttpRequest
from azure.core.tracing.decorator import distributed_trace
from azure.core.utils import case_insensitive_dict
from azure.core.exceptions import map_error, HttpResponseError
from azure.core.pipeline import PipelineResponse

from ..generated.models._models import TokenResponse as TokenResponseGenerated
from ..generated.operations._operations import (
    AuthOperations as AuthOperationsGenerated,
    JobsOperations as JobsOperationsGenerated,
    _SERIALIZER,
)
from .models import DeviceFlowErrorResponse


def build_token_request(**kwargs: Any) -> HttpRequest:
    _headers = case_insensitive_dict(kwargs.pop("headers", {}) or {})

    accept = _headers.pop("Accept", "application/json")

    # Construct URL
    _url = "/api/auth/token"

    _headers["Accept"] = _SERIALIZER.header("accept", accept, "str")

    return HttpRequest(method="POST", url=_url, headers=_headers, **kwargs)


class AuthOperations(AuthOperationsGenerated):
    @distributed_trace
    async def get_oidc_token(
        self, device_code: str, client_id: str, **kwargs
    ) -> TokenResponseGenerated | DeviceFlowErrorResponse:
        request = build_token_request(
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": device_code,
                "client_id": client_id,
            },
        )
        request.url = self._client.format_url(request.url)

        _stream = False
        pipeline_response: PipelineResponse = (
            self._client._pipeline.run(  # pylint: disable=protected-access
                request, stream=_stream, **kwargs
            )
        )

        response = pipeline_response.http_response

        if response.status_code == 200:
            return self._deserialize("TokenResponse", pipeline_response)
        elif response.status_code == 400:
            return self._deserialize("DeviceFlowErrorResponse", pipeline_response)
        else:
            map_error(status_code=response.status_code, response=response, error_map={})
            raise HttpResponseError(response=response)


class JobsOperations(JobsOperationsGenerated):
    @distributed_trace
    def search(  # type: ignore[override]
        self,
        *,
        parameters: list[str] | None = None,
        search: list[str] | None = None,
        sort: list[str] | None = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """TODO"""
        body = {}
        if parameters is not None:
            body["parameters"] = parameters
        if search is not None:
            body["search"] = search
        if sort is not None:
            body["sort"] = sort
        # TODO: The BytesIO here is only needed to satify the typing
        # Probably an autorest bug
        body_data = io.BytesIO(json.dumps(body).encode("utf-8"))
        return super().search(body_data, **kwargs)

    @distributed_trace
    def summary(  # type: ignore[override]
        self,
        *,
        grouping: list[str] | None = None,
        search: list[str] | None = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """TODO"""
        body = {}
        if grouping is not None:
            body["grouping"] = grouping
        if search is not None:
            body["search"] = search
        # TODO: The BytesIO here is only needed to satify the typing
        # Probably an autorest bug
        body_data = io.BytesIO(json.dumps(body).encode("utf-8"))
        return super().summary(body_data, **kwargs)
