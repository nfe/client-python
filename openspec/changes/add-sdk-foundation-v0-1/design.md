## Context

Motivação e escopo: ver `proposal.md`. Este documento decide **como** construir o v0.1.

Restrições que moldam tudo (regras do projeto, não renegociadas aqui): Python 3.10+, zero dependências de
runtime, sync + async desde o início (async via `asyncio.to_thread`), PyPI `nfe-io` / import `nfeio`,
design inspirado no stripe-python, contrato decidido por spec + sonda ao vivo.

Fontes de evidência citadas abaixo, por sigla:

| Sigla | Fonte |
|---|---|
| **SONDA** | `docs/contrato/probe-2026-10-08.md` (seções §1–§11), saída crua em `scripts/probes/out/` |
| **SPEC** | `nfeio-docs/static/api/*` (cópia mais fresca) |
| **FIX** | `../client-nodejs/tests/fixtures/live-contracts/*.json` e `../client-nodejs/tests/fixtures/webhook-signatures.json` |
| **VAULT** | `~/Documents/obsidian/nfeio/SDKs/…` (nota citada pelo nome) |
| **NODE/PHP/RUBY** | código dos irmãos (só como referência de design, nunca de contrato) |

Decisões marcadas **[D#]** foram **fechadas pelo André em 2026-10-08** (seção "Registro de decisões" de
`docs/contrato/DECISOES-PENDENTES.md`). Resumo do que está valendo: D1 = "D enxuta" (§2), D2 = A, D3 = A
(companies v2 com CRUD), D4 = A (CNPJ v3), D5 = A (reconciliação explícita), D6 = A, D7 = A
(`client.lookups`), D8 = A; auth `Authorization: <chave>`; licença MIT; `SECURITY.md` via GitHub Private
Vulnerability Reporting. Decisões novas surgidas na implementação ficam em
`docs/contrato/DECISOES-FASE2.md`.

## Goals / Non-Goals

**Goals:**

- Núcleo único (sans-IO) para sync e async, sem duplicar lógica de retry, paginação e polling.
- Nenhum caminho de código que possa reenviar uma emissão cujo resultado é desconhecido.
- Modelos de resposta tipados (mypy `--strict`) **sem perder** nenhum campo do fio.
- Toda divergência spec × fio conhecida tratada explicitamente e coberta por teste com fixture.
- Superfície pequena e estável: o que entra no v0.1 precisa sobreviver até o 1.0 sem quebra.

**Non-Goals:**

- NF-e, NFC-e, CT-e, DC-e, distribuição DF-e, cálculo de impostos, RTC (v0.2+).
- NFS-e v3 (CNPJ alfanumérico) — ver Riscos; o desenho reserva espaço para ela ([D7]).
- Pessoas jurídicas/físicas (`legalpeople`/`naturalpeople`), notificações, `municipaltaxes` (escrita),
  `DELETE /v2/webhooks` (apaga todos — fora por segurança).
- Geração de código a partir da OpenAPI (ver §12).
- Transportes httpx/aiohttp (o protocolo permite; não entregamos).

## Decisions

### §1. API pública: cliente explícito + serviços por recurso

```python
from nfeio import NfeClient, AsyncNfeClient, RequestOptions

client = NfeClient(api_key="…", data_api_key="…")          # ou env NFE_API_KEY / NFE_DATA_API_KEY
inv = client.service_invoices.create(
    company_id, {"borrower": {...}, "cityServiceCode": "…", "servicesAmount": 100.0},
    external_id="pedido-123",
    options=RequestOptions(timeout=90, max_retries=0),
)
inv.flow_status            # propriedade tipada snake_case (só campos curados, D1 enxuta)
inv["flowStatus"]          # acesso ao campo do fio (sempre disponível)
inv["borrower"]["name"]    # aninhado por chave: Mapping vira NfeObject; campo sem propriedade fica na chave
inv.last_response.request_id

async with AsyncNfeClient(api_key="…") as aclient:
    inv = await aclient.service_invoices.create_and_wait(company_id, params, external_id="pedido-123")
```

- **Cliente explícito, sem estado global** (stripe-python v8 `StripeClient`; o `stripe.api_key` global foi
  a maior fonte de bug multi-tenant no ecossistema). ERPs como Odoo são multi-empresa/multi-chave: cada
  `NfeClient` carrega sua configuração imutável.
- **Serviços como atributos** (`client.service_invoices`, `client.companies`, `client.certificates`,
  `client.webhooks`, `client.lookups`) — nomes e agrupamento em **[D7]**.
- **Métodos e parâmetros em snake_case** (`company_id`, `external_id`, `page_index`). Corpos de requisição
  seguem o fio em camelCase via `TypedDict` **[D2]**.
- **`RequestOptions`** (dataclass congelada, todos os campos opcionais), por chamada, sobrescreve o cliente:
  `api_key` (substitui a chave que o recurso usaria), `timeout` (`float | Timeout`), `max_retries`,
  `idempotency_key` (enviado como `Idempotency-Key`; **não** muda a política de retry porque a API o
  ignora — VAULT `PHP/Ask API — Idempotency-Key…`), `extra_headers` (não pode sobrescrever
  `Authorization`, `User-Agent`, `Content-Type`).
- **`external_id` não é `RequestOptions`:** é campo do corpo (`externalId`) com semântica de negócio (chave
  de dedupe). Vira argumento nomeado de `service_invoices.create` para ficar visível na assinatura.
- **Chaves:** `api_key` (emissão/gestão) e `data_api_key` (consultas). Se omitidas, lê `NFE_API_KEY` /
  `NFE_DATA_API_KEY`. **Sem fallback** de chave principal para hosts de dados: a chave principal recebe
  403 em todos os hosts de dados (SONDA §1), então o fallback só espalharia a chave mais poderosa sem
  ganho. Consulta sem `data_api_key` → `ConfigurationError` antes de abrir socket. Quem tem uma chave só
  passa o mesmo valor nos dois parâmetros, explicitamente.
- `NfeClient` é thread-safe e reutilizável; `close()` / context manager liberam o pool.

Alternativas descartadas: módulo global estilo `stripe.api_key` (estado compartilhado); resources como
métodos de classe do modelo (`ServiceInvoice.create(...)`, stripe legado) — mistura dado e transporte.

### §2. Modelos de resposta: visão tipada sobre o dict do fio [D1]

