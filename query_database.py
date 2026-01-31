"""
query_database.py - Query the encrypted SCMCU database using SqlciperDll.dll

Run this on Windows (not WSL)
"""

import ctypes
import os
import sys

# Find the DLL - try multiple locations
dll_paths = [
    r".\library\SqlciperDll.dll",
    r".\SCMCU_Writer_V9.01.15_20250521\library\SqlciperDll.dll",
    r".\SCMCU_Writer_V9.01.15\library\SqlciperDll.dll",
]

db_paths = [
    r".\data\database.db",
    r".\SCMCU_Writer_V9.01.15_20250521\data\database.db",
    r".\SCMCU_Writer_V9.01.15\data\database.db",
]

# Structure for query result
class QureyResult(ctypes.Structure):
    _fields_ = [
        ("nRow", ctypes.c_int),
        ("nColumn", ctypes.c_int),
        ("nIndex", ctypes.c_int),
        ("pResult", ctypes.c_void_p),
    ]

def find_file(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    return None

def main():
    # Find DLL
    dll_path = find_file(dll_paths)
    if not dll_path:
        print("Error: Could not find SqlciperDll.dll")
        print("Run this script from the SCMCU_Writer folder or IDE folder")
        sys.exit(1)

    # Find database
    db_path = find_file(db_paths)
    if not db_path:
        print("Error: Could not find database.db")
        sys.exit(1)

    print(f"Using DLL: {os.path.abspath(dll_path)}")
    print(f"Using DB: {os.path.abspath(db_path)}")

    # Load DLL
    try:
        dll = ctypes.CDLL(dll_path)
    except Exception as e:
        print(f"Error loading DLL: {e}")
        sys.exit(1)

    # Define function signatures
    dll.sqlite_connect.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    dll.sqlite_connect.restype = ctypes.c_int

    dll.sqlite_query.argtypes = [ctypes.c_char_p]
    dll.sqlite_query.restype = QureyResult

    dll.sqlite_free.argtypes = [QureyResult]
    dll.sqlite_free.restype = None

    dll.sqlite_close.argtypes = []
    dll.sqlite_close.restype = None

    # Connect to database
    db_path_bytes = db_path.encode('ascii')
    password = b"cmsxc"

    result = dll.sqlite_connect(db_path_bytes, password)
    if result != 1:
        print(f"Failed to connect to database (result={result})")
        sys.exit(1)

    print("Connected to database successfully!\n")

    # Helper function to execute query
    def execute_query(sql):
        sql_bytes = sql.encode('ascii')
        result = dll.sqlite_query(sql_bytes)

        if result.nRow <= 0 or result.nColumn <= 0:
            return [], []

        # Read results
        total = (result.nRow + 1) * result.nColumn
        ptr_array = (ctypes.c_void_p * total)()
        ctypes.memmove(ptr_array, result.pResult, ctypes.sizeof(ptr_array))

        # Extract column names (first row)
        columns = []
        for i in range(result.nColumn):
            if ptr_array[i]:
                columns.append(ctypes.string_at(ptr_array[i]).decode('utf-8', errors='replace'))
            else:
                columns.append(None)

        # Extract data rows
        rows = []
        idx = result.nColumn
        for r in range(result.nRow):
            row = []
            for c in range(result.nColumn):
                if ptr_array[idx]:
                    row.append(ctypes.string_at(ptr_array[idx]).decode('utf-8', errors='replace'))
                else:
                    row.append(None)
                idx += 1
            rows.append(row)

        dll.sqlite_free(result)
        return columns, rows

    # Query 1: Get all tables
    print("=== Tables in database ===")
    cols, rows = execute_query("SELECT name FROM sqlite_master WHERE type='table'")
    for row in rows:
        print(f"  {row[0]}")

    # Query 2: Get TABLE_SERIES structure and content
    print("\n=== TABLE_SERIES (MCU series definitions) ===")
    cols, rows = execute_query("SELECT * FROM TABLE_SERIES")
    if cols:
        print(f"Columns: {cols}")
        for row in rows[:20]:  # First 20
            print(f"  {row}")

    # Query 3: Search for SC8P in MCU names
    print("\n=== MCUs containing 'SC8P' ===")
    cols, rows = execute_query("SELECT m.MCU_NAME, s.NAME, s.ARCH FROM SCMCU AS m INNER JOIN TABLE_SERIES AS s ON m.MCU_SERIES = s.ID WHERE m.MCU_NAME LIKE '%SC8P%' ORDER BY m.MCU_NAME")
    if cols:
        print(f"{'MCU_NAME':<20} {'SERIES_NAME':<15} {'ARCH':<10}")
        print("-" * 50)
        for row in rows:
            print(f"{row[0]:<20} {row[1]:<15} {row[2]:<10}")

    # Query 4: Specifically check SC8P052
    print("\n=== SC8P052 details ===")
    cols, rows = execute_query("SELECT m.*, s.* FROM SCMCU AS m INNER JOIN TABLE_SERIES AS s ON m.MCU_SERIES = s.ID WHERE m.MCU_NAME = 'SC8P052'")
    if cols and rows:
        for i, col in enumerate(cols):
            print(f"  {col}: {rows[0][i]}")
    else:
        print("  SC8P052 not found!")

    # Close database
    dll.sqlite_close()
    print("\nDatabase closed.")

if __name__ == "__main__":
    main()
