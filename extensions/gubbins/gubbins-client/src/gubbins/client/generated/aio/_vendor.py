# --------------------------------------------------------------------------
# Code generated by Microsoft (R) AutoRest Code Generator (autorest: 3.10.4, generator: @autorest/python@6.31.0)
# Changes may cause incorrect behavior and will be lost if the code is regenerated.
# --------------------------------------------------------------------------

from typing import Optional

from azure.core import MatchConditions


def raise_if_not_implemented(cls, abstract_methods):
    not_implemented = [
        f for f in abstract_methods if not callable(getattr(cls, f, None))
    ]
    if not_implemented:
        raise NotImplementedError(
            "The following methods on operation group '{}' are not implemented: '{}'."
            " Please refer to https://aka.ms/azsdk/python/dpcodegen/python/customize to learn how to customize.".format(
                cls.__name__, "', '".join(not_implemented)
            )
        )


def quote_etag(etag: Optional[str]) -> Optional[str]:
    if not etag or etag == "*":
        return etag
    if etag.startswith("W/"):
        return etag
    if etag.startswith('"') and etag.endswith('"'):
        return etag
    if etag.startswith("'") and etag.endswith("'"):
        return etag
    return '"' + etag + '"'


def prep_if_match(
    etag: Optional[str], match_condition: Optional[MatchConditions]
) -> Optional[str]:
    if match_condition == MatchConditions.IfNotModified:
        if_match = quote_etag(etag) if etag else None
        return if_match
    if match_condition == MatchConditions.IfPresent:
        return "*"
    return None


def prep_if_none_match(
    etag: Optional[str], match_condition: Optional[MatchConditions]
) -> Optional[str]:
    if match_condition == MatchConditions.IfModified:
        if_none_match = quote_etag(etag) if etag else None
        return if_none_match
    if match_condition == MatchConditions.IfMissing:
        return "*"
    return None
