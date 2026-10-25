import os
import time
import uuid
import re
import math
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, jsonify
from werkzeug.utils import secure_filename
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME
from recommendation_engine import HybridRecommendationEngine

app = Flask(__name__)
app.secret_key = 'thriftmap_dev_secret_key_2026'

# Upload configuration
UPLOAD_FOLDER = os.path.join(app.root_path, 'static', 'uploads', 'stores')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max upload size
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Check if the filename has an allowed extension (JPG, JPEG, PNG, WebP)."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_and_save_image(file_storage):
    """
    Validate uploaded image type and size, generate safe unique filename,
    and save file to static/uploads/stores.
    Returns: (relative_path_for_db, error_message, saved_abs_path)
    """
    if not file_storage or file_storage.filename == '':
        return None, None, None

    filename = secure_filename(file_storage.filename)
    if not filename or not allowed_file(filename):
        return None, "Invalid image format. Supported formats are JPG, JPEG, PNG, and WebP.", None

    # Check file size (max 5 MB)
    file_storage.seek(0, os.SEEK_END)
    size_bytes = file_storage.tell()
    file_storage.seek(0)
    if size_bytes > 5 * 1024 * 1024:
        return None, "Image file size exceeds the 5 MB limit.", None

    # Generate unique safe filename
    ext = filename.rsplit('.', 1)[1].lower()
    unique_filename = f"store_{uuid.uuid4().hex[:12]}_{int(time.time())}.{ext}"
    abs_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)

    try:
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        file_storage.save(abs_path)
    except Exception as e:
        print(f"Error saving uploaded file: {e}")
        return None, "Server error occurred while saving the uploaded image.", None

    # Relative path stored in database: uploads/stores/<filename>
    rel_path = f"uploads/stores/{unique_filename}"
    return rel_path, None, abs_path

@app.template_filter('store_image_url')
def store_image_url(image_path):
    """Template filter to return the correct public static URL or placeholder for a store image."""
    if not image_path:
        return url_for('static', filename='images/store-placeholder.svg')
    if image_path.startswith(('http://', 'https://', '/static/')):
        return image_path
    if image_path.startswith('static/'):
        return url_for('static', filename=image_path[7:])
    return url_for('static', filename=image_path)

@app.errorhandler(413)
def request_entity_too_large(error):
    flash("Uploaded file is too large. Maximum file size allowed is 5 MB.", "danger")
    return redirect(request.url or url_for('owner_dashboard'))

def is_valid_coordinate(lat, lng):
    """
    Validate latitude and longitude values server-side.
    Latitude must be between -90 and 90.
    Longitude must be between -180 and 180.
    Returns True if both are valid numbers within range, False otherwise.
    """
    if lat is None or lng is None:
        return False
    try:
        lat_f = float(lat)
        lng_f = float(lng)
        import math
        if math.isnan(lat_f) or math.isinf(lat_f) or math.isnan(lng_f) or math.isinf(lng_f):
            return False
        return (-90.0 <= lat_f <= 90.0) and (-180.0 <= lng_f <= 180.0)
    except (ValueError, TypeError):
        return False

# India geographic boundaries (mainland, Andaman & Nicobar, Lakshadweep)
INDIA_LAT_MIN = 6.0
INDIA_LAT_MAX = 38.0
INDIA_LNG_MIN = 68.0
INDIA_LNG_MAX = 98.0

def is_in_india(lat, lng):
    """
    Check if the given coordinates fall within the geographic boundaries of India,
    accounting for India's mainland and island territories.
    """
    if not is_valid_coordinate(lat, lng):
        return False
    lat_f = float(lat)
    lng_f = float(lng)
    return (INDIA_LAT_MIN <= lat_f <= INDIA_LAT_MAX) and (INDIA_LNG_MIN <= lng_f <= INDIA_LNG_MAX)

def get_db_connection():
    """Create and return a new MySQL database connection."""
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

