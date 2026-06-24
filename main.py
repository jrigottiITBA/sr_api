# Importar librerias
from flask import Flask, jsonify, g, request
import sqlite3
import os
import pickle

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data','data.db')
RANKING_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'ranking.pkl')
LIBROS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'libros.pkl')
libros_cache = []  # variable global

# ******************************************************************
# Funcion get db controller
# ******************************************************************
def get_db():
    """Reutiliza la conexión dentro del mismo request."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row  # permite acceder por nombre de columna
    return g.db


# ******************************************************************
# Funcion elegir_estrategia
# Decide qué algoritmo usar según el historial del lector
# ******************************************************************
def elegir_estrategia(id_lector, db):
    n_interacciones = db.execute(
        "SELECT COUNT(*) FROM interacciones WHERE id_lector = ?",
        [id_lector]
    ).fetchone()[0]

    if n_interacciones < 10:
        return "popularidad"   # arranque en frio
    return "perfil"


# ******************************************************************
# Funcion recomendar_popularidad
# ******************************************************************
def recomendar_popularidad(n_recomendaciones, id_lector):
    db = get_db()

    # cargar ranking precalculado desde pickle (lista ordenada por score)
    with open(RANKING_PATH, 'rb') as f:
        ranking = pickle.load(f)

    # libros ya leidos por el lector
    leidos = set(
        row["id_libro"] for row in db.execute(
            "SELECT id_libro FROM interacciones WHERE id_lector = ?",
            [id_lector]
        ).fetchall()
    )

    # filtrar leidos y retornar top-N
    recomendaciones = [id_libro for id_libro in ranking if id_libro not in leidos]
    return recomendaciones[:n_recomendaciones]



# ******************************************************************
# Funcion construir_perfil
# Construye el perfil de un lector basado en sus interacciones
# Retorna dos dicts: {genero: peso} y {autor: peso}
# El peso es AVG(rating)/10 normalizado, con minimo 3 interacciones
# ******************************************************************
def construir_perfil(id_lector, db):
    # perfil de generos
    cursor = db.execute("""
        SELECT l.genero, AVG(i.rating) / 10.0 AS peso
        FROM interacciones i
        JOIN libros l ON i.id_libro = l.id_libro
        WHERE i.id_lector = ?
        GROUP BY l.genero
        HAVING COUNT(*) >= 3
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """, [id_lector])
    rows = cursor.fetchall()
    generos = {row["genero"]: row["peso"] for row in rows}
    total = sum(generos.values())
    if total > 0:
        generos = {k: v / total for k, v in generos.items()}

    # perfil de autores
    cursor = db.execute("""
        SELECT l.autor, AVG(i.rating) / 10.0 AS peso
        FROM interacciones i
        JOIN libros l ON i.id_libro = l.id_libro
        WHERE i.id_lector = ?
        GROUP BY l.autor
        HAVING COUNT(*) >= 3
        ORDER BY COUNT(*) DESC
        LIMIT 10
    """, [id_lector])
    rows = cursor.fetchall()
    autores = {row["autor"]: row["peso"] for row in rows}
    total = sum(autores.values())
    if total > 0:
        autores = {k: v / total for k, v in autores.items()}

    return generos, autores


# ******************************************************************
# Funcion recomendar_perfil
# Recomienda libros basados en el perfil del lector
# score = peso_genero + peso_autor
# ******************************************************************
def recomendar_perfil(n_recomendaciones, id_lector):
    global libros_cache
    db = get_db()

    # cargar libros desde cache
    if not libros_cache:
        with open(LIBROS_PATH, 'rb') as f:
            libros_cache = pickle.load(f)

    generos, autores = construir_perfil(id_lector, db)

    # libros ya leidos
    leidos = set(
        row["id_libro"] for row in db.execute(
            "SELECT id_libro FROM interacciones WHERE id_lector = ?",
            [id_lector]
        ).fetchall()
    )

    # scoring sobre cache en memoria, sin SQL
    scored = []
    for libro in libros_cache:
        if libro["id_libro"] in leidos:
            continue
        score = generos.get(libro["genero"], 0.0) + autores.get(libro["autor"], 0.0)
        if score > 0:
            scored.append((libro["id_libro"], score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [id_libro for id_libro, _ in scored[:n_recomendaciones]]


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ******************************************************************
# Route /api/init
# Para generar la tabla de libros agregados por rating_avg
# ******************************************************************
@app.route('/api/init')
def api_init():
    db = get_db()

    # calcular ranking
    rows = db.execute("""
        SELECT
            l.id_libro,
            AVG(i.rating)                                           AS rating_promedio,
            COUNT(*)                                                AS cantidad_ratings,
            (COUNT(*) * AVG(i.rating) + prior.global_avg * 25)
                / (COUNT(*) + 25)                                   AS score
        FROM libros l
        INNER JOIN interacciones i ON l.id_libro = i.id_libro
        CROSS JOIN (SELECT AVG(rating) AS global_avg FROM interacciones) prior
        GROUP BY l.id_libro
        ORDER BY score DESC
    """)

    # guardar en disco como lista de id_libros ordenados
    ranking = [row["id_libro"] for row in rows]
    with open(RANKING_PATH, 'wb') as f:
        pickle.dump(ranking, f)

    # guardar todos los libros en pickle
    libros = db.execute("SELECT id_libro, genero, autor FROM libros").fetchall()
    libros_list = [{"id_libro": r["id_libro"], "genero": r["genero"], "autor": r["autor"]} for r in libros]
    with open(LIBROS_PATH, 'wb') as f:
        pickle.dump(libros_list, f)

    return jsonify({
        "status": "ok",
        "data": f"ranking inicializado con {len(ranking)} libros"
    })


# ******************************************************************
# Route /api/ping
# ******************************************************************
@app.route('/api/ping')
def api_ping():
    return jsonify({
        "status": "ok",
        "data": "pong"
    })


# ******************************************************************
# Route: /api/recomendar_todos
# Method: POST
# Type: Path Parameters
# parameters in url:
#  /n_recomendaciones /id_lector
#
# Ejemplo_1: /api/recomendar

# ******************************************************************
@app.route('/api/recomendar_todos/<int:n_recomendaciones>', methods=['POST'])
def api_recomendar_todos(n_recomendaciones):
    payload = request.get_json()

    lectores = payload['id_lectores']
    if not lectores:
        return jsonify({"status": "error", "message": "La lista de lectores no puede estar vacía"}), 400
    
    db = get_db()
    recomendaciones = []
    for id_lector in lectores:
        estrategia = elegir_estrategia(id_lector, db)
        if estrategia == "popularidad":
            recs = recomendar_popularidad(n_recomendaciones, id_lector)
        elif estrategia == "perfil":
            recs = recomendar_perfil(n_recomendaciones, id_lector)
        recomendaciones.append({
            'id_lector': id_lector,
            'recomendacion': recs,
            'estrategia': estrategia
        })

    return jsonify({
        "status": "ok",
        "recomendaciones": recomendaciones,
    })



# ******************************************************************
# Route: /api/recomendar
# Type: Path Parameters
# parameters in url:
#  /n_recomendaciones /id_lector
#
# Ejemplo_1: /api/recomendar/10/moses
# ******************************************************************
@app.route('/api/recomendar/<int:n_recomendaciones>/<string:id_lector>')
def api_recomendar_path_params(n_recomendaciones, id_lector):
    db = get_db()
    estrategia = elegir_estrategia(id_lector, db)

    if estrategia == "popularidad":
        recomendaciones = recomendar_popularidad(n_recomendaciones, id_lector)
    elif estrategia == "perfil":
        recomendaciones = recomendar_perfil(n_recomendaciones, id_lector)

    print(f"  estrategia: {estrategia}, recomendaciones: {len(recomendaciones)}")

    return jsonify({
        "status": "ok",
        "recomendaciones": recomendaciones,
        "estrategia": estrategia
    })

# ******************************************************************
# Route: /api/recomendar
# Type: Query Parameters
#
# n_recomendaciones
# id_lector
# page
# per_page
# 
# Ejemplo_1: /api/recomendar?n_recomendaciones=10&id_lector=moses
# Ejemplo_2: /api/recomendar?n_recomendaciones=10&id_lector=popocito
# ******************************************************************
@app.route('/api/recomendar')
def api_recomendar_query_params():
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get("per_page", default=10, type=int)
    n_recomendaciones = request.args.get('n_recomendaciones', default=10, type=int)
    id_lector = request.args.get("id_lector", type=str)
    if not id_lector:
        return jsonify({"status": "error", "message": "id_lector es requerido"}), 400

    per_page = min(per_page, 200)
    page = max(page, 1)
    n_recomendaciones = min(n_recomendaciones, 2000)
    offset = (page - 1) * per_page

    db = get_db()

    total_disponible = db.execute(
        "SELECT COUNT(*) FROM interacciones WHERE id_lector = ?",
        (id_lector,)
    ).fetchone()[0]
    total = min(total_disponible, n_recomendaciones)

    limit = min(per_page, max(0, n_recomendaciones - offset))
    cursor = db.execute(
        """
        SELECT id_libro 
        FROM libros
        WHERE id_libro NOT IN (SELECT id_libro FROM interacciones WHERE id_lector = ?)
        ORDER BY random()
        LIMIT ? OFFSET ?
        """,
        (id_lector, limit, offset)
    )
    rows = cursor.fetchall()

    return jsonify({
        "status": "ok",
        "data": [dict(row) for row in rows],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page
        }
    })

# ******************************************************************
# Route /api/lectores
# parameters en params
# page
# per_page
#
# Ejemplo: /api/lectores?per_page=10
# ******************************************************************
@app.route('/api/lectores')
def api_lectores():
    page = request.args.get('page', default=1, type=int)
    per_page = request.args.get("per_page", default=10, type=int)

    # límites de seguridad
    per_page = min(per_page, 200)  # evita que pidan 1.000.000 de golpe
    page = max(page, 1)
    offset = (page - 1) * per_page
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM lectores").fetchone()[0]
    cursor = db.execute(
        "SELECT * FROM lectores LIMIT ? OFFSET ?",
        (per_page, offset)
    )
    rows = cursor.fetchall()
    lectores = [dict(row) for row in rows]

    return jsonify({
        "status": "ok",
        "data": lectores,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": (total + per_page - 1) // per_page  # ceil division
        }
    })
if __name__ == '__main__':
    app.run(debug=True)