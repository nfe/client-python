# Fixtures de contrato ao vivo (SDK Python)

Capturadas em 2026-10-08 pelos testes `tests/live/` (fase 2 da change `add-sdk-foundation-v0-1`).

**Envelope real, corpo sintético.** Status, cabeçalhos relevantes (`Content-Type`, `Location`) e a
FORMA do corpo vêm de respostas reais da API. Ids, CNPJ, CPF, `externalId`, nomes e URLs
pré-assinadas foram trocados por valores fabricados. A evidência crua redigida fica em
`tests/live/out/` (fora do git).

Consumidas por `tests/unit/test_live_contracts.py`, que reexecuta cada troca no SDK com o
transporte falso e verifica o comportamento esperado.

| Arquivo | O que prova |
|---|---|
| `service-invoice-lifecycle.json` | emissão 202 + `Location` http, busca por `externalId`, duplicidade 400, download 302 sem credencial, cancelamento 202 + `Location`, XML de cancelamento 404 |
| `company-v2-crud.json` | criação 200 com envelope `company`, update 200, DELETE 204 = soft delete (`Inactive`) |
| `webhook-crud.json` | criação 201 (status ignorado, segredo ecoado), verificação da URI na criação (400 `40001`) |
| `certificate-upload-v2.json` | campo `file` aceito pela v2; arquivo inválido → 500 ProblemDetails |
| `auth-cross-key.json` | chave de dados em NFS-e → 403 vazio; chave principal em CEP → 403 vazio |
