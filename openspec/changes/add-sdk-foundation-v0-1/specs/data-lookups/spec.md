## Purpose

Define as consultas de dados cadastrais oferecidas pelo SDK — pessoa jurídica por CNPJ, situação de
pessoa física por CPF e endereço por CEP — que usam a chave de dados e hosts próprios.

## ADDED Requirements

### Requirement: Consulta de CNPJ
`lookups.cnpj(cnpj, *, update_address=None, update_city_code=None)` SHALL enviar
`GET https://legalentity.api.nfe.io/v3/legalentities/basicInfo/{cnpj}` com a chave de dados e devolver
`LegalEntity` desembrulhada de `legalEntity`. O SDK SHALL aceitar CNPJ numérico ou alfanumérico, com ou
sem máscara, normalizá-lo para 14 caracteres maiúsculos e validar os dígitos verificadores pelo
algoritmo da Receita Federal antes da requisição.

#### Scenario: CNPJ com máscara
- **WHEN** o usuário consulta `"00.000.000/0001-91"`
- **THEN** a requisição usa o path `/v3/legalentities/basicInfo/00000000000191`

#### Scenario: CNPJ alfanumérico
- **WHEN** o usuário consulta `"12.ABC.345/01DE-35"`
- **THEN** a validação local aceita e a requisição usa `12ABC34501DE35`

#### Scenario: Dígito verificador errado
- **WHEN** o usuário consulta `"00000000000100"`
- **THEN** o SDK levanta `InvalidParameterError` sem requisição

### Requirement: Inscrições estaduais por CNPJ
`lookups.cnpj_state_taxes(cnpj, state)` SHALL enviar `GET …/v3/legalentities/stateTaxInfo/{UF}/{cnpj}`
com a UF validada entre as 27 unidades federativas.

#### Scenario: UF inválida
- **WHEN** o usuário informa `state="XX"`
- **THEN** o SDK levanta `InvalidParameterError` sem requisição

### Requirement: Consulta de CPF
`lookups.cpf(cpf, birth_date)` SHALL enviar
`GET https://naturalperson.api.nfe.io/v1/naturalperson/status/{cpf}/{AAAA-MM-DD}` com a chave de dados,
aceitando `birth_date` como `date` ou texto `AAAA-MM-DD` e validando os dígitos do CPF antes da
requisição. CPF existente com data divergente SHALL resultar em `NotFoundError`.

#### Scenario: Data divergente
- **WHEN** a API responde 404 com `{"errors":[{"code":40401,"message":"not found"}]}`
- **THEN** o SDK levanta `NotFoundError` com `error_code == 40401`

#### Scenario: Data em formato brasileiro
- **WHEN** o usuário passa `birth_date="01/01/1990"`
- **THEN** o SDK levanta `InvalidParameterError` sem requisição

### Requirement: Consulta de CEP
`lookups.cep(cep)` SHALL enviar `GET https://address.api.nfe.io/v2/addresses/{cep}` com a chave de
dados, aceitando CEP com ou sem hífen (normalizado para 8 dígitos), e devolver `Address` desembrulhado
de `address`. O SDK MUST NOT oferecer busca de endereço por termo ou filtro.

#### Scenario: CEP com hífen
- **WHEN** o usuário consulta `"01310-100"`
- **THEN** a requisição usa o path `/v2/addresses/01310100` e o retorno tem `address["city"]["code"] == "3550308"`

### Requirement: Modelos de consulta
Os modelos de consulta SHALL seguir a regra enxuta de `client-core`: `LegalEntity` SHALL expor
propriedades tipadas para `federal_tax_number` (string de 14 caracteres), `status`, `opened_on`,
`status_on` e `share_capital` (`Decimal`); `NaturalPerson` para `federal_tax_number` (string de 11
dígitos), `status` e `birth_on`; `Address` para `postal_code` (8 dígitos). Os demais campos (`name`,
`tradeName`, `address`, `phones`, `economicActivities`, `street`, `district`, `city`, `state`, …) SHALL
estar disponíveis no acesso por chave.

#### Scenario: Endereço
- **WHEN** a resposta é `{"address":{"state":"SP","city":{"code":"3550308","name":"São Paulo"},"postalCode":"01310-100",…}}`
- **THEN** `address["state"] == "SP"`, `address["city"]["name"] == "São Paulo"` e `address.postal_code == "01310100"`
