## Purpose

Define como o SDK expõe listagens paginadas da NFE.io — páginas por índice 1-based (API v1) e por cursor
(API v2) — e a iteração automática síncrona e assíncrona, respeitando os limites que a API realmente
aplica.

## ADDED Requirements

### Requirement: Página por índice 1-based
Listagens da API v1 SHALL aceitar `page_index` (primeira página = 1) e `page_count` (itens por página) e
SHALL devolver uma página com `data`, `page_index`, `page_count` e `has_more`. Como a API não informa
totais, `has_more` SHALL ser verdadeiro quando a página vier cheia (`len(data) == page_count`).

#### Scenario: Primeira página
- **WHEN** o usuário lista notas com `page_index=1, page_count=2` e a API devolve 2 itens
- **THEN** a requisição envia `pageIndex=1&pageCount=2` e a página tem `has_more == True`

#### Scenario: Última página
- **WHEN** a API devolve menos itens que `page_count`
- **THEN** `has_more == False`

### Requirement: Limites de página validados localmente
O SDK SHALL rejeitar com `InvalidParameterError`, sem requisição, `page_index < 1` e `page_count` fora
do intervalo aceito pela rota (1–50 em listagens de notas de serviço), mantendo os limites por rota numa
tabela única.

#### Scenario: Índice zero
- **WHEN** o usuário pede `page_index=0`
- **THEN** o SDK levanta `InvalidParameterError` explicando que a paginação começa em 1

#### Scenario: Página grande demais
- **WHEN** o usuário pede `page_count=100`
- **THEN** o SDK levanta `InvalidParameterError` informando o máximo de 50

### Requirement: Página por cursor
Listagens da API v2 SHALL aceitar `limit`, `starting_after` e `ending_before` e SHALL devolver uma página
com `data` e `has_more` lidos do fio (`hasMore`). `limit` MUST estar entre 1 e 50.

#### Scenario: Cursor para frente
- **WHEN** o usuário lista com `limit=2, starting_after="X"`
- **THEN** a requisição envia `limit=2&startingAfter=X`

#### Scenario: limit zero
- **WHEN** o usuário pede `limit=0`
- **THEN** o SDK levanta `InvalidParameterError` sem requisição

### Requirement: Iteração automática
Toda página SHALL oferecer `auto_paging_iter()`, que percorre os itens de todas as páginas seguintes sob
demanda, e `next_page()`, que devolve a próxima página ou `None`. Na paginação por cursor, as páginas
seguintes SHALL usar o tamanho máximo (`limit=50`); na paginação por índice, SHALL manter o `page_count`
da página inicial, porque trocar o tamanho desloca o índice e pularia itens. A iteração MUST parar ao
receber página vazia, mesmo que a API indique `hasMore: true`. O SDK MUST NOT
oferecer método que carregue todas as páginas em memória de uma vez.

#### Scenario: Varredura completa
- **WHEN** existem 120 notas e o usuário itera `list(...).auto_paging_iter()`
- **THEN** recebe as 120 notas em ordem, buscando páginas sob demanda

#### Scenario: hasMore inconsistente
- **WHEN** a API devolve `{"hasMore": true, "companies": []}`
- **THEN** a iteração termina sem nova requisição

### Requirement: Iteração assíncrona
No cliente assíncrono, `auto_paging_iter()` SHALL devolver um iterador assíncrono (`async for`) com o
mesmo comportamento da versão síncrona.

#### Scenario: async for
- **WHEN** o usuário faz `async for inv in (await aclient.service_invoices.list(cid)).auto_paging_iter()`
- **THEN** recebe todos os itens sem bloquear o event loop
