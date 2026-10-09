## 0. Pré-requisitos (bloqueiam a implementação)

- [x] 0.1 Obter o OK do André em D1–D8 de `docs/contrato/DECISOES-PENDENTES.md` e ajustar specs/design ao que for decidido (D1 = "D enxuta"); verificar com `openspec validate add-sdk-foundation-v0-1 --strict`
- [x] 0.2 Sonda de escrita controlada, feita pelos testes live do próprio SDK (seção 15), dentro das permissões da fase 2: (a) NFS-e só na `NFE_COMPANY_ID`, `externalId` único `sdkpy-<uuid>`, no máximo ~5 notas: emitir, repetir o POST (esperar 400 de duplicidade), `find_by_external_id` logo após o 202 (medir atraso de indexação), baixar PDF/XML, cancelar (confirmar 202 + `Location`); (b) criar e apagar UMA empresa descartável `SDK-PY TESTE DESCARTAVEL <data>` (CRUD v2); (c) criar e apagar webhooks apontando para `https://example.com/nfeio-sdkpy-test`. Fora do escopo: `sendemail` ao vivo e upload de certificado real. Registrar em `docs/contrato/probe-fase2.md` e evidências redigidas em `tests/fixtures/live-contracts/`
- [x] 0.3 Renovação do certificado da empresa de teste (Menor 4: ok, será renovado) e canal do `SECURITY.md` (Menor 3: GitHub Private Vulnerability Reporting) — registrados no DECISOES

## 1. Fundação do repositório

- [x] 1.1 Criar `pyproject.toml` (hatchling, `name = "nfe-io"`, `requires-python = ">=3.10"`, sem `dependencies`, versão dinâmica de `src/nfeio/_version.py`, grupos dev) e `uv.lock`; verificar com `uv sync` e `uv build` gerando wheel sem `Requires-Dist`
- [x] 1.2 Criar `src/nfeio/__init__.py`, `_version.py`, `py.typed` e `_generated/README.md` (regra 5); verificar `uv run python -c "import nfeio; print(nfeio.__version__)"`
- [x] 1.3 Configurar ruff (regras E, F, W, I, B, UP, S, SIM, RUF, PT, ASYNC + format), mypy `--strict`, pytest (marcador `live`), coverage com mínimos por módulo; verificar os quatro comandos verdes no repositório vazio
- [x] 1.4 Adicionar `LICENSE`, `SECURITY.md`, `CHANGELOG.md` (pt-BR, Keep a Changelog, seção `[Não lançado]`) e `README.md` mínimo; verificar presença no sdist com `tar tzf dist/*.tar.gz`
- [x] 1.5 Teste que falha se houver literal de versão fora de `_version.py`; verificar introduzindo uma literal falsa e vendo o teste falhar

## 2. Núcleo sans-IO

- [x] 2.1 Implementar `Effect` (`Send`, `Sleep`, `Now`), `run_sync` e `run_async` em `_core/ops.py`; verificar com testes de um `Op` de exemplo rodando nos dois drivers com transporte falso
- [x] 2.2 Criar `FakeTransport` de teste (fila de respostas roteiro, registro de requisições) e relógio falso; verificar que testes não fazem I/O real nem `sleep` real (tempo da suíte unitária < 5 s)

## 3. Configuração, segredos e paths

- [x] 3.1 Implementar `ClientConfig`, `RequestOptions`, `Timeout`, `ApiFamily` e tabela de hosts, com leitura de `NFE_API_KEY`/`NFE_DATA_API_KEY` e validações (https, timeouts finitos, cabeçalhos protegidos); verificar cenários de `client-core`
- [x] 3.2 Implementar `SecretStr` e `repr` mascarado de cliente/config/opções; verificar teste de varredura de vazamento (log DEBUG + repr + exceções)
- [x] 3.3 Implementar `_core/paths.py`: segmento opaco, `external_id` percent-encoded, CNPJ (numérico e alfanumérico, DV da RFB), CPF, CEP, UF, data; verificar com testes tabulares incluindo `../`, vazio, controle, 256 chars, CNPJ `12ABC34501DE35` e `00000000000100`

## 4. Transporte

