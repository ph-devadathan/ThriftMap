from flask import Flask, render_template, request, redirect, url_for, flash, session
import re
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

app = Flask(__name__)
app.secret_key = 'thriftmap_dev_secret_key_2026'

def get_db_connection():
    """Create and return a new MySQL database connection."""
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

# Test database connection
try:
    db = get_db_connection()
    print("Database Connected Successfully")
except Exception as e:
    print("Database Connection Failed")
    print(e)

@app.route('/')
def home():
    """Home page route for ThriftMap displaying hero, categories, and featured approved stores."""
    conn = None
    cursor = None
    featured_stores = []
    categories = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Fetch categories
        cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name ASC")
        categories = cursor.fetchall()

        # Fetch featured approved stores (strictly status = 'approved')
        query = """
            SELECT 
                s.store_id,
                s.store_name,
                s.category_id,
                s.description,
                s.city,
                s.image,
                s.status,
                c.category_name
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.status = 'approved'
            ORDER BY s.created_at DESC
            LIMIT 6
        """
        cursor.execute(query)
        featured_stores = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching home page data: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template('index.html', stores=featured_stores, categories=categories)

@app.route('/stores')
def stores():
    """Public store directory listing approved stores with search and category filtering."""
    search_query = request.args.get('search', '').strip()
    city_filter = request.args.get('city', '').strip()
    category_filter = request.args.get('category', '').strip()

    conn = None
    cursor = None
    stores_list = []
    categories = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch all categories for filter options
        cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name ASC")
        categories = cursor.fetchall()

        # Parameterized query - strictly ONLY approved stores
        base_query = """
            SELECT 
                s.store_id,
                s.store_name,
                s.category_id,
                s.description,
                s.city,
                s.image,
                s.status,
                s.created_at,
                c.category_name
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.status = 'approved'
        """
        params = []

        # Search by Store Name and/or City
        if search_query:
            base_query += " AND (s.store_name LIKE %s OR s.city LIKE %s)"
            params.extend([f"%{search_query}%", f"%{search_query}%"])

        # Specific city filter if passed
        if city_filter:
            base_query += " AND s.city LIKE %s"
            params.append(f"%{city_filter}%")

        # Filter by Category
        if category_filter:
            if category_filter.isdigit():
                base_query += " AND s.category_id = %s"
                params.append(int(category_filter))
            else:
                base_query += " AND c.category_name = %s"
                params.append(category_filter)

        base_query += " ORDER BY s.created_at DESC"
        cursor.execute(base_query, tuple(params))
        stores_list = cursor.fetchall()

    except Exception as e:
        print(f"Error fetching stores: {e}")
        flash("An error occurred while loading stores.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'stores.html',
        stores=stores_list,
        categories=categories,
        search_query=search_query,
        city_filter=city_filter,
        category_filter=category_filter,
        total_stores=len(stores_list)
    )

