with open("C:/new project/New folder/frontend/Data/M231-11.csv", "r", encoding="utf-8") as f:
    lines = [f.readline().strip() for _ in range(10)]
with open("C:/new project/New folder/csv_inspection.txt", "w") as f:
    f.write("\n".join(lines))
