import requests
import sqlite3
import math
from os import path

# ******************************************************************
# Configuracion
# ******************************************************************
BASE_URL = "http://localhost:5000"
THIS_FOLDER = path.dirname(path.abspath(__file__))
DB_PATH = path.join(THIS_FOLDER, "data", "data.db")
DB_TEST_PATH = path.join(THIS_FOLDER, "data", "data_test.db")
N = 100  # cantidad de recomendaciones a pedir


# ******************************************************************
# NDCG (igual que el profe)
# ******************************************************************
def ndcg(groud_truth, recommendation):
    dcg = 0.0
    for i, r in enumerate(recommendation):
        rel = int(r in groud_truth)
        dcg += rel / math.log2(i + 1 + 1)

    rels = [r for r in recommendation if r in groud_truth]
    not_rels = [r for r in recommendation if r not in groud_truth]

    idcg = 0.0000000000001
    for i, r in enumerate(rels + not_rels):
        idcg += 1.0 / math.log2(i + 1 + 1)

    return dcg / idcg



# ******************************************************************
# Helpers
# ******************************************************************
def ok(msg):
    print(f"  ✓ {msg}")

def error(msg):
    print(f"  ✗ {msg}")


# ******************************************************************
# Tests
# ******************************************************************
def test_ping():
    print("\n[1/3] GET /api/ping")
    endpoint = "/api/ping"
    res = requests.get(BASE_URL + endpoint, timeout=10)
    assert res.status_code == 200, f"status code esperado 200, recibido {res.status_code}"
    assert res.headers.get("content-type") == "application/json", "no devolvió JSON"
    j = res.json()
    assert "status" in j, "falta clave 'status'"
    assert j["status"] == "ok", f"status esperado 'ok', recibido '{j['status']}'"
    ok("ping ok")


def test_init():
    print("\n[2/3] GET /api/init")
    endpoint = "/api/init"
    res = requests.get(BASE_URL + endpoint, timeout=300)
    assert res.status_code == 200, f"status code esperado 200, recibido {res.status_code}"
    assert res.headers.get("content-type") == "application/json", "no devolvió JSON"
    j = res.json()
    assert "status" in j, "falta clave 'status'"
    assert j["status"] == "ok", f"status esperado 'ok', recibido '{j['status']}'"
    ok(f"init ok → {j.get('data', '')}")


def test_recomendar():
    print(f"\n[3/3] GET /api/recomendar/<N>/<id_lector>  (N={N})")
    endpoint = "/api/recomendar"

    # lectores a evaluar: los que tienen al menos una interaccion con rating >= 7 en test
    con_test = sqlite3.connect(DB_TEST_PATH)
    con_test.row_factory = sqlite3.Row
    cur_test = con_test.cursor()
    id_lectores = [
        r["id_lector"]
        for r in cur_test.execute(
            "SELECT DISTINCT id_lector FROM interacciones WHERE rating >= 7 ORDER BY id_lector"
        ).fetchall()
    ]
    con_test.close()

    print(f"  Lectores a evaluar: {len(id_lectores)} (usando primeros 20)")
    id_lectores = id_lectores[:20]

    # base de datos de libros validos
    con_data = sqlite3.connect(DB_PATH)
    con_data.row_factory = sqlite3.Row
    cur_data = con_data.cursor()

    recomendaciones = []
    for id_lector in id_lectores:
        res = requests.get(f"{BASE_URL}{endpoint}/{N}/{id_lector}", timeout=60)

        assert res.status_code == 200, f"status code esperado 200, recibido {res.status_code}"
        assert res.headers.get("content-type") == "application/json", "no devolvió JSON"
        j = res.json()
        assert "status" in j, "falta clave 'status'"
        assert j["status"] == "ok", f"status esperado 'ok', recibido '{j['status']}'"
        assert "recomendaciones" in j, "falta clave 'recomendaciones'"
        assert isinstance(j["recomendaciones"], list), "'recomendaciones' debe ser una lista"
        assert len(j["recomendaciones"]) == N, f"se esperaban {N} recomendaciones, se recibieron {len(j['recomendaciones'])}"

        # verificar que cada id_libro existe en data.db
        for id_libro in j["recomendaciones"]:
            res_libro = cur_data.execute(
                "SELECT * FROM libros WHERE id_libro = ?", [id_libro]
            ).fetchone()
            assert res_libro is not None, f"id_libro '{id_libro}' no existe en la base de datos"

        recomendaciones.append({
            "id_lector": id_lector,
            "recomendaciones": j["recomendaciones"]
        })
        print(f"  . {id_lector} ok", end="\r")

    con_data.close()
    ok(f"recomendar ok → {len(recomendaciones)} lectores evaluados")
    return recomendaciones


def calcular_ndcg(recomendaciones):
    print("\n[NDCG]")
    con_test = sqlite3.connect(DB_TEST_PATH)
    con_test.row_factory = sqlite3.Row
    cur_test = con_test.cursor()

    scores = []
    for rec in recomendaciones:
        gt = [
            r["id_libro"]
            for r in cur_test.execute(
                "SELECT id_libro FROM interacciones WHERE id_lector = ?",
                [rec["id_lector"]]
            ).fetchall()
        ]
        score = ndcg(gt, rec["recomendaciones"])
        scores.append(score)
        print(f"  {rec['id_lector']:20s} → NDCG: {score:.4f}  (GT size: {len(gt)})")

    con_test.close()

    promedio = sum(scores) / len(scores)
    print(f"\n  NDCG promedio: {promedio:.4f}")
    return promedio


# ******************************************************************
# Main
# ******************************************************************
if __name__ == "__main__":
    print("=" * 50)
    print(f"  Servidor: {BASE_URL}")
    print("=" * 50)

    try:
        test_ping()
        test_init()
        recomendaciones = test_recomendar()
        calcular_ndcg(recomendaciones)
        print("\n" + "=" * 50)
        print("  RESULTADO: OK")
        print("=" * 50)
    except AssertionError as e:
        print(f"\n  ERROR: {e}")
        print("=" * 50)
        print("  RESULTADO: ERROR")
        print("=" * 50)
