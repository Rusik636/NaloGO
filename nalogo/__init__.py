"""
Asynchronous Python client for Russian self-employed tax service (Moy Nalog).

This is a Python port of the PHP library shoman4eg/moy-nalog,
providing async HTTP client for interaction with lknpd.nalog.ru API.

Original PHP library: https://github.com/shoman4eg/moy-nalog
Author: Artem Dubinin <artem@dubinin.me>
License: MIT
"""

from .client import Client
from .exceptions import (
    ClientException,
    DateTimeFormatException,
    DomainException,
    ForbiddenException,
    InputException,
    NotFoundException,
    PhoneException,
    ServerException,
    TimezoneException,
    UnauthorizedException,
    UnknownErrorException,
    ValidationException,
)
from .timezone import API_TIMEZONE, DEFAULT_INPUT_TIMEZONE

__version__ = "1.0.0"
__all__ = [
    "API_TIMEZONE",
    "DEFAULT_INPUT_TIMEZONE",
    "Client",
    "ClientException",
    "DateTimeFormatException",
    "DomainException",
    "ForbiddenException",
    "InputException",
    "NotFoundException",
    "PhoneException",
    "ServerException",
    "TimezoneException",
    "UnauthorizedException",
    "UnknownErrorException",
    "ValidationException",
]