@app.route('/store/<int:store_id>')
def store_details(store_id):
    """Public route gated behind login to view complete store details."""
    # 1. Login Gating Check: If user is not logged in, redirect to login with flash
    if 'user_id' not in session:
        flash("Please login to view complete store information.", 'warning')
        return redirect(url_for('login'))

    # 2. Fetch store details joining users and categories
    conn = None
    cursor = None
    store = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT 
                s.store_id,
                s.owner_id,
                s.category_id,
                s.store_name,
                s.description,
                s.address,
                s.city,
                s.contact_number,
                s.opening_hours,
                s.latitude,
                s.longitude,
                s.image,
                s.status,
                s.created_at,
                u.full_name AS owner_name,
                c.category_name
            FROM stores s
            JOIN users u ON s.owner_id = u.user_id
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.store_id = %s
        """
        cursor.execute(query, (store_id,))
        store = cursor.fetchone()
    except Exception as e:
        print(f"Error fetching store details: {e}")
        flash("An error occurred while loading store details.", 'danger')
        return redirect(url_for('stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # 3. Only approved stores can be viewed. If store is pending or non-existent: Return 404
    if not store or store['status'] != 'approved':
        return render_template('404.html'), 404

    return render_template(
        'store_details.html',
        store=store,
        full_name=session.get('full_name'),
        role=session.get('role')
    )

@app.errorhandler(404)
def page_not_found(e):
    """Render 404 page for non-existent or inaccessible pages."""
    return render_template('404.html'), 404

@app.route('/register', methods=['GET', 'POST'])
def register():
    """User registration route with field validation and database persistence."""
    if request.method == 'POST':
        print("Registration started")
        fullname = request.form.get('fullname', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        role = request.form.get('role', '').strip()

        # Server-side validation for required fields
        errors = []
        if not fullname:
            errors.append("Full Name is required.")
        elif len(fullname) < 2:
            errors.append("Full Name must be at least 2 characters.")

        if not email:
            errors.append("Email address is required.")
        elif not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors.append("Please enter a valid email address.")

        if not password:
            errors.append("Password is required.")
        elif len(password) < 6:
            errors.append("Password must be at least 6 characters long.")

        valid_roles = ["user", "owner"]
        if not role:
            errors.append("Please select a role (User or Store Owner).")
        elif role not in valid_roles:
            errors.append("Invalid role selected. Must be User or Store Owner.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            return render_template('register.html', fullname=fullname, email=email, role=role), 400

        # Insert user into MySQL database table users
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            query = "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, %s)"
            cursor.execute(query, (fullname, email, password, role))
            conn.commit()
            print("User inserted successfully")
        except mysql.connector.Error as e:
            print(f"Database error: {e}")
            if conn:
                conn.rollback()
            if e.errno == 1062:
                flash("An account with this email address already exists.", 'danger')
            else:
                flash("Database error occurred while registering.", 'danger')
            return render_template('register.html', fullname=fullname, email=email, role=role), 400
        except Exception as e:
            print(f"Database error: {e}")
            if conn:
                conn.rollback()
            flash("An unexpected database error occurred. Please try again.", 'danger')
            return render_template('register.html', fullname=fullname, email=email, role=role), 500
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

        flash(f"Registration successful! Welcome to ThriftMap, {fullname} ({role}).", 'success')
        return render_template('register.html', success=True, registered_user={'fullname': fullname, 'role': role})

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """User authentication route with role-based dashboard redirection."""
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        # Validate required fields
        if not email or not password:
            if not email:
                flash("Email address is required.", 'danger')
            if not password:
                flash("Password is required.", 'danger')
            return render_template('login.html', email=email), 400

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            query = "SELECT user_id, full_name, email, password, role FROM users WHERE email = %s"
            cursor.execute(query, (email,))
            user = cursor.fetchone()

            # Verify user exists
            if not user:
                flash("No account found with this email address.", 'danger')
                return render_template('login.html', email=email), 400

            # Verify password
            if user['password'] != password:
                flash("Incorrect password.", 'danger')
                return render_template('login.html', email=email), 400

            # Set session variables
            session['user_id'] = user['user_id']
            session['full_name'] = user['full_name']
            session['role'] = user['role']

            flash(f"Welcome back, {user['full_name']}!", 'success')

            # Redirect based on user role
            role = user['role']
            if role == 'owner':
                return redirect(url_for('owner_dashboard'))
            elif role == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('user_dashboard'))

        except mysql.connector.Error as e:
            print(f"Database error during login: {e}")
            flash("Database error occurred while logging in. Please try again.", 'danger')
            return render_template('login.html', email=email), 500
        except Exception as e:
            print(f"Unexpected error during login: {e}")
            flash("An unexpected error occurred. Please try again.", 'danger')
            return render_template('login.html', email=email), 500
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    return render_template('login.html')

@app.route('/user-dashboard')
def user_dashboard():
    """User dashboard route protected by role-based access control."""
    if 'user_id' not in session:
        flash("Please log in to access your dashboard.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'user':
        flash("Access denied. You do not have permission to access the User Dashboard.", 'danger')
        if user_role == 'owner':
            return redirect(url_for('owner_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    return render_template('user_dashboard.html', full_name=session.get('full_name'), role=user_role)

@app.route('/owner-dashboard')
def owner_dashboard():
    """Owner dashboard route protected by role-based access control."""
    if 'user_id' not in session:
        flash("Please log in to access your dashboard.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'owner':
        flash("Access denied. You do not have permission to access the Owner Dashboard.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    return render_template('owner_dashboard.html', full_name=session.get('full_name'), role=user_role)

@app.route('/add-store', methods=['GET', 'POST'])
def add_store():
    """Route for store owners to register a new store listing."""
    # 1. Access Control: Must be logged in
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    # 2. Access Control: Must be store owner
    user_role = session.get('role')
    if user_role != 'owner':
        flash("Access denied. Only store owners can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    def fetch_categories():
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_id ASC")
            return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching categories: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    if request.method == 'POST':
        store_name = request.form.get('store_name', '').strip()
        category_id_raw = request.form.get('category_id', '').strip()
        description = request.form.get('description', '').strip()
        address = request.form.get('address', '').strip()
        city = request.form.get('city', '').strip()
        contact_number = request.form.get('contact_number', '').strip()
        opening_hours = request.form.get('opening_hours', '').strip() or None
        latitude_raw = request.form.get('latitude', '').strip()
        longitude_raw = request.form.get('longitude', '').strip()

        # Validation
        errors = []
        if not store_name:
            errors.append("Store Name is required.")
        elif len(store_name) > 150:
            errors.append("Store Name cannot exceed 150 characters.")

        category_id = None
        if not category_id_raw:
            errors.append("Category is required.")
        else:
            try:
                category_id = int(category_id_raw)
            except ValueError:
                errors.append("Invalid category selected.")

        if not description:
            errors.append("Description is required.")

        if not address:
            errors.append("Address is required.")

        if not city:
            errors.append("City is required.")
        elif len(city) > 100:
            errors.append("City cannot exceed 100 characters.")

        if not contact_number:
            errors.append("Contact Number is required.")
        elif len(contact_number) > 20:
            errors.append("Contact Number cannot exceed 20 characters.")

        latitude = None
        if latitude_raw:
            try:
                latitude = float(latitude_raw)
            except ValueError:
                errors.append("Latitude must be a valid decimal number.")

        longitude = None
        if longitude_raw:
            try:
                longitude = float(longitude_raw)
            except ValueError:
                errors.append("Longitude must be a valid decimal number.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            categories = fetch_categories()
            return render_template(
                'add_store.html',
                categories=categories,
                store_name=store_name,
                selected_category=category_id_raw,
                description=description,
                address=address,
                city=city,
                contact_number=contact_number,
                opening_hours=opening_hours or '',
                latitude=latitude_raw,
                longitude=longitude_raw
            ), 400

        # owner_id strictly from session
        owner_id = session.get('user_id')
        status = 'pending'
        image = None

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            query = """
                INSERT INTO stores (
                    owner_id, category_id, store_name, description,
                    address, city, contact_number, opening_hours,
                    latitude, longitude, image, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (
                owner_id, category_id, store_name, description,
                address, city, contact_number, opening_hours,
                latitude, longitude, image, status
            ))
            conn.commit()

            flash("Store submitted successfully and is awaiting admin approval.", 'success')
            return redirect(url_for('owner_dashboard'))

        except mysql.connector.Error as e:
            print(f"Database error while adding store: {e}")
            if conn:
                conn.rollback()
            flash("Database error occurred while submitting your store. Please try again.", 'danger')
            categories = fetch_categories()
            return render_template(
                'add_store.html',
                categories=categories,
                store_name=store_name,
                selected_category=category_id_raw,
                description=description,
                address=address,
                city=city,
                contact_number=contact_number,
                opening_hours=opening_hours or '',
                latitude=latitude_raw,
                longitude=longitude_raw
            ), 500
        except Exception as e:
            print(f"Unexpected error while adding store: {e}")
            if conn:
                conn.rollback()
            flash("An unexpected error occurred. Please try again.", 'danger')
            categories = fetch_categories()
            return render_template('add_store.html', categories=categories), 500
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # GET request
    categories = fetch_categories()
    return render_template('add_store.html', categories=categories)

