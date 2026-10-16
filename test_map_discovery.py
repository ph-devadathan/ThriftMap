"""
Comprehensive test suite for ThriftMap India-only Store Discovery and Interactive Location Picker.
Strictly non-destructive: only executes read-only queries or validation checks; no live DB records are modified.
"""
import unittest
import json
import re
from app import app, is_valid_coordinate, is_in_india, get_db_connection, INDIA_LAT_MIN, INDIA_LAT_MAX, INDIA_LNG_MIN, INDIA_LNG_MAX
import config

class TestIndiaStoreDiscoveryAndPicker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        # Capture baseline database record counts and schema
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM stores")
            cls.baseline_stores_count = cursor.fetchone()['cnt']
            
            cursor.execute("SELECT COUNT(*) as cnt FROM users")
            cls.baseline_users_count = cursor.fetchone()['cnt']
            
            cursor.execute("SELECT COUNT(*) as cnt FROM categories")
            cls.baseline_categories_count = cursor.fetchone()['cnt']
            
            cursor.execute("DESCRIBE stores")
            cls.baseline_stores_columns = [
                (col['Field'], col['Type'], col['Null'], col['Default'])
                for col in cursor.fetchall()
            ]

            # Fetch existing stores snapshot to guarantee they are never modified during test execution
            cursor.execute("SELECT store_id, store_name, city, latitude, longitude, status FROM stores ORDER BY store_id ASC")
            cls.baseline_stores = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

    def setUp(self):
        self.client = app.test_client()

    def test_01_india_boundary_and_coordinate_helpers(self):
        """Verify coordinate validation and India boundary logic."""
        # 1. Valid coordinates inside India
        self.assertTrue(is_valid_coordinate(9.3835, 76.5741))
        self.assertTrue(is_in_india(9.3835, 76.5741))     # Thiruvalla, Kerala
        self.assertTrue(is_in_india(28.6139, 77.2090))    # New Delhi
        self.assertTrue(is_in_india(19.0760, 72.8777))    # Mumbai
        self.assertTrue(is_in_india(13.0827, 80.2707))    # Chennai
        self.assertTrue(is_in_india(11.6670, 92.7359))    # Port Blair (Andaman & Nicobar Islands)
        self.assertTrue(is_in_india(10.5667, 72.6417))    # Kavaratti (Lakshadweep)
        self.assertTrue(is_in_india(INDIA_LAT_MIN, INDIA_LNG_MIN)) # Boundary edges
        self.assertTrue(is_in_india(INDIA_LAT_MAX, INDIA_LNG_MAX))

        # 2. Coordinates outside India
        self.assertFalse(is_in_india(40.7128, -74.0060))   # Brooklyn / New York, USA
        self.assertFalse(is_in_india(51.5074, -0.1278))    # London, UK
        self.assertFalse(is_in_india(35.6762, 139.6503))   # Tokyo, Japan
        self.assertFalse(is_in_india(3.0, 78.0))           # South of India
        self.assertFalse(is_in_india(42.0, 78.0))          # North of India
        self.assertFalse(is_in_india(20.0, 60.0))          # West of India
        self.assertFalse(is_in_india(20.0, 102.0))         # East of India

        # 3. None or invalid inputs
        self.assertFalse(is_in_india(None, None))
        self.assertFalse(is_in_india(None, 78.0))
        self.assertFalse(is_in_india(20.0, None))
        self.assertFalse(is_in_india('abc', 'def'))

    def test_02_public_discovery_shows_only_stores_inside_india(self):
        """Verify public map and directory only show approved stores with coordinates inside India."""
        # Check /map
        resp_map = self.client.get('/map')
        self.assertEqual(resp_map.status_code, 200)
        html_map = resp_map.data.decode('utf-8')
        match = re.search(r'<script id="mapped-stores-data" type="application/json">(.*?)</script>', html_map)
        self.assertIsNotNone(match)
        mapped = json.loads(match.group(1))

        # Every single store returned on the map must be within India
        for store in mapped:
            self.assertTrue(is_in_india(store['latitude'], store['longitude']))

        # Check /stores
        resp_stores = self.client.get('/stores')
        self.assertEqual(resp_stores.status_code, 200)
        html_stores = resp_stores.data.decode('utf-8')
        self.assertIn("Stores in India", html_stores)

    def test_03_out_of_india_and_null_coord_stores_excluded(self):
        """Stores without coordinates or located outside India are excluded from public discovery."""
        # Simulated database response with a null-coord store and a foreign store
        simulated_stores = [
            {'store_id': 901, 'latitude': None, 'longitude': None},
            {'store_id': 902, 'latitude': 40.7128, 'longitude': -74.0060}, # Brooklyn, NY
            {'store_id': 903, 'latitude': 9.3835, 'longitude': 76.5741}    # Thiruvalla, India
        ]

        filtered = [s for s in simulated_stores if is_in_india(s.get('latitude'), s.get('longitude'))]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]['store_id'], 903)

    def test_04_map_page_centered_on_india_and_has_leaflet(self):
        """Map page defaults to India center [20.5937, 78.9629] with zoom 5."""
        resp = self.client.get('/map')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check Leaflet assets & OpenStreetMap
        self.assertIn('leaflet@1.9.4/dist/leaflet.css', html)
        self.assertIn('leaflet@1.9.4/dist/leaflet.js', html)
        self.assertIn('OpenStreetMap', html)

        # Check India map center and zoom level in JavaScript
        self.assertIn('const defaultCenter = [20.5937, 78.9629];', html)
        self.assertIn('const defaultZoom = 5;', html)

        # Check India branding
        self.assertIn('Explore Thrift Stores in India', html)

    def test_05_simulated_indian_store_rendering(self):
        """Simulated approved Indian store with valid coordinates renders marker and popup."""
        indian_store = [{
            'store_id': 101,
            'store_name': 'Kochi Vintage Wardrobe',
            'category_name': 'Retro Clothing',
            'city': 'Kochi',
            'address': 'Fort Kochi, Kerala',
            'latitude': 9.9658,
            'longitude': 76.2421,
            'image': None,
            'image_url': '/static/images/store-placeholder.svg',
            'details_url': '/store/101'
        }]

        with app.test_request_context('/map'):
            from flask import render_template
            rendered = render_template(
                'map.html',
                mapped_stores=indian_store,
                categories=[],
                search_query='',
                city_filter='',
                category_filter='',
                total_mapped=1,
                total_stores=1
            )

            # JSON payload contains the Indian store coordinates
            match = re.search(r'<script id="mapped-stores-data" type="application/json">(.*?)</script>', rendered)
            self.assertIsNotNone(match)
            parsed = json.loads(match.group(1))
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]['store_name'], 'Kochi Vintage Wardrobe')
            self.assertEqual(parsed[0]['latitude'], 9.9658)
            self.assertEqual(parsed[0]['longitude'], 76.2421)
            self.assertIn('sidebar-item-101', rendered)

    def test_06_add_store_form_has_location_picker(self):
        """Add Store form includes Leaflet CSS/JS, interactive picker container, instructions, and inputs."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 5
            sess['full_name'] = 'Store Owner'
            sess['role'] = 'owner'

        resp = self.client.get('/add-store')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check Leaflet includes
        self.assertIn('leaflet@1.9.4/dist/leaflet.css', html)
        self.assertIn('leaflet@1.9.4/dist/leaflet.js', html)

        # Check location picker map container and clear button
        self.assertIn('id="store-location-picker-map"', html)
        self.assertIn('id="btn-clear-pin"', html)
        self.assertIn('id="map-location-feedback"', html)

        # Check required instruction text
        self.assertIn("Click the map to pin your store location, then drag the marker to adjust it.", html)

        # Check input fields for latitude and longitude
        self.assertIn('name="latitude"', html)
        self.assertIn('id="latitude"', html)
        self.assertIn('name="longitude"', html)
        self.assertIn('id="longitude"', html)

        # Check India boundary guidance
        self.assertIn("Stores submitted without coordinates remain saved in your dashboard, but will not appear in the public India map and directory until verified coordinates are added.", html)

    def test_07_edit_store_form_has_location_picker(self):
        """Edit Store form includes Leaflet CSS/JS, location picker container, and pre-population logic."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 5  # Owner of store 3
            sess['full_name'] = 'Store Owner'
            sess['role'] = 'owner'

        resp = self.client.get('/edit-store/3')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode('utf-8')

        # Check Leaflet includes
        self.assertIn('leaflet@1.9.4/dist/leaflet.css', html)
        self.assertIn('leaflet@1.9.4/dist/leaflet.js', html)

        # Check location picker map container and clear button
        self.assertIn('id="store-location-picker-map"', html)
        self.assertIn('id="btn-clear-pin"', html)
        self.assertIn('id="map-location-feedback"', html)

        # Check required instruction text
        self.assertIn("Click the map to pin your store location, then drag the marker to adjust it.", html)

        # Check pre-population initialization script
        self.assertIn('initLat = parseFloat(latInput.value);', html)
        self.assertIn('setMarkerLocation(initLat, initLng, true);', html)

    def test_08_out_of_india_location_rejected_on_add_store(self):
        """Submitting coordinates outside India in Add Store is rejected with clear error message."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 5
            sess['full_name'] = 'Store Owner'
            sess['role'] = 'owner'

        # Post Brooklyn, NY coordinates
        payload = {
            'store_name': 'Foreign Thrift Boutique',
            'category_id': 1,
            'description': 'A thrift store located outside India',
            'address': '123 Atlantic Ave',
            'city': 'Brooklyn',
            'contact_number': '1234567890',
            'opening_hours': '10 AM - 6 PM',
            'latitude': '40.7128',
            'longitude': '-74.0060'
        }

        resp = self.client.post('/add-store', data=payload, follow_redirects=True)
        self.assertEqual(resp.status_code, 400)
        html = resp.data.decode('utf-8')

        # Expect clear validation error message
        self.assertIn("Selected store location must be within India (Latitude: 6.0° to 38.0° N, Longitude: 68.0° to 98.0° E).", html)

    def test_09_out_of_india_location_rejected_on_edit_store(self):
        """Submitting coordinates outside India in Edit Store is rejected with clear error message."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 5  # Owner of store 3
            sess['full_name'] = 'Store Owner'
            sess['role'] = 'owner'

        # Attempt to set Brooklyn coordinates on store 3
        payload = {
            'store_name': 'Vintage Hub',
            'category_id': 1,
            'description': 'Updated description',
            'address': '55 Hope St',
            'city': 'Brooklyn',
            'contact_number': '1234567890',
            'opening_hours': '11 AM - 7 PM',
            'latitude': '40.712776',
            'longitude': '-74.005974'
        }

        resp = self.client.post('/edit-store/3', data=payload, follow_redirects=True)
        self.assertEqual(resp.status_code, 400)
        html = resp.data.decode('utf-8')

        # Expect clear validation error message
        self.assertIn("Selected store location must be within India (Latitude: 6.0° to 38.0° N, Longitude: 68.0° to 98.0° E).", html)

    def test_10_invalid_coordinate_format_rejected(self):
        """Malformed coordinate values are rejected with appropriate error message."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 5
            sess['full_name'] = 'Store Owner'
            sess['role'] = 'owner'

        payload = {
            'store_name': 'Invalid Coords Test',
            'category_id': 1,
            'description': 'Test invalid coords',
            'address': 'MG Road',
            'city': 'Bengaluru',
            'contact_number': '1234567890',
            'opening_hours': '10 AM - 6 PM',
            'latitude': '999.000',
            'longitude': '77.5946'
        }

        resp = self.client.post('/add-store', data=payload, follow_redirects=True)
        self.assertEqual(resp.status_code, 400)
        html = resp.data.decode('utf-8')
        self.assertIn("Latitude and Longitude must be valid decimal coordinates.", html)

    def test_11_authorization_and_ownership_checks_preserved(self):
        """Store ownership checks and role authorization remain strictly enforced."""
        # 1. Unauthenticated access redirects to login
        self.assertEqual(self.client.get('/add-store').status_code, 302)
        self.assertEqual(self.client.get('/edit-store/3').status_code, 302)
        self.assertEqual(self.client.get('/owner-dashboard').status_code, 302)
        self.assertEqual(self.client.get('/admin-dashboard').status_code, 302)

        # 2. Regular user cannot access add-store or edit-store
        with self.client.session_transaction() as sess:
            sess['user_id'] = 2
            sess['full_name'] = 'Regular User'
            sess['role'] = 'user'

        resp_user_add = self.client.get('/add-store', follow_redirects=True)
        self.assertIn('Access denied', resp_user_add.data.decode('utf-8'))

        resp_user_edit = self.client.get('/edit-store/3', follow_redirects=True)
        self.assertIn('Access denied', resp_user_edit.data.decode('utf-8'))

        # 3. Another user cannot edit Store 3 (owned by Owner 5)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 4
            sess['full_name'] = 'Another User'
            sess['role'] = 'user'

        resp_wrong_owner = self.client.get('/edit-store/3', follow_redirects=True)
        self.assertIn('Access denied', resp_wrong_owner.data.decode('utf-8'))

    def test_12_non_destructive_database_safety(self):
        """Verify database schema, record counts, and store records remain completely unchanged."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Record counts
            cursor.execute("SELECT COUNT(*) as cnt FROM stores")
            self.assertEqual(cursor.fetchone()['cnt'], self.baseline_stores_count)
            cursor.execute("SELECT COUNT(*) as cnt FROM users")
            self.assertEqual(cursor.fetchone()['cnt'], self.baseline_users_count)
            cursor.execute("SELECT COUNT(*) as cnt FROM categories")
            self.assertEqual(cursor.fetchone()['cnt'], self.baseline_categories_count)

            # Columns
            cursor.execute("DESCRIBE stores")
            current_columns = [
                (col['Field'], col['Type'], col['Null'], col['Default'])
                for col in cursor.fetchall()
            ]
            self.assertEqual(current_columns, self.baseline_stores_columns)

            # Store records integrity check
            cursor.execute("SELECT store_id, store_name, city, latitude, longitude, status FROM stores ORDER BY store_id ASC")
            current_stores = cursor.fetchall()
            self.assertEqual(current_stores, self.baseline_stores)
        finally:
            cursor.close()
            conn.close()

if __name__ == '__main__':
    unittest.main()
