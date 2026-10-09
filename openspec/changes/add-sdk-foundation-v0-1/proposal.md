## Why

ERPs open source escritos em Python (Odoo/OCA, ERPNext/Frappe, Tryton, InvenTree) não têm cliente oficial
da NFE.io. Cada integração reimplementa HTTP, retry e webhook, e repete os erros que já custaram caro aos
SDKs irmãos: POST de emissão retentado após 504 gerando nota duplicada em produção (incidente de
2026-06-25 a 07-02), paginação 0-based quebrada, chave de API errada por host, assinatura de webhook
rejeitando entregas legítimas. O v0.1 entrega um núcleo seguro por construção e a NFS-e completa,
ancorados no contrato provado ao vivo (sonda de 2026-10-08), não no que os irmãos inferiram.

## What Changes

- Novo pacote PyPI `nfe-io` (import `nfeio`), Python 3.10+, **zero dependências de runtime**.
- Clientes explícitos `NfeClient` (sync) e `AsyncNfeClient` (async via `asyncio.to_thread`), com
  serviços por recurso (`client.service_invoices.create(...)`) e `RequestOptions` por chamada.
- Transporte stdlib plugável (protocolo), TLS sempre verificado, timeouts finitos, limite de tamanho de
  resposta, User-Agent honesto e multipart sem dependências.
- Retry ciente de método e de fase da falha (port da tabela do PHP `RetryingTransport`): POST nunca é
  retentado em 5xx nem em falha ambígua; dedupe de emissão por `externalId` + `find_by_external_id`.
- Hierarquia de erros tipados por status, preservando corpo, mensagem da API (5 envelopes observados),
  `x-request-id` e `traceId`.
- Paginação v1 1-based (offset) e por cursor, com `auto_paging_iter()` sync/async.
- Fluxo assíncrono 202 + `Location` e polling (`wait`, `create_and_wait`, `cancel_and_wait`) sobre
  `GET` da nota.
- NFS-e completa: emitir, listar, consultar, consultar por `externalId`, cancelar, reenviar e-mail,
  baixar PDF/XML (redirect seguido sem credencial).
- Empresas (listar/consultar/CRUD) e certificado digital (upload multipart, consulta de status).
- Consultas de dados: CNPJ, CPF e CEP, com a chave de dados.
- Webhooks: CRUD em `/v2/webhooks`, tipos de evento, `verify_signature` (HMAC-SHA1, tempo constante,
  nunca lança) e `construct_event`.
- Empacotamento e release: hatchling, `py.typed`, CI 3.10–3.14, PyPI Trusted Publishing (OIDC) com
  attestations, auditoria de supply chain.

Não há código existente: nenhuma mudança é **BREAKING**.

## Capabilities

### New Capabilities

- `client-core`: configuração do cliente, chaves por família de API, hosts, `RequestOptions`, mascaramento de segredos, validação de IDs de path, modelos de resposta com preservação de campos desconhecidos.
- `http-transport`: protocolo de transporte, implementação stdlib, TLS, timeouts, limite de resposta, User-Agent, multipart, redirects.
- `retry-idempotency`: política de retry por método e fase da falha, backoff com jitter, `Retry-After`, dedupe de emissão por `externalId`.
- `errors`: hierarquia de exceções, mapeamento status → classe, extração de mensagem dos envelopes da API, request id.
- `pagination`: páginas offset 1-based e cursor, iteração automática sync/async, limites validados.
- `polling`: fluxo 202 + `Location`, espera por estado terminal com backoff, prazos e falhas de processamento.
- `service-invoices`: operações de NFS-e v1 (emissão, consulta, cancelamento, e-mail, downloads).
- `companies`: listagem, consulta e CRUD de empresas.
- `certificates`: upload de certificado A1 e consulta de status.
- `data-lookups`: consultas de CNPJ, CPF e CEP.
- `webhooks`: CRUD de webhooks da conta, tipos de evento, verificação de assinatura e parse de evento.
- `async-client`: cliente assíncrono com a mesma superfície do síncrono.
- `packaging-release`: empacotamento, tipagem, qualidade, CI, publicação e política de segurança.

### Modified Capabilities

(nenhuma — repositório sem specs anteriores)

## Impact

- **Código novo:** `src/nfeio/` (pacote), `tests/` (unit, contrato com fixtures, integração opt-in),
  `pyproject.toml`, CI em `.github/workflows/`, `SECURITY.md`, `CHANGELOG.md` (pt-BR).
- **Dependências:** nenhuma em runtime; dev-only: pytest, pytest-asyncio, coverage, ruff, mypy,
  bandit, pip-audit (via `uv`).
- **Sistemas externos:** `api.nfe.io`, `api.nfse.io`, `legalentity.api.nfe.io`,
  `naturalperson.api.nfe.io`, `address.api.nfe.io`; PyPI (publicação só com OK do André).
- **Decisões** que alteram a API pública foram fechadas pelo André em 2026-10-08 (registro em
  `docs/contrato/DECISOES-PENDENTES.md`); as que surgirem na implementação vão para
  `docs/contrato/DECISOES-FASE2.md`.
- **Evidência:** `docs/contrato/probe-2026-10-08.md` (sonda de leitura), fixtures do
  `client-nodejs/tests/fixtures/live-contracts/`, notas do vault `SDKs/`.