@app.route('/manage-stores')
def manage_stores():
    """Route for store owners to view and manage their store listings."""
    # 1. Access Control: Must be logged in
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    # 2. Access Control: Must be store owner
    user_role = session.get('role')
    if user_role != 'owner':
        flash("Access denied. Only store owners can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    owner_id = session.get('user_id')
    conn = None
    cursor = None
    stores = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT 
                s.store_id,
                s.owner_id,
                s.category_id,
                s.store_name,
                s.description,
                s.address,
                s.city,
                s.contact_number,
                s.opening_hours,
                s.latitude,
                s.longitude,
                s.image,
                s.status,
                s.created_at,
                c.category_name
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.owner_id = %s
            ORDER BY s.created_at DESC
        """
        cursor.execute(query, (owner_id,))
        stores = cursor.fetchall()
    except mysql.connector.Error as e:
        print(f"Database error while fetching owner stores: {e}")
        flash("Database error occurred while retrieving stores.", 'danger')
    except Exception as e:
        print(f"Unexpected error while fetching owner stores: {e}")
        flash("An unexpected error occurred. Please try again.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template('manage_stores.html', stores=stores, full_name=session.get('full_name'), role=user_role)

@app.route('/edit-store/<int:store_id>', methods=['GET', 'POST'])
def edit_store(store_id):
    """Route for store owners to edit their existing store listing."""
    # 1. Access Control: Must be logged in
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    # 2. Access Control: Must be store owner
    user_role = session.get('role')
    if user_role != 'owner':
        flash("Access denied. Only store owners can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    owner_id = session.get('user_id')

    def fetch_categories():
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_id ASC")
            return cursor.fetchall()
        except Exception as e:
            print(f"Error fetching categories: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # 3. Security: Check store existence and ownership
    conn = None
    cursor = None
    store = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM stores WHERE store_id = %s", (store_id,))
        store = cursor.fetchone()
    except Exception as e:
        print(f"Database error checking store: {e}")
        flash("Database error occurred while fetching store.", 'danger')
        return redirect(url_for('manage_stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    if not store:
        flash("Store not found.", 'danger')
        return redirect(url_for('manage_stores'))

    # Rule 8: Owner can edit only their own stores
    if store['owner_id'] != owner_id:
        flash("Access denied. You do not have permission to edit this store.", 'danger')
        return redirect(url_for('manage_stores'))

    if request.method == 'POST':
        store_name = request.form.get('store_name', '').strip()
        category_id_raw = request.form.get('category_id', '').strip()
        description = request.form.get('description', '').strip()
        address = request.form.get('address', '').strip()
        city = request.form.get('city', '').strip()
        contact_number = request.form.get('contact_number', '').strip()
        opening_hours = request.form.get('opening_hours', '').strip() or None
        latitude_raw = request.form.get('latitude', '').strip()
        longitude_raw = request.form.get('longitude', '').strip()
        image = request.form.get('image', '').strip() or store.get('image') or None

        # Validation
        errors = []
        if not store_name:
            errors.append("Store Name is required.")
        elif len(store_name) > 150:
            errors.append("Store Name cannot exceed 150 characters.")

        category_id = None
        if not category_id_raw:
            errors.append("Category is required.")
        else:
            try:
                category_id = int(category_id_raw)
            except ValueError:
                errors.append("Invalid category selected.")

        if not description:
            errors.append("Description is required.")

        if not address:
            errors.append("Address is required.")

        if not city:
            errors.append("City is required.")
        elif len(city) > 100:
            errors.append("City cannot exceed 100 characters.")

        if not contact_number:
            errors.append("Contact Number is required.")
        elif len(contact_number) > 20:
            errors.append("Contact Number cannot exceed 20 characters.")

        latitude = None
        if latitude_raw:
            try:
                latitude = float(latitude_raw)
            except ValueError:
                errors.append("Latitude must be a valid decimal number.")

        longitude = None
        if longitude_raw:
            try:
                longitude = float(longitude_raw)
            except ValueError:
                errors.append("Longitude must be a valid decimal number.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            categories = fetch_categories()
            form_store = dict(store)
            form_store.update({
                'store_name': store_name,
                'category_id': category_id_raw,
                'description': description,
                'address': address,
                'city': city,
                'contact_number': contact_number,
                'opening_hours': opening_hours or '',
                'latitude': latitude_raw,
                'longitude': longitude_raw,
                'image': image
            })
            return render_template('edit_store.html', store=form_store, categories=categories), 400

        # Update database with editable fields strictly excluding store_id, owner_id, status, created_at
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            update_query = """
                UPDATE stores SET
                    category_id = %s,
                    store_name = %s,
                    description = %s,
                    address = %s,
                    city = %s,
                    contact_number = %s,
                    opening_hours = %s,
                    latitude = %s,
                    longitude = %s,
                    image = %s
                WHERE store_id = %s AND owner_id = %s
            """
            cursor.execute(update_query, (
                category_id, store_name, description,
                address, city, contact_number, opening_hours,
                latitude, longitude, image,
                store_id, owner_id
            ))
            conn.commit()

            flash("Store updated successfully.", 'success')
            return redirect(url_for('manage_stores'))

        except mysql.connector.Error as e:
            print(f"Database error while updating store: {e}")
            if conn:
                conn.rollback()
            flash("Database error occurred while updating store. Please try again.", 'danger')
            categories = fetch_categories()
            return render_template('edit_store.html', store=store, categories=categories), 500
        except Exception as e:
            print(f"Unexpected error while updating store: {e}")
            if conn:
                conn.rollback()
            flash("An unexpected error occurred. Please try again.", 'danger')
            categories = fetch_categories()
            return render_template('edit_store.html', store=store, categories=categories), 500
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    # GET request
    categories = fetch_categories()
    return render_template('edit_store.html', store=store, categories=categories)

@app.route('/delete-store/<int:store_id>', methods=['GET', 'POST'])
def delete_store(store_id):
    """Route for store owners to delete their own store."""
    # 1. Access Control: Must be logged in
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    # 2. Access Control: Must be store owner
    user_role = session.get('role')
    if user_role != 'owner':
        flash("Access denied. Only store owners can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    owner_id = session.get('user_id')

    # Security: Verify store existence and ownership
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT store_id, owner_id, store_name FROM stores WHERE store_id = %s", (store_id,))
        store = cursor.fetchone()

        if not store:
            flash("Store not found.", 'danger')
            return redirect(url_for('manage_stores'))

        # Rule 10: Owner can delete only their own stores
        if store['owner_id'] != owner_id:
            flash("Access denied. You do not have permission to delete this store.", 'danger')
            return redirect(url_for('manage_stores'))

        # Delete any associated reviews first, then the store
        cursor.execute("DELETE FROM reviews WHERE store_id = %s", (store_id,))
        delete_query = "DELETE FROM stores WHERE store_id = %s AND owner_id = %s"
        cursor.execute(delete_query, (store_id, owner_id))
        conn.commit()

        flash("Store deleted successfully.", 'success')
        return redirect(url_for('manage_stores'))

    except mysql.connector.Error as e:
        print(f"Database error while deleting store: {e}")
        if conn:
            conn.rollback()
        flash("Database error occurred while deleting store. Please try again.", 'danger')
        return redirect(url_for('manage_stores'))
    except Exception as e:
        print(f"Unexpected error while deleting store: {e}")
        if conn:
            conn.rollback()
        flash("An unexpected error occurred. Please try again.", 'danger')
        return redirect(url_for('manage_stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/view-store/<int:store_id>')
def view_store(store_id):
    """Route for store owners to view store details."""
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'owner':
        flash("Access denied. Only store owners can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    owner_id = session.get('user_id')
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT store_id, owner_id FROM stores WHERE store_id = %s", (store_id,))
        store = cursor.fetchone()

        if not store:
            flash("Store not found.", 'danger')
            return redirect(url_for('manage_stores'))

        if store['owner_id'] != owner_id:
            flash("Access denied. You do not have permission to view this store.", 'danger')
            return redirect(url_for('manage_stores'))

        return redirect(url_for('manage_stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/admin-dashboard')
def admin_dashboard():
    """Admin dashboard route protected by role-based access control with live store metrics."""
    if 'user_id' not in session:
        flash("Please log in to access your dashboard.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. You do not have permission to access the Admin Dashboard.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'owner':
            return redirect(url_for('owner_dashboard'))
        return redirect(url_for('login'))

    conn = None
    cursor = None
    total_stores = 0
    pending_stores = 0
    approved_stores = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                COUNT(*) AS total_stores,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_stores,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_stores
            FROM stores
        """)
        stats = cursor.fetchone()
        if stats:
            total_stores = stats.get('total_stores') or 0
            pending_stores = int(stats.get('pending_stores') or 0)
            approved_stores = int(stats.get('approved_stores') or 0)
    except Exception as e:
        print(f"Error fetching admin store statistics: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'admin_dashboard.html',
        full_name=session.get('full_name'),
        role=user_role,
        total_stores=total_stores,
        pending_stores=pending_stores,
        approved_stores=approved_stores
    )

