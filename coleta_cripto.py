"""
Pipeline de coleta de dados de criptomoedas.

Fluxo: API pública (CoinGecko) -> Python/Pandas -> PostgreSQL -> Power BI

Cada execucao grava um snapshot com timestamp, formando serie historica.
Rodar de forma agendada (cron / Agendador de Tarefas) monta o historico
que o dashboard usa para mostrar variacao ao longo do tempo.

Uso:
    python coleta_cripto.py                      # top 20 moedas em BRL
    python coleta_cripto.py --top 50
    python coleta_cripto.py --moedas bitcoin,ethereum,solana
    python coleta_cripto.py --csv saida.csv      # exporta tambem em CSV
    python coleta_cripto.py --exemplo            # roda sem internet, com dados de amostra
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy import create_engine, text

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv e opcional
    pass


API_URL = "https://api.coingecko.com/api/v3/coins/markets"
TABELA = "precos_cripto"

# A API publica da CoinGecko limita requisicoes por minuto no plano gratuito.
# Coletar 1x por hora (ou menos) fica folgado dentro do limite.
TENTATIVAS = 4
ESPERA_INICIAL = 5  # segundos, dobra a cada tentativa

# Colunas que vem da API -> nome final no banco
COLUNAS = {
    "id": "moeda_id",
    "symbol": "simbolo",
    "name": "nome",
    "current_price": "preco",
    "market_cap": "market_cap",
    "market_cap_rank": "ranking",
    "total_volume": "volume_24h",
    "price_change_percentage_24h": "variacao_24h_pct",
    "circulating_supply": "oferta_circulante",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("cripto")


# ----------------------------------------------------------------------
# 1. COLETA
# ----------------------------------------------------------------------
def coletar(moeda_fiat: str = "brl", top: int = 20, moedas: str | None = None) -> list[dict]:
    """Busca dados de mercado na API publica, com retry em caso de rate limit."""
    params = {
        "vs_currency": moeda_fiat,
        "order": "market_cap_desc",
        "per_page": min(top, 250),
        "page": 1,
        "sparkline": "false",
        "price_change_percentage": "24h",
    }
    if moedas:
        params["ids"] = moedas
        params.pop("per_page", None)

    espera = ESPERA_INICIAL
    for tentativa in range(1, TENTATIVAS + 1):
        try:
            resp = requests.get(API_URL, params=params, timeout=30)

            # 429 = limite de requisicoes. Espera e tenta de novo.
            if resp.status_code == 429:
                log.warning(
                    "Limite de requisicoes atingido (429). "
                    "Tentativa %d/%d, aguardando %ds.",
                    tentativa, TENTATIVAS, espera,
                )
                time.sleep(espera)
                espera *= 2
                continue

            resp.raise_for_status()
            dados = resp.json()
            log.info("Coletadas %d moedas da API.", len(dados))
            return dados

        except requests.RequestException as e:
            log.warning("Falha na requisicao (%d/%d): %s", tentativa, TENTATIVAS, e)
            if tentativa == TENTATIVAS:
                raise
            time.sleep(espera)
            espera *= 2

    raise RuntimeError("Nao foi possivel coletar os dados da API.")


def coletar_exemplo() -> list[dict]:
    """Dados de amostra, para testar o pipeline sem depender da internet."""
    caminho = Path(__file__).parent / "amostra.json"
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    log.info("Modo exemplo: %d moedas carregadas de amostra.json.", len(dados))
    return dados


# ----------------------------------------------------------------------
# 2. TRATAMENTO
# ----------------------------------------------------------------------
def tratar(dados: list[dict], moeda_fiat: str) -> pd.DataFrame:
    """Normaliza o JSON da API em um DataFrame limpo e tipado."""
    if not dados:
        raise ValueError("A API nao retornou nenhuma moeda.")

    df = pd.json_normalize(dados)

    faltando = [c for c in COLUNAS if c not in df.columns]
    if faltando:
        raise ValueError(f"A API nao retornou as colunas esperadas: {faltando}")

    df = df[list(COLUNAS)].rename(columns=COLUNAS)

    # Tipagem explicita: campo numerico que vem nulo da API vira NaN, nao string.
    numericas = [
        "preco", "market_cap", "ranking",
        "volume_24h", "variacao_24h_pct", "oferta_circulante",
    ]
    for col in numericas:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["simbolo"] = df["simbolo"].str.upper()
    df["moeda_fiat"] = moeda_fiat.upper()

    # Timestamp unico por execucao: todas as linhas do mesmo snapshot
    # compartilham o mesmo horario, o que facilita o agrupamento no Power BI.
    df["coletado_em"] = datetime.now(timezone.utc)

    # Sem preco nao ha o que analisar; sem id nao ha como relacionar no tempo.
    antes = len(df)
    df = df.dropna(subset=["moeda_id", "preco"])
    if len(df) < antes:
        log.warning("Descartadas %d linhas sem preco ou sem id.", antes - len(df))

    df = df.drop_duplicates(subset=["moeda_id"])

    # Ranking e inteiro, mas vira float por causa dos nulos da API.
    # Int64 (com I maiusculo) e o inteiro do pandas que aceita nulo.
    df["ranking"] = df["ranking"].astype("Int64")

    df = df.sort_values("market_cap", ascending=False).reset_index(drop=True)
    log.info("Tratamento concluido: %d linhas prontas.", len(df))
    return df


# ----------------------------------------------------------------------
# 3. ARMAZENAMENTO
# ----------------------------------------------------------------------
def conectar():
    """
    Conecta no PostgreSQL via DATABASE_URL.
    Sem a variavel definida, cai para SQLite local — util para testar
    o pipeline inteiro antes de ter um banco de verdade.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        log.info("Conectando no PostgreSQL.")
        return create_engine(url, future=True)

    log.warning("DATABASE_URL nao definida. Usando SQLite local (cripto.db).")
    return create_engine("sqlite:///cripto.db", future=True)