- [x] 4.1 Implementar protocolos `Transport`/`AsyncTransport`, `HttpRequest`/`HttpResponse` (cabeçalhos case-insensitive); verificar com transporte customizado nos testes
- [x] 4.2 Implementar `HttpClientTransport` sobre `http.client`: connect explícito, classificação de fase, pool LIFO por host com lock, POST sempre em conexão nova; verificar com servidor local de teste (DNS inválido, porta fechada, servidor que não responde, servidor que fecha a conexão)
- [x] 4.3 TLS: contexto padrão TLS ≥ 1.2, aceitar `ssl_context`/`ca_bundle` só com verificação ligada; verificar rejeição de `CERT_NONE`/`check_hostname=False` e falha contra servidor local autoassinado
- [x] 4.4 Timeouts (connect, read, prazo total) e limite de resposta em chunks com `Accept-Encoding: identity`; verificar com servidor local lento e com corpo maior que o limite
- [x] 4.5 User-Agent e `app_info`; verificar formato exato em teste
- [x] 4.6 Encoder multipart; verificar corpo byte a byte e saneamento de filename
- [x] 4.7 `ThreadedAsyncTransport` (`asyncio.to_thread`); verificar teste de concorrência com `asyncio.gather` e tarefa paralela progredindo

## 5. Erros

- [x] 5.1 Implementar hierarquia de `nfeio.errors` e mapeamento status → classe; verificar tabela de status (400, 401, 403, 404, 405, 408, 409, 415, 422, 429, 500, 502, 503, 504)
- [x] 5.2 Implementar extrator de mensagem para os 5 envelopes + corpo vazio, saneamento e truncamento, `request_id`/`trace_id`; verificar com as respostas reais redigidas de `scripts/probes/out/` convertidas em fixtures de teste
- [x] 5.3 Dica de chave em `PermissionDeniedError`; verificar mensagem para família fiscal e de dados

## 6. Retry e idempotência

- [x] 6.1 Implementar tabela método × status × fase, backoff com jitter e `Retry-After` (segundos e data HTTP, teto); verificar cada célula da tabela em teste parametrizado e nos dois drivers
- [x] 6.2 Marcar `outcome_unknown` em erros de POST incertos e logging DEBUG sem dados sensíveis; verificar cenários de `retry-idempotency`
- [x] 6.3 `DuplicateExternalIdError` por casamento tolerante da mensagem; verificar com a mensagem real registrada no vault e variações de caixa

## 7. Modelos

- [x] 7.1 Implementar `NfeObject` (Mapping imutável sem `__getattr__`, aninhados por chave como `NfeObject`, listas copiadas, `to_dict`, `__eq__`, `last_response`, `repr` com chaves sensíveis mascaradas), descritores de campo tipado e parser tolerante de datas/`Decimal`; verificar cenários de `client-core` em Python 3.10 e 3.14
- [x] 7.2 Encoder JSON que aceita `Decimal` sem perda; verificar `Decimal("100.10")` → `100.10`
- [x] 7.3 Teste de alinhamento ancorado em path: cada propriedade tipada aponta para chave da spec ou da lista de divergências provadas; verificar falha ao incluir propriedade fantasma

## 8. Paginação

- [x] 8.1 Implementar `OffsetPage`/`CursorPage` com `next_page` e `auto_paging_iter` (sync e async), parada em página vazia e tabela de limites por rota; verificar cenários de `pagination`, incluindo `hasMore:true` com lista vazia

## 9. Polling

- [x] 9.1 Implementar parse de 202 (corpo + path do `Location`), `wait` com backoff, estados terminais, tolerância a 404 inicial e `PollingTimeoutError`/`InvoiceProcessingError`; verificar cenários de `polling` com relógio falso

## 10. NFS-e

- [x] 10.1 Implementar `service_invoices.create/list/retrieve/find_by_external_id/cancel/send_email`; verificar cenários de `service-invoices` com fixtures redigidas
- [x] 10.2 Implementar `download_pdf/xml/cancellation_xml` com follow de redirect sem credencial; verificar que a requisição ao destino não tem `Authorization` e que o XML sem prólogo volta intacto
- [x] 10.3 Implementar `create_and_wait`/`cancel_and_wait`; verificar sequência 202 → WaitingSend → Issued
- [x] 10.4 Modelo `ServiceInvoice` (+ `Borrower`, `Provider`, `Address`) e `TypedDict` do corpo de emissão; verificar com a nota real redigida da sonda

## 11. Empresas e certificados

- [x] 11.1 Implementar `companies.list/retrieve/create/update/delete` conforme D3; verificar cenários de `companies`
- [x] 11.2 Implementar `certificates.upload/list` e modelo `Certificate` com `expires_on`/`is_expired`; verificar cenários de `certificates` e ausência da senha em logs/erros

