from typing import NotRequired, Protocol, TypedDict


class FdrFields(TypedDict):
    fdr_number: str | None
    bank_name: str | None
    branch: str | None
    holder_name: str | None
    amount: str | int | float | None
    issue_date: str | None
    maturity_date: str | None
    document_format: NotRequired[str | None]
    format_reason: NotRequired[str | None]


class FdrExtractor(Protocol):
    async def extract(self, pages: list[bytes]) -> FdrFields: ...
