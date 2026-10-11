import logging
import time

from thlpro_client.rtd_client import ExcelBridgeRTDClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("teste_rtd")

client = ExcelBridgeRTDClient(logger)
client.connect()

client.subscribe("ABEVA100", ["ULT", "OCP", "OVD"])

print("Aguardando 25 segundos para o RTD popular...")

time.sleep(25)

updates = client.poll_updates(1)

print(f"UPDATES: {len(updates)}")

for update in updates[:10]:
    print(update.rtd_symbol, update.field, update.value)

client.close()