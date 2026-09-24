# Pipeline de Criptomoedas — API → Python/Pandas → PostgreSQL → Power BI

> **Projeto encerrado.** A coleta automática rodou de 2026-08-31 a 2026-09-24 e foi
> desligada — nada mais consome o dado desde que a [cripto-api](https://github.com/WilsonGorosthides/cripto-api)
> foi congelada. O código roda; o que parou foi o agendamento. Os números medidos da
> operação estão em [Encerramento](#encerramento).

## Problema

Acompanhar preço e capitalização de mercado de criptomoedas exige abrir site, copiar número e colar em planilha — várias vezes por dia, e sem histórico nenhum ao final do mês.

Este pipeline coleta os dados sozinho, guarda cada leitura com data e hora e entrega uma base pronta para o Power BI. O histórico se forma automaticamente a cada execução.

## Painel

![Painel do Power BI conectado ao PostgreSQL](docs/painel.png)

Painel construído sobre a tabela `precos_cripto` e a view `vw_cripto_atual`. A série de preço é a leitura direta do que o pipeline acumulou, gravado pelo Agendador de Tarefas do Windows.

**Esta captura é de 2026-09-01**, no segundo dia de operação — o painel não foi regravado depois, e a série seguiu crescendo até as 113 coletas registradas em [Encerramento](#encerramento). O que a imagem mostra é o formato do painel, não o volume final.

## Entrada

API pública da CoinGecko (`/coins/markets`), sem chave e sem custo. Por execução são coletados, para cada moeda: preço, capitalização de mercado, ranking, volume em 24h, variação percentual em 24h e oferta circulante.

## Saída

Tabela `precos_cripto` no PostgreSQL, um registro por moeda por coleta:

| coluna | tipo | descrição |
|---|---|---|
| `moeda_id` | texto | identificador da moeda (`bitcoin`) |
| `simbolo` | texto | sigla (`BTC`) |
| `nome` | texto | nome (`Bitcoin`) |
| `moeda_fiat` | texto | moeda de referência (`BRL`) |
| `preco` | numérico | preço no momento da coleta |
| `market_cap` | numérico | capitalização de mercado |
| `ranking` | inteiro | posição por capitalização |
| `volume_24h` | numérico | volume negociado em 24h |
| `variacao_24h_pct` | numérico | variação percentual em 24h |
| `oferta_circulante` | numérico | unidades em circulação |
| `coletado_em` | timestamp | data e hora da coleta (UTC) |

Exportação em CSV opcional, com `--csv`.

## Por que automatizar

A alternativa era o que o [Problema](#problema) descreve: abrir o site, copiar número, colar em planilha. **Nunca cronometrei quanto isso levaria**, então não há número aqui para comparar. O que a automação entrega e a planilha não entregava é **série histórica** — cada leitura fica gravada com data e hora, e o histórico existe no fim do mês sem ninguém ter mantido nada.

O lado automatizado, esse dá para medir. Em 113 execuções, o trecho entre "20 moedas recebidas da API" e "coleta finalizada" — tratamento com pandas mais gravação no banco — levou **mediana abaixo de 1 segundo**, média de 0,54 s e 5 s no pior caso.

Esse número **não é o tempo de ponta a ponta**: a partida do interpretador Python e a própria requisição HTTP ficam de fora, porque o log não as instrumenta.

---

## Como rodar

```bash
pip install -r requirements.txt

# testar sem internet e sem banco, com dados de amostra
python coleta_cripto.py --exemplo

# coleta real: top 20 moedas em reais
python coleta_cripto.py

# variações
python coleta_cripto.py --top 50
python coleta_cripto.py --moedas bitcoin,ethereum,solana
python coleta_cripto.py --moeda-fiat usd
python coleta_cripto.py --csv snapshot.csv
```

Sem a variável `DATABASE_URL` definida, o script grava em SQLite local (`cripto.db`), o que permite testar o fluxo inteiro antes de ter um PostgreSQL. Com ela definida, grava no PostgreSQL.

## Configuração

Copie `.env.example` para `.env`:

```
DATABASE_URL=postgresql+psycopg2://usuario:senha@localhost:5432/cripto
```

## Agendamento

> O agendamento **está desligado** desde 2026-09-24 (ver [Encerramento](#encerramento)). As instruções abaixo continuam válidas para quem quiser rodar o pipeline.

A coleta automatizada é o que forma o histórico. Uma vez por hora é folgado dentro do limite de requisições da API pública — em 113 coletas, a API nunca devolveu HTTP 429.

Vale a ressalva de que "de hora em hora" depende da máquina estar ligada. Aqui foram **113 coletas em 24 dias** — cerca de 4,7 por dia, não 24: o agendador dispara de hora em hora, mas só quando o computador está de pé.

**Linux / macOS** (`crontab -e`):

```
0 * * * * cd /caminho/do/projeto && /usr/bin/python3 coleta_cripto.py >> coleta.log 2>&1
```

**Windows** — Agendador de Tarefas: ação "Iniciar um programa", programa `python`, argumentos `coleta_cripto.py`, campo "Iniciar em" apontando para a pasta do projeto.

## Conectando ao Power BI

1. No Power BI Desktop: **Obter Dados → Banco de Dados PostgreSQL**
2. Servidor `localhost` (ou o host do banco), Banco de dados `cripto`
3. Se o Power BI pedir, instale o provedor **Npgsql** — é o conector .NET para PostgreSQL, exigido pelo Power BI Desktop
4. Selecione a tabela `precos_cripto`
5. Modo **Importação** para análise histórica; **DirectQuery** se quiser o dado sempre vivo

Visuais do painel:

- **Gráfico de linhas**: `preco` por `coletado_em`, segmentado por `simbolo` — é aqui que o histórico aparece
- **Gráfico de barras**: `market_cap` por moeda, limitado às 10 maiores, sobre `vw_cripto_atual`
- **Tabela**: ranking, símbolo, nome, preço e variação em 24h, sobre `vw_cripto_atual`
- **Cartões**: capitalização, variação em 24h e data da última coleta
- **Segmentação**: por `simbolo`

Duas armadilhas de agregação que o painel evita, e que valem mais que os visuais em si:

- **Preço não é aditivo.** O Power BI aplica `Soma` por reflexo em qualquer coluna numérica. Somar o preço de 20 moedas produz um número que não existe, e a curva resultante mede quantas coletas houve no período, não o preço. Preço usa `Média`; `market_cap` e `volume_24h`, que são aditivos, usam `Soma`.
- **Hierarquia de data em eixo de timestamp.** Ao arrastar `coletado_em` para o eixo, o Power BI insere uma hierarquia Ano/Trimestre/Mês/Dia e agrupa por dia do mês — o que ordena 01 antes de 31 e faz o tempo correr para trás quando a série cruza a virada do mês. O campo precisa entrar como valor contínuo.

Medida DAX útil para isolar a coleta mais recente:

```dax
UltimaColeta = CALCULATE(MAX(precos_cripto[coletado_em]), ALL(precos_cripto))
```

## Decisões de implementação

- **Snapshot, não sobrescrita.** Cada execução acrescenta linhas em vez de atualizar as existentes. Sem isso não há série temporal, e "posterior análise" fica impossível.
- **Timestamp único por execução.** Todas as linhas da mesma rodada compartilham o mesmo `coletado_em`, o que permite agrupar por coleta no Power BI sem tolerância de segundos.
- **Retry com espera progressiva no HTTP 429.** A API pública limita requisições por minuto; o script espera e tenta de novo em vez de falhar.
- **Chave única `(moeda_id, moeda_fiat, coletado_em)`.** Impede que uma execução duplicada suje o histórico.
- **Descarte de linhas sem preço ou sem id.** Registrado no log, não silenciosamente.
- **Fallback para SQLite.** Permite demonstrar o pipeline inteiro sem infraestrutura montada.

## Servindo os dados por HTTP

O histórico acumulado aqui é consumido por uma API REST em Spring Boot:
[**cripto-api**](https://github.com/WilsonGorosthides/cripto-api).

```
CoinGecko ──▶ cripto-pipeline (Python) ──▶ PostgreSQL ──▶ cripto-api (Java) ──▶ HTTP
              113 coletas, 24 dias                          sob demanda
                  (encerrado)
```

São repositórios separados porque são unidades de implantação diferentes: este é um job em
lote que roda por segundos e termina; a API é um serviço de vida longa. Cada um sobe,
escala e falha sem o outro.

A tabela `precos_cripto` pertence a este projeto. A API a lê como somente leitura e não
emite DDL sobre ela.

---

## Encerramento

A coleta automática foi desligada em **2026-09-24**. Motivo: a `cripto-api`, único consumidor
deste dado, foi congelada em 09/09 e não está hospedada — manter a coleta viva era custo sem
retorno. O agendamento foi **desabilitado, não removido**, e o banco foi preservado.

### O que a operação produziu

| medida | valor |
|---|---|
| Primeira coleta | 2026-08-31 17:39:50 |
| Última coleta | 2026-09-24 |
| Janela | **24 dias** |
| Coletas concluídas | **113** |
| Cadência real | ~4,7 por dia (o agendador dispara de hora em hora, mas só com a máquina ligada) |
| Moedas por coleta | 20 |
| Linhas gravadas | **2.260** — destas, 40 foram para o SQLite de fallback, nas duas primeiras rodadas, antes de o PostgreSQL estar configurado |

### O que o retry absorveu

O tratamento de falha de rede não ficou decorativo: foi exercitado.

| medida | valor |
|---|---|
| Tentativas que falharam e foram repetidas com sucesso | **25** |
| Coletas perdidas mesmo após esgotar as tentativas | **3** |
| Taxa de sucesso | **113 de 116** |
| Ocorrências de HTTP 429 | **nenhuma** |

As três perdas foram falha de DNS e timeout **da própria máquina**, não recusa da CoinGecko. E **nenhum 429 aconteceu** — o que o backoff salvou aqui foi rede instável, não limite de API.

**Limitação conhecida:** o retry repete em qualquer `requests.RequestException`, o que inclui HTTP 4xx — um 404 é tentado três vezes à toa. O certo seria repetir só em 429, 5xx e erro de rede.

### Reproduzir os números

Os valores das tabelas acima saem do `coleta.log`, versionado neste repositório:

```bash
grep -c "Coleta finalizada com sucesso" coleta.log   # coletas concluídas
grep -cE "ERROR \|"  coleta.log                      # coletas perdidas
grep -cE "WARNING \|" coleta.log                     # tentativas repetidas
```

A contagem autoritativa de linhas é a do banco:

```sql
SELECT count(*) AS linhas,
       count(DISTINCT coletado_em) AS coletas,
       count(DISTINCT moeda_id) AS moedas,
       min(coletado_em) AS primeira,
       max(coletado_em) AS ultima
  FROM precos_cripto;
```

### Religar

```powershell
Enable-ScheduledTask -TaskName "cripto-pipeline-coleta"
```

O código não foi tocado. Uma execução manual (`python coleta_cripto.py`) continua funcionando
e continua acrescentando à mesma série.