| Opção | Tipagem | Campos desconhecidos | Custo de manutenção | Usado por |
|---|---|---|---|---|
| A. Objeto dinâmico (`StripeObject`, dict + `__getattr__`) | fraca (stubs à parte) | preservados | baixo | stripe-python |
| B. `@dataclass(frozen, slots)` + `raw` | forte | só em `raw`; risco de DTO incompleto | alto (mapear cada campo) | PHP (DTO + `raw`), Ruby (`Data.define` + `raw`) |
| C. `TypedDict` do fio (camelCase) | média (chaves) | preservados (é dict) | baixo | Node (interfaces sobre JSON) |
| **D. Visão tipada: `Mapping` imutável do fio + propriedades snake_case tipadas** | forte nas propriedades | **preservados por construção** | médio | — (híbrido de A e B) |

**Decidido: D enxuta (André, 2026-10-08).** `NfeObject` implementa `Mapping[str, Any]` imutável sobre o
JSON decodificado. Regras:

- **Propriedades tipadas só onde corrigem ou tipam algo:** ids, status/enums abertos, datas (`datetime`
  aware; `date` para datas puras), dinheiro e alíquotas (`Decimal`), documentos (CNPJ/CPF como `str`
  normalizada) e os aninhados que contêm documento (`borrower`, `provider`). Texto livre (`name`,
  `description`, `cityServiceCode`, `uri`, …) fica **só** no acesso por chave. Cada modelo tem uma lista
  pequena; nada de espelhar a spec inteira.
- **Sem `__getattr__` dinâmico.** Evita a colisão com `items`/`keys`/`values`/`get` do `Mapping` (a NF-e
  da v0.2 tem campo `items`) e mantém erro de digitação visível para o mypy.
- **`obj["x"]` devolve o valor do fio**, com uma conversão: `Mapping` aninhado vira `NfeObject` genérico
  (imutável, com `to_dict()`), e lista vira `list` **nova** cujos `Mapping` também viram `NfeObject`
  (mutar a lista devolvida não altera o objeto). Escalares voltam como vieram (`float` para dinheiro,
  D6). `obj.to_dict()` continua devolvendo o fio puro (dicts e listas comuns).
- **Aninhado por propriedade** devolve o modelo tipado do aninhado (`inv.borrower` → `Party` com
  `federal_tax_number`); por chave devolve `NfeObject` genérico.
- Propriedades são **descritores declarativos** (`StrField("flowStatus")`, `DecimalField(...)`, …) que
  registram a chave do fio; o teste de alinhamento (§12) lê esse registro.
- `repr` mascara chaves sensíveis (`secret`, `password`, `apiKey`, sem distinção de maiúsculas) — a
  entrega de ping de webhook traz o `Secret` em claro; `to_dict()` não mascara.

- **Forward-compat sem esforço:** nada é copiado nem filtrado; campo novo no fio aparece em `obj["novo"]`
  e em `obj.to_dict()` no mesmo dia. Elimina a classe de bug "DTO cobre 13 de 39 campos" (VAULT
  `PHP/DTO ServiceInvoice incompleto`) e o `totalAmount` fantasma.
- **Lição do Ruby:** classes geradas que descartam chaves não listadas (`Data.define` + `from_api`) perderam
  dado — D não tem esse modo de falha.
- `to_dict()` devolve cópia profunda, JSON-serializável, com as chaves do fio; `__eq__` compara o dict.
- `last_response` (`status_code`, `headers` case-insensitive, `request_id`) em todo objeto/página.
- **Datas:** propriedades `datetime` (aware) com parser tolerante (sufixo `Z`, 0–7 dígitos fracionários,
  data sem hora) porque `datetime.fromisoformat` do 3.10 não aceita os formatos do fio
  (`2026-09-01T02:55:33.418+00:00`). Valor não parseável → propriedade `None`; o texto segue em `obj[...]`.
  Texto sem fuso é interpretado como UTC (**INFERÊNCIA**, registrada em `DECISOES-FASE2.md`).
- **Dinheiro e alíquotas [D6]:** propriedades devolvem `Decimal` construído de `repr(float)` (recupera o
  literal decimal do JSON para até 15 dígitos significativos); o dict cru fica com `float` (JSON nativo,
  serializável). Na requisição, `Decimal` é aceito e serializado como número JSON exato.
- **Enums abertos:** `flow_status` é `str`, com constantes em `FlowStatus` e `Literal` para os valores
  conhecidos — valor novo do servidor não quebra (ex.: `Error`, `WaitingReturnCancel`, ver §16).
- Tipos de documento fiscal (`federalTaxNumber`) expostos como `str` normalizado (só dígitos/letras),
  porque o fio alterna `int` (perde zeros à esquerda: CNPJ `00000000000191` vira `191`), string formatada
  e string crua (SONDA §9) — e o CNPJ alfanumérico não cabe em `int`.

### §3. Matriz host × família × chave

| Família (v0.1) | Base | Chave | SPEC | Prova |
|---|---|---|---|---|
| NFS-e v1 | `https://api.nfe.io/v1/companies/{id}/serviceinvoices` | principal | `nf-servico-v1.yaml` servers[0] | SONDA §1 (dados → 403), §6 |
| Empresas v2 **[D3]** | `https://api.nfse.io/v2/companies` | principal | `contribuintes-v2.json` | SONDA §1, §4 |
| Empresas v1 (legado; **não usada** — D3 = v2) | `https://api.nfe.io/v1/companies` | principal | `nf-servico-v1.yaml` | SONDA §4 |
| Certificados | `https://api.nfse.io/v2/companies/{id}/certificates` | principal | `contribuintes-v2.json` | SONDA §5 (GET); upload v2 = **INFERÊNCIA** (FIX provou o campo `file` só no `POST /v1/…/certificate`; confirmar na fase 2a, com v1 como plano B) |
| Webhooks | `https://api.nfse.io/v2/webhooks` | principal | `nf-servico-v1.yaml` servers[1] "Webhooks" | SONDA §8 (`api.nfe.io` idem) |
| CNPJ **[D4]** | `https://legalentity.api.nfe.io/v3/legalentities` | dados | `consulta-cnpj-v3.json` (sem host) + `consulta-cnpj.yaml` (host) | SONDA §9 |
| CPF | `https://naturalperson.api.nfe.io/v1/naturalperson` | dados | `cpf-api.yaml` | SONDA §1, §9 |
| CEP | `https://address.api.nfe.io/v2/addresses` | dados | `consulta-endereco.yaml` | SONDA §1, §9 |
| Download (redirect) | `https://api.nfse.io/v1/blob/download?b&e&s` | **nenhuma** | — | SONDA §6 |

