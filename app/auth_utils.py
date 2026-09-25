from __future__ import annotations

import re


USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_login(value: str) -> str:
    login = value.strip().casefold()
    if len(login) > 254:
        raise ValueError("Login deve ter no máximo 254 caracteres")
    if "@" in login:
        if not EMAIL_PATTERN.fullmatch(login):
            raise ValueError("Informe um e-mail válido")
    elif not USERNAME_PATTERN.fullmatch(login):
        raise ValueError("Login deve conter 3-64 letras, números, ponto, hífen ou sublinhado")
    return login
