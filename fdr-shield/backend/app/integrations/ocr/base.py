from typing import Protocol, TypedDict


class FdrFields(TypedDict):
    fdr_number: str | None
    bank_name: str | None
    branch: str | None
    holder_name: str | None
    amount: str | int | float | None
    issue_date: str | None
    maturity_date: str | None


class FdrExtractor(Protocol):
    async def extract(self, pages: list[bytes]) -> FdrFields: ...
