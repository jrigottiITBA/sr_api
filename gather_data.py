import sqlite3
con = sqlite3.connect("data/data.db")
con.row_factory = sqlite3.Row

id_lector = '10155485526803149'

rows = con.execute("""
    SELECT l.genero, COUNT(*) as cant, AVG(i.rating) / 10.0 AS peso
    FROM interacciones i
    JOIN libros l ON i.id_libro = l.id_libro
    WHERE i.id_lector = ?
    GROUP BY l.genero
    HAVING COUNT(*) >= 3
    ORDER BY cant DESC
""", [id_lector]).fetchall()

print("generos con HAVING >= 3:")
for r in rows:
    print(dict(r))

# sin el HAVING para ver la distribucion real
rows2 = con.execute("""
    SELECT l.genero, COUNT(*) as cant
    FROM interacciones i
    JOIN libros l ON i.id_libro = l.id_libro
    WHERE i.id_lector = ?
    GROUP BY l.genero
    ORDER BY cant DESC
""", [id_lector]).fetchall()

print("\ngeneros sin filtro:")
for r in rows2:
    print(dict(r))

con.close()