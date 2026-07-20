from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class SymbolNotFoundError(Exception):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"Unknown symbol: {symbol}")


class NoDataAvailableError(Exception):
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        super().__init__(f"No live snapshot available for {symbol} yet")


class DatabaseUnavailableError(Exception):
    pass


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(SymbolNotFoundError)
    async def symbol_not_found_handler(request: Request, exc: SymbolNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(NoDataAvailableError)
    async def no_data_available_handler(request: Request, exc: NoDataAvailableError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(DatabaseUnavailableError)
    async def database_unavailable_handler(request: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})
