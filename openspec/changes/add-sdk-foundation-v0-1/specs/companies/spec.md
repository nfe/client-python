## Purpose

Define o gerenciamento de empresas (contribuintes) pelo SDK sobre a API de Empresas v2
(`api.nfse.io/v2/companies`), que a documentação oficial indica como substituta da v1 em
descontinuação (decisão D3 = A, 2026-10-08).

## ADDED Requirements

### Requirement: Listar empresas por cursor
`companies.list(*, limit=10, starting_after=None, ending_before=None)` SHALL enviar `GET /v2/companies`
com a chave principal e devolver uma página por cursor de `Company` lida de `companies`, com `has_more`
lido de `hasMore`.

#### Scenario: Varredura de todas as empresas
- **WHEN** a conta tem 662 empresas e o usuário itera `companies.list().auto_paging_iter()`
- **THEN** recebe 662 empresas distintas usando `limit=50` e `startingAfter` com o id do último item

### Requirement: Consultar empresa
`companies.retrieve(company_id)` SHALL enviar `GET /v2/companies/{company_id}` e devolver a empresa
desembrulhada de `company`.

#### Scenario: Empresa inexistente
- **WHEN** a API responde 404 com `{"errors":[{"code":40401,"message":"…"}]}`
- **THEN** o SDK levanta `NotFoundError` com `error_code == 40401`

### Requirement: Criar, alterar e excluir empresa
`companies.create(params)` SHALL enviar `POST /v2/companies` com o corpo embrulhado em `{"company": …}`;
`companies.update(company_id, params)` SHALL enviar `PUT /v2/companies/{company_id}` com o mesmo envelope
e substituição completa; `companies.delete(company_id)` SHALL enviar `DELETE /v2/companies/{company_id}`
e aceitar 204. As respostas com corpo SHALL ser desembrulhadas de `company`.

#### Scenario: Criação
- **WHEN** o usuário chama `create({"name": "…", "federalTaxNumber": …, "taxRegime": "SimplesNacional", "address": {…}})`
- **THEN** o corpo enviado é `{"company": {…}}` e o retorno é a empresa criada

#### Scenario: Exclusão
- **WHEN** a API responde 204
- **THEN** o método retorna `None` sem erro

### Requirement: Modelo Company
`Company` SHALL expor propriedades tipadas apenas para `id`, `account_id`, `federal_tax_number`
(string normalizada de 14 caracteres), `tax_regime`, `status`, `municipal_tax_ids` (lista de ids de
`municipalTaxes`), `state_tax_ids`, `created_on` e `modified_on`; `name`, `tradeName`, `address` e os
demais campos ficam no acesso por chave. O SDK MUST NOT expor
o campo `municipalTaxNumber` da v2 como inscrição municipal, porque o fio o preenche com o id da
inscrição; o valor continua acessível pelo nome do fio.

#### Scenario: municipalTaxNumber com id
- **WHEN** a resposta v2 traz `"municipalTaxNumber": "0a1b2c3d4e5f60718293a4b5c6d7e8f9"`
- **THEN** não existe propriedade tipada que o apresente como inscrição municipal e `company["municipalTaxNumber"]` devolve o valor cru
