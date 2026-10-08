## Purpose

Define quando o SDK repete uma requisição e quando não pode repetir, para que falhas transitórias sejam
absorvidas sem nunca duplicar uma emissão fiscal, e como o usuário reconcilia emissões de resultado
incerto usando `externalId`.

## ADDED Requirements

### Requirement: Retry ciente de método e de fase
O SDK SHALL repetir requisições GET, HEAD, PUT e DELETE em respostas 408, 429, 500, 502, 503 e 504 e em
falhas de rede de qualquer fase. Para POST, o SDK SHALL repetir apenas falhas de rede ocorridas antes de
a conexão ser estabelecida, e MUST NOT repetir em resposta 408, 429 ou 5xx nem em falha ocorrida depois
do envio. Demais respostas 4xx MUST NOT ser repetidas.

#### Scenario: GET com 503
- **WHEN** um GET recebe 503 e depois 200
- **THEN** o SDK devolve o resultado do 200 após uma nova tentativa

#### Scenario: POST de emissão com 504
- **WHEN** o POST de emissão recebe 504
- **THEN** o SDK não faz nova tentativa e levanta `ServerError` com `outcome_unknown=True`

#### Scenario: POST com conexão recusada
- **WHEN** o POST falha por conexão recusada antes do envio e a nova tentativa conecta
- **THEN** o SDK envia a requisição uma única vez ao servidor e devolve a resposta

#### Scenario: POST com timeout de leitura
- **WHEN** o POST é enviado e a leitura da resposta estoura o timeout
- **THEN** o SDK não repete e levanta `APITimeoutError` com `outcome_unknown=True`

#### Scenario: POST com 429
- **WHEN** um POST recebe 429
- **THEN** o SDK não repete e levanta `RateLimitError` com `retry_after` quando informado

### Requirement: Idempotency-Key não libera retry
O SDK MUST NOT tratar a presença de `Idempotency-Key` como autorização para repetir POST, enquanto a API
não honrar esse cabeçalho.

#### Scenario: POST com idempotency_key e 500
- **WHEN** o usuário envia um POST com `idempotency_key` e recebe 500
- **THEN** o SDK não repete a requisição

### Requirement: Backoff exponencial com jitter
O SDK SHALL esperar entre tentativas `min(max_delay, base · 2^(n−1))` multiplicado por fator aleatório
uniforme entre 0,7 e 1,3, com padrões `max_retries=3`, `base=1,0 s` e `max_delay=30 s`, todos
configuráveis no cliente, e `max_retries` também por chamada.

#### Scenario: Retries desligados
- **WHEN** a chamada usa `max_retries=0` e recebe 503 num GET
- **THEN** o SDK levanta `ServerError` após uma única tentativa

#### Scenario: Limite de tentativas
- **WHEN** um GET recebe 503 em todas as tentativas com a configuração padrão
- **THEN** o SDK faz 4 tentativas no total e levanta `ServerError`

### Requirement: Respeito a Retry-After
Em resposta repetível com `Retry-After`, o SDK SHALL aguardar o valor informado, em segundos inteiros ou
data HTTP, quando ele for menor ou igual a `max_retry_after` (padrão 60 s); acima disso, o SDK MUST NOT
repetir e SHALL levantar o erro correspondente com `retry_after` preenchido.

#### Scenario: Retry-After em data HTTP
- **WHEN** um GET recebe 429 com `Retry-After` em formato de data 5 s no futuro
- **THEN** o SDK espera cerca de 5 s antes da nova tentativa

#### Scenario: Retry-After longo demais
- **WHEN** um GET recebe 429 com `Retry-After: 3600`
- **THEN** o SDK levanta `RateLimitError` com `retry_after == 3600` sem esperar

### Requirement: Registro de tentativas sem dados sensíveis
O SDK SHALL registrar cada nova tentativa no logger `nfeio` em nível DEBUG com método, host, path,
status, número da tentativa, espera e request id, e MUST NOT registrar cabeçalhos de autenticação, query
string ou corpo.

#### Scenario: Log de retry
- **WHEN** um GET é repetido após 502 com log DEBUG ativo
- **THEN** existe um registro com status 502 e tentativa 1, sem a chave de API

### Requirement: Dedupe de emissão por externalId
`service_invoices.create` SHALL aceitar `external_id` e enviá-lo como `externalId` no corpo. Quando a API
rejeitar a emissão por `externalId` já existente, o SDK SHALL levantar `DuplicateExternalIdError` com o
`external_id`. Erros de resultado incerto em emissão SHALL carregar `outcome_unknown=True` e o
`external_id`. O SDK MUST NOT reenviar uma emissão automaticamente após resultado incerto.

#### Scenario: externalId repetido
- **WHEN** a API responde 400 com `service invoice with external id (pedido-1) already exists`
- **THEN** o SDK levanta `DuplicateExternalIdError` com `external_id == "pedido-1"`

#### Scenario: Resultado incerto
- **WHEN** a emissão com `external_id="pedido-2"` recebe 500
- **THEN** o erro tem `outcome_unknown=True` e `external_id == "pedido-2"` e nenhuma segunda emissão é enviada

### Requirement: Busca por externalId com espera de indexação
`service_invoices.find_by_external_id(company_id, external_id, wait=0)` SHALL devolver a nota quando a
API retornar lista com itens e `None` quando retornar lista vazia, e, com `wait > 0`, SHALL repetir a
busca com backoff até encontrar ou esgotar o prazo.

#### Scenario: Nota encontrada
- **WHEN** a API responde `{"serviceInvoices":[{…}], "page":1}`
- **THEN** o método devolve o primeiro item como `ServiceInvoice`

#### Scenario: Nota inexistente
- **WHEN** a API responde 200 com `{"serviceInvoices":[], "page":1}`
- **THEN** o método devolve `None` sem levantar erro

#### Scenario: Indexação atrasada
- **WHEN** `wait=30` e a primeira busca volta vazia e a terceira traz a nota
- **THEN** o método devolve a nota
