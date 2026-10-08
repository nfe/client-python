# Política de segurança

## Versões suportadas

| Versão | Suporte a correções de segurança |
|---|---|
| 0.1.x | sim |
| < 0.1 | não (não publicadas) |

Enquanto o SDK estiver em 0.x, só a minor mais recente recebe correções.

## Como reportar uma vulnerabilidade

**Não abra issue pública.** Use o canal privado do GitHub:

1. Acesse a aba **Security** do repositório `nfe/client-python`.
2. Clique em **Report a vulnerability** (GitHub Private Vulnerability Reporting).
3. Descreva o problema, a versão afetada e, se possível, um passo a passo para reproduzir.

Não inclua chaves de API, certificados ou dados fiscais reais no relato. Se precisar mostrar uma
requisição, troque os valores por marcadores (`<API_KEY>`, `<CNPJ>`).

## Prazos

- **Primeira resposta:** até 3 dias úteis.
- **Avaliação inicial (confirmação e severidade):** até 10 dias úteis.
- **Correção:** depende da severidade; falhas críticas têm prioridade sobre qualquer outra entrega.

## Escopo

Este canal cobre o **código do SDK Python** (`nfe-io` no PyPI, import `nfeio`): por exemplo,
vazamento de chave em log, envio de credencial em redirect, falha na verificação de assinatura de
webhook, validação de parâmetros que permita path traversal, desserialização insegura.

Problemas na **API da NFE.io** em si (servidores, painel, emissão) devem ir para o suporte da
NFE.io, não para este repositório.

## Divulgação coordenada

Pedimos que a vulnerabilidade não seja divulgada antes da publicação da correção. Combinamos a data
de divulgação com quem reportou e damos crédito no aviso de segurança (GitHub Security Advisory),
se a pessoa quiser.
