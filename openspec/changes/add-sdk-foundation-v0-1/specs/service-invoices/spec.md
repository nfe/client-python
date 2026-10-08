## Purpose

Define as operações de Nota Fiscal de Serviço eletrônica (NFS-e, API v1 em `api.nfe.io`) oferecidas pelo
SDK: emitir, listar, consultar por id e por `externalId`, cancelar, reenviar e-mail e baixar PDF e XML,
seguindo o contrato observado no fio.

## ADDED Requirements

### Requirement: Emitir NFS-e
`service_invoices.create(company_id, params, *, external_id=None, options=None)` SHALL enviar
`POST /v1/companies/{company_id}/serviceinvoices` com o corpo informado (chaves do fio) acrescido de
`externalId` quando `external_id` for informado, e SHALL aceitar 202 (assíncrono) e 200/201 (imediato).

#### Scenario: Emissão assíncrona
- **WHEN** a API responde 202
- **THEN** o SDK devolve a nota parcial com `id` e `flow_status` e `last_response.status_code == 202`

#### Scenario: Conflito de externalId informado nos dois lugares
- **WHEN** o usuário passa `external_id="A"` e `params["externalId"] == "B"`
- **THEN** o SDK levanta `InvalidParameterError` sem requisição

### Requirement: Listar NFS-e
`service_invoices.list(company_id, *, page_index=1, page_count=10, issued_begin=None, issued_end=None,
created_begin=None, created_end=None)` SHALL enviar `GET /v1/companies/{company_id}/serviceinvoices`
com os filtros informados (datas em `AAAA-MM-DD`) e SHALL devolver uma página por índice de
`ServiceInvoice` lida de `serviceInvoices`.

#### Scenario: Filtro por data de emissão
- **WHEN** o usuário lista com `issued_begin=date(2026,1,1)` e `issued_end=date(2026,12,31)`
- **THEN** a requisição envia `issuedBegin=2026-01-01&issuedEnd=2026-12-31`

### Requirement: Consultar NFS-e
`service_invoices.retrieve(company_id, invoice_id)` SHALL enviar `GET …/serviceinvoices/{invoice_id}` e
devolver a nota (objeto sem envelope).

#### Scenario: Nota inexistente
- **WHEN** a API responde 404 com a string `service invoice with id (X) was not found`
- **THEN** o SDK levanta `NotFoundError` com essa mensagem

### Requirement: Consultar por externalId
`service_invoices.find_by_external_id` SHALL enviar `GET …/serviceinvoices/external/{external_id}` com o
valor codificado e SHALL tratar a resposta como lista conforme a capacidade `retry-idempotency`.

#### Scenario: Codificação do externalId
- **WHEN** o usuário busca `external_id="WOO NFE/110"`
- **THEN** o path enviado termina em `/external/WOO%20NFE%2F110`

### Requirement: Cancelar NFS-e
`service_invoices.cancel(company_id, invoice_id)` SHALL enviar `DELETE …/serviceinvoices/{invoice_id}` e
SHALL aceitar 202 (assíncrono, tratado como na capacidade `polling`) e 200 (corpo de nota ou texto).

#### Scenario: Cancelamento assíncrono
- **WHEN** a API responde 202 com `Location`
- **THEN** o SDK devolve a nota parcial com o id da nota cancelada

### Requirement: Reenviar e-mail
`service_invoices.send_email(company_id, invoice_id)` SHALL enviar
`PUT …/serviceinvoices/{invoice_id}/sendemail` sem corpo e SHALL concluir sem erro em resposta 2xx.

#### Scenario: Reenvio aceito
- **WHEN** a API responde 200
- **THEN** o método retorna sem levantar exceção

### Requirement: Baixar PDF e XML
`download_pdf`, `download_xml` e `download_cancellation_xml` SHALL enviar `GET` para `…/{invoice_id}/pdf`,
`…/xml` e `…/cancellation-xml` e SHALL devolver os `bytes` do documento, seguindo redirects conforme a
capacidade `http-transport`. O XML SHALL ser devolvido sem alteração, inclusive quando não tiver prólogo
`<?xml`. Os métodos MUST exigir `invoice_id` (não existe download em lote).

#### Scenario: PDF via redirect
- **WHEN** `GET …/pdf` responde 302 para uma URL pré-assinada que devolve `application/pdf`
- **THEN** o método devolve bytes começando com `%PDF`

#### Scenario: XML sem prólogo
- **WHEN** o documento baixado começa com `<Nfse>`
- **THEN** os bytes devolvidos são idênticos aos recebidos

#### Scenario: XML de cancelamento indisponível
- **WHEN** a API responde 404 com a explicação de que o XML de cancelamento só existe no ambiente nacional
- **THEN** o SDK levanta `NotFoundError` com essa mensagem

### Requirement: Modelo ServiceInvoice
`ServiceInvoice` SHALL expor propriedades tipadas apenas para `id`, `external_id`, `environment`,
`flow_status`, `flow_message`, `status`, `services_amount`, `base_tax_amount`, `deductions_amount`,
`iss_rate`, `iss_tax_amount`, `amount_net`, `issued_on`, `cancelled_on`, `created_on`, `modified_on`,
`provider` e `borrower` (estes dois como `Party`, com `id` e `federal_tax_number` normalizado), cada uma
correspondendo a uma chave presente na spec ou observada no fio, e SHALL preservar todas as demais chaves
(por exemplo `number`, `checkCode`, `rpsNumber`, `description`, `cityServiceCode`) no acesso por chave
conforme a capacidade `client-core`.

#### Scenario: Tomador com documento numérico
- **WHEN** a resposta traz `"borrower": {"federalTaxNumber": 52998224725}`
- **THEN** `invoice.borrower.federal_tax_number == "52998224725"`

### Requirement: Corpo de emissão tipado
O SDK SHALL publicar um tipo de corpo de emissão com as chaves do fio documentadas na spec de NFS-e v1,
aceitando valores monetários como `int`, `float` ou `Decimal`, serializados como número JSON sem perda.

#### Scenario: Valor Decimal na emissão
- **WHEN** o corpo contém `"servicesAmount": Decimal("100.10")`
- **THEN** o JSON enviado contém `"servicesAmount":100.10`
