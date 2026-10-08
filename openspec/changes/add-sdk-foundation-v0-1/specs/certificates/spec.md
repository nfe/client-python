## Purpose

Define o envio do certificado digital A1 de uma empresa e a consulta do seu estado e validade, operações
necessárias para que a empresa emita NFS-e.

## ADDED Requirements

### Requirement: Upload de certificado A1
`certificates.upload(company_id, file, password)` SHALL enviar `multipart/form-data` com as partes
`file` (conteúdo do PFX/P12, `Content-Type: application/x-pkcs12`) e `password` para
`POST /v2/companies/{company_id}/certificates` com a chave principal, aceitando `file` como `bytes`,
caminho de arquivo ou objeto binário legível, e SHALL devolver o `Certificate` desembrulhado de
`certificate`.
A senha MUST NOT aparecer em log, `repr` ou mensagem de erro.

#### Scenario: Upload a partir de caminho
- **WHEN** o usuário chama `upload(company_id, Path("cert.pfx"), "senha")`
- **THEN** o corpo multipart contém a parte `file` com os bytes do arquivo e a parte `password`

#### Scenario: Erro do servidor no upload
- **WHEN** a API responde 500 ao upload
- **THEN** o SDK não repete a requisição e levanta `ServerError` sem a senha na mensagem

### Requirement: Validação local do arquivo
Antes do envio, o SDK SHALL rejeitar com `InvalidParameterError` arquivo vazio ou maior que 1 MiB.

#### Scenario: Arquivo vazio
- **WHEN** o usuário envia `b""`
- **THEN** o SDK levanta `InvalidParameterError` sem requisição

### Requirement: Consultar certificados
`certificates.list(company_id)` SHALL enviar `GET /v2/companies/{company_id}/certificates` e devolver a
lista lida de `certificates`; empresa sem certificado SHALL resultar em lista vazia.

#### Scenario: Empresa sem certificado
- **WHEN** a API responde `{"certificates": []}`
- **THEN** o método devolve lista vazia sem erro

### Requirement: Modelo Certificate
`Certificate` SHALL expor propriedades tipadas apenas para `thumbprint`, `tax_id` (documento
normalizado), `status`, `provider_type`, `expires_on` e `modified_on`, sendo `expires_on` lido de
`validUntil` e, na ausência, de `expiresOn`, e SHALL oferecer `is_expired(at=None) -> bool`; `subject`,
`resolution` e os demais campos ficam no acesso por chave.

#### Scenario: Validade
- **WHEN** a resposta traz `"validUntil": "2026-11-03T16:18:00+00:00"`
- **THEN** `cert.expires_on` é esse instante e `cert.is_expired(at=datetime(2026,12,1,tzinfo=UTC))` é `True`
