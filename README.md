# NFE.io SDK para Python

SDK oficial da [NFE.io](https://nfe.io) para Python. Emite e gerencia **NFS-e**, cadastra
**empresas** e **certificados digitais**, administra **webhooks** e consulta **CNPJ, CPF e CEP**.

- Python 3.10 a 3.14, cliente síncrono e assíncrono.
- **Zero dependências de runtime**: só a biblioteca padrão.
- Retry seguro: uma emissão nunca é reenviada depois que pode ter chegado à API.
- Tipado (`py.typed`, mypy `--strict`), sem estado global, TLS sempre verificado.

> Versão 0.1 (alfa). NF-e, NFC-e, CT-e, distribuição DF-e e cálculo de impostos chegam nas
> próximas versões.

## Instalação

```bash
pip install nfe-io
# ou
uv add nfe-io
```

O pacote se chama `nfe-io` no PyPI e é importado como `nfeio`.

## Chaves de API

A NFE.io usa duas chaves, cada uma para um grupo de APIs:

| Parâmetro | Variável de ambiente | Usada em |
|---|---|---|
| `api_key` | `NFE_API_KEY` | NFS-e, empresas, certificados, webhooks |
| `data_api_key` | `NFE_DATA_API_KEY` | consultas de CNPJ, CPF e CEP |

O SDK nunca usa uma chave no lugar da outra: os hosts de consulta recusam a chave principal com
403. Se você tem uma chave só, passe o mesmo valor nos dois parâmetros.

```python
from nfeio import NfeClient

client = NfeClient(api_key="SUA_CHAVE", data_api_key="SUA_CHAVE_DE_DADOS")
# ou, lendo NFE_API_KEY e NFE_DATA_API_KEY do ambiente:
client = NfeClient()
```

Não existe host de homologação: o ambiente (produção ou teste) é configurado na empresa.

## Início rápido

```python
from nfeio import NfeClient

client = NfeClient()
company_id = "ID_DA_EMPRESA"

invoice = client.service_invoices.create_and_wait(
    company_id,
    {
        "cityServiceCode": "10677",
        "description": "Consultoria em tecnologia",
        "servicesAmount": 150.00,
        "borrower": {
            "type": "NaturalPerson",
            "name": "Maria Silva",
            "federalTaxNumber": "52998224725",
            "email": "maria@example.com",
        },
    },
    external_id="pedido-1001",  # sua chave de deduplicação (recomendado sempre)
)

print(invoice.flow_status)         # "Issued"
print(invoice["number"])           # qualquer campo do JSON, pelo nome original
pdf = client.service_invoices.download_pdf(company_id, invoice.id)
```

O corpo da requisição usa **as mesmas chaves (camelCase) da documentação da API**: copie um
exemplo da doc e ele funciona. Os argumentos dos métodos seguem o padrão Python (snake_case).

### Objetos de resposta

Toda resposta é um `NfeObject`: um `Mapping` imutável sobre o JSON recebido.

- `obj["campo"]` dá acesso a **qualquer** campo, inclusive os que o SDK ainda não conhece.
  Objetos aninhados também são `NfeObject` (`invoice["borrower"]["address"]["city"]["code"]`).
- Algumas **propriedades tipadas** corrigem ou tipam o que vem no fio: ids, status, datas
  (`datetime` com fuso), valores (`Decimal`) e documentos (CNPJ/CPF como `str` com zeros à
  esquerda). Exemplos: `invoice.flow_status`, `invoice.services_amount`, `invoice.issued_on`,
  `invoice.borrower.federal_tax_number`.
- `obj.to_dict()` devolve uma cópia em dicionários comuns (serializável com `json.dumps`).
- `obj.last_response.request_id` traz o `x-request-id`. Informe esse valor ao suporte.

Valores monetários aparecem como `float` no acesso por chave (como no JSON) e como `Decimal` nas
propriedades. Nas requisições, `int`, `float` e `Decimal` são aceitos; `Decimal` é enviado sem
perda (`Decimal("100.10")` vira `100.10`).

## Emissão segura e reconciliação

A emissão de NFS-e é assíncrona: a API responde `202` e a nota passa por estados
(`WaitingCalculateTaxes`, `WaitingSend`, …) até `Issued`. `create_and_wait` e `wait` consultam a
nota com backoff até um estado final.

**O SDK nunca reenvia uma emissão sozinho.** A API pode criar a nota e mesmo assim responder
500 ou 504. Por isso:

- `POST` não é repetido após timeout de leitura, conexão interrompida, 408, 429 ou 5xx;
- esses erros chegam com `outcome_unknown=True` e o `external_id` usado;
- reenviar o mesmo `externalId` é rejeitado pela API (`DuplicateExternalIdError`).

Receita recomendada: sempre envie `external_id` e, diante de resultado incerto, procure a nota
antes de tentar de novo.

```python
from nfeio import APIConnectionError, APIError, DuplicateExternalIdError


def emitir(client, company_id, pedido):
    external_id = f"pedido-{pedido['id']}"
    try:
        return client.service_invoices.create(company_id, pedido["nfse"], external_id=external_id)
    except DuplicateExternalIdError:
        pass  # a primeira tentativa foi registrada: busque a nota
    except (APIError, APIConnectionError) as erro:
        if not erro.outcome_unknown:
            raise  # erro de validação, chave inválida etc.: corrija e tente de novo
    nota = client.service_invoices.find_by_external_id(company_id, external_id, wait=30)
    if nota is None:
        raise RuntimeError("emissão não registrada: é seguro tentar de novo mais tarde")
    return nota
```

`find_by_external_id(..., wait=30)` repete a busca com backoff por até 30 segundos, cobrindo o
atraso de indexação logo após o `202`.

### Cancelamento

```python
nota = client.service_invoices.cancel_and_wait(company_id, invoice_id)
assert nota.flow_status == "Cancelled"
```

### Falhas de processamento e prazo

`wait`, `create_and_wait` e `cancel_and_wait` levantam `InvoiceProcessingError` quando a nota
termina em `IssueFailed`, `CancelFailed` ou `Error` (com `flow_message`, a explicação da
prefeitura) e `PollingTimeoutError` quando o prazo (`timeout=120` s por padrão) acaba.

## Listagens e paginação

```python
# NFS-e: paginação por índice, começando em 1 (page_count de 1 a 50)
page = client.service_invoices.list(company_id, page_count=50, issued_begin="2026-01-01")
for nota in page.auto_paging_iter():  # busca as próximas páginas sob demanda
    print(nota.id, nota.flow_status)

# Empresas (API v2): paginação por cursor
for empresa in client.companies.list(limit=50).auto_paging_iter():
    print(empresa.id, empresa["name"])
```

`page.data`, `page.has_more` e `page.next_page()` também estão disponíveis. Não existe método que
carregue todas as páginas na memória de uma vez.

## Empresas e certificados

```python
empresa = client.companies.create({
    "name": "Minha Empresa LTDA",
    "federalTaxNumber": 11222333000181,
    "taxRegime": "SimplesNacional",
    "address": {
        "country": "BRA", "postalCode": "80010000", "street": "Rua Exemplo", "number": "1",
        "district": "Centro", "state": "PR", "city": {"code": "4106902", "name": "Curitiba"},
    },
})

with open("certificado.pfx", "rb") as arquivo:
    client.certificates.upload(empresa.id, arquivo, "senha-do-certificado")

for cert in client.certificates.list(empresa.id):
    print(cert.thumbprint, cert.expires_on, cert.is_expired())
```

`companies.update` substitui a empresa inteira (envie todos os campos). `companies.delete` é uma
desativação na API: a empresa continua consultável com `status == "Inactive"`.

## Consultas de CNPJ, CPF e CEP

```python
empresa = client.lookups.cnpj("00.000.000/0001-91")   # numérico ou alfanumérico
print(empresa["name"], empresa.status, empresa.share_capital)

inscricoes = client.lookups.cnpj_state_taxes("00000000000191", "SP")
pessoa = client.lookups.cpf("529.982.247-25", "1990-01-31")  # data divergente -> NotFoundError
endereco = client.lookups.cep("01310-100")
print(endereco["city"]["code"], endereco["street"])
```

CNPJ, CPF e CEP são validados localmente (inclusive dígitos verificadores) antes da requisição.

## Webhooks

### Gerenciar

```python
hook = client.webhooks.create({
    "uri": "https://erp.exemplo.com.br/nfeio/webhook",
    "secret": "um-segredo-longo-e-aleatorio",
    "contentType": "json",
    "filters": ["service_invoice.issued_successfully", "service_invoice.cancelled_successfully"],
})
```

A API chama a URI na criação para verificá-la: o endpoint precisa estar no ar e responder 2xx.

`update` **substitui o webhook inteiro**; omitir `status` desativa o webhook. Busque, altere e
envie o objeto completo:

```python
atual = client.webhooks.retrieve(hook.id).to_dict()
atual["filters"].append("service_invoice.issued_failed")
client.webhooks.update(hook.id, atual)
```

### Receber

Verifique a assinatura `X-Hub-Signature` sobre o **corpo bruto** da requisição (nunca sobre um
`json.dumps` do corpo já interpretado). `verify_signature` nunca levanta exceção e compara em
tempo constante; `construct_event` verifica e só então interpreta o JSON.

As entregas podem chegar mais de uma vez: use `event.hook_id` (`X-Hook-Id`) para deduplicar.

**Flask**

```python
from flask import Flask, request
from nfeio.errors import SignatureVerificationError
from nfeio.webhooks import construct_event

app = Flask(__name__)
SEGREDO = "um-segredo-longo-e-aleatorio"


@app.post("/nfeio/webhook")
def nfeio_webhook():
    try:
        event = construct_event(request.get_data(), request.headers, SEGREDO)
    except SignatureVerificationError:
        return "", 400
    if event.action == "issued_successfully":
        registrar_nota(event.hook_id, event.data.id, event.data.flow_status)
    return "", 204
```

**Django**

```python
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from nfeio.errors import SignatureVerificationError
from nfeio.webhooks import construct_event


@csrf_exempt
@require_POST
def nfeio_webhook(request):
    try:
        event = construct_event(request.body, request.headers, SEGREDO)
    except SignatureVerificationError:
        return HttpResponse(status=400)
    processar(event)
    return HttpResponse(status=204)
```

**FastAPI**

```python
from fastapi import FastAPI, HTTPException, Request, Response
from nfeio.errors import SignatureVerificationError
from nfeio.webhooks import construct_event

app = FastAPI()


@app.post("/nfeio/webhook", status_code=204)
async def nfeio_webhook(request: Request) -> Response:
    try:
        event = construct_event(await request.body(), request.headers, SEGREDO)
    except SignatureVerificationError:
        raise HTTPException(status_code=400) from None
    await processar(event)
    return Response(status_code=204)
```

## Cliente assíncrono

`AsyncNfeClient` tem os mesmos recursos, métodos e comportamento do `NfeClient`; cada método é
uma corrotina. A E/S roda em threads (`asyncio.to_thread`) e as esperas usam `asyncio.sleep`,
então o event loop não é bloqueado.

```python
import asyncio
from nfeio import AsyncNfeClient


async def main():
    async with AsyncNfeClient() as client:
        nota = await client.service_invoices.create_and_wait(
            "ID_DA_EMPRESA", {"cityServiceCode": "10677", "description": "x", "servicesAmount": 10},
            external_id="pedido-1002",
        )
        async for item in (await client.companies.list()).auto_paging_iter():
            print(item.id)


asyncio.run(main())
```

## Erros

Todas as exceções derivam de `nfeio.NfeError`.

| Exceção | Quando |
|---|---|
| `ConfigurationError` | chave ausente, opção inválida, TLS inseguro |
| `InvalidParameterError` | parâmetro recusado localmente (id, CNPJ, CPF, CEP, data) |
| `InvalidRequestError` | 400, 405, 415, 422 … (`DuplicateExternalIdError` para `externalId` repetido) |
| `AuthenticationError` | 401 |
| `PermissionDeniedError` | 403 (a mensagem diz qual chave a família usa) |
| `NotFoundError` | 404 |
| `ConflictError` | 409 |
| `RateLimitError` | 429 (`retry_after`) |
| `ServerError` | 408 e 5xx |
| `APIConnectionError` / `APITimeoutError` | falha de rede (`phase` diz se a requisição pode ter saído) |
| `InvoiceProcessingError` / `PollingTimeoutError` | espera por estado final |
| `SignatureVerificationError` | assinatura de webhook inválida |

Erros da API trazem `status_code`, `message`, `error_code`, `request_id`, `trace_id`, `body` e
`outcome_unknown`. Nenhuma exceção, `repr` ou log contém a chave de API.

## Configuração

```python
from nfeio import NfeClient, RequestOptions, Timeout

client = NfeClient(
    timeout=Timeout(connect=10, read=60, total=120),  # padrões; precisam ser finitos
    max_retries=3,                                    # só GET/PUT/DELETE, ou falha antes de conectar
    app_info=("meu-modulo-erp", "1.2.0"),             # vai no User-Agent
    ca_bundle="/etc/ssl/certs/ca-proxy.pem",          # CA extra (proxy corporativo)
)

# Por chamada:
client.service_invoices.list(company_id, options=RequestOptions(timeout=90, max_retries=0))
```

- TLS é sempre verificado (mínimo TLS 1.2). Não existe opção para desligar a verificação.
- Respostas acima de 10 MiB são recusadas (`max_response_bytes`).
- O logger `nfeio` registra requisições e novas tentativas em nível `DEBUG`, sem cabeçalhos,
  corpo, query ou documentos (ids e documentos do path aparecem como `*`).
- O transporte padrão usa só a biblioteca padrão. Para usar outro cliente HTTP, implemente
  `nfeio.transport.Transport` ou `AsyncTransport`.

## Desenvolvimento

Veja [CONTRIBUTING.md](CONTRIBUTING.md). Vulnerabilidades: [SECURITY.md](SECURITY.md).
Histórico de versões: [CHANGELOG.md](CHANGELOG.md).

## Licença

[MIT](LICENSE).
