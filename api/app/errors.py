from fastapi import HTTPException, status


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def payment_required(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)
