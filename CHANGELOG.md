# Changelog

Todas as mudanças relevantes deste projeto são registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto adota o
[Versionamento Semântico](https://semver.org/lang/pt-BR/). Enquanto a versão for 0.x, uma minor
pode trazer mudança incompatível; ela sempre será anunciada aqui.

## [Não lançado]

## [0.1.0] - não publicada

Primeira versão do SDK oficial da NFE.io para Python (`pip install nfe-io`, `import nfeio`).

### Adicionado

- Clientes `NfeClient` (síncrono) e `AsyncNfeClient` (assíncrono, via `asyncio.to_thread`), com a
  mesma superfície e o mesmo comportamento, sem estado global.
- Duas chaves por família de API: `api_key` (NFS-e, empresas, certificados, webhooks) e
  `data_api_key` (CNPJ, CPF, CEP), lidas também de `NFE_API_KEY` e `NFE_DATA_API_KEY`. Envio em
  `Authorization: <chave>`.
- NFS-e (API v1): `create`, `list`, `retrieve`, `find_by_external_id`, `cancel`, `send_email`,
  `download_pdf`, `download_xml`, `download_cancellation_xml`, `wait`, `create_and_wait` e
  `cancel_and_wait`.
- Empresas (API v2, paginação por cursor): `list`, `retrieve`, `create`, `update`, `delete`.
- Certificados: `upload` (multipart, campo `file`) e `list`, com `expires_on` e `is_expired()`.
- Webhooks da conta: `list`, `retrieve`, `create`, `update`, `delete`, `ping`, `event_types`.
- `nfeio.webhooks.verify_signature` (HMAC-SHA1 em tempo constante, nunca levanta exceção) e
  `construct_event` (verifica antes de interpretar o corpo).
- Consultas: `lookups.cnpj` (v3, CNPJ numérico e alfanumérico), `lookups.cnpj_state_taxes`,
  `lookups.cpf` e `lookups.cep`, com validação local de dígitos verificadores.
- Modelos `NfeObject`: `Mapping` imutável sobre o JSON do fio, com propriedades tipadas para ids,
  status, datas (`datetime` com fuso), valores (`Decimal`) e documentos (CNPJ/CPF normalizados).
- Paginação por índice (1-based) e por cursor com `auto_paging_iter()` síncrono e assíncrono.
- Hierarquia de erros por status com `request_id`, `trace_id`, `error_code` e
  `outcome_unknown`; leitura dos cinco formatos de erro usados pela API.
- `RequestOptions` por chamada (`api_key`, `timeout`, `max_retries`, `idempotency_key`,
  `extra_headers`) e `app_info` no User-Agent.
- Transporte só com a biblioteca padrão, substituível pelos protocolos `Transport` e
  `AsyncTransport`.

### Segurança

- Retry ciente de método e da fase da falha: um `POST` (como a emissão) nunca é repetido depois
  que pode ter chegado à API; `Idempotency-Key` não muda essa regra.
- TLS sempre verificado (mínimo 1.2), sem opção para desligar; timeouts finitos; respostas
  limitadas a 10 MiB; sem compressão.
- JSON não confiável (respostas, erros e webhooks) limitado a 128 níveis de aninhamento, com o
  mesmo resultado em qualquer versão do Python.
- Redirect de download seguido só em https e **sem** a chave de API.
- Ids, `externalId` e documentos validados antes de entrar no path (sem path traversal).
- Chaves, senha de certificado e segredo de webhook nunca aparecem em `repr`, logs ou
  exceções; logs não registram documentos nem `externalId`.
- Zero dependências de runtime.
