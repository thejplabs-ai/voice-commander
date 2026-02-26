# voice/ai_utils.py — Shared utilities for AI provider modules (gemini.py, openai_.py)
#
# Evita duplicação do bloco try/except/rate-limit/fallback que aparece
# de forma idêntica nos 7 modos de cada provider. (CODE-04)

from typing import Callable


def call_with_fallback(
    fn: Callable[[], str | None],
    fallback: str,
    is_rate_limit: Callable[[Exception], bool],
    rate_limit_msg: Callable[[], str],
    rate_limit_log: str,
    error_log_prefix: str,
) -> str:
    """
    Executa fn() dentro de um bloco try/except com tratamento padronizado:
    - Rate limit detectado → loga rate_limit_log e retorna rate_limit_msg()
    - Outra exceção → loga error_log_prefix + erro e retorna fallback
    - fn() retorna falsy → retorna fallback
    - fn() retorna str → retorna resultado

    Parâmetros:
      fn             — callable sem argumentos que retorna str | None
      fallback       — valor retornado em caso de falha ou resultado vazio
      is_rate_limit  — predicado para detectar erro de rate limit
      rate_limit_msg — callable que retorna a mensagem de rate limit
      rate_limit_log — mensagem a logar quando rate limit é detectado
      error_log_prefix — prefixo da mensagem de warning para outros erros
    """
    try:
        result = fn()
        if result:
            return result
    except Exception as e:
        if is_rate_limit(e):
            print(rate_limit_log)
            return rate_limit_msg()
        print(f"{error_log_prefix} ({e})")
    return fallback
