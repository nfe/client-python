# Contribuindo

Obrigado pelo interesse. Este guia cobre o ambiente, as regras do projeto e como testar.

## Ambiente

Use [uv](https://docs.astral.sh/uv/):

```bash
uv sync                      # cria .venv com as dependências de desenvolvimento
uv run pytest                # testes unitários (sem rede)
uv run ruff check .          # lint
uv run ruff format --check . # formatação
uv run mypy --strict src tests
```

Cobertura com os mínimos do CI (núcleo, erros e webhooks >= 90%, total >= 85%):

```bash
uv run coverage run -m pytest
uv run coverage json -o coverage.json
uv run python scripts/check_coverage.py coverage.json
```

Segurança e empacotamento:

```bash
uv run bandit -c pyproject.toml -r src
uv export --format requirements-txt --all-groups --no-emit-project -o requirements-audit.txt
uv run pip-audit --strict --disable-pip -r requirements-audit.txt
uv build && uv run twine check --strict dist/*
```

## Regras do projeto

1. **Zero dependências de runtime.** O pacote usa só a biblioteca padrão. Dependências novas só
   no grupo `dev`.
2. **Contrato vem da OpenAPI e de sonda ao vivo**, nunca de outro SDK. Quando algo não puder ser
   observado, registre como inferência explícita (`docs/contrato/`).
3. **Nunca retentar emissão ambígua.** `POST` não é repetido após possível envio. Não mude a
   tabela de `src/nfeio/_core/retry.py` sem evidência da API.
4. **Segurança:** nada de chave, senha ou documento em log, `repr` ou exceção; TLS sempre
   verificado; todo valor de path passa por `nfeio._core.paths`; nada de `pickle`/`eval`.
5. **Sync e async não divergem.** Comportamento novo é escrito uma vez como operação em
   `resources/` ou `_core/` (gerador de efeitos) e exposto nas duas fachadas com a mesma
   assinatura (o teste de paridade verifica).
6. **Modelos enxutos.** Propriedade tipada só para id, status, data, dinheiro ou documento; o
   resto fica no acesso por chave. Toda propriedade aponta para uma chave da spec (ou para uma
   divergência provada listada em `tests/unit/test_spec_alignment.py`).
7. Código gerado, se um dia existir, fica em `src/nfeio/_generated/` e não é editado à mão.
8. Código, identificadores e docstrings em inglês; documentação e CHANGELOG em pt-BR.

Ao mudar uma spec em `nfeio-docs`, regenere o snapshot usado pelo teste de alinhamento:

```bash
uv run python scripts/spec_keys.py
```

## Testes de integração (opt-in)

Os testes em `tests/live/` falam com a API real e ficam pulados por padrão. Eles leem as chaves
do ambiente ou do arquivo `.env` (fora do git).

```bash
uv run pytest tests/live --run-integration                 # só leitura
uv run pytest tests/live --run-integration --live-write    # também escrita
```

As variáveis `NFE_RUN_INTEGRATION=1` e `NFE_LIVE_WRITE=1` têm o mesmo efeito.

Escrita é restrita: NFS-e só na empresa `NFE_COMPANY_ID` (homologação), sempre com
`externalId` único e cancelamento ao final; uma empresa descartável; webhooks de teste removidos
ao final. Evidências redigidas vão para `tests/live/out/` (fora do git); fixtures versionadas em
`tests/fixtures/live-contracts/` usam valores sintéticos.

## Commits e versões

- [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `docs:`,
  `test:`, `build:`, `ci:`).
- Toda mudança visível ao usuário entra no `CHANGELOG.md` (pt-BR, Keep a Changelog).
- A versão vive só em `src/nfeio/_version.py`. Publicação só pelo workflow de release, por tag,
  com aprovação no environment `pypi`.