def ensure_schema_compatibility():
    """Ensure database has required columns without modifying existing records."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SHOW COLUMNS FROM users LIKE 'status'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE users ADD COLUMN status ENUM('active', 'inactive') NOT NULL DEFAULT 'active' AFTER role")
            conn.commit()
            print("Added 'status' column to users table.")
    except Exception as e:
        print(f"Schema compatibility check: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

# Test database connection
try:
    db = get_db_connection()
    print("Database Connected Successfully")
    ensure_schema_compatibility()
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

        # Fetch featured approved stores in India with valid coordinates
        query = """
            SELECT 
                s.store_id,
                s.store_name,
                s.category_id,
                s.description,
                s.city,
                s.latitude,
                s.longitude,
                s.image,
                s.status,
                c.category_name
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.status = 'approved'
              AND s.latitude IS NOT NULL
              AND s.longitude IS NOT NULL
              AND s.latitude BETWEEN %s AND %s
              AND s.longitude BETWEEN %s AND %s
            ORDER BY s.created_at DESC
        """
        cursor.execute(query, (INDIA_LAT_MIN, INDIA_LAT_MAX, INDIA_LNG_MIN, INDIA_LNG_MAX))
        raw_featured = cursor.fetchall()
        featured_stores = [s for s in raw_featured if is_in_india(s.get('latitude'), s.get('longitude'))]
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

        # Parameterized query - strictly ONLY approved stores located within India
        base_query = """
            SELECT 
                s.store_id,
                s.store_name,
                s.category_id,
                s.description,
                s.city,
                s.latitude,
                s.longitude,
                s.image,
                s.status,
                s.created_at,
                c.category_name
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.status = 'approved'
              AND s.latitude IS NOT NULL
              AND s.longitude IS NOT NULL
              AND s.latitude BETWEEN %s AND %s
              AND s.longitude BETWEEN %s AND %s
        """
        params = [INDIA_LAT_MIN, INDIA_LAT_MAX, INDIA_LNG_MIN, INDIA_LNG_MAX]

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
        raw_stores = cursor.fetchall()
        stores_list = [s for s in raw_stores if is_in_india(s.get('latitude'), s.get('longitude'))]

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

@app.route('/map')
def store_map():
    """
    Public interactive map route displaying approved stores in India with Leaflet.js 1.9.4 and OpenStreetMap.
    Supports filtering by search query (name/city), specific city, and category.
    Strictly queries status = 'approved' stores with valid coordinates located within India.
    Stores without coordinates or outside India are excluded from public India discovery.
    Accessible to both guests and authenticated users.
    """
    search_query = request.args.get('search', '').strip()
    city_filter = request.args.get('city', '').strip()
    category_filter = request.args.get('category', '').strip()

    conn = None
    cursor = None
    categories = []
    mapped_stores = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Fetch all categories for filter options
        cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name ASC")
        categories = cursor.fetchall()

        # Parameterized query - strictly ONLY approved stores within India's boundary
        base_query = """
            SELECT 
                s.store_id,
                s.store_name,
                s.category_id,
                s.address,
                s.city,
                s.latitude,
                s.longitude,
                s.image,
                c.category_name
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.status = 'approved'
              AND s.latitude IS NOT NULL
              AND s.longitude IS NOT NULL
              AND s.latitude BETWEEN %s AND %s
              AND s.longitude BETWEEN %s AND %s
        """
        params = [INDIA_LAT_MIN, INDIA_LAT_MAX, INDIA_LNG_MIN, INDIA_LNG_MAX]

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

        base_query += " ORDER BY s.store_name ASC"
        cursor.execute(base_query, tuple(params))
        all_stores = cursor.fetchall()

        for s in all_stores:
            lat = s.get('latitude')
            lng = s.get('longitude')

            if is_in_india(lat, lng):
                store_item = {
                    'store_id': s['store_id'],
                    'store_name': s['store_name'],
                    'category_name': s['category_name'],
                    'category_id': s['category_id'],
                    'city': s['city'],
                    'address': s['address'],
                    'image': s.get('image'),
                    'image_url': store_image_url(s.get('image')),
                    'details_url': url_for('store_details', store_id=s['store_id']),
                    'latitude': float(lat),
                    'longitude': float(lng)
                }
                mapped_stores.append(store_item)

    except Exception as e:
        print(f"Error loading map stores: {e}")
        flash("An error occurred while loading store locations.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'map.html',
        mapped_stores=mapped_stores,
        categories=categories,
        search_query=search_query,
        city_filter=city_filter,
        category_filter=category_filter,
        total_mapped=len(mapped_stores),
        total_stores=len(mapped_stores)
    )

def get_store_details_data(store_id):
    """
    Fetch complete store information, approved status, customer reviews with author info,
    average rating, star breakdown, and current user's review state.
    Returns: (store, reviews, avg_rating, total_reviews, rating_counts, user_review)
    """
    conn = None
    cursor = None
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
        if not store or store['status'] != 'approved':
            return None, [], None, 0, {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}, None

        reviews_query = """
            SELECT 
                r.review_id,
                r.store_id,
                r.user_id,
                r.rating,
                r.comment,
                r.created_at,
                u.full_name AS author_name,
                u.role AS author_role
            FROM reviews r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.store_id = %s
            ORDER BY r.created_at DESC, r.review_id DESC
        """
        cursor.execute(reviews_query, (store_id,))
        reviews = cursor.fetchall()

        total_reviews = len(reviews)
        avg_rating = round(float(sum(r['rating'] for r in reviews)) / total_reviews, 1) if total_reviews > 0 else None

        rating_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in reviews:
            rt = r.get('rating')
            if rt in rating_counts:
                rating_counts[rt] += 1

        current_user_id = session.get('user_id')
        user_review = next((r for r in reviews if r['user_id'] == current_user_id), None)

        return store, reviews, avg_rating, total_reviews, rating_counts, user_review
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def handle_submit_review(store_id):
    """Process review submission with server-side validation, duplicate check, and DB persistence."""
    if 'user_id' not in session:
        flash("Please login to submit a review.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Verify store exists and is approved
        cursor.execute("SELECT store_id, status FROM stores WHERE store_id = %s", (store_id,))
        store = cursor.fetchone()
        if not store or store['status'] != 'approved':
            return render_template('404.html'), 404

        # 2. Enforce one review per user per store
        cursor.execute("SELECT review_id FROM reviews WHERE store_id = %s AND user_id = %s", (store_id, user_id))
        existing_review = cursor.fetchone()
        if existing_review:
            flash("You have already reviewed this store. You can edit your existing review.", 'warning')
            store_data, reviews, avg_rating, total_reviews, rating_counts, user_review = get_store_details_data(store_id)
            return render_template(
                'store_details.html',
                store=store_data,
                reviews=reviews,
                avg_rating=avg_rating,
                total_reviews=total_reviews,
                rating_counts=rating_counts,
                user_review=user_review,
                current_user_id=user_id,
                full_name=session.get('full_name'),
                role=session.get('role')
            ), 400

        # 3. Server-side validation for rating and review comment
        errors = []
        rating_raw = request.form.get('rating', '').strip()
        comment = request.form.get('comment', '').strip()

        rating = None
        try:
            rating = int(rating_raw)
            if rating < 1 or rating > 5:
                errors.append("Rating must be an integer between 1 and 5.")
        except (ValueError, TypeError):
            errors.append("Rating must be a valid number between 1 and 5.")

        if not comment:
            errors.append("Review comment cannot be empty.")
        elif len(comment) < 3:
            errors.append("Review comment must be at least 3 characters long.")
        elif len(comment) > 1000:
            errors.append("Review comment must not exceed 1,000 characters.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            store_data, reviews, avg_rating, total_reviews, rating_counts, user_review = get_store_details_data(store_id)
            return render_template(
                'store_details.html',
                store=store_data,
                reviews=reviews,
                avg_rating=avg_rating,
                total_reviews=total_reviews,
                rating_counts=rating_counts,
                user_review=user_review,
                current_user_id=user_id,
                full_name=session.get('full_name'),
                role=session.get('role'),
                submitted_comment=comment,
                submitted_rating=rating_raw
            ), 400

        # 4. Insert review using parameterized SQL
        cursor.execute(
            "INSERT INTO reviews (store_id, user_id, rating, comment) VALUES (%s, %s, %s, %s)",
            (store_id, user_id, rating, comment)
        )
        conn.commit()
        flash("Your review has been published successfully!", 'success')
        return redirect(url_for('store_details', store_id=store_id) + '#reviews')

    except mysql.connector.Error as e:
        print(f"Database error submitting review: {e}")
        if conn:
            conn.rollback()
        flash("A database error occurred while submitting your review.", 'danger')
        return redirect(url_for('store_details', store_id=store_id))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/store/<int:store_id>', methods=['GET', 'POST'])
def store_details(store_id):
    """Public route gated behind login to view complete store details, ratings, and customer reviews."""
    # 1. Login Gating Check: If user is not logged in, redirect to login with flash
    if 'user_id' not in session:
        flash("Please login to view complete store information.", 'warning')
        return redirect(url_for('login'))

    if request.method == 'POST':
        return handle_submit_review(store_id)

    store, reviews, avg_rating, total_reviews, rating_counts, user_review = get_store_details_data(store_id)
    # Only approved stores can be viewed. If store is pending, rejected or non-existent: Return 404
    if not store:
        return render_template('404.html'), 404

    # Check if currently logged in user saved this store
    is_favorited = False
    current_user_id = session.get('user_id')
    if current_user_id:
        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM favorites WHERE user_id = %s AND store_id = %s", (current_user_id, store_id))
            is_favorited = cursor.fetchone() is not None
        except Exception as e:
            print(f"Error checking favorite status: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    return render_template(
        'store_details.html',
        store=store,
        reviews=reviews,
        avg_rating=avg_rating,
        total_reviews=total_reviews,
        rating_counts=rating_counts,
        user_review=user_review,
        is_favorited=is_favorited,
        current_user_id=current_user_id,
        full_name=session.get('full_name'),
        role=session.get('role')
    )

@app.route('/store/<int:store_id>/review', methods=['POST'])
def submit_review(store_id):
    """Endpoint specifically for submitting store reviews."""
    return handle_submit_review(store_id)

@app.route('/review/<int:review_id>/edit', methods=['GET', 'POST'])
def edit_review(review_id):
    """Edit an existing review. Strictly restricted: users can edit only their own reviews."""
    if 'user_id' not in session:
        flash("Please log in to edit your review.", 'warning')
        return redirect(url_for('login'))

    current_user_id = session.get('user_id')
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT review_id, store_id, user_id, rating, comment FROM reviews WHERE review_id = %s", (review_id,))
        review = cursor.fetchone()
        if not review:
            flash("Review not found.", 'danger')
            return render_template('404.html'), 404

        # Strict authorization check: Only the author can edit their review
        # Store owners cannot edit reviews written by others
        if review['user_id'] != current_user_id:
            abort(403, description="Unauthorized: You can only edit your own reviews.")

        store_id = review['store_id']

        if request.method == 'GET':
            next_url = request.args.get('next')
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('store_details', store_id=store_id) + '#reviews')

        # Server-side validation
        errors = []
        rating_raw = request.form.get('rating', '').strip()
        comment = request.form.get('comment', '').strip()

        rating = None
        try:
            rating = int(rating_raw)
            if rating < 1 or rating > 5:
                errors.append("Rating must be an integer between 1 and 5.")
        except (ValueError, TypeError):
            errors.append("Rating must be a valid number between 1 and 5.")

        if not comment:
            errors.append("Review comment cannot be empty.")
        elif len(comment) < 3:
            errors.append("Review comment must be at least 3 characters long.")
        elif len(comment) > 1000:
            errors.append("Review comment must not exceed 1,000 characters.")

        if errors:
            for error in errors:
                flash(error, 'danger')
            next_url = request.form.get('next')
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            store_data, reviews, avg_rating, total_reviews, rating_counts, user_review = get_store_details_data(store_id)
            return render_template(
                'store_details.html',
                store=store_data,
                reviews=reviews,
                avg_rating=avg_rating,
                total_reviews=total_reviews,
                rating_counts=rating_counts,
                user_review=user_review,
                current_user_id=current_user_id,
                full_name=session.get('full_name'),
                role=session.get('role'),
                submitted_comment=comment,
                submitted_rating=rating_raw
            ), 400

        # Update using parameterized SQL
        cursor.execute(
            "UPDATE reviews SET rating = %s, comment = %s WHERE review_id = %s",
            (rating, comment, review_id)
        )
        conn.commit()
        flash("Your review has been updated successfully!", 'success')
        next_url = request.form.get('next')
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for('store_details', store_id=store_id) + '#reviews')

    except mysql.connector.Error as e:
        print(f"Database error editing review: {e}")
        if conn:
            conn.rollback()
        flash("A database error occurred while updating your review.", 'danger')
        return redirect(url_for('stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/review/<int:review_id>/delete', methods=['POST'])
def delete_review(review_id):
    """Delete an existing review. Strictly restricted: users can delete only their own reviews."""
    if 'user_id' not in session:
        flash("Please log in to delete your review.", 'warning')
        return redirect(url_for('login'))

    current_user_id = session.get('user_id')
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT review_id, store_id, user_id FROM reviews WHERE review_id = %s", (review_id,))
        review = cursor.fetchone()
        if not review:
            flash("Review not found.", 'danger')
            return render_template('404.html'), 404

        # Strict authorization check: Only the author can delete their review
        # Store owners cannot delete reviews written by others
        if review['user_id'] != current_user_id:
            abort(403, description="Unauthorized: You can only delete your own reviews.")

        store_id = review['store_id']

        # Delete using parameterized SQL
        cursor.execute("DELETE FROM reviews WHERE review_id = %s", (review_id,))
        conn.commit()
        flash("Your review has been deleted successfully.", 'success')
        next_url = request.form.get('next')
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for('store_details', store_id=store_id) + '#reviews')

    except mysql.connector.Error as e:
        print(f"Database error deleting review: {e}")
        if conn:
            conn.rollback()
        flash("A database error occurred while deleting your review.", 'danger')
        return redirect(url_for('stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

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
            query = "SELECT user_id, full_name, email, password, role, status FROM users WHERE email = %s"
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

            # Check account status
            if user.get('status') == 'inactive':
                flash("Your account has been deactivated. Please contact an administrator.", 'danger')
                return render_template('login.html', email=email), 403

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
    """User dashboard route protected by role-based access control with hybrid ML recommendations and store showcase."""
    if 'user_id' not in session:
        flash("Please log in to access your dashboard.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    user_role = session.get('role')
    if user_role != 'user':
        flash("Access denied. You do not have permission to access the User Dashboard.", 'danger')
        if user_role == 'owner':
            return redirect(url_for('owner_dashboard'))
        elif user_role == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('login'))

    if request.args.get('refresh') == '1':
        flash("Recommendations recalculated with your latest preferences and activity.", 'info')

    conn = None
    cursor = None
    featured_stores = []
    all_categories = []
    user_pref_cat_ids = []
    user_preferred_city = ''
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                s.store_id,
                s.store_name,
                s.category_id,
                s.description,
                s.city,
                s.latitude,
                s.longitude,
                s.image,
                s.status,
                c.category_name
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            WHERE s.status = 'approved'
              AND s.latitude IS NOT NULL
              AND s.longitude IS NOT NULL
              AND s.latitude BETWEEN %s AND %s
              AND s.longitude BETWEEN %s AND %s
            ORDER BY s.created_at DESC
            LIMIT 6
        """, (INDIA_LAT_MIN, INDIA_LAT_MAX, INDIA_LNG_MIN, INDIA_LNG_MAX))
        raw_featured = cursor.fetchall()
        featured_stores = [s for s in raw_featured if is_in_india(s.get('latitude'), s.get('longitude'))]

        # Fetch all available categories for preference customization
        cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name ASC")
        all_categories = cursor.fetchall()

        # Fetch user preferences (graceful fallback if schema does not have preference columns)
        try:
            cursor.execute("SELECT preferred_categories, preferred_city FROM users WHERE user_id = %s", (user_id,))
            user_prefs = cursor.fetchone() or {}
            pref_cats_str = user_prefs.get('preferred_categories') or ''
            user_pref_cat_ids = [int(c.strip()) for c in str(pref_cats_str).split(',') if c.strip().isdigit()]
            user_preferred_city = user_prefs.get('preferred_city') or ''
        except Exception:
            user_pref_cat_ids = []
            user_preferred_city = ''

    except Exception as e:
        print(f"Error fetching user dashboard stores: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    # Generate hybrid ML recommendations for the user
    recommendations = []
    try:
        engine = HybridRecommendationEngine()
        recommendations = engine.get_recommendations(user_id=user_id, limit=6)
    except Exception as re_err:
        print(f"Error generating hybrid recommendations: {re_err}")

    return render_template(
        'user_dashboard.html',
        full_name=session.get('full_name'),
        role=user_role,
        stores=featured_stores,
        recommendations=recommendations,
        all_categories=all_categories,
        user_pref_cat_ids=user_pref_cat_ids,
        user_preferred_city=user_preferred_city
    )

@app.route('/update-preferences', methods=['POST'])
def update_preferences():
    """Allow user to update preferred categories and location for personalized ML recommendations."""
    if 'user_id' not in session:
        flash("Please log in to update preferences.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    selected_cats = request.form.getlist('preferred_categories')
    city = request.form.get('preferred_city')
    if city is not None:
        city = city.strip()

    try:
        engine = HybridRecommendationEngine()
        engine.update_user_preferences(user_id, preferred_categories=selected_cats, preferred_city=city)
        flash("Your style and location preferences have been updated! Recommendations refreshed.", 'success')
    except Exception as e:
        print(f"Error updating user preferences: {e}")
        flash("An error occurred while updating your preferences.", 'danger')

    return redirect(url_for('user_dashboard') + '#recommendations-section')

@app.route('/my-reviews')
def my_reviews():
    """Display reviews written by the currently logged-in user."""
    if 'user_id' not in session:
        flash("Please log in to view your reviews.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    user_role = session.get('role')
    full_name = session.get('full_name')

    conn = None
    cursor = None
    user_reviews = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                r.review_id,
                r.store_id,
                r.user_id,
                r.rating,
                r.comment,
                r.created_at,
                s.store_name,
                s.city,
                s.image AS store_image,
                s.status AS store_status,
                c.category_name
            FROM reviews r
            JOIN stores s ON r.store_id = s.store_id
            LEFT JOIN categories c ON s.category_id = c.category_id
            WHERE r.user_id = %s
            ORDER BY r.created_at DESC, r.review_id DESC
        """, (user_id,))
        user_reviews = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching user reviews: {e}")
        flash("A database error occurred while loading your reviews.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'my_reviews.html',
        reviews=user_reviews,
        full_name=full_name,
        role=user_role
    )

@app.route('/my-favorites')
def my_favorites():
    """Display saved/bookmarked thrift stores for the logged-in user."""
    if 'user_id' not in session:
        flash("Please log in to view your saved stores.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    user_role = session.get('role')
    full_name = session.get('full_name')

    conn = None
    cursor = None
    saved_stores = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                f.favorite_id,
                f.user_id,
                f.store_id,
                f.created_at AS saved_at,
                s.store_name,
                s.description,
                s.city,
                s.address,
                s.contact_number,
                s.image,
                s.status,
                c.category_name
            FROM favorites f
            JOIN stores s ON f.store_id = s.store_id
            LEFT JOIN categories c ON s.category_id = c.category_id
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC, f.favorite_id DESC
        """, (user_id,))
        saved_stores = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching user favorites: {e}")
        flash("A database error occurred while loading your saved stores.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'my_favorites.html',
        stores=saved_stores,
        full_name=full_name,
        role=user_role
    )

@app.route('/favorite/<int:store_id>/add', methods=['POST'])
@app.route('/store/<int:store_id>/save', methods=['POST'])
def save_favorite(store_id):
    """Save an approved thrift store to user's favorites list."""
    if 'user_id' not in session:
        flash("Please log in to save stores.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT store_id, store_name, status FROM stores WHERE store_id = %s", (store_id,))
        store = cursor.fetchone()
        if not store or store['status'] != 'approved':
            flash("Store not found or unavailable.", 'danger')
            return render_template('404.html'), 404

        cursor.execute("SELECT favorite_id FROM favorites WHERE user_id = %s AND store_id = %s", (user_id, store_id))
        existing = cursor.fetchone()
        if existing:
            flash(f"'{store['store_name']}' is already in your saved stores.", 'info')
        else:
            cursor.execute("INSERT INTO favorites (user_id, store_id) VALUES (%s, %s)", (user_id, store_id))
            conn.commit()
            flash(f"'{store['store_name']}' has been added to your saved stores!", 'success')

        next_url = request.form.get('next')
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for('store_details', store_id=store_id))
    except mysql.connector.Error as e:
        print(f"Database error adding favorite: {e}")
        if conn:
            conn.rollback()
        flash("A database error occurred while saving the store.", 'danger')
        return redirect(url_for('stores'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/favorite/<int:store_id>/remove', methods=['POST'])
@app.route('/store/<int:store_id>/unsave', methods=['POST'])
def remove_favorite_by_store(store_id):
    """Remove a store from user's favorites list by store_id."""
    if 'user_id' not in session:
        flash("Please log in to manage your saved stores.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT f.favorite_id, s.store_name FROM favorites f JOIN stores s ON f.store_id = s.store_id WHERE f.user_id = %s AND f.store_id = %s", (user_id, store_id))
        fav = cursor.fetchone()
        if not fav:
            cursor.execute("SELECT favorite_id FROM favorites WHERE store_id = %s", (store_id,))
            other = cursor.fetchone()
            if other:
                abort(403, description="Unauthorized: You cannot remove another user's saved store.")
            flash("Store was not found in your saved list.", 'info')
        else:
            cursor.execute("DELETE FROM favorites WHERE user_id = %s AND store_id = %s", (user_id, store_id))
            conn.commit()
            flash(f"Removed '{fav['store_name']}' from your saved stores.", 'success')

        next_url = request.form.get('next')
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for('my_favorites'))
    except mysql.connector.Error as e:
        print(f"Database error removing favorite: {e}")
        if conn:
            conn.rollback()
        flash("A database error occurred while removing the store.", 'danger')
        return redirect(url_for('my_favorites'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/favorite/<int:favorite_id>/delete', methods=['POST'])
def delete_favorite(favorite_id):
    """Remove a favorite by favorite_id. Strictly restricted to the owner."""
    if 'user_id' not in session:
        flash("Please log in to manage your saved stores.", 'warning')
        return redirect(url_for('login'))

    user_id = session.get('user_id')
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT f.favorite_id, f.user_id, s.store_name FROM favorites f JOIN stores s ON f.store_id = s.store_id WHERE f.favorite_id = %s", (favorite_id,))
        fav = cursor.fetchone()
        if not fav:
            flash("Saved store record not found.", 'danger')
            return render_template('404.html'), 404

        if fav['user_id'] != user_id:
            abort(403, description="Unauthorized: You cannot remove another user's saved store.")

        cursor.execute("DELETE FROM favorites WHERE favorite_id = %s AND user_id = %s", (favorite_id, user_id))
        conn.commit()
        flash(f"Removed '{fav['store_name']}' from your saved stores.", 'success')

        next_url = request.form.get('next')
        if next_url and next_url.startswith('/') and not next_url.startswith('//'):
            return redirect(next_url)
        return redirect(url_for('my_favorites'))
    except mysql.connector.Error as e:
        print(f"Database error deleting favorite: {e}")
        if conn:
            conn.rollback()
        flash("A database error occurred while deleting the favorite.", 'danger')
        return redirect(url_for('my_favorites'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

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

@app.route('/owner/reviews')
@app.route('/owner-reviews')
def owner_reviews():
    """Route for store owners to view customer reviews for all stores they own."""
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
    full_name = session.get('full_name')

    conn = None
    cursor = None
    reviews = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                r.review_id,
                r.store_id,
                r.user_id,
                r.rating,
                r.comment,
                r.created_at,
                u.full_name AS reviewer_name,
                u.email AS reviewer_email,
                s.store_name,
                s.city,
                s.status AS store_status,
                s.image AS store_image,
                c.category_name
            FROM reviews r
            JOIN stores s ON r.store_id = s.store_id
            JOIN users u ON r.user_id = u.user_id
            LEFT JOIN categories c ON s.category_id = c.category_id
            WHERE s.owner_id = %s
            ORDER BY r.created_at DESC, r.review_id DESC
        """, (owner_id,))
        reviews = cursor.fetchall()
    except Exception as e:
        print(f"Error fetching owner reviews: {e}")
        flash("A database error occurred while retrieving customer reviews.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    total_reviews = len(reviews)
    avg_rating = round(sum(r['rating'] for r in reviews) / total_reviews, 1) if total_reviews > 0 else None

    return render_template(
        'owner_reviews.html',
        reviews=reviews,
        total_reviews=total_reviews,
        avg_rating=avg_rating,
        full_name=full_name,
        role=user_role
    )

@app.route('/add-store', methods=['GET', 'POST'])
def add_store():
    """Route for store owners to register a new store listing with image upload."""
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
            cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name ASC")
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

        if category_id:
            available_categories = fetch_categories()
            valid_cat_ids = {c['category_id'] for c in available_categories}
            if category_id not in valid_cat_ids:
                errors.append("Selected category does not exist.")

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

        if latitude is not None and longitude is not None:
            if not is_valid_coordinate(latitude, longitude):
                errors.append("Latitude and Longitude must be valid decimal coordinates.")
            elif not is_in_india(latitude, longitude):
                errors.append("Selected store location must be within India (Latitude: 6.0° to 38.0° N, Longitude: 68.0° to 98.0° E).")
        elif (latitude is not None and longitude is None) or (latitude is None and longitude is not None):
            errors.append("Both Latitude and Longitude are required to set a map location.")

        # Process image upload if provided
        image = None
        saved_abs_path = None
        if 'store_image' in request.files:
            file = request.files['store_image']
            if file and file.filename != '':
                rel_path, img_error, abs_path = validate_and_save_image(file)
                if img_error:
                    errors.append(img_error)
                else:
                    image = rel_path
                    saved_abs_path = abs_path

        if errors:
            # Clean up newly uploaded file if other validations failed
            if saved_abs_path and os.path.exists(saved_abs_path):
                try:
                    os.remove(saved_abs_path)
                except Exception as cleanup_err:
                    print(f"Error cleaning up uploaded file: {cleanup_err}")

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
            if saved_abs_path and os.path.exists(saved_abs_path):
                try:
                    os.remove(saved_abs_path)
                except Exception as cleanup_err:
                    print(f"Error cleaning up uploaded file: {cleanup_err}")
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
            if saved_abs_path and os.path.exists(saved_abs_path):
                try:
                    os.remove(saved_abs_path)
                except Exception as cleanup_err:
                    print(f"Error cleaning up uploaded file: {cleanup_err}")
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
    """Route for store owners to edit their existing store listing with image replacement."""
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
            cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name ASC")
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

        if category_id:
            available_categories = fetch_categories()
            valid_cat_ids = {c['category_id'] for c in available_categories}
            if category_id not in valid_cat_ids:
                errors.append("Selected category does not exist.")

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

        if latitude is not None and longitude is not None:
            if not is_valid_coordinate(latitude, longitude):
                errors.append("Latitude and Longitude must be valid decimal coordinates.")
            elif not is_in_india(latitude, longitude):
                errors.append("Selected store location must be within India (Latitude: 6.0° to 38.0° N, Longitude: 68.0° to 98.0° E).")
        elif (latitude is not None and longitude is None) or (latitude is None and longitude is not None):
            errors.append("Both Latitude and Longitude are required to set a map location.")

        # Process image replacement if new file uploaded; preserve existing if none selected
        image = store.get('image')
        new_saved_abs_path = None
        if 'store_image' in request.files:
            file = request.files['store_image']
            if file and file.filename != '':
                rel_path, img_error, abs_path = validate_and_save_image(file)
                if img_error:
                    errors.append(img_error)
                else:
                    image = rel_path
                    new_saved_abs_path = abs_path

        if errors:
            if new_saved_abs_path and os.path.exists(new_saved_abs_path):
                try:
                    os.remove(new_saved_abs_path)
                except Exception as cleanup_err:
                    print(f"Error cleaning up uploaded file: {cleanup_err}")

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

            # Clean up old uploaded image if replaced
            if new_saved_abs_path and store.get('image') and store.get('image') != image:
                try:
                    old_path = os.path.join(app.root_path, 'static', store['image'])
                    if os.path.exists(old_path) and 'uploads' in store['image']:
                        os.remove(old_path)
                except Exception as old_cleanup_err:
                    print(f"Error removing old image: {old_cleanup_err}")

            flash("Store updated successfully.", 'success')
            return redirect(url_for('manage_stores'))

        except mysql.connector.Error as e:
            print(f"Database error while updating store: {e}")
            if conn:
                conn.rollback()
            if new_saved_abs_path and os.path.exists(new_saved_abs_path):
                try:
                    os.remove(new_saved_abs_path)
                except Exception as cleanup_err:
                    print(f"Error cleaning up uploaded file: {cleanup_err}")
            flash("Database error occurred while updating store. Please try again.", 'danger')
            categories = fetch_categories()
            return render_template('edit_store.html', store=store, categories=categories), 500
        except Exception as e:
            print(f"Unexpected error while updating store: {e}")
            if conn:
                conn.rollback()
            if new_saved_abs_path and os.path.exists(new_saved_abs_path):
                try:
                    os.remove(new_saved_abs_path)
                except Exception as cleanup_err:
                    print(f"Error cleaning up uploaded file: {cleanup_err}")
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

@app.route('/admin/users')
def admin_users():
    """Admin route to list and filter registered users with role counts and pagination."""
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

    search = request.args.get('search', '').strip()
    role_filter = request.args.get('role', '').strip().lower()
    status_filter = request.args.get('status', '').strip().lower()
    page = request.args.get('page', 1, type=int)
    per_page = 10

    if role_filter not in ['user', 'owner', 'admin']:
        role_filter = ''
    if status_filter not in ['active', 'inactive']:
        status_filter = ''

    conn = None
    cursor = None
    users = []
    counts = {
        'total': 0,
        'shopper': 0,
        'owner': 0,
        'admin': 0,
        'active': 0,
        'inactive': 0
    }
    total_count = 0
    total_pages = 1

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Overview counts across all users
        cursor.execute("""
            SELECT 
                COUNT(*) AS total_users,
                SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS shopper_count,
                SUM(CASE WHEN role = 'owner' THEN 1 ELSE 0 END) AS owner_count,
                SUM(CASE WHEN role = 'admin' THEN 1 ELSE 0 END) AS admin_count,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active_count,
                SUM(CASE WHEN status = 'inactive' THEN 1 ELSE 0 END) AS inactive_count
            FROM users
        """)
        summary_row = cursor.fetchone()
        if summary_row:
            counts['total'] = summary_row.get('total_users') or 0
            counts['shopper'] = int(summary_row.get('shopper_count') or 0)
            counts['owner'] = int(summary_row.get('owner_count') or 0)
            counts['admin'] = int(summary_row.get('admin_count') or 0)
            counts['active'] = int(summary_row.get('active_count') or 0)
            counts['inactive'] = int(summary_row.get('inactive_count') or 0)

        # Build dynamic WHERE clause
        conditions = []
        params = []
        if search:
            conditions.append("(u.full_name LIKE %s OR u.email LIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        if role_filter:
            conditions.append("u.role = %s")
            params.append(role_filter)
        if status_filter:
            conditions.append("u.status = %s")
            params.append(status_filter)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        # Count filtered rows
        count_query = f"SELECT COUNT(*) AS total FROM users u {where_clause}"
        cursor.execute(count_query, tuple(params))
        total_count_row = cursor.fetchone()
        total_count = total_count_row['total'] if total_count_row else 0

        total_pages = max(1, math.ceil(total_count / per_page))
        if page < 1:
            page = 1
        elif page > total_pages:
            page = total_pages
        offset = (page - 1) * per_page

        # Fetch users with store, review, and favorite counts
        users_query = f"""
            SELECT 
                u.user_id,
                u.full_name,
                u.email,
                u.role,
                u.status,
                u.created_at,
                u.preferred_city,
                u.preferred_categories,
                (SELECT COUNT(*) FROM stores s WHERE s.owner_id = u.user_id) AS store_count,
                (SELECT COUNT(*) FROM reviews r WHERE r.user_id = u.user_id) AS review_count,
                (SELECT COUNT(*) FROM favorites f WHERE f.user_id = u.user_id) AS favorite_count
            FROM users u
            {where_clause}
            ORDER BY u.created_at DESC, u.user_id DESC
            LIMIT %s OFFSET %s
        """
        user_params = list(params) + [per_page, offset]
        cursor.execute(users_query, tuple(user_params))
        users = cursor.fetchall()

    except mysql.connector.Error as e:
        print(f"Database error in admin_users: {e}")
        flash("Database error occurred while retrieving user list.", 'danger')
    except Exception as e:
        print(f"Unexpected error in admin_users: {e}")
        flash("An unexpected error occurred. Please try again.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'admin_users.html',
        users=users,
        search=search,
        role_filter=role_filter,
        status_filter=status_filter,
        counts=counts,
        page=page,
        per_page=per_page,
        total_count=total_count,
        total_pages=total_pages,
        full_name=session.get('full_name'),
        role=user_role,
        current_user_id=session.get('user_id')
    )

@app.route('/admin/user/<int:user_id>')
def admin_user_details(user_id):
    """Admin route to inspect a specific user's details, stores, reviews, and favorites."""
    if 'user_id' not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
            return jsonify({'success': False, 'message': 'Authentication required'}), 401
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
            return jsonify({'success': False, 'message': 'Access denied'}), 403
        flash("Access denied. Only administrators can access this page.", 'danger')
        return redirect(url_for('admin_dashboard'))

    conn = None
    cursor = None
    user = None
    stores = []
    reviews = []
    favorites = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT user_id, full_name, email, role, status, created_at,
                   preferred_city, preferred_categories, preferred_lat, preferred_lng
            FROM users WHERE user_id = %s
        """, (user_id,))
        user = cursor.fetchone()

        if not user:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
                return jsonify({'success': False, 'message': 'User not found'}), 404
            flash("User not found.", 'danger')
            return redirect(url_for('admin_users'))

        # Fetch stores owned
        cursor.execute("""
            SELECT store_id, store_name, city, status, created_at
            FROM stores WHERE owner_id = %s ORDER BY created_at DESC
        """, (user_id,))
        stores = cursor.fetchall()

        # Fetch reviews written
        cursor.execute("""
            SELECT r.review_id, r.store_id, s.store_name, r.rating, r.comment, r.created_at
            FROM reviews r
            JOIN stores s ON r.store_id = s.store_id
            WHERE r.user_id = %s ORDER BY r.created_at DESC
        """, (user_id,))
        reviews = cursor.fetchall()

        # Fetch favorites saved
        cursor.execute("""
            SELECT f.favorite_id, f.store_id, s.store_name, s.city, f.created_at
            FROM favorites f
            JOIN stores s ON f.store_id = s.store_id
            WHERE f.user_id = %s ORDER BY f.created_at DESC
        """, (user_id,))
        favorites = cursor.fetchall()

    except Exception as e:
        print(f"Error fetching user details: {e}")
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
            return jsonify({'success': False, 'message': 'Database error'}), 500
        flash("Error fetching user details.", 'danger')
        return redirect(url_for('admin_users'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.args.get('format') == 'json':
        user_serialized = {
            'user_id': user['user_id'],
            'full_name': user['full_name'],
            'email': user['email'],
            'role': user['role'],
            'status': user['status'],
            'created_at': user['created_at'].strftime('%b %d, %Y %I:%M %p') if user.get('created_at') else 'N/A',
            'preferred_city': user.get('preferred_city') or 'None set',
            'preferred_categories': user.get('preferred_categories') or 'None set'
        }
        stores_serialized = [
            {
                'store_id': s['store_id'],
                'store_name': s['store_name'],
                'city': s['city'],
                'status': s['status'],
                'created_at': s['created_at'].strftime('%b %d, %Y') if s.get('created_at') else ''
            }
            for s in stores
        ]
        reviews_serialized = [
            {
                'review_id': r['review_id'],
                'store_id': r['store_id'],
                'store_name': r['store_name'],
                'rating': r['rating'],
                'comment': r['comment'],
                'created_at': r['created_at'].strftime('%b %d, %Y') if r.get('created_at') else ''
            }
            for r in reviews
        ]
        favorites_serialized = [
            {
                'favorite_id': f['favorite_id'],
                'store_id': f['store_id'],
                'store_name': f['store_name'],
                'city': f['city'],
                'created_at': f['created_at'].strftime('%b %d, %Y') if f.get('created_at') else ''
            }
            for f in favorites
        ]
        return jsonify({
            'success': True,
            'user': user_serialized,
            'stores': stores_serialized,
            'reviews': reviews_serialized,
            'favorites': favorites_serialized
        })

    return render_template(
        'admin_user_details.html',
        target_user=user,
        stores=stores,
        reviews=reviews,
        favorites=favorites,
        full_name=session.get('full_name'),
        role=user_role,
        current_user_id=session.get('user_id')
    )

@app.route('/admin/user/<int:user_id>/change-role', methods=['POST'])
def admin_change_user_role(user_id):
    """Admin route to safely change a user's role between Shopper and Store Owner."""
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. Only administrators can perform this action.", 'danger')
        return redirect(url_for('admin_dashboard'))

    # Security: Prevent admin from changing own role
    if user_id == session.get('user_id'):
        flash("Action blocked: You cannot change your own administrator role.", 'danger')
        return redirect(url_for('admin_users'))

    new_role = request.form.get('new_role', '').strip().lower()
    if new_role not in ['user', 'owner']:
        flash("Invalid role specified. Role can only be changed between Shopper and Store Owner.", 'danger')
        return redirect(url_for('admin_users'))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE user_id = %s", (user_id,))
        target_user = cursor.fetchone()
        if not target_user:
            flash("User not found.", 'danger')
            return redirect(url_for('admin_users'))

        # Security: Prevent demoting the last administrator account
        if target_user['role'] == 'admin':
            cursor.execute("SELECT COUNT(*) AS admin_count FROM users WHERE role = 'admin'")
            admin_count = cursor.fetchone().get('admin_count', 0)
            if admin_count <= 1:
                flash("Action blocked: Cannot change role of the only administrator account.", 'danger')
                return redirect(url_for('admin_users'))

        cursor.execute("UPDATE users SET role = %s WHERE user_id = %s", (new_role, user_id))
        conn.commit()

        role_label = "Store Owner" if new_role == 'owner' else "Shopper"
        flash(f"Role for user '{target_user['full_name']}' was successfully updated to {role_label}.", 'success')
        return redirect(request.referrer or url_for('admin_users'))

    except mysql.connector.Error as e:
        print(f"Database error changing user role: {e}")
        if conn:
            conn.rollback()
        flash("Database error occurred while changing user role.", 'danger')
        return redirect(url_for('admin_users'))
    except Exception as e:
        print(f"Unexpected error changing user role: {e}")
        if conn:
            conn.rollback()
        flash("An unexpected error occurred. Please try again.", 'danger')
        return redirect(url_for('admin_users'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/admin/user/<int:user_id>/toggle-status', methods=['POST'])
def admin_toggle_user_status(user_id):
    """Admin route to activate or deactivate a user account."""
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. Only administrators can perform this action.", 'danger')
        return redirect(url_for('admin_dashboard'))

    # Security: Prevent admin from deactivating own account
    if user_id == session.get('user_id'):
        flash("Action blocked: You cannot deactivate your own administrator account.", 'danger')
        return redirect(url_for('admin_users'))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT user_id, full_name, email, role, status FROM users WHERE user_id = %s", (user_id,))
        target_user = cursor.fetchone()
        if not target_user:
            flash("User not found.", 'danger')
            return redirect(url_for('admin_users'))

        # Security: Prevent deactivating the last active administrator account
        if target_user['role'] == 'admin' and target_user['status'] == 'active':
            cursor.execute("SELECT COUNT(*) AS active_admins FROM users WHERE role = 'admin' AND status = 'active'")
            active_admins = cursor.fetchone().get('active_admins', 0)
            if active_admins <= 1:
                flash("Action blocked: Cannot deactivate the only active administrator account.", 'danger')
                return redirect(url_for('admin_users'))

        new_status = 'inactive' if target_user['status'] == 'active' else 'active'
        cursor.execute("UPDATE users SET status = %s WHERE user_id = %s", (new_status, user_id))
        conn.commit()

        action_word = "deactivated" if new_status == 'inactive' else "activated"
        flash(f"User account '{target_user['full_name']}' has been {action_word} successfully.", 'success')
        return redirect(request.referrer or url_for('admin_users'))

    except mysql.connector.Error as e:
        print(f"Database error toggling user status: {e}")
        if conn:
            conn.rollback()
        flash("Database error occurred while updating account status.", 'danger')
        return redirect(url_for('admin_users'))
    except Exception as e:
        print(f"Unexpected error toggling user status: {e}")
        if conn:
            conn.rollback()
        flash("An unexpected error occurred. Please try again.", 'danger')
        return redirect(url_for('admin_users'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/admin/user/<int:user_id>/delete', methods=['POST'])
def admin_delete_user(user_id):
    """Admin route to safely delete a user account and cleanly handle dependent records in a transaction."""
    if 'user_id' not in session:
        flash("Please log in to access this page.", 'warning')
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role != 'admin':
        flash("Access denied. Only administrators can perform this action.", 'danger')
        return redirect(url_for('admin_dashboard'))

    # Security: Prevent admin from deleting their own account
    if user_id == session.get('user_id'):
        flash("Action blocked: You cannot delete your own administrator account.", 'danger')
        return redirect(url_for('admin_users'))

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE user_id = %s", (user_id,))
        target_user = cursor.fetchone()
        if not target_user:
            flash("User not found.", 'danger')
            return redirect(url_for('admin_users'))

        # Security: Prevent deleting the last administrator account
        if target_user['role'] == 'admin':
            cursor.execute("SELECT COUNT(*) AS admin_count FROM users WHERE role = 'admin'")
            admin_count = cursor.fetchone().get('admin_count', 0)
            if admin_count <= 1:
                flash("Action blocked: Cannot delete the only administrator account.", 'danger')
                return redirect(url_for('admin_users'))

        # Execute safe cascading cleanup in a single transaction
        # 1. Clean up images for stores owned by user
        cursor.execute("SELECT store_id, image FROM stores WHERE owner_id = %s", (user_id,))
        owned_stores = cursor.fetchall()
        for st in owned_stores:
            img = st.get('image')
            if img:
                img_path = os.path.join(app.root_path, 'static', img)
                if os.path.exists(img_path) and os.path.isfile(img_path):
                    try:
                        os.remove(img_path)
                    except Exception as img_err:
                        print(f"Error removing store image during user deletion: {img_err}")

        # 2. Delete reviews and favorites linked to stores owned by this user
        cursor.execute("DELETE FROM favorites WHERE store_id IN (SELECT store_id FROM stores WHERE owner_id = %s)", (user_id,))
        cursor.execute("DELETE FROM reviews WHERE store_id IN (SELECT store_id FROM stores WHERE owner_id = %s)", (user_id,))

        # 3. Delete stores owned by this user
        cursor.execute("DELETE FROM stores WHERE owner_id = %s", (user_id,))

        # 4. Delete reviews and favorites authored by this user
        cursor.execute("DELETE FROM reviews WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM favorites WHERE user_id = %s", (user_id,))

        # 5. Finally, delete the user record
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        conn.commit()

        flash(f"User account '{target_user['full_name']}' and associated records have been safely deleted.", 'success')
        return redirect(url_for('admin_users'))

    except mysql.connector.Error as e:
        print(f"Database error deleting user: {e}")
        if conn:
            conn.rollback()
        flash("Database error occurred while deleting user account.", 'danger')
        return redirect(url_for('admin_users'))
    except Exception as e:
        print(f"Unexpected error deleting user: {e}")
        if conn:
            conn.rollback()
        flash("An unexpected error occurred while deleting user.", 'danger')
        return redirect(url_for('admin_users'))
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/admin/reports')
def admin_reports():
    """Admin reporting dashboard with real-time summary metrics, detailed reports, and Chart.js analytics."""
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

    category_filter = request.args.get('category_id', '').strip()
    city_filter = request.args.get('city', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    # Basic date validation YYYY-MM-DD
    if date_from and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_from):
        date_from = ''
    if date_to and not re.match(r"^\d{4}-\d{2}-\d{2}$", date_to):
        date_to = ''

    conn = None
    cursor = None

    summary = {
        'total_users': 0,
        'total_shoppers': 0,
        'total_store_owners': 0,
        'total_stores': 0,
        'approved_stores': 0,
        'pending_stores': 0,
        'rejected_stores': 0,
        'total_reviews': 0,
        'total_favorites': 0
    }

    categories = []
    cities = []

    # Detailed report data structures
    user_roles_data = []
    user_trends_data = []
    store_status_data = []
    store_category_data = []
    store_city_data = []
    review_metrics = {'total_reviews': 0, 'avg_rating': 0.0}
    review_rating_distribution = [0, 0, 0, 0, 0]  # indices 0-4 for 1-5 stars
    most_reviewed_stores = []
    popular_stores_favorites = []
    popular_stores_reviews = []
    popular_stores_ratings = []

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Global summary card counts
        cursor.execute("""
            SELECT 
                COUNT(*) AS total_users,
                SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS total_shoppers,
                SUM(CASE WHEN role = 'owner' THEN 1 ELSE 0 END) AS total_store_owners
            FROM users
        """)
        u_stats = cursor.fetchone() or {}
        summary['total_users'] = int(u_stats.get('total_users') or 0)
        summary['total_shoppers'] = int(u_stats.get('total_shoppers') or 0)
        summary['total_store_owners'] = int(u_stats.get('total_store_owners') or 0)

        cursor.execute("""
            SELECT 
                COUNT(*) AS total_stores,
                SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_stores,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_stores,
                SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) AS rejected_stores
            FROM stores
        """)
        s_stats = cursor.fetchone() or {}
        summary['total_stores'] = int(s_stats.get('total_stores') or 0)
        summary['approved_stores'] = int(s_stats.get('approved_stores') or 0)
        summary['pending_stores'] = int(s_stats.get('pending_stores') or 0)
        summary['rejected_stores'] = int(s_stats.get('rejected_stores') or 0)

        cursor.execute("SELECT COUNT(*) AS total_reviews FROM reviews")
        r_stats = cursor.fetchone() or {}
        summary['total_reviews'] = int(r_stats.get('total_reviews') or 0)

        cursor.execute("SELECT COUNT(*) AS total_favorites FROM favorites")
        f_stats = cursor.fetchone() or {}
        summary['total_favorites'] = int(f_stats.get('total_favorites') or 0)

        # Filter option dropdowns
        cursor.execute("SELECT category_id, category_name FROM categories ORDER BY category_name ASC")
        categories = cursor.fetchall()

        cursor.execute("SELECT DISTINCT city FROM stores WHERE city IS NOT NULL AND city != '' ORDER BY city ASC")
        cities = [c['city'] for c in cursor.fetchall()]

        # 2. User Report Queries (with date filters)
        user_filter_clauses = []
        user_params = []
        if date_from:
            user_filter_clauses.append("DATE(created_at) >= %s")
            user_params.append(date_from)
        if date_to:
            user_filter_clauses.append("DATE(created_at) <= %s")
            user_params.append(date_to)

        user_where = ("WHERE " + " AND ".join(user_filter_clauses)) if user_filter_clauses else ""

        cursor.execute(f"SELECT role, COUNT(*) AS count FROM users {user_where} GROUP BY role ORDER BY count DESC", tuple(user_params))
        for r in cursor.fetchall():
            role_title = 'Shopper' if r['role'] == 'user' else ('Store Owner' if r['role'] == 'owner' else 'Admin')
            user_roles_data.append({'role': role_title, 'raw_role': r['role'], 'count': int(r['count'])})

        cursor.execute(f"SELECT DATE(created_at) AS reg_date, COUNT(*) AS count FROM users {user_where} GROUP BY DATE(created_at) ORDER BY reg_date ASC", tuple(user_params))
        for r in cursor.fetchall():
            date_str = str(r['reg_date']) if r.get('reg_date') else ''
            user_trends_data.append({'date': date_str, 'count': int(r['count'])})

        # 3. Store Report Queries (with category, city, date filters)
        store_conds = []
        store_params = []
        if category_filter:
            store_conds.append("s.category_id = %s")
            store_params.append(category_filter)
        if city_filter:
            store_conds.append("s.city = %s")
            store_params.append(city_filter)
        if date_from:
            store_conds.append("DATE(s.created_at) >= %s")
            store_params.append(date_from)
        if date_to:
            store_conds.append("DATE(s.created_at) <= %s")
            store_params.append(date_to)

        store_where = ("WHERE " + " AND ".join(store_conds)) if store_conds else ""

        # Store counts grouped by approval status
        cursor.execute(f"SELECT status, COUNT(*) AS count FROM stores s {store_where} GROUP BY status", tuple(store_params))
        for r in cursor.fetchall():
            store_status_data.append({'status': str(r['status']).capitalize(), 'raw_status': r['status'], 'count': int(r['count'])})

        # Store counts grouped by category
        category_join_conds = ["c.category_id = s.category_id"]
        category_params = []
        if city_filter:
            category_join_conds.append("s.city = %s")
            category_params.append(city_filter)
        if date_from:
            category_join_conds.append("DATE(s.created_at) >= %s")
            category_params.append(date_from)
        if date_to:
            category_join_conds.append("DATE(s.created_at) <= %s")
            category_params.append(date_to)

        cat_query = f"""
            SELECT c.category_id, c.category_name, COUNT(s.store_id) AS count
            FROM categories c
            LEFT JOIN stores s ON {" AND ".join(category_join_conds)}
            GROUP BY c.category_id, c.category_name
            ORDER BY count DESC, c.category_name ASC
        """
        cursor.execute(cat_query, tuple(category_params))
        for r in cursor.fetchall():
            store_category_data.append({'category_name': str(r['category_name']), 'count': int(r['count'])})

        # Store counts grouped by city
        cursor.execute(f"SELECT s.city, COUNT(*) AS count FROM stores s {store_where} GROUP BY s.city ORDER BY count DESC", tuple(store_params))
        for r in cursor.fetchall():
            if r.get('city'):
                store_city_data.append({'city': str(r['city']), 'count': int(r['count'])})

        # 4. Review Report Queries (filtered by store category, store city, review created_at date)
        review_conds = []
        review_params = []
        if category_filter:
            review_conds.append("s.category_id = %s")
            review_params.append(category_filter)
        if city_filter:
            review_conds.append("s.city = %s")
            review_params.append(city_filter)
        if date_from:
            review_conds.append("DATE(r.created_at) >= %s")
            review_params.append(date_from)
        if date_to:
            review_conds.append("DATE(r.created_at) <= %s")
            review_params.append(date_to)

        review_where = ("WHERE " + " AND ".join(review_conds)) if review_conds else ""

        # Total reviews & average rating
        cursor.execute(f"""
            SELECT 
                COUNT(r.review_id) AS total_reviews,
                COALESCE(ROUND(AVG(r.rating), 2), 0.0) AS avg_rating
            FROM reviews r
            JOIN stores s ON r.store_id = s.store_id
            {review_where}
        """, tuple(review_params))
        r_met = cursor.fetchone() or {}
        review_metrics['total_reviews'] = int(r_met.get('total_reviews') or 0)
        review_metrics['avg_rating'] = float(r_met.get('avg_rating') or 0.0)

        # Review counts by rating (1 to 5)
        cursor.execute(f"""
            SELECT r.rating, COUNT(*) AS count
            FROM reviews r
            JOIN stores s ON r.store_id = s.store_id
            {review_where}
            GROUP BY r.rating
            ORDER BY r.rating ASC
        """, tuple(review_params))
        for r in cursor.fetchall():
            rat = r.get('rating')
            if rat and 1 <= rat <= 5:
                review_rating_distribution[rat - 1] = int(r['count'])

        # Most-reviewed stores
        cursor.execute(f"""
            SELECT 
                s.store_id, 
                s.store_name, 
                s.city,
                c.category_name,
                COUNT(r.review_id) AS review_count,
                COALESCE(ROUND(AVG(r.rating), 1), 0.0) AS avg_rating
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            JOIN reviews r ON s.store_id = r.store_id
            {review_where}
            GROUP BY s.store_id, s.store_name, s.city, c.category_name
            ORDER BY review_count DESC, avg_rating DESC
            LIMIT 10
        """, tuple(review_params))
        for r in cursor.fetchall():
            most_reviewed_stores.append({
                'store_id': r['store_id'],
                'store_name': r['store_name'],
                'city': r['city'],
                'category_name': r['category_name'],
                'review_count': int(r['review_count']),
                'avg_rating': float(r['avg_rating'])
            })

        # 5. Popular Stores Report Queries
        # Stores ranked by favorites
        cursor.execute(f"""
            SELECT 
                s.store_id,
                s.store_name,
                s.city,
                c.category_name,
                COUNT(f.favorite_id) AS favorite_count,
                COALESCE(ROUND((SELECT AVG(rating) FROM reviews WHERE store_id = s.store_id), 1), 0.0) AS avg_rating
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            LEFT JOIN favorites f ON s.store_id = f.store_id
            {store_where}
            GROUP BY s.store_id, s.store_name, s.city, c.category_name
            ORDER BY favorite_count DESC, s.store_name ASC
            LIMIT 10
        """, tuple(store_params))
        for r in cursor.fetchall():
            popular_stores_favorites.append({
                'store_id': r['store_id'],
                'store_name': r['store_name'],
                'city': r['city'],
                'category_name': r['category_name'],
                'favorite_count': int(r['favorite_count']),
                'avg_rating': float(r['avg_rating'])
            })

        # Stores ranked by number of reviews
        cursor.execute(f"""
            SELECT 
                s.store_id,
                s.store_name,
                s.city,
                c.category_name,
                COUNT(r.review_id) AS review_count,
                COALESCE(ROUND(AVG(r.rating), 1), 0.0) AS avg_rating
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            LEFT JOIN reviews r ON s.store_id = r.store_id
            {store_where}
            GROUP BY s.store_id, s.store_name, s.city, c.category_name
            ORDER BY review_count DESC, avg_rating DESC, s.store_name ASC
            LIMIT 10
        """, tuple(store_params))
        for r in cursor.fetchall():
            popular_stores_reviews.append({
                'store_id': r['store_id'],
                'store_name': r['store_name'],
                'city': r['city'],
                'category_name': r['category_name'],
                'review_count': int(r['review_count']),
                'avg_rating': float(r['avg_rating'])
            })

        # Stores ranked by average rating
        cursor.execute(f"""
            SELECT 
                s.store_id,
                s.store_name,
                s.city,
                c.category_name,
                COUNT(r.review_id) AS review_count,
                COALESCE(ROUND(AVG(r.rating), 1), 0.0) AS avg_rating
            FROM stores s
            JOIN categories c ON s.category_id = c.category_id
            LEFT JOIN reviews r ON s.store_id = r.store_id
            {store_where}
            GROUP BY s.store_id, s.store_name, s.city, c.category_name
            HAVING review_count > 0
            ORDER BY avg_rating DESC, review_count DESC, s.store_name ASC
            LIMIT 10
        """, tuple(store_params))
        for r in cursor.fetchall():
            popular_stores_ratings.append({
                'store_id': r['store_id'],
                'store_name': r['store_name'],
                'city': r['city'],
                'category_name': r['category_name'],
                'review_count': int(r['review_count']),
                'avg_rating': float(r['avg_rating'])
            })

    except mysql.connector.Error as e:
        print(f"Database error in admin_reports: {e}")
        flash("Database error occurred while generating reports.", 'danger')
    except Exception as e:
        print(f"Unexpected error in admin_reports: {e}")
        flash("An unexpected error occurred while compiling reports.", 'danger')
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

    return render_template(
        'admin_reports.html',
        full_name=session.get('full_name'),
        role=user_role,
        summary=summary,
        categories=categories,
        cities=cities,
        category_filter=category_filter,
        city_filter=city_filter,
        date_from=date_from,
        date_to=date_to,
        user_roles_data=user_roles_data,
        user_trends_data=user_trends_data,
        store_status_data=store_status_data,
        store_category_data=store_category_data,
        store_city_data=store_city_data,
        review_metrics=review_metrics,
        review_rating_distribution=review_rating_distribution,
        most_reviewed_stores=most_reviewed_stores,
        popular_stores_favorites=popular_stores_favorites,
        popular_stores_reviews=popular_stores_reviews,
        popular_stores_ratings=popular_stores_ratings
    )

@app.route('/logout')
def logout():
    """Clear session and log out the user."""
    session.clear()
    flash("You have been logged out successfully.", 'info')
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)