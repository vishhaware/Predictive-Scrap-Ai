import os
files = ["M231-11.csv", "M356-57.csv", "M471-23.csv", "M607-30.csv", "M612-33.csv"]
data_dir = "C:/new project/New folder/frontend/Data"

results = {}
for f_name in files:
    path = os.path.join(data_dir, f_name)
    if not os.path.exists(path):
        results[f_name] = "Missing"
        continue
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 1000))
        tail = f.read().decode("utf-8", errors="ignore")
        results[f_name] = tail.strip().split("\n")[-1]

with open("C:/new project/New folder/csv_tails.txt", "w") as f:
    for k, v in results.items():
        f.write(f"{k}: {v}\n")
