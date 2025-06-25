from flask import Flask, request, jsonify, send_file # Añadir send_file
from neo4j import GraphDatabase
from flask_cors import CORS

app = Flask(__name__)
CORS(app) # Habilitar CORS para toda la aplicación

# Configuración de conexión a Neo4j
# Asegúrate de que tu instancia de Neo4j esté corriendo y que la contraseña sea la correcta.
# Por defecto, la URL es bolt://localhost:7687 y el usuario es neo4j.
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
# >>>>>> ¡¡¡REEMPLAZA ESTO CON TU CONTRASEÑA REAL DE NEO4J!!! <<<<<<
PASSWORD = "basededatos123"

# Objeto Driver de Neo4j
driver = None

def get_db_connection():
    global driver
    if driver is None:
        try:
            driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
            driver.verify_connectivity() # Verifica que la conexión se pueda establecer
            print("Conexión a Neo4j establecida correctamente.")
        except Exception as e:
            print(f"Error al conectar a Neo4j: {e}")
            driver = None # Resetea el driver si falla la conexión
            # Dependiendo de tu aplicación, podrías no querer lanzar la excepción en producción
            # pero para depuración es útil saber el error.
            raise
    return driver

# Ruta principal que servirá el archivo index.html
@app.route('/')
def serve_index():
    return send_file('index.html') # Sirve el archivo index.html de la misma carpeta

