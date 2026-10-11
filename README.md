# THLPro Client (Fase 4)

Cliente local Windows em Python para capturar cotações RTD do Profit e enviar ao backend THLPro.

## Recursos implementados

- App local com base para execução em bandeja + janela de configuração (`tkinter` + `pystray`).
- Abstração de RTD em `thlpro_client/rtd_client.py`:
  - `ComRTDClient`: integração `rtdtrading.rtdserver` (COM), com fallback de polling curto.
  - `ProfitApiRtdClient`: stub documentado para integração via API/plugin oficial da Nelogica (pendente validação real).
  - `SimulatedRTDClient`: modo simulação explícito para desenvolvimento (`SIMULATE=1` ou `--simulate`).
- Login via `/auth/login`, registro via `/clients/register`, uso de API key nos endpoints `/clients/*`.
- Armazenamento de API key com DPAPI no Windows (`win32crypt.CryptProtectData`) e fallback local para testes Linux.
- Fila offline SQLite (`queue.db`) com deduplicação por `(option_symbol, quote_timestamp)`.
- Deduplicação de envio: só envia quando houver mudança real em `last_price/bid/ask/timestamp` e respeita intervalo mínimo.
- Heartbeat periódico em `/clients/heartbeat` com reconexão/backoff exponencial no envio.
- Watchdog de threads (`capture_worker`, `sender_worker`) com reinício automático.
- Logs rotativos em `%APPDATA%/THLPro/logs/thlpro_client.log`.

## Estrutura

- `thlpro_client/main.py`: entrypoint principal.
- `thlpro_client/config.py`: persistência de configuração (`%APPDATA%/THLPro/config.json`).
- `thlpro_client/api_client.py`: integração REST.
- `thlpro_client/queue_store.py`: fila local SQLite.
- `thlpro_client/dedup_cache.py`: filtro de duplicidade.
- `thlpro_client/capture_service.py`: captura RTD/simulada e montagem de payload.
- `thlpro_client/sender_service.py`: envio em lote + heartbeat.
- `thlpro_client/supervisor.py`: watchdog/restart de workers.

## Payload enviado para `/clients/quotes`

Campos principais:

- `asset`
- `option_symbol`
- `last_price` (ULT)
- `bid` (OCP)
- `ask` (OVD)
- `premium` (= `last_price`)
- `quote_timestamp` (ISO com offset America/Sao_Paulo)
- `source` (`Profit RTD` ou `SIMULATED`)
- `data_status`

## Execução local para testes

```bash
cd /home/ubuntu/thlpro/client
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m thlpro_client --simulate --no-gui
```

> `localhost` acima refere-se à VM do agente Abacus, não ao seu computador local.

## Build Windows (.exe)

No Windows (Python 3.12 x64):

```bat
build_win.bat
```

ou:

```bat
python build_client.py
```

Saída esperada: `dist\THLProClient.exe`.

## Instalador Inno Setup

1. Gerar `dist\THLProClient.exe`.
2. Abrir `Instalador THLPro.iss` no Inno Setup 6.
3. Compilar para gerar `Instalador-THLPro-Client.exe`.

## Testes

```bash
cd /home/ubuntu/thlpro/client
source .venv/bin/activate
pytest -q
```

## Limitações conhecidas

- Integração COM real com Profit **não pode ser validada neste ambiente Linux**.
- `ProfitApiRtdClient` está documentado como pendente de implementação runtime com documentação oficial e ambiente Windows/Profit.
