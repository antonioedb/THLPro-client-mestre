import time

import win32com.client

excel = win32com.client.DispatchEx("Excel.Application")
excel.Visible = True

workbook = excel.Workbooks.Add()
worksheet = workbook.Worksheets(1)

formula = '=RTD("rtdtrading.rtdserver";;"ABEVA100";"ULT")'

worksheet.Range("A1").FormulaLocal = formula

print("Aguardando 25 segundos para o RTD popular...")

time.sleep(25)

value = worksheet.Range("A1").Value

print("VALOR:", repr(value))

workbook.Close(SaveChanges=False)
excel.Quit()