- Cada recurso declara sua `ApiFamily` (`FISCAL` | `DATA`); o requestor escolhe chave e host pela família.
  `base_urls` é configurável por família (testes, proxy corporativo), nunca por recurso solto.
- **Esquema de auth: `Authorization: <chave>`** (crua, sem prefixo — decidido, Menor 1). A chave **nunca**
  segue um redirect (download 302 pré-assinado vai para outro host sem nenhum cabeçalho de credencial). É o único esquema que está **na spec**
  (`securitySchemes` de todas as famílias) **e** provado em todos os hosts (SONDA §1). `X-NFE-APIKEY`
  também funciona mas não está em spec alguma; e `Authorization` é redigido por padrão por proxies,
  APMs e loggers, enquanto um header custom tende a vazar em log. `?apikey=` nunca (vaza em log de URL).
- Não existe host sandbox: ambiente é atributo da empresa/chave (VAULT `PHP/review-07-14-2026/08`).
- A chave de dados recebeu 200 em companies/webhooks (SONDA §1) — anotado, **não** explorado: o
  roteamento segue a família.

### §4. Transporte stdlib plugável

```python
class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...   # nunca segue redirect
    def close(self) -> None: ...

class AsyncTransport(Protocol):
    async def send(self, request: HttpRequest) -> HttpResponse: ...
    async def aclose(self) -> None: ...
```

- **Implementação padrão sobre `http.client`, não `urllib.request`.** Motivo decisivo: classificar a
  **fase da falha** (§5). Com `http.client` o `connect()` é explícito: DNS, conexão recusada e handshake
  TLS falham **antes** de qualquer byte da requisição sair (`ConnectionNotEstablished`); qualquer falha
  depois disso é `RequestMaybeSent`. `urllib` mistura as duas num `URLError`. Além disso `urllib` segue
  redirects **reenviando headers ao novo host** — inaceitável com a chave em `Authorization`.
- **Pool:** LIFO de `HTTPSConnection` por host, com lock, máx. 10 ociosas/host. **Requisições não
  idempotentes (POST) sempre usam conexão nova**: falha em conexão keep-alive reaproveitada é ambígua
  (o servidor pode ou não ter lido), e uma emissão não pode cair nesse caso por economia de handshake.
- **TLS:** `ssl.create_default_context()`, `minimum_version = TLSv1_2`, verificação de hostname e cadeia
  sempre. Aceita `ssl_context` ou `ca_bundle` do usuário **somente para acrescentar confiança** (proxy
  corporativo); contexto com `CERT_NONE` ou `check_hostname=False` → `ConfigurationError`. Não há flag
  `verify=False`. Quem precisar mesmo (laboratório) injeta o próprio `Transport` — escolha explícita e
  visível em code review.
- **Timeouts finitos:** padrão `Timeout(connect=10.0, read=60.0)`; `read` é por operação de socket e há
  um **prazo total** por tentativa (`total=120.0`) checado entre leituras de chunk. `None`/infinito é
  rejeitado. 60 s de leitura acompanha o PHP e o 408 "60s" documentado na emissão (SPEC
  `nf-servico-v1.yaml` 408).
- **Limite de resposta:** leitura em chunks de 64 KiB até `max_response_bytes` (padrão 10 MiB, PDFs de NFS-e
  têm ~55 KB — SONDA §6); estourou → `ResponseTooLargeError`, conexão descartada. Envia
  `Accept-Encoding: identity` (sem gzip ⇒ sem bomba de descompressão).
- **User-Agent honesto:** `nfe-io-python/<__version__> python/<major>.<minor> <platform.system().lower()>`
  + sufixo opcional `app_info=("odoo-l10n_br_nfse_nfeio", "18.0.1.0")` → `… odoo-l10n_br_nfse_nfeio/18.0.1.0`.
  `__version__` vem de um único `src/nfeio/_version.py`, lido pelo hatchling; teste falha se outra literal
  de versão aparecer no pacote. Lição do Node v6 (CHANGELOG: 93.995 requisições/30 dias, 23 variantes de
  UA, **uma** versão reportada, nome de pacote inexistente). O sufixo `app_info` atende o plano de
  telemetria por módulo de ERP (VAULT `ideias-integracoes/03`).
- **Multipart sem dependências** (`_multipart.encode`): boundary `secrets.token_hex(16)`, partes `file`
  (filename sanitizado: sem `"`, CR, LF; `Content-Type: application/x-pkcs12`) e `password`; corpo em
  `bytes` (certificado A1 tem poucos KB). Nome do campo `file` (minúsculo, SPEC v1 e FIX
  `certificate-upload-field.json`: `file`/`File` aceitos, `certificate` → 400).
- **Redirects:** o transporte devolve o 3xx. Só a operação de download segue: até 3 saltos, **só https**,
  **sem nenhuma credencial** (a URL pré-assinada é autoportante; o salto muda de `api.nfe.io` para
  `api.nfse.io` — SONDA §6). Sem allowlist de host (a inbound usa R2, VAULT `P1/00` ②).
- **`Location` de 202** nunca é seguido como URL: só o **path** é lido (vem `http://` — FIX
  `service-invoice-rtc-create.json`), validado contra `/v1/companies/{company_id}/serviceinvoices/{id}` e o
  id extraído; a URL de polling é reconstruída a partir da base configurada.

### §5. Retry ciente de método e de fase (port do PHP `RetryingTransport`)

Tabela (VAULT `PHP/Retry seguro e idempotência`, PHP `src/Http/RetryingTransport.php:18-22`, adaptada):

| Método | 429 | 408, 500, 502, 503, 504 | falha antes de conectar | falha após envio / timeout de leitura |
|---|---|---|---|---|
| GET, HEAD, PUT, DELETE | retenta | retenta | retenta | retenta |
| POST (qualquer) | **não** [D8] | **não** | retenta | **não** |

