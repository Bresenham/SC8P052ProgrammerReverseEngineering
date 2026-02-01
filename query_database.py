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

    # Query 5: Find all C* tables (likely programming tables)
    print("\n=== All C* tables (potential programming parameters) ===")
    cols, rows = execute_query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'C%' ORDER BY name")
    if rows:
        for row in rows:
            print(f"  {row[0]}")

    # Query 6: Check CXYD table structure and data for series 59 (SC8P052 series)
    print("\n=== CXYD table (Programming parameters) ===")
    cols, rows = execute_query("PRAGMA table_info(CXYD)")
    if cols:
        print("Columns:")
        for row in rows:
            print(f"  {row}")
    
    print("\nCXYD data for series 59 (SC8P052):")
    cols, rows = execute_query("SELECT * FROM CXYD WHERE ID=59 OR rowid=59 LIMIT 5")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")
    else:
        # Try without WHERE clause
        cols, rows = execute_query("SELECT * FROM CXYD LIMIT 3")
        if cols and rows:
            print(f"Columns: {cols}")
            for row in rows:
                print(f"  {row}")

    # Query 7: Check CFMT table (Format)
    print("\n=== CFMT table (Format structure) ===")
    cols, rows = execute_query("PRAGMA table_info(CFMT)")
    if cols:
        print("Columns:")
        for row in rows:
            print(f"  {row}")
    
    print("\nCFMT data:")
    cols, rows = execute_query("SELECT * FROM CFMT LIMIT 5")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")

    # Query 8: Check CBW table (Byte width?)
    print("\n=== CBW table ===")
    cols, rows = execute_query("PRAGMA table_info(CBW)")
    if cols:
        print("Columns:")
        for row in rows:
            print(f"  {row}")
    
    print("\nCBW data:")
    cols, rows = execute_query("SELECT * FROM CBW LIMIT 5")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")

    # Query 9: Check CJY table
    print("\n=== CJY table ===")
    cols, rows = execute_query("PRAGMA table_info(CJY)")
    if cols:
        print("Columns:")
        for row in rows:
            print(f"  {row}")
    
    print("\nCJY data:")
    cols, rows = execute_query("SELECT * FROM CJY LIMIT 5")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")

    # Query 10: Find timing-related columns
    print("\n=== Tables with timing/delay columns ===")
    cols, rows = execute_query("""
        SELECT m.name as table_name, p.name as column_name 
        FROM sqlite_master m 
        JOIN pragma_table_info(m.name) p 
        WHERE m.type='table' 
        AND (p.name LIKE '%TIME%' OR p.name LIKE '%DELAY%' OR p.name LIKE '%CLK%' OR p.name LIKE '%FREQ%')
        ORDER BY m.name
    """)
    if rows:
        for row in rows:
            print(f"  {row[0]}.{row[1]}")

    # Query 11: Check CKDHM table
    print("\n=== CKDHM table ===")
    cols, rows = execute_query("PRAGMA table_info(CKDHM)")
    if cols:
        print("Columns:")
        for row in rows:
            print(f"  {row}")
    
    print("\nCKDHM data:")
    cols, rows = execute_query("SELECT * FROM CKDHM LIMIT 5")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")

    # Query 12: Get row counts for all tables
    print("\n=== Table row counts ===")
    cols, rows = execute_query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    if rows:
        for row in rows:
            table_name = row[0]
            count_cols, count_rows = execute_query(f"SELECT COUNT(*) FROM {table_name}")
            if count_rows:
                print(f"  {table_name}: {count_rows[0][0]} rows")

    # Query 13: Check version table
    print("\n=== version table ===")
    cols, rows = execute_query("SELECT * FROM version")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")

    # Query 14: Check CJDZ table
    print("\n=== CJDZ table ===")
    cols, rows = execute_query("PRAGMA table_info(CJDZ)")
    if cols:
        print("Columns:")
        for row in rows:
            print(f"  {row}")
    
    print("\nCJDZ data:")
    cols, rows = execute_query("SELECT * FROM CJDZ LIMIT 5")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")

    # Query 15: Check CJX table
    print("\n=== CJX table ===")
    cols, rows = execute_query("PRAGMA table_info(CJX)")
    if cols:
        print("Columns:")
        for row in rows:
            print(f"  {row}")
    
    print("\nCJX data:")
    cols, rows = execute_query("SELECT * FROM CJX LIMIT 5")
    if cols and rows:
        print(f"Columns: {cols}")
        for row in rows:
            print(f"  {row}")

    # Close database
    dll.sqlite_close()
    print("\n" + "="*60)
    print("DATABASE ANALYSIS COMPLETE")
    print("="*60)
    print("\nPlease share this output for ICSP protocol analysis!")
    print("Focus on any binary/hex data in CXYD, CFMT, CBW, CJY tables.")

if __name__ == "__main__":
    main()
