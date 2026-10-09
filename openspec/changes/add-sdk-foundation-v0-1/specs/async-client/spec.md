## Purpose

Define o cliente assíncrono `AsyncNfeClient`, que oferece a mesma superfície e o mesmo comportamento do
cliente síncrono para aplicações asyncio, sem dependências extras.

## ADDED Requirements

### Requirement: Paridade de superfície
`AsyncNfeClient` SHALL expor os mesmos recursos e métodos públicos de `NfeClient`, com os mesmos nomes,
parâmetros e tipos de retorno, sendo cada método uma corrotina.

#### Scenario: Assinaturas iguais
- **WHEN** o teste de paridade compara a assinatura de cada método público dos dois clientes
- **THEN** parâmetros, valores padrão e anotações de retorno coincidem

### Requirement: Comportamento idêntico
Retry, mapeamento de erros, paginação, polling, validação de parâmetros e mascaramento de segredos SHALL
ter no cliente assíncrono exatamente o mesmo comportamento do síncrono para a mesma sequência de
respostas.

#### Scenario: Mesma sequência de respostas
- **WHEN** um GET recebe 503, 503 e 200 nos dois clientes
- **THEN** ambos fazem 3 tentativas com o mesmo cálculo de espera e devolvem o mesmo objeto

### Requirement: Event loop não bloqueado
O transporte assíncrono padrão SHALL executar a E/S em thread separada (via `asyncio.to_thread` sobre o
transporte síncrono) e as esperas de retry e polling SHALL usar `asyncio.sleep`. O SDK SHALL aceitar
um transporte assíncrono nativo do usuário pelo protocolo público.

#### Scenario: Concorrência
- **WHEN** o usuário dispara 10 consultas com `asyncio.gather`
- **THEN** outras tarefas do loop continuam executando enquanto as requisições estão em voo

### Requirement: Ciclo de vida
`AsyncNfeClient` SHALL suportar `async with` e `aclose()`, liberando as conexões do pool;
`NfeClient` SHALL suportar `with` e `close()`.

#### Scenario: Context manager assíncrono
- **WHEN** o bloco `async with AsyncNfeClient(...) as c:` termina
- **THEN** as conexões ociosas são fechadas
