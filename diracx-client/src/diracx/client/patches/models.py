from typing import Any
from ..generated._serialization import Model


class DeviceFlowErrorResponse(Model):
    """TokenResponse.

    All required parameters must be populated in order to send to Azure.

    :ivar access_token: Access Token. Required.
    :vartype access_token: str
    :ivar expires_in: Expires In. Required.
    :vartype expires_in: int
    :ivar state: State. Required.
    :vartype state: str
    """

    _validation = {
        "error": {"required": True},
    }

    _attribute_map = {
        "error": {"key": "error", "type": "str"},
    }

    def __init__(self, *, error: str, **kwargs: Any) -> None:
        """
        :keyword error: Access Token. Required.
        :paramtype error: str
        """
        super().__init__(**kwargs)
        self.error = error
