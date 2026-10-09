# Sonda da fase 2 — 2026-10-08 (leitura e escrita controlada, pelo próprio SDK)

Change: `add-sdk-foundation-v0-1`, fase 2 (implementação). Diferente da sonda da fase 1
(`probe-2026-10-08.md`, só `GET` com scripts avulsos), esta foi feita **pelo SDK**, nos testes
`tests/live/`, com transporte que grava cada troca redigida.

- **Como rodar:** `uv run pytest tests/live --run-integration [--live-write]` (ou
  `NFE_RUN_INTEGRATION=1` / `NFE_LIVE_WRITE=1`). Chaves do `.env`, nunca impressas.
- **Evidência crua redigida:** `tests/live/out/*.json` (fora do git). **Fixtures versionadas**
  (envelope real, valores sintéticos): `tests/fixtures/live-contracts/`, reexecutadas por
  `tests/unit/test_live_contracts.py`.
- **Redação deste documento:** ids encurtados (`6ac8…ba46`), sem CNPJ, CPF, chave ou URL
  pré-assinada.
- **Legenda:** **PROVADO** = observado hoje no fio. **INFERÊNCIA** = não observado; fonte citada.

## Escritas executadas (dentro da autorização da fase 2)

| Permissão | O que foi feito | Resultado | Limpeza |
|---|---|---|---|
| a) NFS-e só na `NFE_COMPANY_ID` (≤ ~5 notas) | **2 notas** emitidas em homologação com `externalId` `sdkpy-<uuid>`: `6ac8…ba46` (cliente sync) e `6ac8…1369` (cliente async). Uma tentativa de duplicata (recusada pela API, não criou nota) | ambas `Issued` | ambas **canceladas** (`Cancelled`, conferido depois por listagem) |
| b) UMA empresa descartável | `SDK-PY TESTE DESCARTAVEL 2026-10-08`, id `ad95…37dd`, CNPJ aleatório com DV válido (prefixo 99) | criar, consultar, alterar ok | `DELETE` → 204 duas vezes; a API faz **soft delete**: a empresa continua na conta com `status: Inactive` (não há remoção definitiva pela API) |
| c) webhooks de teste | 1ª tentativa em `https://example.com/nfeio-sdkpy-test` **recusada pela API** (verificação da URI, 405 → 400); depois 1 webhook em `https://httpbin.org/status/200?nfeio-sdkpy-test=1` | criar, consultar, alterar ok | apagado (204); conferido que não restou nenhum |

Fora do escopo e **não** executado: `sendemail`, `ping` de webhook, upload de certificado real,
qualquer escrita em outras empresas. Um único `POST` de certificado com **arquivo falso** foi
enviado à empresa descartável para saber se a API aceita upload sem certificado válido (não
aceita: 500).

## Resultados — provado × inferência

### NFS-e (`api.nfe.io/v1`)

| Ponto | Antes (fase 1) | Hoje |
|---|---|---|
| Emissão | INFERÊNCIA (fixture Node RTC): 202 + `Location` http | **PROVADO**: 202, `Location: http://api.nfe.io/v1/companies/{id}/serviceinvoices/{id}`, corpo = **nota completa** (38 chaves, `flowStatus: WaitingCalculateTaxes`), não só `{id, environment, flowStatus}` |
| Busca por `externalId` logo após o 202 | VAULT: atraso de "segundos" | **PROVADO**: achada na **primeira** chamada (0,21 s). O `wait=30` continua recomendado (o atraso pode voltar) |
| `externalId` repetido | VAULT (jul/2026) | **PROVADO**: 400, corpo string `"service invoice with external id (…) already exists"`, sem `code` |
| Polling | `GET …/{id}` (não há `/status`) | **PROVADO**: `WaitingCalculateTaxes` → `Issued` em segundos |
| PDF/XML | PROVADO (302 → blob) | **PROVADO de novo pelo SDK**: 302 → `api.nfse.io/v1/blob/download?b&e&s`, seguido **sem** `Authorization`; PDF ~56 KB `%PDF-1.4`; XML ~1,3 KB começando em `<Nfse><InfNfse>` |
| Cancelamento | INFERÊNCIA: 202 + `Location` | **PROVADO**: `DELETE` → 202 + `Location` http, corpo de nota; termina em `Cancelled` |
| XML de cancelamento | PROVADO (404 em provedor legado) | **PROVADO**: 404 string "National environment only…" |
| Valores | — | `Decimal("10.00")` enviado como `10.00`; `services_amount == Decimal("10.00")` na volta |
| Tomador com CPF inteiro | PROVADO (fio manda int) | **PROVADO**: `borrower.federal_tax_number == "52998224725"` |
| 500/504 com nota criada | VAULT (incidente) | **INFERÊNCIA** (não provocável sem incidente); o SDK trata como `outcome_unknown` |
| Empresa inexistente em POST → 503 | VAULT | **INFERÊNCIA** (não testado: exigiria POST em empresa alheia) |
| `sendemail` | spec | **INFERÊNCIA** (fora da autorização da fase 2) |