# Endpoint para probar la conexión a la base de datos
@app.route('/test_db_connection')
def test_db_connection():
    try:
        driver_obj = get_db_connection()
        if driver_obj:
            with driver_obj.session() as session:
                result = session.run("MATCH (n) RETURN count(n) AS node_count")
                node_count = result.single()["node_count"]
                return jsonify({"status": "success", "node_count": node_count})
        else:
            return jsonify({"status": "error", "message": "No se pudo conectar a la base de datos."}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error en la consulta de prueba: {e}"}), 500

# === Tarea II.1: Ruta Más Rápida (Dijkstra/Shortest Path) ===
# Encuentra la ruta más rápida (menor tiempo_minutos total) entre un origen y un destino.
# El origen puede ser CentroDistribucion o Zona, el destino es Zona.
# Usa la librería GDS (Graph Data Science).
@app.route('/fastest_route', methods=['GET'])
def get_fastest_route():
    start_name = request.args.get('start')
    end_name = request.args.get('end')

    if not start_name or not end_name:
        return jsonify({"status": "error", "message": "Por favor, especifica 'start' y 'end'."}), 400

    try:
        driver_obj = get_db_connection()
        with driver_obj.session() as session:
            query = """
            MATCH (startNode), (endNode)
            WHERE (startNode:CentroDistribucion AND startNode.nombre = $start_name)
               OR (startNode:Zona AND startNode.nombre = $start_name)
            AND endNode:Zona AND endNode.nombre = $end_name
            CALL gds.shortestPath.dijkstra.stream('delivery_graph', {
                sourceNode: startNode,
                targetNode: endNode,
                relationshipWeightProperty: 'tiempo_minutos'
            })
            YIELD nodeIds, totalCost
            RETURN [id IN nodeIds | gds.util.asNode(id).nombre] AS path, totalCost
            """
            result = session.run(query, start_name=start_name, end_name=end_name)
            record = result.single()

            if record:
                return jsonify({
                    "status": "success",
                    "path": record["path"],
                    "total_time_minutes": record["totalCost"]
                })
            else:
                return jsonify({"status": "info", "message": "No se encontró una ruta."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al encontrar la ruta más rápida: {e}"}), 500

# Variante de complejidad: Ruta más rápida entre dos Zonas cualesquiera, sin pasar por zonas bloqueadas.
@app.route('/fastest_route_blocked', methods=['GET'])
def get_fastest_route_blocked():
    start_name = request.args.get('start')
    end_name = request.args.get('end')
    blocked_zones_str = request.args.get('blocked_zones', '') # Lista de zonas separadas por coma

    if not start_name or not end_name:
        return jsonify({"status": "error", "message": "Por favor, especifica 'start' y 'end'."}), 400

    blocked_zones = [zone.strip() for zone in blocked_zones_str.split(',') if zone.strip()]

    try:
        driver_obj = get_db_connection()
        with driver_obj.session() as session:
            # Usamos shortestPath puro de Cypher aquí para manejar la exclusión de nodos dinámicamente
            query = """
            MATCH (startNode:Zona {nombre: $start_name}), (endNode:Zona {nombre: $end_name})
            MATCH p = shortestPath((startNode)-[r:CONECTA*]->(endNode))
            WHERE ALL (node IN nodes(p) WHERE NOT node.nombre IN $blocked_zones)
            RETURN [node IN nodes(p) | node.nombre] AS path,
                   reduce(totalTiempo = 0, rel IN relationships(p) | totalTiempo + rel.tiempo_minutos) AS total_time_minutes
            ORDER BY total_time_minutes ASC
            LIMIT 1
            """
            result = session.run(query, start_name=start_name, end_name=end_name, blocked_zones=blocked_zones)
            record = result.single()

            if record:
                return jsonify({
                    "status": "success",
                    "path": record["path"],
                    "total_time_minutes": record["total_time_minutes"]
                })
            else:
                return jsonify({"status": "info", "message": "No se encontró una ruta con las restricciones dadas."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al encontrar la ruta más rápida con zonas bloqueadas: {e}"}), 500

# === Tarea II.2: Zonas Directamente Accesibles ===
# Lista todas las zonas que son directamente accesibles desde un CentroDistribucion determinado en menos de X minutos.
@app.route('/accessible_zones', methods=['GET'])
def get_accessible_zones():
    centro_name = request.args.get('centro')
    max_time_str = request.args.get('max_time')

    if not centro_name or not max_time_str:
        return jsonify({"status": "error", "message": "Por favor, especifica 'centro' y 'max_time'."}), 400

    try:
        max_time = int(max_time_str)
    except ValueError:
        return jsonify({"status": "error", "message": "El tiempo máximo debe ser un número entero."}), 400

    try:
        driver_obj = get_db_connection()
        with driver_obj.session() as session:
            query = """
            MATCH (cd:CentroDistribucion {nombre: $centro_name})-[r:CONECTA]->(z:Zona)
            WHERE r.tiempo_minutos <= $max_time
            RETURN z.nombre AS Zona, r.tiempo_minutos AS Tiempo
            ORDER BY r.tiempo_minutos
            """
            result = session.run(query, centro_name=centro_name, max_time=max_time)
            zones = [{"zona": record["Zona"], "tiempo": record["Tiempo"]} for record in result]
            
            if zones:
                return jsonify({"status": "success", "accessible_zones": zones})
            else:
                return jsonify({"status": "info", "message": "No se encontraron zonas directamente accesibles en el tiempo especificado."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al obtener zonas accesibles: {e}"}), 500

# === Tarea II.3: Zonas con Mayor Tráfico/Congestión ===
# Identifica las relaciones CONECTA (calles) que tienen un trafico_actual 'alto' o que superan cierta capacidad.
@app.route('/congested_routes', methods=['GET'])
def get_congested_routes():
    # Parámetro opcional para un umbral de capacidad si se quiere probar diferentes valores
    capacity_threshold_str = request.args.get('capacity_threshold')
    capacity_threshold = None
    if capacity_threshold_str:
        try:
            capacity_threshold = int(capacity_threshold_str)
        except ValueError:
            return jsonify({"status": "error", "message": "El umbral de capacidad debe ser un número entero."}), 400

    try:
        driver_obj = get_db_connection()
        with driver_obj.session() as session:
            # Añadir una cláusula WHERE para la capacidad si se proporciona un umbral
            query = """
            MATCH (n)-[r:CONECTA]->(m)
            WHERE r.trafico_actual = 'alto'
            """
            params = {}

            if capacity_threshold is not None:
                # CAMBIO AQUÍ: Reemplazado EXISTS(r.capacidad) con r.capacidad IS NOT NULL
                query += " OR (r.capacidad IS NOT NULL AND r.capacidad < $capacity_threshold)"
                params['capacity_threshold'] = capacity_threshold
            
            query += """
            RETURN n.nombre AS ZonaOrigen, m.nombre AS ZonaDestino, r.tiempo_minutos AS Tiempo, r.trafico_actual AS Trafico, r.capacidad AS Capacidad
            """
            result = session.run(query, params)
            routes = [record.data() for record in result] # .data() obtiene el dict completo

            if routes:
                return jsonify({"status": "success", "congested_routes": routes})
            else:
                return jsonify({"status": "info", "message": "No se encontraron rutas congestionadas."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al obtener rutas congestionadas: {e}"}), 500

# === Tarea II.4: Conectividad de la Red ===
# Verifica si todas las zonas son accesibles desde al menos un CentroDistribucion.
@app.route('/check_connectivity', methods=['GET'])
def check_network_connectivity():
    try:
        driver_obj = get_db_connection()
        with driver_obj.session() as session:
            query = """
            MATCH (z:Zona)
            OPTIONAL MATCH p = shortestPath((:CentroDistribucion)-[:CONECTA*]->(z))
            WITH z, p
            WHERE p IS NULL
            RETURN COLLECT(z.nombre) AS ZonasNoAccesibles
            """
            result = session.run(query)
            record = result.single()
            non_accessible_zones = record["ZonasNoAccesibles"] if record else []

            if non_accessible_zones:
                return jsonify({
                    "status": "warning",
                    "message": "Se encontraron zonas no accesibles desde ningún Centro de Distribución.",
                    "non_accessible_zones": non_accessible_zones
                })
            else:
                return jsonify({"status": "success", "message": "Todas las zonas son accesibles desde al menos un Centro de Distribución."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al verificar la conectividad de la red: {e}"}), 500

# Variante de complejidad: Encuentra todas las Zonas que quedarían aisladas si una Zona específica se "cerrara".
@app.route('/isolated_zones_by_zone_closure', methods=['GET'])
def get_isolated_zones_by_zone_closure():
    excluded_zone_name = request.args.get('excluded_zone')

    if not excluded_zone_name:
        return jsonify({"status": "error", "message": "Por favor, especifica 'excluded_zone'."}), 400

    try:
        driver_obj = get_db_connection()
        with driver_obj.session() as session:
            query = """
            MATCH (allZones:Zona)
            WHERE allZones.nombre <> $excluded_zone_name
            OPTIONAL MATCH p = shortestPath((:CentroDistribucion)-[:CONECTA*]->(allZones))
            WHERE ALL (node IN nodes(p) WHERE NOT node.nombre = $excluded_zone_name) // Excluir el nodo de la ruta
            WITH allZones, p
            WHERE p IS NULL
            RETURN COLLECT(allZones.nombre) AS ZonasAisladasPorCierreDeZona
            """
            result = session.run(query, excluded_zone_name=excluded_zone_name)
            record = result.single()
            isolated_zones = record["ZonasAisladasPorCierreDeZona"] if record else []

            if isolated_zones:
                return jsonify({
                    "status": "warning",
                    "message": f"Zonas que quedarían aisladas si '{excluded_zone_name}' se cerrara.",
                    "isolated_zones": isolated_zones
                })
            else:
                return jsonify({"status": "success", "message": f"Ninguna zona quedaría aislada si '{excluded_zone_name}' se cerrara."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al simular cierre de zona: {e}"}), 500

# Variante de complejidad: Encuentra todas las Zonas que quedarían aisladas si una relación CONECTA específica se "cerrara".
@app.route('/isolated_zones_by_route_closure', methods=['GET'])
def get_isolated_zones_by_route_closure():
    excluded_route_start = request.args.get('start_zone')
    excluded_route_end = request.args.get('end_zone')

    if not excluded_route_start or not excluded_route_end:
        return jsonify({"status": "error", "message": "Por favor, especifica 'start_zone' y 'end_zone' para la ruta a cerrar."}), 400

    try:
        driver_obj = get_db_connection()
        with driver_obj.session() as session:
            # NOTA: Esta consulta asume que hay una única relación entre start_zone y end_zone para la exclusión simple.
            # Para relaciones bidireccionales, deberías considerar si el cierre afecta ambos sentidos.
            query = """
                MATCH (z:Zona)
                OPTIONAL MATCH p = shortestPath((:CentroDistribucion)-[r:CONECTA*]->(z))
                WHERE NOT EXISTS {
                    MATCH (n1:Zona {nombre: $excluded_route_start})-[r_exclude:CONECTA]->(n2:Zona {nombre: $excluded_route_end})
                    WHERE r_exclude IN relationships(p)
                }
                WITH z, p
                WHERE p IS NULL
                RETURN COLLECT(z.nombre) AS ZonasAisladasPorCierreDeRuta
            """
            result = session.run(query, excluded_route_start=excluded_route_start, excluded_route_end=excluded_route_end)
            record = result.single()
            isolated_zones = record["ZonasAisladasPorCierreDeRuta"] if record else []

            if isolated_zones:
                return jsonify({
                    "status": "warning",
                    "message": f"Zonas que quedarían aisladas si la ruta entre '{excluded_route_start}' y '{excluded_route_end}' se cerrara.",
                    "isolated_zones": isolated_zones
                })
            else:
                return jsonify({"status": "success", "message": f"Ninguna zona quedaría aislada si la ruta entre '{excluded_route_start}' y '{excluded_route_end}' se cerrara."})
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error al simular cierre de ruta: {e}"}), 500


if __name__ == '__main__':
    # Asegúrate de que tu instancia Neo4j esté corriendo ANTES de ejecutar Flask
    app.run(debug=True)