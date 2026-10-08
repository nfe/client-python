## Purpose

Define o transporte HTTP do SDK: implementação só com a biblioteca padrão, substituível por protocolo,
com TLS sempre verificado, timeouts finitos, limite de tamanho de resposta, User-Agent honesto, envio
multipart sem dependências e tratamento seguro de redirects.

## ADDED Requirements

### Requirement: Zero dependências de runtime
O pacote instalado MUST NOT declarar dependências de runtime; todo o transporte SHALL usar apenas a
biblioteca padrão do Python.

#### Scenario: Metadados do pacote
- **WHEN** o wheel publicado é inspecionado
- **THEN** a lista `Requires-Dist` não contém dependências obrigatórias

### Requirement: Transporte substituível
O SDK SHALL definir protocolos públicos de transporte síncrono e assíncrono e SHALL aceitar uma
implementação do usuário na criação do cliente. O transporte MUST NOT seguir redirects por conta própria.

#### Scenario: Transporte customizado
- **WHEN** o usuário passa um objeto que implementa o protocolo de transporte
- **THEN** todas as requisições do cliente passam por ele, com retry, erros e paginação funcionando igual

### Requirement: Classificação da fase da falha de rede
O transporte padrão SHALL distinguir falhas que ocorrem antes de qualquer byte da requisição ser enviado
(resolução de nome, conexão recusada, handshake TLS) das que ocorrem depois (timeout de leitura,
conexão encerrada), expondo a fase na exceção. Requisições POST MUST usar conexão nova, nunca uma
conexão reaproveitada do pool.

#### Scenario: DNS falha
- **WHEN** o host não resolve
- **THEN** a exceção de conexão informa a fase "não estabelecida"

#### Scenario: Timeout de leitura
- **WHEN** a conexão é estabelecida, a requisição é enviada e a resposta não chega dentro do timeout
- **THEN** a exceção de timeout informa a fase "pode ter sido enviada"

### Requirement: TLS sempre verificado
O SDK SHALL verificar certificado e nome do host em toda conexão, com versão mínima TLS 1.2. O SDK MAY
aceitar um contexto TLS ou pacote de CAs do usuário para acrescentar confiança, mas MUST rejeitar com
`ConfigurationError` qualquer contexto que desligue a verificação de certificado ou de nome do host. O
SDK MUST NOT oferecer opção para desligar a verificação.

#### Scenario: Contexto inseguro
- **WHEN** o usuário passa um `ssl.SSLContext` com `verify_mode = CERT_NONE`
- **THEN** a criação do cliente levanta `ConfigurationError`

#### Scenario: Certificado inválido no servidor
- **WHEN** o servidor apresenta certificado autoassinado não confiável
- **THEN** a requisição falha com erro de conexão na fase "não estabelecida"

### Requirement: Timeouts finitos
O SDK SHALL aplicar por padrão 10 s de timeout de conexão, 60 s de timeout de leitura e 120 s de prazo
total por tentativa, configuráveis no cliente e por chamada. O SDK MUST rejeitar timeout nulo, zero,
negativo ou infinito.

#### Scenario: Timeout infinito recusado
- **WHEN** o usuário configura `timeout=None`
- **THEN** o SDK levanta `ConfigurationError`

### Requirement: Limite de tamanho de resposta
O SDK SHALL ler respostas em blocos e interromper a leitura ao exceder `max_response_bytes` (padrão
10 MiB), levantando `ResponseTooLargeError` e descartando a conexão. O SDK SHALL pedir respostas sem
compressão (`Accept-Encoding: identity`).

#### Scenario: Resposta gigante
- **WHEN** o servidor envia um corpo maior que o limite configurado
- **THEN** o SDK levanta `ResponseTooLargeError` sem carregar o corpo inteiro em memória

### Requirement: User-Agent honesto
Toda requisição SHALL enviar `User-Agent: nfe-io-python/<versão> python/<major>.<minor> <plataforma>`,
onde a versão vem da fonte única de versão do pacote, e SHALL acrescentar `<nome>/<versão>` quando o
usuário informar `app_info`. O pacote MUST NOT conter outra literal de versão.

#### Scenario: Formato do User-Agent
- **WHEN** o SDK 0.1.0 roda em Python 3.12 no Linux
- **THEN** o cabeçalho é `nfe-io-python/0.1.0 python/3.12 linux`

#### Scenario: Identificação do módulo de ERP
- **WHEN** o cliente é criado com `app_info=("odoo-l10n_br_nfse_nfeio", "18.0.1.0")`
- **THEN** o cabeçalho termina com ` odoo-l10n_br_nfse_nfeio/18.0.1.0`

### Requirement: Multipart sem dependências
O SDK SHALL montar corpos `multipart/form-data` com fronteira aleatória imprevisível, nome de arquivo
saneado (sem aspas, CR ou LF) e partes binárias intactas.

#### Scenario: Nome de arquivo malicioso
- **WHEN** o nome do arquivo contém `"` e quebra de linha
- **THEN** o corpo enviado não contém esses caracteres no cabeçalho da parte

### Requirement: Redirects seguidos só sem credencial
Quando uma operação de download recebe 3xx, o SDK SHALL seguir no máximo 3 redirects, somente para
URLs `https`, e MUST NOT enviar a chave de API nem outros cabeçalhos de autenticação ao destino do
redirect. Redirect para `http` SHALL levantar erro.

#### Scenario: Download de PDF
- **WHEN** `GET …/pdf` responde 302 para uma URL pré-assinada em outro host
- **THEN** o SDK busca a URL sem `Authorization` e devolve os bytes do PDF

#### Scenario: Redirect para http
- **WHEN** o destino do redirect usa `http://`
- **THEN** o SDK levanta `UnexpectedResponseError` sem fazer a requisição

### Requirement: Location de resposta assíncrona não é seguido como URL
O SDK SHALL extrair somente o path do cabeçalho `Location` de respostas 202, validá-lo contra o formato
esperado do recurso e reconstruir qualquer URL derivada a partir da base configurada. O SDK MUST NOT
fazer requisição ao host ou esquema informados no `Location`.

#### Scenario: Location com http
- **WHEN** a emissão responde 202 com `Location: http://api.nfe.io/v1/companies/C/serviceinvoices/I`
- **THEN** o SDK registra o id `I` e consultas posteriores vão para a base `https` configurada
