# Decisões — SDK Python v0.1 (todas fechadas em 2026-10-08)

Para o OK do André antes da implementação (change `add-sdk-foundation-v0-1`). Design e specs já
seguem a **recomendação** de cada item. Se a escolha for outra, ajusto specs e tasks antes de codar.
Evidência: `docs/contrato/probe-2026-10-08.md` (SONDA) e `design.md` (§).

Resposta curta aceita: "D1 ok, D3 opção A, …".

---

## D1. Como representar os modelos de resposta

| Opção | Como fica | Prós | Contras |
|---|---|---|---|
| A. Objeto dinâmico (`StripeObject`) | `inv.flowStatus` via `__getattr__` | preserva tudo; zero manutenção | tipagem fraca; nomes camelCase; erro de digitação só em runtime |
| B. `dataclass` congelada + `raw` (como PHP/Ruby) | `inv.flow_status`, `inv.raw["x"]` | tipagem forte | mapeamento campo a campo; histórico de DTO incompleto (PHP cobria 13 de 39 campos) |
| C. `TypedDict` do fio (como o Node) | `inv["flowStatus"]` | zero runtime; preserva tudo | camelCase no código Python; sem datas/Decimal; sem métodos |
| **D. Visão tipada (recomendada)** | `inv.flow_status` **e** `inv["flowStatus"]` | tipagem forte nas propriedades; **não perde campo por construção**; `to_dict()` devolve o fio | modelo inédito na família; propriedades escritas à mão |

**Recomendação: D.** **Trade-off:** mantemos propriedades à mão, protegidas por um teste de alinhamento
com a spec, e ganhamos compatibilidade futura sem esforço. (design §2)

## D2. Formato do corpo das requisições

| Opção | Exemplo | Prós | Contras |
|---|---|---|---|
| **A. `TypedDict` com chaves do fio em camelCase (recomendada)** | `create(cid, {"cityServiceCode": "…", "borrower": {...}})` | copia-e-cola da doc da API; nenhuma camada de tradução; campo novo funciona no mesmo dia | mistura estilos: argumentos em snake_case, corpo em camelCase |
| B. kwargs/TypedDict em snake_case traduzidos | `create(cid, city_service_code="…")` | 100% pythônico | tradutor recursivo para corpos de ~80 campos; bug de tradução vira erro fiscal; diverge da doc |
| C. Aceitar os dois | — | flexível | ambiguidade quando vêm os dois; dobra a superfície de teste |

**Recomendação: A.** Argumentos de método (`company_id`, `external_id`, `page_index`) continuam em
snake_case. **Trade-off:** inconsistência estética em troca de fidelidade ao contrato e de zero
tradução. (design §1)

## D3. Empresas: API v1 ou v2 no v0.1

**Evidência nova (SONDA §4):**
- O cursor da v2 varreu as 662 empresas sem erro, e o "registro venenoso" de jul/2026 hoje responde 200.
  O critério 1 do gate deixou de reproduzir.
- As projeções continuam diferentes: na v2, `municipalTaxNumber` guarda o id da inscrição.
- A v1 só enxerga 357 das 662 empresas, porque lista apenas empresas com inscrição municipal.
- A doc oficial marca a v1 como "em descontinuação".

| Opção | Prós | Contras |
|---|---|---|
| **A. v2 (cursor) para listar/consultar/CRUD (recomendada)** | API que a NFE.io manda usar; enxerga todas as empresas; sem migração futura | escrita v2 não provada ao vivo (create/delete exigem empresa nova, fora da `NFE_COMPANY_ID`); dados de NFS-e (ambiente, RPS, ISS) ficam em `municipaltaxes`, fora do v0.1 |
| B. v1 (offset) como nos irmãos | contrato provado; projeção com campos de NFS-e | nasce em API descontinuada → quebra garantida na v0.2; vê só 357/662 empresas |
| C. v2 só leitura no v0.1; CRUD na v0.2 | só o provado ao vivo | v0.1 não cadastra empresa (o ERP precisaria do painel) |

**Recomendação: A**, com a escrita v2 validada na fase 2a. Para `create`/`delete`, preciso de autorização
para criar e apagar **uma** empresa descartável na conta de teste. Sem isso, fico com C.
**Trade-off:** quem precisar de ambiente/RPS/ISS espera a v0.2 (`municipal_taxes`) ou lê pelo acesso
cru do objeto.

## D4. Versão da consulta de CNPJ

