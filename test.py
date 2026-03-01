import csv
import sys
rows = list(csv.reader(open('C:/new project/New folder/frontend/Data/M231-11.csv', 'r')))
print("Last 10 rows:")
for r in rows[-10:]:
    print(r)
