## Purpose

Define o gerenciamento dos webhooks da conta (`/v2/webhooks`) e o tratamento seguro das entregas
recebidas: verificação de assinatura HMAC-SHA1 em tempo constante e interpretação do evento.

## ADDED Requirements

### Requirement: CRUD de webhooks da conta
O SDK SHALL oferecer em `client.webhooks`: `list()` (`GET /v2/webhooks`, desembrulha `webHooks`),
`retrieve(id)` (desembrulha `webHook`), `create(params)` e `update(id, params)` (corpo embrulhado em
`{"webHook": …}`), `delete(id)` e `ping(id)` (`PUT /v2/webhooks/{id}/pings`), usando a chave principal.
O SDK MUST NOT oferecer a remoção de todos os webhooks numa chamada.

#### Scenario: Criação com envelope
- **WHEN** o usuário chama `create({"uri": "https://erp.exemplo/hook", "secret": "…", "filters": ["service_invoice.issued_successfully"]})`
- **THEN** o corpo enviado é `{"webHook": {…}}` e o retorno é o webhook desembrulhado

#### Scenario: URI recusada na verificação
- **WHEN** a API não consegue validar a URI na criação e responde 400 com `code` 40001
- **THEN** o SDK levanta `InvalidRequestError` com `error_code == 40001` e a mensagem da API

#### Scenario: Valores textuais do fio
- **WHEN** a listagem traz `"contentType": "json"` e `"status": "Active"`
- **THEN** `hook.content_type == "json"` e `hook.status == "Active"`

### Requirement: Atualização é substituição completa
`webhooks.update` SHALL enviar o objeto informado como substituição completa, sem mesclar com o estado
atual, e sua documentação MUST avisar que omitir `status` desativa o webhook.

#### Scenario: Update sem merge
- **WHEN** o usuário chama `update(id, {"uri": "https://novo"})`
- **THEN** o corpo enviado contém apenas `{"webHook": {"uri": "https://novo"}}`

### Requirement: Tipos de evento
`webhooks.event_types()` SHALL enviar `GET /v2/webhooks/eventtypes` e devolver a lista lida de
`eventTypes`, com `id` tratado como texto livre.

#### Scenario: Lista de tipos
- **WHEN** a API devolve 47 tipos, incluindo identificadores fora do padrão
- **THEN** o método devolve os 47 sem erro

### Requirement: Verificação de assinatura
`nfeio.webhooks.verify_signature(payload, signature, secret) -> bool` SHALL devolver `True` somente
quando `signature` tiver o prefixo `sha1=` (sem distinção de maiúsculas) seguido de exatamente 40
dígitos hexadecimais iguais, sem distinção de maiúsculas, ao HMAC-SHA1 de `payload` com `secret`. A
comparação MUST usar `hmac.compare_digest`. A função MUST NOT levantar exceção para nenhuma entrada:
assinatura ausente, vazia, malformada, com outro algoritmo, segredo vazio ou tipos inesperados SHALL
resultar em `False`. `payload` SHALL aceitar `bytes` ou `str` (codificada em UTF-8) e `signature`
SHALL aceitar `str`, sequência de `str` (usa o primeiro) ou `None`. Não requer cliente.

#### Scenario: Entregas reais
- **WHEN** a função recebe cada um dos 3 corpos de ping reais do arquivo de vetores com o segredo e o `X-Hub-Signature` capturados
- **THEN** devolve `True` para os três

#### Scenario: Hex em minúsculas
- **WHEN** a assinatura válida é enviada em minúsculas
- **THEN** a função devolve `True`

#### Scenario: Corpo adulterado
- **WHEN** um byte do corpo é alterado
- **THEN** a função devolve `False`

#### Scenario: Entradas inválidas
- **WHEN** a assinatura é `sha256=<hex válido>`, ou 40 hex sem prefixo, ou `sha1=abc`, ou contém não hex, ou `None`, ou o segredo é vazio
- **THEN** a função devolve `False` sem levantar exceção

### Requirement: Construção do evento
`nfeio.webhooks.construct_event(payload, headers, secret) -> WebhookEvent` SHALL verificar a assinatura
lida de `X-Hub-Signature` antes de interpretar o corpo e SHALL levantar `SignatureVerificationError`
quando ela não for válida. Só após a verificação o corpo SHALL ser decodificado como JSON, com limite de
5 MiB. `WebhookEvent` SHALL expor `action`, `event_type` (de `X-Hook-Event`), `hook_id` (de `X-Hook-Id`),
`data` e `raw` (bytes recebidos). Para corpo `{"action", "payload"}`, `data` SHALL ser o `payload`
(como `ServiceInvoice` quando `event_type` for `service_invoice`); para ping
`{"action":"ping","webHook"}`, `data` SHALL ser o `webHook`.

#### Scenario: Entrega de nota emitida
- **WHEN** chega `{"action":"issued_successfully","payload":{"id":"…","flowStatus":"Issued"}}` com `X-Hook-Event: service_invoice` e assinatura válida
- **THEN** `event.action == "issued_successfully"` e `event.data.flow_status == "Issued"`

#### Scenario: Assinatura inválida
- **WHEN** a assinatura não confere
- **THEN** o SDK levanta `SignatureVerificationError` sem decodificar o corpo

#### Scenario: Cabeçalhos sem distinção de maiúsculas
- **WHEN** os cabeçalhos chegam como `x-hub-signature` e `x-hook-id`
- **THEN** o evento é construído normalmente
