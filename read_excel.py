import pandas as pd
import json

def read_excel_to_text():
    file_path = 'frontend/Data/AI_cup_parameter_info.xlsx'
    df = pd.read_excel(file_path)
    
    with open('frontend/Data/AI_cup_parameter_info.txt', 'w', encoding='utf-8') as f:
        for idx, row in df.iterrows():
            f.write(f"--- Row {idx + 1} ---\n")
            for col in df.columns:
                f.write(f"{col}: {row[col]}\n")
            f.write("\n")
            
if __name__ == '__main__':
    read_excel_to_text()
