## Purpose

Define como o usuário cria e configura o cliente da NFE.io em Python: chaves por família de API, hosts,
opções por chamada, proteção de segredos, validação de identificadores e representação dos modelos de
resposta com preservação integral do que vem no fio.

## ADDED Requirements

### Requirement: Cliente explícito sem estado global
O SDK SHALL expor `NfeClient` (síncrono) e `AsyncNfeClient` (assíncrono) como pontos de entrada, cada
instância com configuração própria e imutável. O SDK MUST NOT manter chave de API, host ou opção em
estado global de módulo, de modo que duas instâncias com chaves diferentes coexistam no mesmo processo
sem interferência.

#### Scenario: Dois clientes com chaves diferentes no mesmo processo
- **WHEN** o usuário cria `NfeClient(api_key="A")` e `NfeClient(api_key="B")` e chama o mesmo método nos dois
- **THEN** cada requisição sai com a chave do seu cliente

#### Scenario: Recursos expostos como atributos
- **WHEN** o usuário acessa `client.service_invoices`, `client.companies`, `client.certificates`, `client.webhooks` e `client.lookups`
- **THEN** cada atributo devolve o serviço do recurso, com métodos em snake_case

### Requirement: Chaves por família de API
O SDK SHALL aceitar `api_key` (famílias fiscais e de gestão) e `data_api_key` (consultas de CNPJ, CPF e
CEP) e, quando omitidas, SHALL ler `NFE_API_KEY` e `NFE_DATA_API_KEY` do ambiente. Cada recurso MUST
usar a chave da sua família. O SDK MUST NOT usar a chave principal como substituta da chave de dados.

#### Scenario: Consulta sem chave de dados
- **WHEN** o cliente foi criado só com `api_key` e o usuário chama uma consulta de CNPJ
- **THEN** o SDK levanta `ConfigurationError` informando que `data_api_key` é necessária, sem abrir conexão

#### Scenario: Emissão usa a chave principal
- **WHEN** o cliente tem `api_key` e `data_api_key` e o usuário lista notas de serviço
- **THEN** a requisição sai com a `api_key`

#### Scenario: Nenhuma chave disponível
- **WHEN** o cliente é criado sem `api_key` e sem `NFE_API_KEY` no ambiente e o usuário chama um recurso fiscal
- **THEN** o SDK levanta `ConfigurationError` antes de qualquer requisição

### Requirement: Autenticação pelo cabeçalho Authorization
O SDK SHALL enviar a chave no cabeçalho `Authorization` com o valor cru da chave, sem prefixo, em todos
os hosts. O SDK MUST NOT enviar a chave na query string nem em requisição a destino de redirect.

#### Scenario: Cabeçalho de autenticação
- **WHEN** qualquer requisição autenticada é enviada
- **THEN** ela contém `Authorization: <chave>` e a URL não contém a chave

### Requirement: Hosts por família configuráveis
O SDK SHALL usar, por padrão, `https://api.nfe.io` para NFS-e, `https://api.nfse.io` para empresas,
certificados e webhooks, `https://legalentity.api.nfe.io` para CNPJ, `https://naturalperson.api.nfe.io`
para CPF e `https://address.api.nfe.io` para CEP, e SHALL permitir sobrescrever a base de cada família na
criação do cliente. O SDK MUST rejeitar base que não use `https`.

#### Scenario: Base sobrescrita para testes
- **WHEN** o usuário cria o cliente com a base da família fiscal apontando para `https://localhost:8443`
- **THEN** as requisições de NFS-e vão para esse host e as das demais famílias continuam nos padrões

#### Scenario: Base sem TLS
- **WHEN** o usuário informa uma base `http://`
- **THEN** o SDK levanta `ConfigurationError`

### Requirement: Opções por chamada
Todo método público que faz requisição SHALL aceitar `options: RequestOptions | None`, com `api_key`,
`timeout`, `max_retries`, `idempotency_key` e `extra_headers`, que sobrescrevem a configuração do cliente
só naquela chamada. `extra_headers` MUST NOT sobrescrever `Authorization`, `User-Agent` nem
`Content-Type`. `idempotency_key` SHALL ser enviado como cabeçalho `Idempotency-Key` e MUST NOT alterar a
política de retry.

#### Scenario: Timeout e retries por chamada
- **WHEN** o usuário chama `create(..., options=RequestOptions(timeout=90, max_retries=0))`
- **THEN** só essa chamada usa 90 s de timeout e nenhuma nova tentativa

#### Scenario: Cabeçalho protegido
- **WHEN** `extra_headers` contém `Authorization`
- **THEN** o SDK levanta `ConfigurationError` e não envia a requisição

### Requirement: Segredos mascarados
O SDK MUST NOT expor chaves de API ou senha de certificado em `repr`, `str`, mensagens de exceção ou
registros de log. Representações de cliente, configuração e opções SHALL mostrar no máximo os 4 últimos
caracteres da chave.

#### Scenario: repr do cliente
- **WHEN** o usuário imprime `repr(client)`
- **THEN** a saída não contém a chave completa e mostra apenas um sufixo mascarado

