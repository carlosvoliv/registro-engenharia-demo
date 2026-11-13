# Roteiro local do gate

Execute na raiz do repo:

```bash
bash docs/demo-local.sh
```

O script clona **localmente** este repo para uma pasta temporária, configura somente logins fictícios (`eva-demo`) e faz três PRs simulados como commits: S1 tenta `awaiting-approval → planned` sem review e recebe MG-020; S2 pula para `implementing` e recebe MG-010; S3 repete S1 com um review `APPROVED` no SHA exato e passa. Ele não usa rede e apaga a pasta temporária ao terminar.

O arquivo `reviews.json` é uma fixture local. Na publicação, o workflow buscará reviews da API do GitHub; essa integração ainda precisa ser validada no repo remoto.
