## Purpose

Define como o SDK trata operações fiscais assíncronas da NFE.io (resposta 202 com `Location`) e como o
usuário espera a nota chegar a um estado final, com prazos, backoff e erros claros.

## ADDED Requirements

### Requirement: Resposta 202 preservada
Ao receber 202 numa emissão ou cancelamento, o SDK SHALL devolver a nota parcial construída a partir do
corpo da resposta (por exemplo `id`, `environment`, `flowStatus`), usando o id extraído do path do
`Location` quando o corpo não trouxer `id`.

#### Scenario: Corpo com id
- **WHEN** a emissão responde 202 com `{"id":"I","flowStatus":"WaitingCalculateTaxes"}`
- **THEN** o objeto devolvido tem `id == "I"` e `flow_status == "WaitingCalculateTaxes"`

#### Scenario: Corpo de nota completa no 202
- **WHEN** a emissão responde 202 com a nota completa (como observado em 2026-10-08)
- **THEN** o objeto devolvido preserva todos os campos e `flow_status` reflete o estado inicial

#### Scenario: Corpo vazio com Location
- **WHEN** a emissão responde 202 sem corpo e com `Location: http://api.nfe.io/v1/companies/C/serviceinvoices/I`
- **THEN** o objeto devolvido tem `id == "I"`

### Requirement: Espera por estado terminal
`service_invoices.wait(company_id, invoice_id, ...)` SHALL consultar a nota por `GET` do recurso até que
`flowStatus` seja terminal, com intervalo inicial de 1 s multiplicado por 1,5 a cada consulta até o
máximo de 10 s e prazo total padrão de 120 s, todos configuráveis. O SDK MUST NOT usar a rota
`/serviceinvoices/{id}/status`.

#### Scenario: Emissão concluída
- **WHEN** a nota passa de `WaitingSend` para `Issued`
- **THEN** `wait` devolve a nota com `flow_status == "Issued"`

#### Scenario: Prazo esgotado
- **WHEN** a nota continua `WaitingReturn` até o fim do prazo
- **THEN** o SDK levanta `PollingTimeoutError` contendo o último estado observado

### Requirement: Estados terminais e falhas de processamento
O SDK SHALL tratar `Issued` e `Cancelled` como terminais de sucesso e `IssueFailed`, `CancelFailed` e
`Error` como terminais de falha. Ao atingir falha, `wait` SHALL levantar `InvoiceProcessingError` com a
nota e o `flowMessage`, a menos que o usuário peça `raise_on_failure=False`. Valores de `flowStatus` não
conhecidos MUST ser tratados como não terminais.

#### Scenario: Rejeição da prefeitura
- **WHEN** a nota chega a `IssueFailed` com `flowMessage` "max retry …"
- **THEN** o SDK levanta `InvoiceProcessingError` com `flow_message` preenchido

#### Scenario: Estado novo desconhecido
- **WHEN** a API devolve `flowStatus: "WaitingSomethingNew"`
- **THEN** `wait` continua consultando até um estado terminal ou o prazo

### Requirement: Tolerância a atraso de indexação
Durante os primeiros `not_found_grace` segundos (padrão 10 s) de uma espera, respostas 404 da consulta
SHALL ser tratadas como "ainda processando"; depois disso, SHALL propagar `NotFoundError`.

#### Scenario: 404 logo após a emissão
- **WHEN** a primeira consulta do `wait` recebe 404 e a segunda recebe a nota
- **THEN** `wait` continua normalmente

### Requirement: Atalhos de emitir e cancelar com espera
O SDK SHALL oferecer `create_and_wait` e `cancel_and_wait`, que executam a operação e em seguida `wait`
com os mesmos parâmetros de espera, propagando `external_id` e marcação de resultado incerto quando a
operação inicial falhar.

#### Scenario: Cancelar e esperar
- **WHEN** o usuário chama `cancel_and_wait(company_id, invoice_id)` e a nota chega a `Cancelled`
- **THEN** o método devolve a nota com `flow_status == "Cancelled"`