#### Scenario: Varredura de vazamento
- **WHEN** uma sequência de chamadas com sucesso, erro 401, erro 500 e falha de rede é executada com log em nível DEBUG
- **THEN** nenhuma linha de log, `repr` ou mensagem de exceção contém a chave ou a senha do certificado

### Requirement: Validação de identificadores antes de compor o path
O SDK SHALL validar todo valor interpolado em path antes da requisição: identificadores opacos MUST casar
`^[A-Za-z0-9_-]{1,64}$`; texto livre (como `external_id`) MUST ser codificado por percent-encoding de
todos os caracteres reservados e MUST ser rejeitado se vazio, igual a `.` ou `..`, com caractere de
controle ou com mais de 255 caracteres. Valor inválido SHALL levantar `InvalidParameterError` sem
requisição.

#### Scenario: Tentativa de path traversal
- **WHEN** o usuário chama `retrieve(company_id, "../../v2/webhooks")`
- **THEN** o SDK levanta `InvalidParameterError` e nenhuma requisição é enviada

#### Scenario: externalId com barra
- **WHEN** o usuário busca o `external_id` `"pedido/123"`
- **THEN** o path enviado contém `pedido%2F123` em um único segmento

### Requirement: Modelos preservam o fio
Todo objeto de resposta SHALL ser um `Mapping[str, Any]` imutável que dá acesso de leitura a todas as
chaves do JSON recebido, inclusive as que o SDK não conhece, pelo nome original do fio (`obj["chave"]`),
e SHALL oferecer `to_dict()` com cópia profunda serializável em JSON. No acesso por chave, um `Mapping`
aninhado SHALL ser devolvido como `NfeObject` e uma lista SHALL ser devolvida como lista nova cujos
`Mapping` também são `NfeObject`; escalares SHALL ser devolvidos como vieram. Propriedades tipadas em
snake_case SHALL existir apenas para campos que o SDK corrige ou tipa (ids, status, datas, valores
monetários e alíquotas, documentos e aninhados que contêm documento). O SDK MUST NOT descartar campos
desconhecidos e MUST NOT resolver atributos dinamicamente a partir das chaves do fio (`__getattr__`).

#### Scenario: Campo novo no servidor
- **WHEN** a API passa a devolver `"novoCampo": 1` numa nota de serviço
- **THEN** `invoice["novoCampo"] == 1` e `invoice.to_dict()["novoCampo"] == 1` sem atualização do SDK

#### Scenario: Propriedade tipada
- **WHEN** a resposta contém `"flowStatus": "Issued"`
- **THEN** `invoice.flow_status == "Issued"`

#### Scenario: Aninhado por chave
- **WHEN** a resposta contém `"borrower": {"name": "Cliente", "address": {"city": {"code": "3550308"}}}`
- **THEN** `invoice["borrower"]["address"]["city"]["code"] == "3550308"`, `invoice["borrower"]` é um `NfeObject` e `invoice.to_dict()["borrower"]` é um `dict` comum

#### Scenario: Campo do fio com nome de método de Mapping
- **WHEN** a resposta contém `"items": [{"code": "1"}]`
- **THEN** `obj["items"][0]["code"] == "1"` e `obj.items()` continua sendo o método de `Mapping`

#### Scenario: Imutabilidade
- **WHEN** o usuário altera a lista devolvida por `obj["filters"]`
- **THEN** `obj["filters"]` e `obj.to_dict()["filters"]` continuam com o valor original

### Requirement: Tipos de dados robustos ao fio
Propriedades de data SHALL devolver `datetime` com fuso, aceitando sufixo `Z`, offset e de 0 a 7 dígitos
fracionários, e SHALL devolver `None` quando o texto não for interpretável, mantendo o valor original no
acesso cru. Propriedades monetárias e de alíquota SHALL devolver `Decimal` sem erro de representação
binária para valores de até 15 dígitos significativos. Números de documento (CNPJ/CPF) SHALL ser
expostos como `str` normalizada, preservando zeros à esquerda.

#### Scenario: Data com milissegundos em Python 3.10
- **WHEN** a resposta contém `"createdOn": "2026-09-01T02:55:33.418+00:00"`
- **THEN** a propriedade devolve o `datetime` correspondente com fuso UTC em todas as versões suportadas

#### Scenario: Valor monetário
- **WHEN** a resposta contém `"servicesAmount": 1234.56`
- **THEN** a propriedade devolve `Decimal("1234.56")`

#### Scenario: CNPJ devolvido como inteiro pela API
- **WHEN** uma resposta traz `"federalTaxNumber": 191` num contexto de CNPJ
- **THEN** a propriedade devolve `"00000000000191"`

### Requirement: Metadados da última resposta
Todo objeto e página devolvidos SHALL expor `last_response` com `status_code`, cabeçalhos
(consulta sem distinção de maiúsculas) e `request_id` lido de `x-request-id`.

#### Scenario: Request id disponível
- **WHEN** a API responde com `x-request-id: 0HNP51M3F3EVD:00000006`
- **THEN** `obj.last_response.request_id == "0HNP51M3F3EVD:00000006"`
