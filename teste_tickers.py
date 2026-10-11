import time

import win32com.client

TICKERS = [
    "ABEVA100",
    "ABEVA100_B_0",
    "ABEVB267_B_0",
    "BOVAJ200",
    "BOVAJ200_B_0",
]

excel = win32com.client.DispatchEx("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False

workbook = excel.Workbooks.Add()
worksheet = workbook.Worksheets(1)

for index, ticker in enumerate(TICKERS, start=1):
    cell = f"A{index}"
    formula = f'=RTD("rtdtrading.rtdserver";;"{ticker}";"ULT")'
    worksheet.Range(cell).FormulaLocal = formula

print("Aguardando 25 segundos para o RTD popular...")

time.sleep(25)

for index, ticker in enumerate(TICKERS, start=1):
    cell = f"A{index}"
    value = worksheet.Range(cell).Value
    print(f"{ticker:20} -> {value!r}")

workbook.Close(SaveChanges=False)
excel.Quit()