@app.route('/admin/stores')
def admin_stores():
    """Admin store management route with status filtering and category/owner JOINs."""
    # 1. Access Control: Must be logged in
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    # 2. Access Control: Must be admin
    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. Only administrators can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'owner':
            return redirect(url_for('owner_dashboard'))
        return redirect(url_for('login'))

    status_filter = request.args.get('status', '').strip().lower()
    if status_filter not in ['pending', 'approved']:
        status_filter = ''

    conn = None
    cursor = None
    stores = []
    counts = {'all': 0, 'pending': 0, 'approved': 0}
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Tab counts
        cursor.execute("""
            SELECT 
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_count
            FROM stores
        """)
        count_row = cursor.fetchone()
        if count_row:
            counts['all'] = count_row.get('total') or 0
            counts['pending'] = int(count_row.get('pending_count') or 0)
            counts['approved'] = int(count_row.get('approved_count') or 0)

        # Query all stores using JOIN with users and categories
        base_query = """
            SELECT 
                s.store_id,
                s.owner_id,
                s.category_id,
                s.store_name,
                s.description,
                s.address,
                s.city,
                s.contact_number,
                s.opening_hours,
                s.latitude,
                s.longitude,
                s.image,
                s.status,
                s.created_at,
                u.full_name AS owner_name,
                u.email AS owner_email,
                c.category_name
            FROM stores s
            JOIN users u ON s.owner_id = u.user_id
            JOIN categories c ON s.category_id = c.category_id
        """

        if status_filter:
            query = base_query + " WHERE s.status = %s ORDER BY s.created_at DESC"
            cursor.execute(query, (status_filter,))
        else:
            query = base_query + " ORDER BY s.created_at DESC"
            cursor.execute(query)

        stores = cursor.fetchall()

    except mysql.connector.Error as e:
        print(f"Database error in admin_stores: {e}")
        flash("Database error occurred while retrieving stores.", 'danger')
    except Exception as e:
        print(f"Unexpected error in admin_stores: {e}")
        flash("An unexpected error occurred. Please try again.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'admin_stores.html',
        stores=stores,
        status_filter=status_filter,
        counts=counts,
        full_name=session.get('full_name'),
        role=user_role
    )