### Empresas (`api.nfse.io/v2/companies`)

| Ponto | Hoje |
|---|---|
| Criar | **PROVADO**: `POST` com `{"company": {…}}` → **200** (não 201), corpo `{"company": {…}}`, `federalTaxNumber` volta **inteiro** |
| Consultar / alterar | **PROVADO**: `GET`/`PUT` → 200 com envelope `company` |
| Excluir | **PROVADO**: `DELETE` → 204; **soft delete** — a empresa continua listada e consultável com `status: Inactive`; um segundo `DELETE` também dá 204 |
| Varredura por cursor | **PROVADO** de novo: 14 páginas de 50, sem duplicatas, sem erro |
| Chave principal | **PROVADO**: todas as rotas acima com `api_key` |

### Certificados

| Ponto | Hoje |
|---|---|
| Listar `GET /v2/companies/{id}/certificates` | **PROVADO** (envelope `certificates`, `validUntil`, `providerType`) |
| Upload v2, campo multipart `file` | **PROVADO em parte**: com arquivo falso a API respondeu **500** ProblemDetails (não 400 "File field is required"), ou seja, o binding aceitou `file`/`password` e falhou ao ler o PFX — mesmo comportamento da v1 em 2026-09-01. O caminho de sucesso exige PFX válido: **não testado** (teste pulado, registrado) |
| Certificado da empresa de teste | vence em **2026-11-03** (renovação combinada) |

### Webhooks (`api.nfse.io/v2/webhooks`)

| Ponto | Hoje |
|---|---|
| Verificação da URI na criação | **PROVADO (novo)**: a API chama a URI ao criar; `example.com` respondeu 405 → **400** `{"errors":[{"code":40001,"message":"WebHook verification failed … Error encountered: 405"}]}` |
| Criar | **PROVADO**: 201, envelope `webHook`; **o segredo é ecoado** no corpo; `status: "Inactive"` enviado na criação foi **ignorado** (voltou `Active`) |
| Alterar | **PROVADO**: `PUT` 200, substituição total; `status: "Inactive"` aplicado |
| Excluir | **PROVADO**: 204 |
| Tipos de evento | **PROVADO** (inclui `service_invoice.issued_successfully`) |
| Assinatura `X-Hub-Signature` | **INFERÊNCIA** a partir de 3 entregas reais de 2026-06-11 (vetores nos testes); `ping` não executado |

### Consultas e autenticação

| Ponto | Hoje |
|---|---|
| `Authorization: <chave>` sem prefixo | **PROVADO** em todos os hosts usados |
| Chave de dados em NFS-e / chave principal em CEP | **PROVADO**: 403 com corpo vazio; o SDK acrescenta a dica de qual chave a família usa |
| CNPJ v3 (`basicInfo`, `stateTaxInfo`) | **PROVADO** (`federalTaxNumber` string de 14) |
| CEP v2 | **PROVADO** (`address.city.code`) |
| CPF com data divergente | **PROVADO**: 404 `{"errors":[{"code":40401,"message":"not found"}]}`; formato de sucesso segue **INFERÊNCIA** (spec) |
| `x-request-id` | **PROVADO** em todas as respostas, inclusive 403/404 e no blob |

## Consequências no SDK

- Fixtures de contrato novas e teste de replay (`test_live_contracts.py`).
- `companies.delete` documenta o soft delete; os testes ao vivo verificam `status == "Inactive"`.
- Teste ao vivo de webhook usa uma URL que responde 2xx (a verificação na criação inviabiliza
  `example.com`); ver `DECISOES-FASE2.md`.
- A busca por `externalId` ficou estrita (só lista vazia explícita significa "não existe").