- Outros 4xx nunca são retentados. 501/505+ não são transitórios.
- **Diferença deliberada do PHP:** o PHP retenta POST com `Idempotency-Key` em tudo. Aqui **não** — a API
  ignora o header (VAULT `PHP/Ask API…`), então a premissa é falsa hoje. Quando a API honrar, basta
  liberar POST+chave na tabela (mudança aditiva).
- **PUT de webhook é full-replace** (idempotente de fato) → retentável. `DELETE` de cancelamento é
  idempotente no efeito; um segundo cancelamento devolve erro de negócio, não duplica.
- Backoff: `delay(n) = min(max_delay, base · 2^(n−1)) · U(0.7, 1.3)`, padrões `max_retries=3` (4
  tentativas), `base=1.0 s`, `max_delay=30 s` — mesmos números de PHP/Ruby/Node para comportamento
  previsível entre SDKs. Jitter via `random.SystemRandom` (evita alerta do bandit, sem custo relevante).
- **`Retry-After`:** segundos inteiros **ou** HTTP-date (`email.utils.parsedate_to_datetime`); usado se
  ≤ `max_retry_after` (60 s); maior que isso → não retenta, levanta `RateLimitError(retry_after=…)`.
  (PHP/Ruby só aceitam inteiro.) **INFERÊNCIA:** a API manda `Retry-After` — nunca observado (SONDA §2).
- Cada tentativa é registrada em `logging.getLogger("nfeio")` em DEBUG, com método, host, path, status,
  tentativa, atraso, `x-request-id` — **nunca** headers de auth, corpo ou query.

**Dedupe de emissão por `externalId` [D5]:**

- `service_invoices.create(..., external_id=…)` grava `externalId` no corpo. A API rejeita o segundo POST
  com o mesmo valor (`400 "service invoice with external id (…) already exists"`, sem código) — VAULT
  `PHP/Retry seguro…`, probe 2026-07-05.
- Erros com resultado incerto (5xx, 408, falha após envio, em POST de emissão) saem como a classe normal
  (`ServerError`, `APIConnectionError`) **com `outcome_unknown=True` e `external_id`** preenchidos. O 400
  de duplicidade vira `DuplicateExternalIdError(InvalidRequestError)` reconhecido pelo texto (casamento
  tolerante: "external id" + "already exists"), carregando `external_id`.
- `find_by_external_id(company_id, external_id, *, wait=0.0) -> ServiceInvoice | None`: `GET
  …/external/{id}`; desembrulha a **lista** (`{"serviceInvoices":[…]}`; vazio = `None`, não 404 —
  SONDA §6). Com `wait>0`, repete com backoff até o prazo para cobrir o atraso de indexação logo após o
  202 (VAULT: "segundos").
- Recomendação: **reconciliação explícita** — o SDK nunca reenvia uma emissão sozinho; a doc traz a
  receita de 6 linhas (`try create / except outcome_unknown or Duplicate → find_by_external_id(wait=30)`).

### §6. Hierarquia de erros

```
NfeError
├── ConfigurationError            (também ValueError)  chave ausente, TLS inseguro, opções inválidas
├── InvalidParameterError         (também ValueError)  ID/CNPJ/CPF/CEP inválido antes da requisição
├── APIError                      status_code, message, error_code, body (bytes), json_body, headers,
│   │                             request_id (x-request-id), trace_id (ProblemDetails), outcome_unknown
│   ├── InvalidRequestError       400, 405, 410, 415, 422 e demais 4xx não listados abaixo
│   │   └── DuplicateExternalIdError
│   ├── AuthenticationError       401
│   ├── PermissionDeniedError     403  (mensagem orienta: "esta família usa api_key|data_api_key")
│   ├── NotFoundError             404
│   ├── ConflictError             409
│   ├── RateLimitError            429  (+ retry_after)
│   └── ServerError               5xx  (408 também, por ser timeout do lado do servidor)
├── APIConnectionError            falha de rede; phase = NOT_ESTABLISHED | MAYBE_SENT; outcome_unknown
│   └── APITimeoutError
├── ResponseTooLargeError
├── UnexpectedResponseError       2xx com corpo não parseável ou forma impossível (ex.: 202 sem id)
├── InvoiceProcessingError        polling terminou em IssueFailed/CancelFailed/Error (+ invoice, flow_message)
├── PollingTimeoutError           prazo do wait esgotado (+ último estado)
└── SignatureVerificationError    só em construct_event (verify_signature devolve bool)
```

- Nomes evitam colidir com builtins (`APITimeoutError`, não `TimeoutError`).
- **Extração de mensagem** cobre os 5 envelopes vistos hoje (SONDA §3): corpo vazio → texto padrão por
  status; **string JSON crua**; `{"errors":[{"code","message"}]}` (junta mensagens, `error_code` = 1º
  `code`); `{"code","message"}`; ProblemDetails (`title` + `errors{campo:[…]}` → `"campo: msg"`;
  `traceId`). Mensagem saneada (sem caracteres de controle) e truncada em 1.000 caracteres; corpo
  integral fica em `body`. Node/PHP/Ruby cobrem só parte disso (PHP e Ruby perdem string crua e
  ModelState; Node mapeia 403 como `ValidationError`).
- `str(err)` e `repr(err)` nunca incluem headers de auth nem o corpo inteiro.

### §7. Paginação

- **Offset v1 (1-based)** — NFS-e: `list(company_id, *, page_index=1, page_count=?, issued_begin=…,
  issued_end=…, created_begin=…, created_end=…) -> OffsetPage[ServiceInvoice]`. Nomes espelham o fio
  (`pageIndex`/`pageCount`) para casar com a doc da API; `page_count` = itens por página.
- O fio **não traz totais** (`{serviceInvoices, page:int}`, mesmo com `hasTotals=true` — SONDA §6), logo
  `has_more = len(data) == page_count` (**inferência** controlada: no pior caso, 1 requisição extra que
  volta vazia).
- Validação local: `page_index ≥ 1`; `page_count` em 1–50 para NFS-e, **2–50** para companies v1 (o
  servidor rejeita 1 com mensagem que diz "between 1 and 50" — SONDA §4). Limites em uma tabela única.
- **Cursor** — companies v2 (**[D3]**): `list(*, limit=10, starting_after=None, ending_before=None) ->
  CursorPage[Company]`; `has_more` do fio. `limit` validado em 1–50 (`limit=0` devolve
  `hasMore:true` com lista vazia — loop infinito garantido sem a validação, SONDA §4).
