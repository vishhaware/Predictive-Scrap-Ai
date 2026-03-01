import subprocess
def find_locker(path):
    # This is a bit hard on windows without handle.exe
    # But we can try to use open() to see it fails
    try:
        with open(path, "a") as f:
            pass
        return "Not locked"
    except Exception as e:
        return str(e)

path = "C:/new project/New folder/frontend/Data/M231-11.csv"
print(f"Locker check for {path}: {find_locker(path)}")