DDL_POSTGRES = f"""
CREATE TABLE IF NOT EXISTS {TABELA} (
    id                BIGSERIAL PRIMARY KEY,
    moeda_id          TEXT        NOT NULL,
    simbolo           TEXT        NOT NULL,
    nome              TEXT        NOT NULL,
    moeda_fiat        TEXT        NOT NULL,
    preco             NUMERIC(24, 8),
    market_cap        NUMERIC(24, 2),
    ranking           INTEGER,
    volume_24h        NUMERIC(24, 2),
    variacao_24h_pct  NUMERIC(12, 4),
    oferta_circulante NUMERIC(28, 4),
    coletado_em       TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_moeda_coleta UNIQUE (moeda_id, moeda_fiat, coletado_em)
);
CREATE INDEX IF NOT EXISTS idx_cripto_moeda_data
    ON {TABELA} (moeda_id, coletado_em DESC);
"""

DDL_SQLITE = f"""
CREATE TABLE IF NOT EXISTS {TABELA} (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    moeda_id          TEXT NOT NULL,
    simbolo           TEXT NOT NULL,
    nome              TEXT NOT NULL,
    moeda_fiat        TEXT NOT NULL,
    preco             REAL,
    market_cap        REAL,
    ranking           INTEGER,
    volume_24h        REAL,
    variacao_24h_pct  REAL,
    oferta_circulante REAL,
    coletado_em       TEXT NOT NULL,
    UNIQUE (moeda_id, moeda_fiat, coletado_em)
);
"""


def criar_tabela(engine) -> None:
    ddl = DDL_POSTGRES if engine.dialect.name == "postgresql" else DDL_SQLITE
    with engine.begin() as conn:
        for comando in filter(None, (c.strip() for c in ddl.split(";"))):
            conn.execute(text(comando))
    log.info("Tabela '%s' pronta.", TABELA)


def gravar(df: pd.DataFrame, engine) -> int:
    df.to_sql(TABELA, engine, if_exists="append", index=False, method="multi")
    log.info("Gravadas %d linhas em '%s'.", len(df), TABELA)
    return len(df)


# ----------------------------------------------------------------------
# ORQUESTRACAO
# ----------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description="Pipeline de coleta de criptomoedas.")
    p.add_argument("--top", type=int, default=20, help="Quantidade de moedas (padrao: 20).")
    p.add_argument("--moedas", help="IDs separados por virgula, ex: bitcoin,ethereum.")
    p.add_argument("--moeda-fiat", default="brl", help="Moeda de referencia (padrao: brl).")
    p.add_argument("--csv", help="Caminho para exportar o snapshot em CSV.")
    p.add_argument("--exemplo", action="store_true", help="Roda com dados de amostra, sem internet.")
    args = p.parse_args()

    try:
        dados = coletar_exemplo() if args.exemplo else coletar(
            moeda_fiat=args.moeda_fiat, top=args.top, moedas=args.moedas
        )
        df = tratar(dados, args.moeda_fiat)

        engine = conectar()
        criar_tabela(engine)
        gravar(df, engine)

        if args.csv:
            df.to_csv(args.csv, index=False, encoding="utf-8-sig")
            log.info("CSV exportado em %s.", args.csv)

        print()
        print(df[["ranking", "simbolo", "nome", "preco", "variacao_24h_pct"]].head(10).to_string(index=False))
        print()
        log.info("Coleta finalizada com sucesso.")
        return 0

    except Exception as e:
        log.error("Coleta falhou: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
