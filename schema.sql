-- Executar uma vez no PostgreSQL. O script tambem cria a tabela sozinho.
CREATE TABLE IF NOT EXISTS precos_cripto (
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
    ON precos_cripto (moeda_id, coletado_em DESC);

-- Ultima coleta de cada moeda (view util para os cartoes do Power BI)
CREATE OR REPLACE VIEW vw_cripto_atual AS
SELECT DISTINCT ON (moeda_id, moeda_fiat) *
FROM precos_cripto
ORDER BY moeda_id, moeda_fiat, coletado_em DESC;
