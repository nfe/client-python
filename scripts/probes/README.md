# Sondas ao vivo (somente leitura)

Scripts stdlib que confirmam o contrato da API antes de qualquer decisão do SDK
(regra 1 das regras do projeto). Resumo redigido: `docs/contrato/probe-2026-10-08.md`.

```bash
cd scripts/probes
python3 p01_auth_matrix.py      # chave × host × esquema de auth
python3 p02_companies.py        # companies v1 (offset) e v2 (cursor), limites, paridade
python3 p03_service_invoices.py # NFS-e: lista, retrieve, externalId, downloads (redirect)
python3 p04_certs_webhooks_lookups.py
python3 p05_rechecks.py         # reconfere afirmações antigas do vault
python3 p06_cnpj_v3.py
```

- Credenciais vêm de `../../.env` (`NFE_API_KEY`, `NFE_DATA_API_KEY`, `NFE_COMPANY_ID`).
- `_probe.request()` recusa qualquer método além de GET/HEAD. Sondas de escrita (fase 2a) vão em
  scripts próprios, com trava para operar só na `NFE_COMPANY_ID`.
- Saída crua em `out/` (gitignored): pode conter dado real de terceiros. Credenciais e query de URL
  pré-assinada são removidas antes de gravar; `save()` aborta se uma chave vazar.
- Consultas de CNPJ/CPF/CEP podem ser tarifadas: rode só o necessário.