**Evidência (SONDA §9):**
- v1, v2 e v3 respondem.
- `federalTaxNumber` muda de tipo entre elas: v1 devolve string formatada; v2 devolve **inteiro**
  (`191`, perdendo zeros); v3 devolve string de 14 caracteres.
- O header da v2 diz `deprecated 2.0 / supported 3.0`.
- Só a v3 aceita CNPJ alfanumérico: o exemplo da RFB chegou à base.

| Opção | Prós | Contras |
|---|---|---|
| **A. v3 (recomendada)** | pronta para CNPJ alfanumérico (2026); tipo certo; versão suportada | spec v3 não declara host (provado ao vivo no `legalentity`) |
| B. v2, como os 3 irmãos | paridade com os outros SDKs | já marcada como deprecated; inteiro perde zeros; não suporta alfanumérico |

**Recomendação: A.** **Trade-off:** diverge dos irmãos, mas eles devem migrar também.

## D5. O que fazer quando a emissão tem resultado incerto

Contexto: a API ignora `Idempotency-Key`, e um POST de emissão pode devolver 500/504 **com a nota
criada**. O `externalId` é rejeitado com 400 na segunda tentativa.

| Opção | Comportamento | Prós | Contras |
|---|---|---|---|
| **A. Reconciliação explícita (recomendada)** | erro com `outcome_unknown=True` + `external_id`; duplicidade → `DuplicateExternalIdError`; helper `find_by_external_id(..., wait=30)`; receita na doc | o SDK nunca esconde um efeito fiscal; o ERP decide (fila, alerta, retry) | cada integração escreve ~6 linhas de reconciliação |
| B. Reconciliação automática quando há `external_id` | em erro incerto ou duplicidade, o SDK busca pelo `externalId` e devolve a nota existente | "simplesmente funciona" | pode devolver nota emitida com **outro** conteúdo (`externalId` reaproveitado por bug do ERP) sem avisar; esconde o incidente |
| C. A + gerar `externalId` automático (UUID) quando omitido | dedupe sempre disponível | protege quem esquece | grava id que o ERP não conhece (não serve para reconciliar depois do crash); altera dado fiscal enviado |

**Recomendação: A.** Também recomendo que a doc trate `external_id` como obrigatório na prática, sem
exigi-lo na assinatura. **Trade-off:** um pouco mais de código no integrador, nenhuma nota fantasma.

## D6. Tipo dos valores monetários e alíquotas

| Opção | Prós | Contras |
|---|---|---|
| **A. `Decimal` nas propriedades tipadas; `float` no dict cru (recomendada)** | aritmética fiscal exata onde o usuário calcula; `to_dict()`/`json.dumps` continuam funcionando | dois tipos para o mesmo campo (`inv.services_amount` × `inv["servicesAmount"]`) |
| B. `Decimal` em tudo (`json.loads(parse_float=Decimal)`) | um tipo só | `json.dumps(inv.to_dict())` quebra sem encoder custom; atrito com Odoo/ERPNext (usam `float`) |
| C. `float` em tudo | simples; igual aos ERPs | erro de arredondamento em soma de impostos; má prática para SDK fiscal |

**Recomendação: A.** Requisições aceitam `int`, `float` ou `Decimal` (este último serializado sem
perda). **Trade-off:** precisa documentar a dualidade.

## D7. Nomes e agrupamento dos recursos (e onde entra a NFS-e v3)

Proposta:
- `client.service_invoices`, `client.companies`, `client.certificates`, `client.webhooks`.
- `client.lookups.cnpj(...)`, `.cnpj_state_taxes(...)`, `.cpf(...)`, `.cep(...)`.

| Opção | Prós | Contras |
|---|---|---|
| **A. Plano + `lookups` agrupado (recomendada)** | curto; `lookups` deixa explícito "usa a chave de dados"; libera `legal_people`/`natural_people` para os tomadores (CRUD da v1) | nome `lookups` não existe nos irmãos |
| B. Espelhar o Node (`legal_entity_lookup`, `natural_person_lookup`, `addresses`) | paridade de nomes | nomes longos; "addresses" sugere CRUD |
| C. Versionado à la stripe v8 (`client.v1.service_invoices`, `client.v3…`) | acomoda NFS-e v3 sem ambiguidade | verboso; a NFE.io versiona por família, não globalmente; v1/v2/v3 coexistem de forma irregular |

