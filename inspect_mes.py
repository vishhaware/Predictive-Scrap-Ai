import pandas as pd
try:
    df = pd.read_excel("C:/new project/New folder/frontend/Data/MES_Manufacturing_M-231_M-356_M-471_M-607_M-612.xlsx")
    with open("C:/new project/New folder/mes_inspection.txt", "w") as f:
        f.write("Columns: " + str(df.columns.tolist()) + "\n\n")
        f.write(df.head(20).to_string())
except Exception as e:
    with open("C:/new project/New folder/mes_inspection.txt", "w") as f:
        f.write(str(e))
