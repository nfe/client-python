## Purpose

Define como o SDK é empacotado, verificado e publicado: metadados, tipagem, qualidade mínima, matriz de
Python suportada, testes de integração opcionais e a cadeia de publicação protegida contra ataques de
supply chain.

## ADDED Requirements

### Requirement: Pacote nfe-io importável como nfeio
O SDK SHALL ser distribuído no PyPI como `nfe-io`, importado como `nfeio`, com `requires-python >= 3.10`,
licença MIT declarada, `py.typed` incluído e `nfeio.__version__` igual à versão publicada.

#### Scenario: Instalação limpa
- **WHEN** o usuário roda `pip install nfe-io` num ambiente vazio com Python 3.10
- **THEN** `import nfeio` funciona e nenhum outro pacote é instalado

### Requirement: Qualidade verificada no CI
Cada pull request SHALL passar `ruff check`, `ruff format --check`, `mypy --strict` sobre `src` e `tests`,
e a suíte de testes em Python 3.10, 3.11, 3.12, 3.13 e 3.14 no Linux e em 3.12 no macOS e no Windows,
com cobertura mínima de 90% nos módulos de núcleo, erros e webhooks e de 85% no total.

#### Scenario: Cobertura abaixo do mínimo
- **WHEN** uma mudança reduz a cobertura do núcleo para 89%
- **THEN** o CI falha

### Requirement: Testes de integração opcionais e seguros
Os testes contra a API real SHALL ser marcados e pulados quando não houver credenciais; testes de escrita
SHALL exigir opt-in explícito (`NFE_LIVE_WRITE=1`) e MUST operar apenas na empresa `NFE_COMPANY_ID`.

#### Scenario: Sem credenciais
- **WHEN** a suíte roda sem `NFE_API_KEY`
- **THEN** os testes de integração aparecem como pulados e a suíte passa

### Requirement: Publicação com Trusted Publishing e attestations
A publicação no PyPI SHALL ocorrer apenas por workflow do GitHub Actions disparado por tag, usando
Trusted Publishing (OIDC) sem token armazenado, com attestations de proveniência, a partir de artefatos
construídos uma única vez num job separado, em environment protegido com aprovação manual. As actions
MUST ser fixadas por SHA de commit e os jobs MUST declarar permissões mínimas.

#### Scenario: Release
- **WHEN** a tag `v0.1.0` é aprovada no environment de publicação
- **THEN** wheel e sdist publicados no PyPI têm attestations verificáveis vinculadas ao workflow do repositório

### Requirement: Auditoria de segurança contínua
O CI SHALL executar `bandit` sobre o código do pacote, `pip-audit` sobre as dependências de
desenvolvimento travadas e análise CodeQL (pelo default setup do repositório), e SHALL manter
Dependabot apenas para GitHub Actions e dependências de desenvolvimento.

#### Scenario: Vulnerabilidade em dependência de dev
- **WHEN** `pip-audit` encontra vulnerabilidade conhecida no lock
- **THEN** o job de auditoria falha

### Requirement: Política de segurança e changelog
O repositório SHALL conter `SECURITY.md` com versões suportadas, canal privado de reporte (GitHub Private
Vulnerability Reporting) e prazos, e
`CHANGELOG.md` em pt-BR no formato Keep a Changelog, atualizado a cada versão.

#### Scenario: Reporte de vulnerabilidade
- **WHEN** um pesquisador abre o repositório procurando como reportar falha
- **THEN** `SECURITY.md` indica o canal privado e o prazo de primeira resposta
