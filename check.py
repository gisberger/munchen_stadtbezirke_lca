import pandas as pd
from pathlib import Path

f = Path(r"D:\Studium\Ökobilanz\proj\Berechnete Impacts pkm\tram_strom_conv.xlsx")
df = pd.read_excel(f, sheet_name="Impacts", header=0)
print("Shape:", df.shape)
print(df.iloc[:, :6].head(15).to_string())