# api.py (CÓDIGO COMPLETO DEL BACKEND)

import os
import psycopg2
import jwt
import datetime
from datetime import timedelta, date # Importa date y timedelta para la lógica semanal
from functools import wraps

# Importaciones de Flask necesarias
from flask import Flask, jsonify, request
from flask_bcrypt import Bcrypt
from flask_cors import CORS # Necesario para permitir que Streamlit (otro dominio) se conecte

# --- 1. Inicialización de la Aplicación ---

app = Flask(__name__)
CORS(app) # Habilita CORS para el frontend de Streamlit
bcrypt = Bcrypt(app)

# Configuración y Clave Secreta (Leyendo de las variables de entorno de Render)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'FALLBACK_KEY_DEBES_CAMBIAR_ESTO')

# Detalles de la conexión a la Base de Datos (Leyendo de las variables de entorno de Render)
DB_NAME = os.environ.get('DATABASE', 'nutrigoal_db')
DB_USER = os.environ.get('USER', 'postgres')
DB_PASSWORD = os.environ.get('PASSWORD') 
DB_HOST = os.environ.get('HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')


# --- 2. Funciones Auxiliares y Decoradores ---

def get_db_connection():
    """Establece una conexión a la base de datos PostgreSQL."""
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    return conn


def token_required(f):
    """Decorador para proteger rutas y verificar el token JWT."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'x-access-tokens' in request.headers:
            token = request.headers['x-access-tokens']

        if not token:
            return jsonify({'message': 'a valid token is missing!'}), 401
        
        try:
            # Decodificar el token usando la SECRET_KEY
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user_id = data['user_id']
        except:
            return jsonify({'message': 'Token is invalid!'}), 401

        # Pasar el user_id a la función decorada
        return f(current_user_id, *args, **kwargs)

    return decorated


# --- 3. Endpoints de la API ---

@app.route('/')
def home():
    """API welcome message."""
    return 'Welcome to the NutriGoal API!'


@app.route('/api/foods', methods=['GET'])
def get_foods():
    """Retrieves all food items from the database based on the selected language."""
    lang = request.args.get('lang', 'es')

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT T1.id, COALESCE(T2.translation, T1.name), T1.is_vegetable_for_challenge, T1.is_prebiotic, T1.is_probiotic
            FROM foods AS T1
            LEFT JOIN food_translations AS T2 ON T1.id = T2.food_id AND T2.lang = %s;
            """,
            (lang,)
        )
        foods = cur.fetchall()
        
        foods_list = []
        for food in foods:
            foods_list.append({
                'id': food[0],
                'name': food[1],
                'is_vegetable_for_challenge': food[2],
                'is_prebiotic': food[3],
                'is_probiotic': food[4]
            })
        return jsonify(foods_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/user_food_logs', methods=['POST'])
@token_required
def add_user_food_log(current_user_id):
    """Adds a new food log for a user."""
    data = request.json
    food_id = data.get('food_id')

    if not food_id:
        return jsonify({'error': 'Missing food_id'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO user_food_logs (user_id, food_id) VALUES (%s, %s);',
            (current_user_id, food_id)
        )
        conn.commit()
        return jsonify({'message': 'Food log added successfully!'}), 201
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/user_food_logs', methods=['GET'])
@token_required
def get_user_food_logs(current_user_id):
    """Retrieves the food log history for a specific user."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                ufl.id, ufl.date_consumed, f.name, f.is_vegetable_for_challenge, f.is_prebiotic, f.is_probiotic
            FROM user_food_logs AS ufl
            JOIN foods AS f ON ufl.food_id = f.id
            WHERE ufl.user_id = %s
            ORDER BY ufl.date_consumed DESC;
            """,
            (current_user_id,)
        )
        logs = cur.fetchall()
        
        logs_list = []
        for log in logs:
            logs_list.append({
                'log_id': log[0],
                'date_consumed': log[1].isoformat(),
                'food_name': log[2],
                'is_vegetable_for_challenge': log[3],
                'is_prebiotic': log[4],
                'is_probiotic': log[5]
            })
        return jsonify(logs_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/user_food_logs/<int:log_id>', methods=['DELETE'])
@token_required
def delete_user_food_log(current_user_id, log_id):
    """Deletes a food log entry for the current user."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # 1. Verificar si el log existe y pertenece al usuario actual
        cur.execute('SELECT user_id FROM user_food_logs WHERE id = %s;', (log_id,))
        log_owner_id = cur.fetchone()
        
        if log_owner_id is None:
             return jsonify({'error': 'Log not found.'}), 404
        
        if log_owner_id[0] != current_user_id:
            return jsonify({'error': 'You do not have permission to delete this log.'}), 403

        # 2. Si es válido, eliminar
        cur.execute('DELETE FROM user_food_logs WHERE id = %s;', (log_id,))
        conn.commit()
        return jsonify({'message': 'Food log deleted successfully!'}), 200
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/register', methods=['POST'])
def register_user():
    """Registers a new user."""
    data = request.json
    username = data.get('username')
    password = data.get('password')
    full_name = data.get('full_name')

    if not all([username, password, full_name]):
        return jsonify({'error': 'Missing username, password, or full name'}), 400

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (username, password_hash, full_name) VALUES (%s, %s, %s) RETURNING id;',
                    (username, hashed_password, full_name))
        user_id = cur.fetchone()[0]
        conn.commit()
        return jsonify({'message': 'User registered successfully!', 'user_id': user_id}), 201
    
    except psycopg2.IntegrityError:
        conn.rollback()
        # CORRECCIÓN CLAVE: Debe haber un return explícito en este bloque
        return jsonify({'error': 'Username already exists'}), 409
        
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/login', methods=['POST'])
def login_user():
    """Logs in an existing user and returns a JWT token."""
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not all([username, password]):
        return jsonify({'error': 'Missing username or password'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('SELECT id, password_hash, full_name FROM users WHERE username = %s;', (username,))
        user = cur.fetchone()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

    if user and bcrypt.check_password_hash(user[1], password):
        token_payload = {
            'user_id': user[0],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24) 
        }
        token = jwt.encode(token_payload, app.config['SECRET_KEY'], algorithm='HS256')
        return jsonify({'message': 'Login successful!', 'token': token, 'full_name': user[2]}), 200
    else:
        return jsonify({'error': 'Invalid username or password'}), 401

@app.route('/api/user/goal', methods=['PUT'])
@token_required
def update_user_goal(current_user_id):
    """Updates the user's weekly vegetable goal."""
    data = request.json
    new_goal = data.get('goal')

    if not isinstance(new_goal, int) or new_goal <= 0:
        return jsonify({'error': 'Invalid goal value. Must be a positive integer.'}), 400

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            'UPDATE users SET weekly_vegetable_goal = %s WHERE id = %s;',
            (new_goal, current_user_id)
        )
        conn.commit()
        return jsonify({'message': 'Goal updated successfully!'}), 200
    except psycopg2.Error as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/user/goal', methods=['GET'])
@token_required
def get_user_goal(current_user_id):
    """Retrieves the user's weekly vegetable goal."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            'SELECT weekly_vegetable_goal FROM users WHERE id = %s;',
            (current_user_id,)
        )
        user_goal = cur.fetchone()
        if user_goal:
            return jsonify({'weekly_vegetable_goal': user_goal[0]}), 200
        else:
            return jsonify({'error': 'User not found.'}), 404
    except psycopg2.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/user_progress', methods=['GET'])
@token_required
def get_user_progress(current_user_id):
    """Calculates the number of unique vegetables consumed this week."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Se usa datetime.date y datetime.timedelta
        today = datetime.date.today()
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        cur.execute(
            """
            SELECT COUNT(DISTINCT T1.id)
            FROM user_food_logs AS T2
            INNER JOIN foods AS T1
            ON T1.id = T2.food_id
            WHERE T2.user_id = %s
            AND T1.is_vegetable_for_challenge = TRUE
            AND T2.date_consumed BETWEEN %s AND %s;
            """,
            (current_user_id, start_of_week, end_of_week)
        )
        vegetable_count = cur.fetchone()[0]
        return jsonify({'vegetable_count': vegetable_count}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/diversity_metrics', methods=['GET'])
@token_required
def get_diversity_metrics(current_user_id):
    """Calculates the number of unique prebiotics and probiotics consumed this week."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        today = datetime.date.today()
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        cur.execute(
            """
            SELECT
                COUNT(DISTINCT CASE WHEN T1.is_prebiotic = TRUE THEN T1.id ELSE NULL END),
                COUNT(DISTINCT CASE WHEN T1.is_probiotic = TRUE THEN T1.id ELSE NULL END)
            FROM user_food_logs AS T2
            INNER JOIN foods AS T1
            ON T1.id = T2.food_id
            WHERE T2.user_id = %s AND T2.date_consumed BETWEEN %s AND %s;
            """,
            (current_user_id, start_of_week, end_of_week)
        )
        metrics = cur.fetchone()
        prebiotic_count = metrics[0]
        probiotic_count = metrics[1]

        return jsonify({
            'prebiotic_count': prebiotic_count,
            'probiotic_count': probiotic_count
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/suggested_foods', methods=['GET'])
@token_required
def get_suggested_foods(current_user_id):
    """Retrieves a list of foods not consumed by the user this week."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        # Get the start and end of the current week
        today = datetime.date.today()
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        # SQL query to get foods not consumed this week
        cur.execute(
            """
            SELECT T1.id, T1.name, T1.is_vegetable_for_challenge, T1.is_prebiotic, T1.is_probiotic
            FROM foods AS T1
            WHERE T1.id NOT IN (
                SELECT T2.food_id FROM user_food_logs AS T2
                WHERE T2.user_id = %s
                AND T2.date_consumed BETWEEN %s AND %s
            );
            """,
            (current_user_id, start_of_week, end_of_week)
        )
        suggested_foods = cur.fetchall()
        
        suggested_list = []
        for food in suggested_foods:
            suggested_list.append({
                'id': food[0],
                'name': food[1],
                'is_vegetable_for_challenge': food[2],
                'is_prebiotic': food[3],
                'is_probiotic': food[4]
            })
        return jsonify(suggested_list), 200
    except psycopg2.Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/user_vegetables', methods=['GET'])
@token_required
def get_user_vegetables(current_user_id):
    """Retrieves the list of unique vegetables consumed by the user this week."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Get the start and end of the current week
        today = datetime.date.today()
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        cur.execute(
            """
            SELECT DISTINCT T1.name
            FROM foods AS T1
            INNER JOIN user_food_logs AS T2
            ON T1.id = T2.food_id
            WHERE T2.user_id = %s
            AND T1.is_vegetable_for_challenge = TRUE
            AND T2.date_consumed BETWEEN %s AND %s;
            """,
            (current_user_id, start_of_week, end_of_week)
        )
        vegetables = cur.fetchall()
        
        vegetables_list = [v[0] for v in vegetables]
        return jsonify(vegetables_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/user_prebiotics', methods=['GET'])
@token_required
def get_user_prebiotics(current_user_id):
    """Retrieves the list of unique prebiotics consumed by the user this week."""
    conn = get_db_connection()
    cur = conn.cursor()

    try:
        today = datetime.date.today()
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        cur.execute(
            """
            SELECT DISTINCT T1.name
            FROM foods AS T1
            INNER JOIN user_food_logs AS T2
            ON T1.id = T2.food_id
            WHERE T2.user_id = %s
            AND T1.is_prebiotic = TRUE
            AND T2.date_consumed BETWEEN %s AND %s;
            """,
            (current_user_id, start_of_week, end_of_week)
        )
        prebiotics = cur.fetchall()

        prebiotics_list = [p[0] for p in prebiotics]
        return jsonify(prebiotics_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()


@app.route('/api/user_probiotics', methods=['GET'])
@token_required
def get_user_probiotics(current_user_id):
    """Retrieves the list of unique probiotics consumed by the user this week."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        today = datetime.date.today()
        start_of_week = today - datetime.timedelta(days=today.weekday())
        end_of_week = start_of_week + datetime.timedelta(days=6)

        cur.execute(
            """
            SELECT DISTINCT T1.name
            FROM foods AS T1
            INNER JOIN user_food_logs AS T2
            ON T1.id = T2.food_id
            WHERE T2.user_id = %s
            AND T1.is_probiotic = TRUE
            AND T2.date_consumed BETWEEN %s AND %s;
            """,
            (current_user_id, start_of_week, end_of_week)
        )
        probiotics = cur.fetchall()
        
        probiotics_list = [p[0] for p in probiotics]
        return jsonify(probiotics_list), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

# --- EJECUTAR EL SERVIDOR ---

if __name__ == '__main__':
    # Esta línea solo se usa para pruebas locales. 
    # En producción (Render), se usa Gunicorn.
    app.run(debug=True)