@app.route('/admin/store/<int:store_id>')
def admin_store_details(store_id):
    """Admin store details route showing complete store, category, and owner information."""
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. Only administrators can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'owner':
            return redirect(url_for('owner_dashboard'))
        return redirect(url_for('login'))

    conn = None
    cursor = None
    store = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT 
                s.store_id,
                s.owner_id,
                s.category_id,
                s.store_name,
                s.description,
                s.address,
                s.city,
                s.contact_number,
                s.opening_hours,
                s.latitude,
                s.longitude,
                s.image,
                s.status,
                s.created_at,
                u.full_name AS owner_name,
                u.email AS owner_email,
                c.category_name
            FROM stores s
            JOIN users u ON s.owner_id = u.user_id
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.store_id = %s
        """
        cursor.execute(query, (store_id,))
        store = cursor.fetchone()
    except Exception as e:
        print(f"Error fetching store details: {e}")
        flash("An error occurred while loading store details.", 'danger')
        return redirect(url_for('admin_stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    if not store:
        flash("Store not found.", 'danger')
        return redirect(url_for('admin_stores'))

    return render_template(
        'admin_store_details.html',
        store=store,
        full_name=session.get('full_name'),
        role=user_role
    )

@app.route('/admin/store/<int:store_id>/approve', methods=['POST'])
def admin_approve_store(store_id):
    """Admin route to approve a pending store."""
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. Only administrators can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'owner':
            return redirect(url_for('owner_dashboard'))
        return redirect(url_for('login'))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Validate store exists
        cursor.execute("SELECT store_id, status FROM stores WHERE store_id = %s", (store_id,))
        store = cursor.fetchone()
        if not store:
            flash("Store not found.", 'danger')
            return redirect(url_for('admin_stores'))

        cursor.execute("UPDATE stores SET status = 'approved' WHERE store_id = %s", (store_id,))
        conn.commit()

        flash("Store approved successfully.", 'success')
        return redirect(url_for('admin_stores'))

    except mysql.connector.Error as e:
        print(f"Database error approving store: {e}")
        if conn:
            conn.rollback()
        flash("Database error occurred while approving store. Please try again.", 'danger')
        return redirect(url_for('admin_stores'))
    except Exception as e:
        print(f"Unexpected error approving store: {e}")
        if conn:
            conn.rollback()
        flash("An unexpected error occurred. Please try again.", 'danger')
        return redirect(url_for('admin_stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/admin/store/<int:store_id>/reject', methods=['POST'])
def admin_reject_store(store_id):
    """Admin route to reject and delete a store."""
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. Only administrators can access this page.", 'danger')
        if user_role == 'user':
            return redirect(url_for('user_dashboard'))
        elif user_role == 'owner':
            return redirect(url_for('owner_dashboard'))
        return redirect(url_for('login'))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Validate store exists
        cursor.execute("SELECT store_id, status FROM stores WHERE store_id = %s", (store_id,))
        store = cursor.fetchone()
        if not store:
            flash("Store not found.", 'danger')
            return redirect(url_for('admin_stores'))

        # Delete related reviews first if any, then delete store
        cursor.execute("DELETE FROM reviews WHERE store_id = %s", (store_id,))
        cursor.execute("DELETE FROM stores WHERE store_id = %s", (store_id,))
        conn.commit()

        flash("Store rejected successfully.", 'success')
        return redirect(url_for('admin_stores'))

    except mysql.connector.Error as e:
        print(f"Database error rejecting store: {e}")
        if conn:
            conn.rollback()
        flash("Database error occurred while rejecting store. Please try again.", 'danger')
        return redirect(url_for('admin_stores'))
    except Exception as e:
        print(f"Unexpected error rejecting store: {e}")
        if conn:
            conn.rollback()
        flash("An unexpected error occurred. Please try again.", 'danger')
        return redirect(url_for('admin_stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/logout')
def logout():
    """Clear session and log out the user."""
    session.clear()
    flash("You have been logged out successfully.", 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)