- `page.auto_paging_iter()` (sync: `Iterator[T]`; async: `AsyncIterator[T]`) percorre a página atual e as
  seguintes e para em página vazia **independentemente** de `has_more`. No cursor, as páginas seguintes usam
  `limit=50`; no offset, mantém o `page_count` da primeira página (trocar o tamanho no meio desloca o
  `pageIndex` e pularia itens) — a doc recomenda `list(..., page_count=50).auto_paging_iter()`. Também
  `page.next_page() -> Page | None`.
- Sem `list_all()` que materializa tudo em memória (contas com milhares de notas).

### §8. Fluxo assíncrono 202 + Location e polling

- `create()` aceita 202 (assíncrono, caso normal), 200/201 (imediato). Com 202: o corpo
  (`{id, environment, flowStatus[, flowMessage]}`, FIX `service-invoice-rtc-create.json`) é **preservado**
  como `ServiceInvoice` parcial (o Node descarta o corpo); `id` do corpo, ou do path do `Location` se
  faltar; sem nenhum dos dois → `UnexpectedResponseError`.
- `cancel()` idem: 202 + `Location` (**INFERÊNCIA** de escrita: VAULT memória
  `integration-tests-need-emission-capable-company`, `Node/review-07-20-2026/01`; spec diz 200 string).
  Aceita também 200 com corpo de nota ou string.
- `wait(company_id, invoice_id, *, timeout=120, initial_interval=1.0, max_interval=10.0, backoff=1.5,
  raise_on_failure=True) -> ServiceInvoice`: faz `GET …/serviceinvoices/{id}` até `flowStatus` terminal.
  **Não** usa `/status`: essa rota não existe em GET (400 de binding `rpsNumber` — SONDA §6, contrariando
  a review do PHP).
- Terminais: `Issued`, `Cancelled` (sucesso); `IssueFailed`, `CancelFailed`, `Error` (falha →
  `InvoiceProcessingError` com `flow_message`). Não terminais conhecidos (SPEC enum + RTC):
  `PullFromCityHall`, `WaitingCalculateTaxes`, `WaitingDefineRpsNumber`, `WaitingSend`, `WaitingSendCancel`,
  `WaitingReturn`, `WaitingReturnCancel`, `WaitingDownload`. **Valor desconhecido = não terminal** (continua
  até o prazo) — mais seguro que declarar sucesso/falha por palpite.
- 404 nos primeiros `not_found_grace=10 s` é tratado como "ainda indexando" (**INFERÊNCIA**, simétrica ao
  atraso do `/external`); depois disso propaga.
- Atalhos: `create_and_wait(...)`, `cancel_and_wait(...)`. O `wait` herda o retry de GET; o prazo total é
  do `wait`, não de cada tentativa.
- Alternativa descartada: `client.poll_until_complete(location)` genérico do Node (heurística fraca
  `status==='completed'`, engole erros).

### §9. Webhooks

- **CRUD** em `/v2/webhooks` (`api.nfse.io`, SPEC servers[1]; `api.nfe.io` serve o mesmo conjunto —
  SONDA §8): `list()` desembrulha `webHooks`; `retrieve(id)` desembrulha `webHook`; `create(params)` e
  `update(id, params)` embrulham em `{"webHook": …}` (sem envelope → 400, NODE spec `account-webhooks`);
  `delete(id)`; `ping(id)` (`PUT …/pings`); `event_types()` (`/eventtypes`, desembrulha `eventTypes`).
- **`update` é substituição total no fio** — omitir `status` desativa o webhook (NODE CHANGELOG 5.1.0).
  O SDK não faz merge mágico; a doc e o docstring avisam, e o exemplo mostra `retrieve` → alterar →
  `update`.
- `contentType`/`status` são **strings** no fio (`"json"`, `"Active"`), apesar da spec dizer inteiro
  (SONDA §8, FIX `webhooks-wire-types.json`). Tipados como `str` com constantes conhecidas.
- **`nfeio.webhooks.verify_signature(payload, signature, secret) -> bool`** — função de módulo (não precisa
  de cliente):
  - `payload: bytes | str` (str é codificada em UTF-8; a doc exige o corpo cru, nunca `json.dumps` de um
    dict re-serializado); `signature: str | Sequence[str] | None` (valor de `X-Hub-Signature`; lista →
    primeiro); `secret: str | bytes`.
  - Exige prefixo `sha1=` (case-insensitive) + exatamente 40 hex; calcula `HMAC-SHA1(secret, payload)`;
    compara com **`hmac.compare_digest`** sobre os hex em minúsculas (o servidor manda maiúsculas).
  - **Nunca lança**: qualquer entrada malformada, segredo vazio ou exceção interna → `False`.
  - Vetores de teste: os 3 pings reais de `FIX webhook-signatures.json` (verificados com `hmac` do
    Python em 2026-10-08: os 3 conferem) + os negativos da spec Node `webhook-signature-verification`
    (adulteração de 1 byte, `sha256=`, hex sem prefixo, `sha1=abc`, não-hex, segredo vazio, header vazio).
- **`construct_event(payload, headers_or_signature, secret) -> WebhookEvent`**: verifica primeiro (falha →
  `SignatureVerificationError`), só então faz `json.loads` (limite de 5 MiB). Envelopes: entrega de evento
  `{"action": "issued_successfully", "payload": {nota}}` (SPEC prosa `catalogo-saida-nfse.md`) e ping
  `{"action":"ping","webHook":{…}}` (FIX). `WebhookEvent` expõe `action`, `event_type` (`X-Hook-Event`),
  `hook_id` (`X-Hook-Id`, chave de idempotência da entrega at-least-once), `data` (`ServiceInvoice` quando
  o tipo é `service_invoice`, senão `NfeObject`) e `raw: bytes`. Sem proteção anti-replay no protocolo
  (não há timestamp assinado) — a doc manda deduplicar por `X-Hook-Id`.
- `X-NFe-Signature`/SHA-256 legado: não suportado (RUBY `webhook.rb:27-29`).

### §10. Cliente assíncrono sem duplicar lógica

Núcleo **sans-IO baseado em geradores**: cada operação é um gerador que produz efeitos e recebe
resultados.

