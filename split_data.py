import sqlite3
import shutil
from os import path

# ******************************************************************
# Configuracion
# ******************************************************************
THIS_FOLDER = path.dirname(path.abspath(__file__))
DB_ORIGINAL  = path.join(THIS_FOLDER, "data", "data_original.db")  # backup
DB_TRAIN     = path.join(THIS_FOLDER, "data", "data.db")
DB_TEST      = path.join(THIS_FOLDER, "data", "data_test.db")
FECHA_CORTE  = "2023"  # testing: 2023 y 2024 (se compara contra el año)


# ******************************************************************
# Backup del original
# ******************************************************************
def hacer_backup():
    source = path.join(THIS_FOLDER, "data", "data.db")
    if not path.exists(DB_ORIGINAL):
        shutil.copy2(source, DB_ORIGINAL)
        print(f"  Backup creado en data_original.db")
    else:
        print(f"  Backup ya existe, no se sobreescribe")


# ******************************************************************
# Copiar tablas estaticas (libros, lectores)
# ******************************************************************
def copiar_tablas_estaticas(src_conn, dst_conn):
    src = src_conn.cursor()
    dst = dst_conn.cursor()

    for tabla in ["libros", "lectores"]:
        # obtener el schema de la tabla
        schema = src.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{tabla}'"
        ).fetchone()

        if schema is None:
            print(f"  Tabla '{tabla}' no encontrada, se omite")
            continue

        dst.execute(f"DROP TABLE IF EXISTS {tabla}")
        dst.execute(schema[0])

        rows = src.execute(f"SELECT * FROM {tabla}").fetchall()
        if rows:
            placeholders = ",".join(["?" for _ in rows[0]])
            dst.executemany(f"INSERT INTO {tabla} VALUES ({placeholders})", rows)

        print(f"  {tabla}: {len(rows)} filas copiadas")

    dst_conn.commit()


# ******************************************************************
# Crear tabla interacciones y poblarla con filtro de fecha
# ******************************************************************
def crear_interacciones(src_conn, dst_conn, filtro, params):
    src = src_conn.cursor()
    dst = dst_conn.cursor()

    schema = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='interacciones'"
    ).fetchone()[0]

    dst.execute("DROP TABLE IF EXISTS interacciones")
    dst.execute(schema)

    # la fecha esta en formato DD-MM-YYYY, extraemos el año con substr(fecha, 7, 4)
    rows = src.execute(
        f"SELECT * FROM interacciones WHERE {filtro}", params
    ).fetchall()

    if rows:
        placeholders = ",".join(["?" for _ in rows[0]])
        dst.executemany(f"INSERT INTO interacciones VALUES ({placeholders})", rows)

    dst_conn.commit()
    return len(rows)


# ******************************************************************
# Main
# ******************************************************************
if __name__ == "__main__":
    print("=" * 50)
    print("  Particion de datos")
    print(f"  Corte: {FECHA_CORTE}")
    print(f"  Training: antes de {FECHA_CORTE}")
    print(f"  Testing:  {FECHA_CORTE} en adelante")
    print("=" * 50)

    hacer_backup()

    con_original = sqlite3.connect(DB_ORIGINAL)

    # verificar cantidad total
    total = con_original.execute("SELECT COUNT(*) FROM interacciones").fetchone()[0]
    print(f"\n  Total interacciones en original: {total}")

    # --- TRAINING ---
    print("\n  Creando data.db (training)...")
    con_train = sqlite3.connect(DB_TRAIN)
    copiar_tablas_estaticas(con_original, con_train)
    n_train = crear_interacciones(
        con_original, con_train,
        filtro="substr(fecha, 7, 4) < ?",
        params=[FECHA_CORTE]
    )
    print(f"  interacciones training: {n_train}")
    con_train.close()

    # --- TESTING ---
    print("\n  Creando data_test.db (testing)...")
    con_test = sqlite3.connect(DB_TEST)
    copiar_tablas_estaticas(con_original, con_test)
    n_test = crear_interacciones(
        con_original, con_test,
        filtro="substr(fecha, 7, 4) >= ?",
        params=[FECHA_CORTE]
    )
    print(f"  interacciones testing: {n_test}")
    con_test.close()

    con_original.close()

    print("\n" + "=" * 50)
    print(f"  Training:  {n_train} interacciones ({n_train*100//total}%)")
    print(f"  Testing:   {n_test} interacciones ({n_test*100//total}%)")
    print(f"  Total:     {n_train + n_test} / {total}")
    print("=" * 50)
