# Decisões da fase 2 — para o André confirmar

Decisões de API pública (ou de processo) que **não estavam cobertas** pelo registro de
`DECISOES-PENDENTES.md` nem pelo design, ou em que a sonda trouxe fato novo. Em cada uma escolhi a
opção mais conservadora e reversível e segui em frente. Resposta curta aceita: "F1 ok, F4 opção B…".

## Modelos e tipos

**F1. Acesso por chave a valores aninhados.** O registro recomendava que `Mapping` aninhado vire
`NfeObject`. Implementado assim, e decidi também as listas: `obj["lista"]` devolve uma **lista
nova** (mutar não altera o objeto) cujos `Mapping` viram `NfeObject`. Escalares voltam como
vieram. `to_dict()` devolve o fio puro.
- Alternativa: devolver `tuple` (imutável de verdade), mas `obj["filters"] == ["a"]` passaria a
  ser `False`, o que surpreende. Mantive `list`.

**F2. Data sem fuso.** Texto de data/hora sem offset é interpretado como **UTC** nas propriedades
`datetime` (o fio observado sempre traz offset; isto só cobre exceções). Valor inválido → `None`.

**F3. Documento inteiro sem `type`.** Em `Party.federal_tax_number` (tomador/prestador), quando o
fio manda inteiro e não há `type` (`LegalEntity`/`NaturalPerson`), uso a heurística "até 11
dígitos = CPF, acima = CNPJ". Com `type` presente (o normal no fio), não há ambiguidade.
Limitação: CNPJ `00.000.000/0001-91` enviado como `191` sem `type` vira CPF `00000000191`.

**F4. Datas em corpos de requisição.** `date`/`datetime` dentro do corpo são enviados como texto
ISO 8601 (conveniência; antes daria `TypeError`). Reverter é trivial.

**F5. `pickle` de `NfeObject`.** Objetos de resposta podem ser serializados com `pickle` (útil
para cache/filas como Celery). O SDK nunca desserializa `pickle`; `SecretStr` recusa ser
serializado. Alternativa: proibir também em `NfeObject`.

**F6. Retorno de `lookups.cnpj_state_taxes`.** Devolve `LegalEntity` (com `stateTaxes` no acesso
por chave), sem modelo próprio para inscrição estadual.

## Erros, retry e rede

**F7. `outcome_unknown` em POST com 429.** D8 decidiu não retentar POST em 429. Também marquei
esse erro com `outcome_unknown=True` (não sabemos se o limitador fica antes do processamento), o
que leva a receita de reconciliação a buscar por `externalId` antes de reenviar. Alternativa:
`False` (supõe que 429 nunca processa).

**F8. `timeout` numérico.** `timeout=90` significa "esta tentativa pode levar até 90 s":
`read = total = 90`, `connect = min(10, 90)`. Um `Timeout(connect, read, total)` dá controle
fino. Limite conhecido da stdlib: a resolução DNS não respeita o timeout de conexão.

**F9. Busca por `externalId` estrita.** Só `{"serviceInvoices": []}` significa "não existe".
Corpo vazio, forma desconhecida ou redirect levantam `UnexpectedResponseError` — preferi falhar
a deixar uma reconciliação concluir "seguro reemitir" por engano.

**F10. Sem suporte a proxy.** `HTTPS_PROXY`/`HTTP_PROXY` são **ignorados** (`http.client` não os
lê e eu não quis adotar uma convenção implícita). Quem precisa de proxy hoje injeta um
`Transport`. Proposta para a v0.2: parâmetro explícito `proxy=` (com `CONNECT` tunelado).

**F11. Paginação por índice mantém `page_count`.** `auto_paging_iter()` da NFS-e usa o
`page_count` da primeira página (trocar para 50 no meio desloca o `pageIndex` e pula itens); no
cursor, as páginas seguintes usam `limit=50`. Paginação que não avança (mesmo cursor ou mesma
primeira nota) levanta `UnexpectedResponseError` em vez de laço infinito. Spec e design já
ajustados.

## Recursos

**F12. `companies.delete` é soft delete.** A sonda mostrou que `DELETE /v2/companies/{id}`
responde 204 e a empresa continua consultável com `status: Inactive`. Mantive o nome `delete`
(espelha o verbo da API) e documentei. Alternativa: renomear para `deactivate`. A empresa
descartável `ad95…37dd` ficou `Inactive` na conta de teste — vale pedir ao backend a remoção
definitiva, se fizer diferença.

**F13. Webhook de teste fora do `example.com`.** A API chama a URI ao criar o webhook; o
`example.com` responde 405 e a criação falha (400 `40001`). Para validar o CRUD usei
`https://httpbin.org/status/200?nfeio-sdkpy-test=1` (serviço público de teste que responde 200 e
não armazena nada; o ping de verificação só leva os dados do webhook de teste, com segredo
descartável). O webhook ficou ativo ~1 s e foi apagado. **Confirme se essa URL serve para as
próximas execuções** ou indique um endpoint próprio da NFE.io.

**F14. Upload de certificado.** `password` precisa ser texto não vazio e o arquivo ter entre 1 byte
e 1 MiB (validação local). `file` aceita `bytes`, caminho ou arquivo binário aberto.

**F15. Evento de webhook tipado.** `construct_event` devolve `data` como `ServiceInvoice` quando
`X-Hook-Event` começa com `service_invoice` (formato do cabeçalho é **inferência** da
documentação; nenhuma entrega real de nota foi capturada). Nos demais casos, `NfeObject`.

## Processo e infraestrutura

**F16. Opt-in dos testes ao vivo também por opção do pytest.** Além de `NFE_RUN_INTEGRATION=1` e
`NFE_LIVE_WRITE=1`, aceitei `--run-integration` e `--live-write` (o ambiente desta sessão não
permitia prefixar variáveis no comando). O opt-in nunca é lido do `.env`.

**F17. CI sem `setup-python`/`setup-uv`.** Para reduzir actions de terceiros, o `uv` é instalado
com `pipx install uv==0.10.8` e o Python vem do próprio `uv`. Só `checkout`, `upload/download-
artifact`, `codeql-action` e `pypa/gh-action-pypi-publish` são usadas.

**F18. Pins de actions não verificados daqui.** Esta sessão não tinha acesso ao GitHub. O SHA do
`actions/checkout` v4.2.2 foi conferido num repositório local; os de `upload-artifact`,
`download-artifact`, `codeql-action` e `gh-action-pypi-publish` vieram de memória e **precisam
ser conferidos** antes do primeiro push: `GH_TOKEN=… python3 scripts/verify_action_pins.py`
(o job `action-pins` do workflow de segurança faz o mesmo no CI e falha se não baterem).

**F19. Arquivos locais não versionados.** O arquivo de instruções do assistente na raiz e o
diretório oculto de configuração dele ficaram fora dos commits (a regra de commits proíbe essa
menção em arquivos versionados). Decida se entram no `.gitignore`.

**F20. Versão.** `_version.py` já diz `0.1.0`; o CHANGELOG marca a seção como "não publicada".
Alternativa: `0.1.0.dev0` até a publicação.

---

## Registro (André, 2026-10-08)

- **F12:** manter o nome `delete`. A docstring já documenta que a API só desativa (`status == "Inactive"`); o README deve dizer o mesmo.
- **F13:** aprovado `https://httpbin.org/status/200?nfeio-sdkpy-test=1` como URI dos webhooks de teste ao vivo.