```python
Op = Generator[Effect, Any, T]          # Effect = Send(HttpRequest) | Sleep(seconds) | Now()

def create_service_invoice(ctx, company_id, params, external_id, options) -> Op[ServiceInvoice]:
    resp = yield from send_with_retry(ctx, build_request(...), options)   # retry também é um Op
    return parse_create(resp, company_id, external_id)

def run_sync(op, transport, clock) -> T: ...            # Send → transport.send; Sleep → time.sleep
async def run_async(op, atransport) -> T: ...           # Send → await atransport.send; Sleep → asyncio.sleep
```

- Retry, paginação, polling, follow de redirect e reconciliação por `externalId` são escritos **uma vez**,
  como `Op`. As fachadas `NfeClient`/`AsyncNfeClient` só repetem **assinaturas** (necessário para tipos e
  docs) e delegam: `return self._run(ops.create_service_invoice(...))` /
  `return await self._run(ops.create_service_invoice(...))`.
- Teste de paridade: para cada método público, `inspect.signature` sync == async (salvo `async`) — impede
  deriva das fachadas.
- `AsyncTransport` padrão = `ThreadedAsyncTransport(transport_sync)` → `asyncio.to_thread(sync.send, req)`.
  O executor é o default do loop (o usuário pode trocar via `loop.set_default_executor`). Cancelamento de
  task não interrompe a thread em voo; o timeout de socket limita quanto ela vive (documentado). Um
  transporte httpx nativo no futuro implementa `AsyncTransport` sem tocar no núcleo.
- Testes do núcleo rodam os `Op` com um driver falso determinístico (sem rede, sem sleep real) — o mesmo
  teste vale para sync e async.

Alternativas: (a) duas implementações à mão — deriva garantida; (b) `unasync` no build — ferramenta extra,
código gerado versionado (regra 5 exigiria `_generated/`) e o caminho sync vira derivado do async, o
oposto do que a maioria dos usuários (Odoo/ERPNext síncronos) roda.

### §11. Segurança

- **Segredos:** `api_key`/`data_api_key` guardados em `SecretStr` interno com `__repr__`/`__str__`
  mascarados (`'nfe_…a1b2'` → só últimos 4); `repr(client)`, `repr(config)`, `repr(RequestOptions)`
  mascarados. Logger `nfeio` nunca recebe headers, query ou corpo; erros não ecoam o header
  `Authorization`. Senha de certificado nunca aparece em repr/log/exceção. Teste varre `repr`/logs/
  exceções de uma execução completa procurando a chave.
- **IDs em path:** toda interpolação passa por `_paths.segment(kind, value)`: IDs opacos casam
  `^[A-Za-z0-9_-]{1,64}$` (cobre os 24 e 32 hex observados sem cravar tamanho); `external_id` (texto
  livre do cliente) é percent-encoded com `quote(safe="")`, rejeita vazio, `.`/`..`, controle e > 255;
  CNPJ (14 chars `[0-9A-Z]{12}[0-9]{2}`, aceita máscara, valida DV — algoritmo alfanumérico da RFB), CPF
  (11 dígitos + DV), CEP (8 dígitos), data `date`/`AAAA-MM-DD`. Falha → `InvalidParameterError` sem
  requisição (consultas de dados podem ser tarifadas — validar DV local evita custo).
- **Desserialização:** só `json.loads` (com limite de tamanho já aplicado); nada de `pickle`, `eval`,
  `yaml.load`, `xml` parse no SDK (XML/PDF são devolvidos como `bytes`, o usuário escolhe o parser —
  recomendar `defusedxml` na doc).
- **TLS:** §4. **Redirects:** §4 (sem credencial, só https). **Logs:** §5.
- **Supply chain:** zero deps de runtime (a superfície de ataque do pacote instalado é só o próprio
  código); `uv.lock` para dev; GitHub Actions com actions **fixadas por SHA**, `permissions: {}` por padrão
  e mínimas por job; **PyPI Trusted Publishing (OIDC)** — sem token de PyPI em secret; publicação com
  **attestations PEP 740** (Sigstore) pelo `pypa/gh-action-pypi-publish`; build único, artefato
  verificado e publicado em job separado com environment `pypi` protegido (aprovação manual);
  `pip-audit` sobre `uv export` (dev); Dependabot só para `github-actions` e dev-deps; CodeQL (python);
  `bandit -r src` no CI; `ruff` com regras `S` (flake8-bandit).
- **`SECURITY.md`:** versões suportadas, canal privado = **GitHub Private Vulnerability Reporting**
  (decidido, Menor 3), prazo de resposta, escopo (SDK, não a API), política de divulgação coordenada.

### §12. Código gerado a partir da OpenAPI: não no v0.1

