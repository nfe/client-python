# Revisão de segurança — SDK Python v0.1 (2026-10-08)

Revisão do código final de `src/nfeio/` contra o design §11 e as regras do projeto, feita depois
da implementação e antes de encerrar a fase 2. Cada item diz **onde** está o controle, **como** foi
verificado e o que foi **corrigido** durante a revisão.

Ferramentas: `bandit -r src` (0 achados), `ruff` com regras `S` (0), `pip-audit` no lock de dev
(0 vulnerabilidades conhecidas), `mypy --strict`, revisão manual e um revisor automático de
segurança que apontou dois itens (ambos corrigidos, abaixo).

## 1. Segredos em log, `repr` e exceções

| Superfície | Controle | Verificação |
|---|---|---|
| Chaves no cliente/config | `SecretStr` (`_config.py`): `repr`/`str` mostram `****` + 4 últimos; `pickle` recusado | `test_secret_masking` |
| `RequestOptions(api_key=…)` | `__repr__` próprio mascarado | idem |
| Requisição | `HttpRequest.__repr__` redige `Authorization`/cookies, omite query e corpo, mascara o path | `test_repr_hides_authorization` |
| Cabeçalhos de resposta | `Headers.__repr__` redige `authorization`, `cookie`, `set-cookie`, `x-nfe-apikey` | `test_headers.py` |
| Erros da API | mensagem e `body` passam por `_scrub`: a chave usada (e senha de certificado/segredo de webhook, quando houver) vira `<redacted>` mesmo se a API ecoar | `test_echoed_key_is_scrubbed`, `test_certificate_upload_500_not_retried_and_password_hidden` |
| Erros de rede | só host e classe da exceção do socket | leitura de `transport.py` |
| Objetos de resposta | `NfeObject.__repr__` mascara chaves `secret`, `password`, `apikey`, `token` (o ping de webhook traz `Secret`; a v1 de empresas traz `loginPassword`) | `test_repr_masks_secrets` |
| Evento de webhook | `WebhookEvent.__repr__` não mostra o corpo | `test_construct_event_ping_and_repr_hides_secret` |
| Logs | logger `nfeio`, só `DEBUG`, `NullHandler` por padrão; registra método, host, path mascarado, status, tentativa, espera e `x-request-id` | `test_retry_log_has_no_secrets`, `test_secret_leak_scan` |

**Corrigido na revisão:** os logs e o `repr` da requisição gravavam o **path concreto**, que contém
CPF, data de nascimento, CNPJ e `externalId` (dados pessoais e de venda). Agora
`_core/redact.log_path` mantém só segmentos estáticos conhecidos e troca o resto por `*`
(`/v1/naturalperson/status/*/*`). Teste: `test_logs_and_reprs_have_no_personal_data`.

Varredura completa (`test_secret_leak_scan`): sequência com sucesso, 401, 500, falha de rede e
upload de certificado, com log em `DEBUG`; nenhuma chave, senha ou segredo aparece em logs,
`repr`, `str` ou atributos das exceções.

## 2. Redirect com credencial

- Transportes **nunca** seguem redirect (`http.client` não segue; o protocolo exige).
- Só downloads seguem (`requestor.follow_download`): até 3 saltos, **só https**, requisição nova
  **sem `Authorization`** nem outro cabeçalho de credencial. Provado ao vivo: o salto para
  `api.nfse.io/v1/blob/download` saiu sem `Authorization` (`authorizationSent: false` na fixture).
- `Location` de 202 nunca é seguido como URL: só o path é lido, validado por `fullmatch` e a
  empresa precisa coincidir.
- **Corrigido na revisão:** um 3xx fora de download chegava ao parser e, na busca por
  `externalId`, podia virar "não existe". Agora `request()` levanta `UnexpectedResponseError` para
  3xx sem `allow_redirect`. Teste: `test_redirect_outside_downloads_is_an_error`.

## 3. Injeção em path (ids)

- Todo valor interpolado em path passa por `_core/paths.py`: ids opacos `[A-Za-z0-9_-]{1,64}`;
  `externalId` com `quote(safe="")` (um segmento só), rejeitando vazio, `.`/`..`, controle e
  > 255; CNPJ (numérico e alfanumérico, DV da RFB), CPF (DV), CEP, UF e data validados.
- Cursores (`starting_after`/`ending_before`) passam pela mesma validação; query via `urlencode`.
- **Corrigido na revisão (revisor automático):** os validadores usavam `^…$` com `re.match`, e em
  Python `$` aceita `\n` final (`"abc\n"` passaria). Todos passaram a `fullmatch` (ids, CNPJ, data,
  nomes de cabeçalho, `app_info`, campos multipart, `Location`). Teste:
  `test_validators_reject_trailing_newline`.
- Cabeçalhos: chave, `Idempotency-Key` e `extra_headers` rejeitam CR/LF/NUL; `extra_headers` não
  sobrescreve `Authorization`, `User-Agent` nem `Content-Type`.

## 4. Tamanho de resposta e desserialização

- Corpo lido em blocos de 64 KiB até `max_response_bytes` (10 MiB); `Content-Length` maior é
  recusado antes de ler; estouro descarta a conexão (`ResponseTooLargeError`). Teste com servidor
  local (`test_response_size_limit`).
