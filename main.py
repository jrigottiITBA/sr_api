# Importar librerias
from flask import Flask, jsonify, g, request
import sqlite3
import os

app = Flask(__name__)
DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.db')

# Funcion get db controller
def get_db():
    """Reutiliza la conexión dentro del mismo request."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row  # permite acceder por nombre de columna
    return g.db

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
    return jsonify({
        "status": "ok",
        "data": "pong"
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
    cursor = db.execute(
        """
        SELECT id_libro 
        FROM libros
        WHERE id_libro NOT IN (SELECT id_libro FROM interacciones WHERE id_lector = ?)
        ORDER BY random()
        LIMIT ?
        """, [id_lector, n_recomendaciones])
    rows = cursor.fetchall()

    return jsonify({
        "status": "ok",
        "recomendaciones": [dict(row) for row in rows],
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