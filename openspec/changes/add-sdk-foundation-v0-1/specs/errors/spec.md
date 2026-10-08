## Purpose

Define as exceções do SDK: hierarquia por categoria e status HTTP, preservação da resposta da API,
extração de mensagem dos formatos de erro realmente usados pela NFE.io e identificação da requisição
para suporte.

## ADDED Requirements

### Requirement: Hierarquia tipada de erros
Todas as exceções do SDK SHALL derivar de `NfeError`. Respostas HTTP de erro SHALL ser mapeadas para
subclasses de `APIError`: 401 → `AuthenticationError`, 403 → `PermissionDeniedError`, 404 →
`NotFoundError`, 409 → `ConflictError`, 429 → `RateLimitError`, 408 e 5xx → `ServerError`, demais 4xx →
`InvalidRequestError`. Falhas de rede SHALL ser `APIConnectionError`, com `APITimeoutError` como
subclasse para timeouts. Erros de configuração e de parâmetro local SHALL derivar também de `ValueError`.

#### Scenario: 403 da API
- **WHEN** a API responde 403
- **THEN** o SDK levanta `PermissionDeniedError` com `status_code == 403`

#### Scenario: 422 da API
- **WHEN** a API responde 422
- **THEN** o SDK levanta `InvalidRequestError`

#### Scenario: Captura genérica
- **WHEN** o usuário captura `NfeError`
- **THEN** qualquer exceção levantada pelo SDK é capturada

### Requirement: Preservação da resposta
`APIError` SHALL expor `status_code`, `message`, `error_code` (quando houver), `body` (bytes integrais),
`json_body` (quando o corpo for JSON), `headers`, `request_id` (de `x-request-id`) e `trace_id` (de
`traceId` em ProblemDetails).

#### Scenario: Request id no erro
- **WHEN** uma resposta 404 traz `x-request-id: abc:1`
- **THEN** a exceção tem `request_id == "abc:1"`

### Requirement: Extração de mensagem dos envelopes da API
O SDK SHALL extrair a mensagem de erro de: corpo vazio (mensagem padrão por status), string JSON crua,
`{"errors":[{"code","message"}]}` (todas as mensagens; `error_code` = primeiro `code`),
`{"errors":[{"message"}]}`, `{"code","message"}` e ProblemDetails (`title` mais cada
`campo: mensagem` de `errors`). A mensagem MUST ter caracteres de controle removidos e no máximo 1.000
caracteres; o corpo integral permanece em `body`.

#### Scenario: String JSON crua
- **WHEN** a API responde 400 com o corpo `"pageCount must be between 1 and 50"`
- **THEN** `message == "pageCount must be between 1 and 50"`

#### Scenario: Lista de erros com código
- **WHEN** a API responde 404 com `{"errors":[{"code":40401,"message":"company id not found"}]}`
- **THEN** `message == "company id not found"` e `error_code == 40401`

#### Scenario: ProblemDetails de validação
- **WHEN** a API responde 400 com `{"title":"One or more validation errors occurred.","errors":{"pageIndex":["The value 'abc' is not valid."]},"traceId":"00-x-y-01"}`
- **THEN** a mensagem contém `pageIndex: The value 'abc' is not valid.` e `trace_id == "00-x-y-01"`

#### Scenario: 401 com corpo vazio
- **WHEN** a API responde 401 sem corpo
- **THEN** o SDK levanta `AuthenticationError` com mensagem padrão não vazia

### Requirement: Dica de chave em 403
`PermissionDeniedError` SHALL informar na mensagem qual parâmetro de chave (`api_key` ou `data_api_key`)
a família do recurso usa.

#### Scenario: Consulta de CNPJ com chave errada
- **WHEN** uma consulta de CNPJ recebe 403
- **THEN** a mensagem menciona `data_api_key`

### Requirement: Erro não expõe segredos
`str`, `repr` e atributos de qualquer exceção MUST NOT conter a chave de API nem o cabeçalho
`Authorization` enviado.

#### Scenario: Erro de autenticação
- **WHEN** a API responde 401
- **THEN** `str(err)` e `repr(err)` não contêm a chave usada

### Requirement: Resposta inesperada
Uma resposta 2xx cujo corpo não seja JSON válido quando JSON é esperado, ou que não permita identificar o
recurso criado, SHALL levantar `UnexpectedResponseError` com o status e o corpo preservados.

#### Scenario: 202 sem identificação
- **WHEN** a emissão responde 202 sem `id` no corpo e sem `Location`
- **THEN** o SDK levanta `UnexpectedResponseError`