- `Accept-Encoding: identity` e nenhuma descompressão no SDK (sem bomba de compressão).
- Webhooks: limite de 5 MiB **antes** de verificar; JSON só depois da assinatura.
- Só `json.loads`; nada de `pickle`, `eval`, `yaml.load`, parser de XML (`test_no_dangerous_calls_in_package`).
  XML e PDF voltam como `bytes`; a doc recomenda `defusedxml`.
- **Corrigido na revisão:** JSON muito aninhado gerava `RecursionError` fora da hierarquia
  `NfeError`; agora é `UnexpectedResponseError` (ou `json_body = None` em erros). Teste:
  `test_deeply_nested_json_stays_inside_the_hierarchy`.
- Limite explícito de aninhamento: todo JSON não confiável (respostas, corpos de erro, webhooks)
  passa por `_core/jsonutil.loads`, que recusa mais de `MAX_JSON_DEPTH = 128` níveis com
  `ValueError` **antes** do `json.loads`, em custo linear (remove as strings e varre só
  `[ ] { }`). Antes a proteção dependia do limite de recursão do interpretador, e o Python 3.14
  decodifica 100 mil níveis sem `RecursionError`. Testes: `test_json_depth_limit_is_explicit`,
  `test_json_depth_ignores_brackets_inside_strings`, `test_deeply_nested_error_body_and_webhook`.
- Mensagens de erro saneadas (sem caracteres de controle) e truncadas em 1.000 caracteres.

## 5. TLS

- `ssl.create_default_context()` + `minimum_version = TLSv1_2`; verificação de cadeia e de nome
  sempre ligadas.
- `ssl_context` do usuário é aceito só se `CERT_REQUIRED` e `check_hostname=True`; `ca_bundle`
  só acrescenta confiança. Não existe `verify=False`.
- Testes com servidor local autoassinado: falha na fase "não estabelecida" sem a CA e sucesso com
  `ca_bundle` (`test_self_signed_rejected_then_trusted_via_ca_bundle`).
- Base URLs só `https`, sem credenciais na URL, sem query/fragmento.

## 6. Retry e efeitos fiscais

- `POST` nunca é repetido após possível envio (timeout de leitura, conexão interrompida, 408, 429,
  5xx); só antes de conectar. Pool: `POST` sempre em conexão nova. `Idempotency-Key` não muda isso.
- Erros incertos carregam `outcome_unknown=True` e `external_id`; `DuplicateExternalIdError` é
  reconhecido pelo texto.
- **Corrigido na revisão:** `find_by_external_id` tratava corpo vazio/forma desconhecida como "não
  existe", o que faria a receita de reconciliação reemitir. Agora só a lista vazia explícita
  significa "não existe" (`test_external_lookup_never_reads_garbage_as_not_found`).
- `Retry-After` limitado a 60 s; acima disso, erro com `retry_after` e sem espera.

## 7. Disponibilidade

- Timeouts finitos obrigatórios (conexão 10 s, leitura 60 s, total 120 s por tentativa).
  Limitação da stdlib: a resolução DNS não respeita o timeout (documentado em `DECISOES-FASE2` F8).
- Polling e busca por `externalId` limitados por prazo; backoff com teto.
- **Corrigido na revisão:** paginação que não avança (mesmo cursor ou mesma página) gerava laço
  infinito em `auto_paging_iter`; agora levanta `UnexpectedResponseError`.
- Cliente async: cancelar a task não interrompe a requisição em voo (thread). Cancelar um `create`
  em andamento deve ser tratado como resultado incerto: reconcilie por `externalId` (README).

## 8. Supply chain

- Zero dependências de runtime (teste de metadados + wheel sem `Requires-Dist` + smoke em venv
  limpo com só `nfe-io` instalado).
- `uv.lock` para dev; `pip-audit` no CI; Dependabot só para actions e dev.
- Workflows com `permissions: {}` e permissões mínimas por job; `persist-credentials: false`;
  nenhuma interpolação de entrada não confiável em `run:`.
- Release: build único, environment `pypi` com aprovação, Trusted Publishing (OIDC) e attestations
  PEP 740.
- **Pendente:** conferir os SHAs das actions (`scripts/verify_action_pins.py`; ver
  `DECISOES-FASE2` F18).

## 9. Webhooks

- `verify_signature`: exige `sha1=` + 40 hex, HMAC-SHA1 sobre o corpo bruto, `hmac.compare_digest`,
  nunca levanta exceção (entradas malformadas, segredo vazio, tipos inesperados → `False`).
  Vetores reais (3 pings de 2026-06-11) e negativos da spec do Node.
- Sem proteção anti-replay no protocolo (não há timestamp assinado): a doc manda deduplicar por
  `X-Hook-Id`.

## Riscos aceitos / fora do escopo

- Sem suporte a proxy na v0.1 (F10).
- `NfeObject` pode ser serializado com `pickle` pelo usuário (F5); o SDK nunca desserializa.
- `check_ssl_context` eleva `minimum_version` do contexto do usuário para TLS 1.2 (efeito colateral
  no objeto recebido; documentado aqui).
