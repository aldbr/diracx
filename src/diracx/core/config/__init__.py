from __future__ import annotations

__all__ = ("Config", "ConfigSource", "LocalGitConfigSource")

import os
from abc import ABCMeta, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import git
import yaml
from cachetools import Cache, LRUCache, TTLCache, cachedmethod
from pydantic import AnyUrl, parse_obj_as

from ..exceptions import BadConfigurationVersion
from .schema import Config

if TYPE_CHECKING:
    from pydantic.config import BaseConfig
    from pydantic.fields import ModelField

DEFAULT_CONFIG_FILE = "default.yml"
DEFAULT_CS_CACHE_TTL = 5
MAX_CS_CACHED_VERSIONS = 1


class ConfigSourceUrl(AnyUrl):
    host_required = False

    @classmethod
    # TODO: This should return ConfigSourceUrl but pydantic's type hints are wrong
    def validate(cls, value: Any, field: ModelField, config: BaseConfig) -> AnyUrl:
        """Overrides AnyUrl.validate to add file:// scheme if not present."""
        if isinstance(value, str) and "://" not in value:
            value = f"git+file://{value}"
        return super().validate(value, field, config)


class ConfigSource(metaclass=ABCMeta):
    __registry: dict[str, type[ConfigSource]] = {}
    scheme: str

    def __init_subclass__(cls) -> None:
        if cls.scheme in cls.__registry:
            raise TypeError(f"{cls.scheme=} is already define")
        cls.__registry[cls.scheme] = cls

    @abstractmethod
    def __init__(self, backend_url: AnyUrl):
        ...

    @classmethod
    def create(cls, backend_url=None):
        if backend_url is None:
            backend_url = os.environ["DIRACX_CONFIG_BACKEND_URL"]
        if isinstance(backend_url, (str, Path)):
            backend_url = parse_obj_as(ConfigSourceUrl, str(backend_url))
        return cls.__registry[backend_url.scheme](backend_url)

    @abstractmethod
    def latest_revision(self) -> tuple[str, datetime]:
        ...

    @abstractmethod
    def read_raw(self, hexsha: str, modified: datetime) -> Config:
        ...

    def read_config(self) -> Config:
        """
        :raises:
            git.exc.BadName if version does not exist
        """
        hexsha, modified = self.latest_revision()
        return self.read_raw(hexsha, modified)

    def clear_caches(self):  # noqa
        pass


class LocalGitConfigSource(ConfigSource):
    scheme = "git+file"

    def __init__(self, backend_url: ConfigSourceUrl):
        if not backend_url.path:
            raise ValueError("Empty path for LocalGitConfigSource")

        repo_location = Path(backend_url.path)
        self.repo_location = repo_location
        self.repo = git.Repo(repo_location)
        self._latest_revision_cache: Cache = TTLCache(
            MAX_CS_CACHED_VERSIONS, DEFAULT_CS_CACHE_TTL
        )
        self._read_raw_cache: Cache = LRUCache(MAX_CS_CACHED_VERSIONS)

    def __hash__(self):
        return hash(self.repo_location)

    def clear_caches(self):
        self._latest_revision_cache.clear()
        self._read_raw_cache.clear()

    @cachedmethod(lambda self: self._latest_revision_cache)
    def latest_revision(self) -> tuple[str, datetime]:
        print("config latest_revision")
        try:
            rev = self.repo.rev_parse("master")
        except git.exc.ODBError as e:  # type: ignore
            raise BadConfigurationVersion(f"Error parsing latest revision: {e}") from e
        return rev.hexsha, rev.committed_datetime.astimezone(timezone.utc)

    @cachedmethod(lambda self: self._read_raw_cache)
    def read_raw(self, hexsha: str, modified: datetime) -> Config:
        """ "
        Returns the raw data from the git repo

        :returns hexsha, commit time, data
        """
        print("config read_raw")
        rev = self.repo.rev_parse(hexsha)
        blob = rev.tree / DEFAULT_CONFIG_FILE
        raw_obj = yaml.safe_load(blob.data_stream.read().decode())
        config = Config.parse_obj(raw_obj)
        config._hexsha = hexsha
        config._modified = modified
        return config
