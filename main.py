# Importar librerias
from flask import Flask, jsonify, g, request
import sqlite3
import os

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data','data.db')

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
    cursor = db.execute(
        """
        SELECT
            r.id_libro
        FROM ranking_libros r
        WHERE r.id_libro NOT IN (
            SELECT i.id_libro
            FROM interacciones i
            WHERE i.id_lector = ?
        )
        ORDER BY
            r.score DESC
        LIMIT ?;
        """, [id_lector, n_recomendaciones])
    rows = cursor.fetchall()

    return [row["id_libro"] for row in rows]



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
    db = get_db()
    generos, autores = construir_perfil(id_lector, db)

    # obtener libros no leidos
    cursor = db.execute("""
        SELECT id_libro, genero, autor
        FROM libros
        WHERE id_libro NOT IN (
            SELECT id_libro FROM interacciones WHERE id_lector = ?
        )
    """, [id_lector])
    libros = cursor.fetchall()

    # calcular score de cada libro
    scored = []
    for libro in libros:
        score = generos.get(libro["genero"], 0.0) + autores.get(libro["autor"], 0.0)
        if score > 0:
            scored.append((libro["id_libro"], score))

    scored.sort(key=lambda x: x[1], reverse=True)

    print(f"  scored total: {len(scored)}")
    print(f"  top 5: {scored[:5]}")
    return [id_libro for id_libro, _ in scored[:n_recomendaciones]]


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# ******************************************************************
# Route /api/init
# Para generar la tabla de libros agregador por rating_avg
# ******************************************************************
@app.route('/api/init')
def api_init():
    db = get_db()

    # db.execute("DROP TABLE ranking_libros")

    db.execute("""
        CREATE TABLE IF NOT EXISTS ranking_libros (
            id_libro TEXT PRIMARY KEY,
            titulo TEXT,
            autor TEXT,
            rating_promedio REAL,
            cantidad_ratings INTEGER,
            score REAL
        )
    """)

    db.execute("DELETE FROM ranking_libros")

    db.execute("""
        INSERT INTO ranking_libros (
            id_libro,
            titulo,
            autor,
            rating_promedio,
            cantidad_ratings,
            score
        )
        SELECT
            l.id_libro,
            l.titulo,
            l.autor,
            AVG(i.rating)                                           AS rating_promedio,
            COUNT(*)                                                AS cantidad_ratings,
            (COUNT(*) * AVG(i.rating) + prior.global_avg * 25)
                / (COUNT(*) + 25)                                   AS score
        FROM libros l
        INNER JOIN interacciones i ON l.id_libro = i.id_libro
        CROSS JOIN (SELECT AVG(rating) AS global_avg FROM interacciones) prior
        GROUP BY l.id_libro, l.titulo, l.autor
        ORDER BY score DESC
    """)

    db.commit()

    total = db.execute("SELECT COUNT(*) FROM ranking_libros").fetchone()[0]

    return jsonify({
        "status": "ok",
        "data": f"ranking_libros inicializada con {total} libros"
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
    if not payload or 'id_lectores' not in payload:
        return jsonify({"status": "error", "message": "Se requiere JSON con la clave 'id_lectores'"}), 400

    lectores = payload['id_lectores']
    if not lectores:
        return jsonify({"status": "error", "message": "La lista de lectores no puede estar vacía"}), 400

    recomendaciones = []
    for id_lector in lectores:
        recomendaciones.append({'id_lector': id_lector, 'recomendacion': recomendar_popularidad(n_recomendaciones, id_lector)})

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