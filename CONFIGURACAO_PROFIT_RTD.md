# Configuração Profit RTD (PT-BR)

## Contexto

A planilha original THLPro usa `RTD("rtdtrading.rtdserver", ..., "rtd:<SIMBOLO>", <CAMPO>)` para ler cotações no Excel.

Este cliente replica a mesma lógica de identificação:

- Símbolo RTD base: `BOVA<codigo>_B_0` (exemplo: `BOVAJ40_B_0`)
- Campos:
  - `ULT` = último preço (prêmio)
  - `OCP` = BID
  - `OVD` = ASK
  - `VEN` = vencimento
  - `PEX` = strike

## Pré-requisitos

1. Windows 10/11 64-bit.
2. Profit Pro/Nelogica instalado e autenticado.
3. Python 3.12 x64 (para build/depuração).
4. `pywin32` instalado.

## Habilitação sugerida no Profit

Como a documentação pública detalhada de automação COM do RTD pode variar por versão/licença:

1. Validar no Excel se `=RTD("rtdtrading.rtdserver",,"rtd:BOVAJ40_B_0","ULT")` retorna valor.
2. Garantir que o Profit esteja aberto na mesma máquina do cliente.
3. Executar o cliente THLPro com permissões normais (sem elevação desnecessária).

## Sobre a integração programática

- Implementada camada `ComRTDClient` para usar ProgID `rtdtrading.rtdserver`.
- Caso APIs/eventos COM específicos não estejam disponíveis na sua versão, o cliente usa polling curto por tópico como fallback.
- `ProfitApiRtdClient` foi deixado como stub explícito para evolução com documentação oficial da Nelogica (pendente validação em ambiente real).

## Validação recomendada em Windows

1. Iniciar backend THLPro.
2. Rodar cliente com modo COM (`RTD_MODE=com`).
3. Verificar no log em `%APPDATA%\THLPro\logs\thlpro_client.log`:
   - "Conectado ao servidor COM rtdtrading.rtdserver"
   - recebimento de atualizações
   - envios aceitos em `/clients/quotes`
4. Confirmar dados na API `/quotes/latest`.