## 12. Consultas de dados

- [x] 12.1 Implementar `lookups.cnpj`, `cnpj_state_taxes`, `cpf`, `cep` com chave de dados e validação local; verificar cenários de `data-lookups`

## 13. Webhooks

- [x] 13.1 Implementar `client.webhooks` (list, retrieve, create, update, delete, ping, event_types) com envelopes; verificar cenários de CRUD
- [x] 13.2 Implementar `nfeio.webhooks.verify_signature` e `construct_event`; verificar com os 3 vetores reais de `client-nodejs/tests/fixtures/webhook-signatures.json` (copiados para `tests/fixtures/`) e todos os negativos da spec

## 14. Cliente assíncrono

- [x] 14.1 Implementar fachadas `AsyncNfeClient` delegando aos mesmos `Op`; verificar teste de paridade de assinaturas e teste de comportamento idêntico (mesmo roteiro de respostas nos dois clientes)
- [x] 14.2 `with`/`close` e `async with`/`aclose`; verificar que o pool fica vazio após o bloco

## 15. Testes de integração (opt-in)

- [x] 15.1 Conftest com parser stdlib de `.env`, marcador `live`, pulo sem chave e trava `NFE_LIVE_WRITE=1` + `NFE_COMPANY_ID`; verificar `uv run pytest` sem `.env` (pulados) e `uv run pytest -m live` com `.env` (leitura passa)
- [x] 15.2 Testes live de leitura: auth por família, varredura de companies v2, lista/retrieve/external/downloads de NFS-e, certificados, webhooks, CNPJ/CEP; verificar contra a conta de teste
- [x] 15.3 Testes live de escrita (opt-in `NFE_LIVE_WRITE=1`): NFS-e só na `NFE_COMPANY_ID` (`create_and_wait` com `external_id`, duplicidade, `find_by_external_id(wait=30)`, downloads, `cancel_and_wait`; pular se o certificado estiver vencido); CRUD v2 de UMA empresa descartável com remoção garantida em `finally`; CRUD de webhook de teste com remoção garantida; upload de certificado só unitário (ou pulado e registrado)

## 16. Documentação

- [x] 16.1 README (instalação, chaves por família, exemplo sync/async, paginação, polling) e guia "emissão segura" com a receita de reconciliação por `external_id`; verificar exemplos executados por teste de documentação contra `FakeTransport`
- [x] 16.2 Guia de webhooks (corpo cru em Django/Flask/FastAPI, deduplicação por `X-Hook-Id`, aviso de update full-replace); verificar exemplos por teste
- [x] 16.3 Atualizar `CHANGELOG.md` com a entrada 0.1.0 em pt-BR; verificar formato Keep a Changelog

## 17. CI e release (sem publicar)

- [ ] 17.1 Workflow de CI: lint, format, mypy, testes na matriz 3.10–3.14 (Linux) + 3.12 (macOS, Windows), cobertura, build; actions fixadas por SHA e `permissions` mínimas; verificar execução verde num PR — **escrito** (`.github/workflows/ci.yml`); comandos equivalentes verdes localmente em 3.10–3.14; falta a primeira execução no GitHub (sem push nesta fase)
- [ ] 17.2 Workflows de segurança: bandit, pip-audit (`uv export` dev), CodeQL; Dependabot para actions e dev; verificar execução verde — **escrito** (`security.yml`, `dependabot.yml`; o CodeQL roda pelo default setup do repositório no GitHub, e o `codeql.yml` próprio foi removido porque o GitHub recusa o SARIF com o default setup ligado); bandit e pip-audit verdes localmente; pins de actions a conferir com `scripts/verify_action_pins.py` (sem acesso ao GitHub nesta sessão)
- [ ] 17.3 Workflow de release por tag com build único, environment `pypi` protegido, Trusted Publishing OIDC e attestations; verificar em dry-run contra TestPyPI **somente após OK do André** — **escrito** (`release.yml`); dry-run no TestPyPI aguarda OK do André
- [ ] 17.4 Revisão final: `openspec validate add-sdk-foundation-v0-1 --strict`, checklist de segurança do design §11 item a item; verificar e registrar no PR — validate `--strict` ok e checklist registrado em `docs/contrato/revisao-seguranca-v0.1.md`; falta anexar ao PR