- Evidência: PHP gerou 856 arquivos **0% usados em runtime** (VAULT `PHP/review-07-14-2026/08`: "~600
  arquivos ociosos"); Node: 33% de 30.487 linhas geradas sem consumidor; Ruby: 551 arquivos que **descartam
  campos**; o gerador do PHP não via schemas inline e emitia nada em silêncio (VAULT `PHP/Codegen ignora
  specs inline`) — exatamente o caso de `nf-servico-v1` (resposta 202/200 inline, `checkCode` repetido 4×).
- A spec erra em pontos centrais do v0.1 (§16): gerar a partir dela cristalizaria os erros.
- **No lugar:** modelos à mão (§2) + **teste de alinhamento ancorado em path** (lição do `operationId`
  duplicado `ServiceInvoices_idGet`): cada propriedade tipada aponta para uma chave que existe no schema
  da spec **ou** numa lista explícita de divergências provadas; TypedDicts de requisição checados contra os
  campos do corpo da spec. PyYAML só como dev-dep do teste.
- `src/nfeio/_generated/` fica reservado (só `README` explicando a regra 5) para quando houver ganho
  claro (provável: TypedDicts dos corpos enormes de NF-e na v0.2).

### §13. Tooling

| Item | Escolha | Motivo |
|---|---|---|
| Ambiente | `uv` (venv local, `uv.lock`) | rápido, lock reproduzível, já em uso |
| Build backend | `hatchling` | padrão PyPA, versão dinâmica de `_version.py`, sem setup.py |
| Lint/format | `ruff` (E, F, W, I, B, UP, S, SIM, RUF, PT, ASYNC; format) | um binário; `S` cobre bandit no editor |
| Tipos | `mypy --strict` + `py.typed` | consumidores tipados (Odoo 18 já usa hints) |
| Testes | `pytest` + `pytest-asyncio` (dev) | async direto nos testes; zero impacto em runtime |
| Cobertura | `coverage` ≥ 90% em `nfeio._core`, `nfeio.errors`, `nfeio.webhooks`; ≥ 85% global | núcleo é onde mora o risco |
| Segurança | `bandit`, `pip-audit`, CodeQL | §11 |
| CI | GitHub Actions; matriz 3.10, 3.11, 3.12, 3.13, 3.14 (ubuntu) + 3.12 em macOS e Windows | 3.14 = atual; 3.10 = piso (Odoo 17/ERPNext 15) |
| Integração | `pytest -m live`, lê `.env` (parser stdlib no conftest), pula sem chave; escrita só com `NFE_LIVE_WRITE=1` e só em `NFE_COMPANY_ID` | regra 2 das regras do projeto |

Comandos: `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run mypy --strict src tests`,
`uv build`.

### §14. Layout

```
src/nfeio/
  __init__.py            # API pública: NfeClient, AsyncNfeClient, RequestOptions, Timeout, __version__
  _version.py            # única fonte da versão
  py.typed
  _client.py             # fachadas NfeClient / AsyncNfeClient
  _config.py             # ClientConfig, RequestOptions, Timeout, ApiFamily, hosts, SecretStr
  errors.py              # hierarquia pública
  webhooks.py            # verify_signature, construct_event, WebhookEvent (sem cliente)
  types.py               # FlowStatus e aliases públicos
  _core/
    ops.py               # Effect, Send, Sleep, run_sync, run_async
    transport.py         # Transport/AsyncTransport, HttpRequest/HttpResponse, HttpClientTransport, ThreadedAsyncTransport
    retry.py  backoff.py # política, tabela, Retry-After
    requestor.py         # monta requisição por família, auth, UA, decodifica, mapeia erro
    paths.py             # validação/encoding de segmentos, CNPJ/CPF/CEP
    multipart.py  json.py (Decimal-aware)  errors_extract.py  pagination.py  polling.py  user_agent.py
  models/
    _base.py             # NfeObject, ResponseInfo, parsers de data/Decimal
    service_invoice.py  company.py  certificate.py  webhook.py  lookups.py
  resources/
    service_invoices.py  companies.py  certificates.py  webhooks.py  lookups.py   # Ops + fachadas
  _generated/README.md   # reservado (regra 5)
tests/
  unit/  contract/ (replay de fixtures redigidas)  live/ (opt-in)  fixtures/
scripts/probes/          # sondas (já existem)
docs/contrato/           # evidência e decisões
```

### §15. Escopo de operações do v0.1 (resumo; contrato nas specs)

- `service_invoices`: `create`, `list`, `retrieve`, `find_by_external_id`, `cancel`, `send_email`,
  `download_pdf`, `download_xml`, `download_cancellation_xml`, `wait`, `create_and_wait`, `cancel_and_wait`.
- `companies` [D3]: `list`, `retrieve`, `create`, `update`, `delete`.
- `certificates`: `upload`, `list` (status/validade).
- `lookups` [D4][D7]: `cnpj` (v3), `cnpj_state_taxes` (inscrições estaduais, v3), `cpf`, `cep`.
- `webhooks`: `list`, `retrieve`, `create`, `update`, `delete`, `ping`, `event_types` + módulo
  `nfeio.webhooks`.

### §16. Divergências spec × fio que o SDK trata

| # | Ponto | Spec diz | Fio faz | Tratamento no SDK | Fonte |
|---|---|---|---|---|---|
| 1 | Auth | `Authorization` / `?apikey` | também `X-NFE-APIKEY`, `Basic <chave crua>`; base64/Bearer → 401 | usa `Authorization: <chave>` | SONDA §1 |
| 2 | Chave por host | — | dados ↔ fiscal complementares (403 cruzado) | família → chave; sem fallback | SONDA §1, FIX matrix |
| 3 | 401/403 | corpo `ErrorsResource` | **corpo vazio** | mensagem padrão + dica de chave | SONDA §1 |
| 4 | Erros | `{errors:[{code,message}]}` | 5 envelopes (string crua, errors c/ e s/ code, code/message, ProblemDetails) | extrator único | SONDA §3, FIX `unreachable-methods` |
| 5 | Request id | não documentado | `x-request-id` em toda resposta; `traceId` no ProblemDetails | `request_id`, `trace_id` | SONDA §2 |
| 6 | POST emissão | 202 sem headers | 202 + `Location` **`http://`** | só o path; id do corpo | FIX `service-invoice-rtc-create` |
| 7 | POST emissão falho | — | 500/504 **com nota criada** | sem retry; `outcome_unknown` | VAULT `Incidente 504`, `Retry seguro` |
| 8 | `Idempotency-Key` | — | ignorado | não altera retry | VAULT `Ask API` |
| 9 | `externalId` duplicado | não documentado | 400 texto livre, sem código | `DuplicateExternalIdError` | VAULT `Retry seguro` |
| 10 | `/external/{id}` | objeto; parâmetro `externalId` ≠ `{id}`; operationId duplicado | **lista**; miss = 200 vazio | desembrulha; `None` | SONDA §6, VAULT `P1/02` |
| 11 | Cancelar | `DELETE` → 200 string | 202 + `Location` | trata como assíncrono | VAULT memória/NR-01 (inferência) |
| 12 | `/status` | ausente | **não existe** (400 binding) | polling via `GET /{id}` | SONDA §6 |
| 13 | PDF/XML | 200 JSON string | **302** p/ blob pré-assinado em outro host | segue sem credencial; `bytes` | SONDA §6 |
| 14 | XML NFS-e | — | começa em `<Nfse`, sem `<?xml` | entregue cru; doc avisa | SONDA §6 |
| 15 | `cancellation-xml` | XML | 404 semântico em provedor legado | `NotFoundError` com mensagem da API | SONDA §6 |
| 16 | Lista v1 | `{…, totalResults, totalPages, page}` | `{…, page:int}` sem totais (mesmo c/ `hasTotals`) | `has_more` por tamanho | SONDA §4, §6 |
| 17 | `pageIndex` | sem mínimo | ≥ 1 (msgs diferentes por rota) | valida local | SONDA §4, §6 |
| 18 | `pageCount` | sem limite | companies 2–50, NFS-e 1–50, default 10 | valida por rota | SONDA §4, §6 |
| 19 | Retrieve company v1 | — | `{"companies": {objeto}}` | desembrulha | SONDA §4 |
| 20 | Companies v2 lista | `{companies}` | `{hasMore, companies}`; `limit` ≤ 50 (msg "less than 50"); `limit=0` → vazio + `hasMore:true` | `CursorPage`; valida `limit≥1` | SONDA §4 |
| 21 | `municipalTaxNumber` v2 | inscrição municipal | contém **id** da inscrição | não expor como inscrição | SONDA §4 |
| 22 | Empresa inexistente | — | GET → 404 string (POST → 503, inferência) | 404 → `NotFoundError`; 503 não é "transitório" em POST | SONDA §6, VAULT `Retry seguro` |
| 23 | Certificado GET | `/v2/…/certificates` | v1 singular e v2 plural iguais; +`providerType`, `resolution`; sem cert = `[]` | `list()` em v2 | SONDA §5 |
| 24 | Data de validade | — | `expiresOn` (lista de empresas) × `validUntil` (certificado) | propriedade única `expires_on` com fallback | SONDA §4/§5 |
| 25 | Upload | `file`/`password` (v1) × `File`/`Password` (v2) | case-insensitive; `certificate` → 400; arquivo ruim → 500 | campo `file`; 500 em POST = sem retry | FIX `certificate-upload-field` |
| 26 | Webhook host | `api.nfse.io` | `api.nfse.io` e `api.nfe.io` iguais | `api.nfse.io` | SONDA §8 |
| 27 | Webhook enums | inteiro 0/1 | strings `"json"`, `"Active"` | `str` | SONDA §8, FIX |
| 28 | Event types | `{eventTypes:[{id,…}]}` | idem; `/eventtypes` ≡ `/eventTypes`; ids com grafia irregular | `str` aberto | SONDA §8 |
| 29 | Entrega de webhook | — | `{action, payload}`; ping `{action, webHook}`; `X-Hook-Id`/`X-Hook-Event` | `construct_event` trata os dois | SPEC prosa, FIX |
| 30 | `flowStatus` | enum sem `Error`; `WaitingReturnCancel` só na RTC | doc de webhook cita `Error` | enum aberto; `Error` = falha | SPEC, SPEC prosa |
| 31 | CNPJ `federalTaxNumber` | int64 (v2) | v1 string formatada, v2 int, v3 string 14 | v3; normaliza `str` | SONDA §9 |
| 32 | CEP | `{addresses:[…]}`; busca/termo | `{address:{…}}`; busca → 404 | só por CEP; desembrulha | SONDA §9 |
| 33 | CPF | 404 "não encontrado ou data divergente" | `{errors:[{code:40401}]}`; data `AAAA-MM-DD` | valida data local | SONDA §9 |
| 34 | Cursor v2 "venenoso" | — | 500 em jul/2026; **200 hoje** | sem workaround; teste live de varredura | SONDA §4, VAULT `Migração companies` |
| 35 | Rota não servida | — | 404 vazio mesmo sem chave (servida → 401) | mensagem de 404 vazio sugere rota inválida | SONDA §10 |

## Risks / Trade-offs

- **[CNPJ alfanumérico × NFS-e v1]** A partir de jul/2026 empresas com CNPJ alfanumérico recebem 400 na
  v1 e são mandadas para a v3 (SPEC `nf-servico-v1` 400 de retrieve; VAULT `PHP/review-07-14-2026/11`). O
  v0.1 nasce sem servir esse público. → Modelos já tratam documento como `str`; [D7] define onde a v3
  entra sem quebrar `service_invoices`; incluir NFS-e v3 cedo na v0.2.
- **[Inferências de escrita]** 202 do cancelamento, upload v2, 503 em POST, `Retry-After`, CRUD v2 de
  empresas não foram observados hoje (sonda só leitura). → Fase 2 começa com sonda de escrita **na
  `NFE_COMPANY_ID`** (emitir 1 NFS-e de homologação, consultar por `externalId`, cancelar, reenviar
  certificado) antes de fixar os testes de contrato.
- **[Certificado da empresa de teste vence em 2026-11-03]** (SONDA §5). → Avisar o André; testes live
  de emissão pulam com mensagem clara se `validUntil` < hoje.
- **[Visão tipada é inédita na família]** Usuários de Ruby/PHP esperam DTO. → `to_dict()` e
  propriedades cobrem os dois estilos; teste de alinhamento evita propriedade fantasma.
- **[`has_more` por tamanho de página]** Uma requisição extra no fim. → Aceito; documentado.
- **[`to_thread` sob carga]** Executor padrão limita concorrência (~32 threads) e não cancela I/O em voo.
  → Documentar; `AsyncTransport` permite httpx depois sem quebrar API.
- **[Sem retry de POST em 429]** [D8] Rajadas de emissão viram erro visível em vez de espera silenciosa.
  → `RateLimitError.retry_after` + receita na doc; revisitar quando a API confirmar que o limitador
  rejeita antes de processar.
- **[Divergências de spec mudam sem aviso]** Ex.: cursor venenoso sumiu, 503 virou 404. → Sondas
  versionadas e reexecutáveis (`scripts/probes/`); testes `live` de leitura no CI noturno (opt-in, segredo
  do repo, só leitura).
- **[Chave de dados com escopo maior que o esperado]** 200 em companies/webhooks (SONDA §1). → Reportar ao
  time da API (possível excesso de privilégio); o SDK não depende disso.

## Migration Plan

Pacote novo, sem usuários: não há migração. Sequência de entrega:

1. OK do André nas decisões [D1]–[D8] — **feito em 2026-10-08**.
2. Fase 2a: sonda de **escrita** controlada na `NFE_COMPANY_ID` (itens de "Inferências de escrita").
3. Implementação por tasks (`tasks.md`), com testes de contrato a partir das fixtures redigidas.
4. Publicação `0.1.0` no PyPI (TestPyPI antes) **somente com OK explícito**; rollback = `yank` da versão
   (PyPI não permite reaproveitar número).

## Open Questions

- Política de versionamento 0.x (minor pode quebrar?) — afeta só o CHANGELOG, não a API do v0.1.
- ~~Canal do `SECURITY.md`~~ — decidido: GitHub Private Vulnerability Reporting.
- Se o time da API confirmar que o rate limiter (429) rejeita antes de processar, liberar POST+429 na
  tabela de retry (mudança aditiva).