**NFS-e v3** (CNPJ alfanumérico; a v1 devolve 400 para esses CNPJs, VAULT `PHP/review-07-14-2026/11`).
Ela fica fora do v0.1. A recomendação é que, na v0.2, `client.service_invoices` passe a escolher a
versão por empresa ou parâmetro, sem novo atributo, decisão a tomar com a sonda da v3.
**Trade-off:** A pode exigir um parâmetro `api_version` no futuro; C antecipa esse custo agora para
todos.

## D8. Retentar POST que recebe 429?

O PHP retenta, supondo que o rate limiter rejeita **antes** de processar. Isso nunca foi confirmado com
o time da API, e não observamos 429 nem `Retry-After` (SONDA §2).

| Opção | Prós | Contras |
|---|---|---|
| **A. Não retentar POST em 429; erro com `retry_after` (recomendada)** | coerente com a regra 3 (nunca retentar emissão ambígua) enquanto não houver confirmação | rajadas viram erro visível; o integrador re-enfileira |
| B. Retentar como o PHP | absorve picos | se o 429 vier de camada que já processou, duplica nota |
| C. Retentar POST em 429 exceto nas rotas de emissão/cancelamento | absorve picos em webhooks/certificado | regra por rota, mais complexa; ganho pequeno no v0.1 |

**Recomendação: A**, e abrir a pergunta ao time da API. Se confirmarem que o limitador fica antes do
processamento, liberar é uma mudança aditiva. **Trade-off:** menos conveniência agora, zero risco de
duplicidade.

---

## Itens menores (confirmar junto; não mudam a arquitetura)

1. **Esquema de auth no fio:** proponho `Authorization: <chave>` (está na spec e foi provado em todos os
   hosts), em vez do `X-NFE-APIKEY` dos irmãos (funciona, mas não está em spec alguma). As regras do projeto
   cita `X-NFE-APIKEY`; preciso do ok para mudar. (design §3)
2. **Licença:** MIT, como o `client-nodejs` e o plano `ideias-integracoes/06`.
3. **Canal do `SECURITY.md`:** e-mail dedicado ou GitHub Private Vulnerability Reporting.
4. **Certificado da empresa de teste vence em 2026-11-03** (SONDA §5): renovar antes da fase 2a e dos
   testes de emissão.
5. **Achado para o time da API:** a chave de dados recebeu 200 em `GET` de companies v1/v2 e webhooks
   (SONDA §1). Pode ser escopo maior que o pretendido. Vale reportar?
6. **Nome no PyPI:** `nfe-io`, `nfeio` e `nfe_io` estão livres hoje (consulta de leitura em 2026-10-08).
   Reservar o nome cedo exigiria publicar, o que depende do seu ok.

---

## Registro de decisões (André, 2026-10-08)

| Item | Decisão |
|---|---|
| D1 | **D enxuta** — `NfeObject` = Mapping imutável do fio (preserva tudo, acesso `obj["campo"]`) + propriedades tipadas SÓ onde corrigem/tipam: ids, status, datas, dinheiro (`Decimal`), documentos (CNPJ/CPF normalizados como `str`). Demais campos ficam no acesso por chave. Atributos dinâmicos (`__getattr__`) NÃO são usados — evita a colisão `items`/`keys` do `dict`. |
| D2 | A — `TypedDict` camelCase do fio no corpo; argumentos em snake_case |
| D3 | A — companies v2; **autorizado criar e apagar UMA empresa descartável** na conta de teste para validar a escrita |
| D4 | A — CNPJ v3 |
| D5 | A — reconciliação explícita (`outcome_unknown`, `find_by_external_id`); o SDK nunca reenvia sozinho |
| D6 | A — `Decimal` nas propriedades, `float` no dict cru |
| D7 | A — recursos planos (`service_invoices`, `companies`, `certificates`, `webhooks`) + `client.lookups.{cnpj,cpf,cep}`; NFS-e v3 entra na v0.2 como adição em `service_invoices` |
| D8 | A — não retentar POST em 429 |
| Menor 1 | `Authorization: <chave>` (sem prefixo) |
| Menor 2 | MIT |
| Menor 3 | GitHub Private Vulnerability Reporting |
| Menor 4 | ok — certificado de teste será renovado |
| Menor 5 | Escopo da chave de dados (companies e webhooks) é intencional; não reportar |
| Menor 6 | Publicar como `nfe-io` no PyPI assim que estiver funcional (com ok final antes do upload) |
