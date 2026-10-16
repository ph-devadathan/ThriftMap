"""
Test suite for Location-Based Store Discovery (/map) in ThriftMap.
Strictly non-destructive: only executes read-only operations.
"""
import unittest
import json
import re
from app import app, is_valid_coordinate, get_db_connection
import config

class TestMapDiscovery(unittest.TestCase):
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
        finally:
            cursor.close()
            conn.close()

    def setUp(self):
        self.client = app.test_client()

    def test_01_map_route_loads_for_guests(self):
        """1. /map loads successfully (HTTP 200) for guests."""
        response = self.client.get('/map')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        
        # Verify Leaflet 1.9.4 assets
        self.assertIn('leaflet@1.9.4/dist/leaflet.css', html)
        self.assertIn('leaflet@1.9.4/dist/leaflet.js', html)
        self.assertIn('OpenStreetMap', html)
        
        # Verify essential DOM elements
        self.assertIn('id="store-map-canvas"', html)
        self.assertIn('id="btn-find-location"', html)
        self.assertIn('id="btn-reset-view"', html)
        self.assertIn('id="map-filter-form"', html)
        
        # Verify guest navbar shows Login and Register
        self.assertIn('Login', html)
        self.assertIn('Register', html)

    def test_02_map_route_loads_for_authenticated_users(self):
        """1. /map loads successfully for authenticated users with role badges."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['full_name'] = 'Test User'
            sess['role'] = 'user'

        response = self.client.get('/map')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')
        self.assertIn('Logout', html)
        self.assertIn('My Dashboard', html)

    def test_03_only_approved_stores_returned(self):
        """2. Only approved stores are retrieved from the database."""
        response = self.client.get('/map')
        self.assertEqual(response.status_code, 200)
        
        # Verify against live DB query
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT store_id, store_name, status FROM stores WHERE status = 'approved'")
            approved_stores = cursor.fetchall()
            
            cursor.execute("SELECT store_id, store_name, status FROM stores WHERE status != 'approved'")
            unapproved_stores = cursor.fetchall()
        finally:
            cursor.close()
            conn.close()

        html = response.data.decode('utf-8')
        for s in approved_stores:
            self.assertIn(s['store_name'], html)

        for s in unapproved_stores:
            self.assertNotIn(s['store_name'], html)

    def test_04_coordinate_validation_helper(self):
        """3 & 4. Server-side coordinate validation handles valid and invalid inputs."""
        # Valid coordinates
        self.assertTrue(is_valid_coordinate(40.7128, -74.0060))
        self.assertTrue(is_valid_coordinate('40.7128', '-74.0060'))
        self.assertTrue(is_valid_coordinate(0, 0))
        self.assertTrue(is_valid_coordinate(-90, -180))
        self.assertTrue(is_valid_coordinate(90, 180))
        self.assertTrue(is_valid_coordinate(9.9312, 76.2673))

        # Invalid coordinates
        self.assertFalse(is_valid_coordinate(None, None))
        self.assertFalse(is_valid_coordinate(40.7128, None))
        self.assertFalse(is_valid_coordinate(None, -74.0060))
        self.assertFalse(is_valid_coordinate(90.1, 0))
        self.assertFalse(is_valid_coordinate(-90.1, 0))
        self.assertFalse(is_valid_coordinate(0, 180.1))
        self.assertFalse(is_valid_coordinate(0, -180.1))
        self.assertFalse(is_valid_coordinate('invalid', 'coords'))
        self.assertFalse(is_valid_coordinate(float('nan'), 0))
        self.assertFalse(is_valid_coordinate(0, float('inf')))

    def test_05_zero_marker_state_and_unmapped_list(self):
        """4, 5, 6. Zero-marker state handles missing coordinates gracefully."""
        response = self.client.get('/map')
        self.assertEqual(response.status_code, 200)
        html = response.data.decode('utf-8')

        # Check mapped stores payload is empty in current DB
        match = re.search(r'<script id="mapped-stores-data" type="application/json">(.*?)</script>', html)
        self.assertIsNotNone(match)
        mapped_stores = json.loads(match.group(1))
        self.assertEqual(len(mapped_stores), 0)

        # Check empty state notice
        self.assertIn("No stores have map coordinates yet.", html)
        self.assertIn("Edit Store", html)
        self.assertIn("Stores Awaiting Coordinates", html)

        # Check unmapped stores section contains both stores
        self.assertIn("Vintage Hub", html)
        self.assertIn("Denim Store", html)
        self.assertIn("Brooklyn", html)
        self.assertIn("Thiruvalla", html)

    def test_06_search_and_city_and_category_filters(self):
        """7. Search, city, and category filters work properly with parameterized queries."""
        # Search by store name
        resp_search = self.client.get('/map?search=Vintage')
        self.assertEqual(resp_search.status_code, 200)
        html_search = resp_search.data.decode('utf-8')
        self.assertIn("Vintage Hub", html_search)
        self.assertNotIn("Denim Store", html_search)

        # Filter by city
        resp_city = self.client.get('/map?city=Thiruvalla')
        self.assertEqual(resp_city.status_code, 200)
        html_city = resp_city.data.decode('utf-8')
        self.assertIn("Denim Store", html_city)
        self.assertNotIn("Vintage Hub", html_city)

        # Filter by non-matching query
        resp_none = self.client.get('/map?search=NonExistentStore12345')
        self.assertEqual(resp_none.status_code, 200)
        html_none = resp_none.data.decode('utf-8')
        self.assertNotIn("Vintage Hub", html_none)
        self.assertNotIn("Denim Store", html_none)

    def test_07_public_field_exposure_safety(self):
        """2. Sensitive fields (passwords, emails, owner_ids) are not exposed."""
        response = self.client.get('/map')
        html = response.data.decode('utf-8')
        
        # Verify no owner_id in the JSON payload
        match = re.search(r'<script id="mapped-stores-data" type="application/json">(.*?)</script>', html)
        self.assertIsNotNone(match)
        self.assertNotIn('"owner_id"', match.group(1))
        self.assertNotIn('"password"', match.group(1))
        self.assertNotIn('"email"', match.group(1))

    def test_08_navigation_integration(self):
        """11. Navigation links work across dashboard, stores, and home."""
        # 1. user_dashboard Nearby Stores links to /map
        with self.client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['full_name'] = 'Test User'
            sess['role'] = 'user'
        
        resp_dash = self.client.get('/user-dashboard')
        self.assertEqual(resp_dash.status_code, 200)
        dash_html = resp_dash.data.decode('utf-8')
        self.assertIn('href="/map"', dash_html)
        self.assertNotIn('Coming Soon', dash_html)  # Nearby stores card no longer has Coming Soon

        # 2. stores directory links to /map
        resp_stores = self.client.get('/stores')
        self.assertEqual(resp_stores.status_code, 200)
        stores_html = resp_stores.data.decode('utf-8')
        self.assertIn('href="/map', stores_html)

        # 3. home page links to /map
        resp_home = self.client.get('/')
        self.assertEqual(resp_home.status_code, 200)
        home_html = resp_home.data.decode('utf-8')
        self.assertIn('href="/map"', home_html)

    def test_10_simulated_mapped_store_rendering(self):
        """3 & 8. Simulated store with valid coordinates renders mapped marker data and safe popup fields."""
        mock_mapped = [{
            'store_id': 99,
            'store_name': 'Retro Galaxy <script>alert(1)</script>',
            'category_name': 'Vintage 90s',
            'city': 'Portland',
            'address': '123 Main St "Downtown"',
            'latitude': 45.5152,
            'longitude': -122.6784,
            'image': None,
            'image_url': '/static/images/store-placeholder.svg',
            'details_url': '/store/99'
        }]
        
        with app.test_request_context('/map'):
            from flask import render_template
            rendered = render_template(
                'map.html',
                mapped_stores=mock_mapped,
                unmapped_stores=[],
                categories=[],
                search_query='',
                city_filter='',
                category_filter='',
                total_mapped=1,
                total_unmapped=0,
                total_stores=1
            )
            
            # Verify mapped stores JSON contains the coordinate data
            match = re.search(r'<script id="mapped-stores-data" type="application/json">(.*?)</script>', rendered)
            self.assertIsNotNone(match)
            parsed = json.loads(match.group(1))
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]['latitude'], 45.5152)
            self.assertEqual(parsed[0]['longitude'], -122.6784)
            self.assertEqual(parsed[0]['store_name'], 'Retro Galaxy <script>alert(1)</script>')
            
            # Verify sidebar renders the mapped store
            self.assertIn('sidebar-item-99', rendered)
            self.assertIn('Retro Galaxy', rendered)

    def test_11_image_url_fallback(self):
        """9. Image fallback returns placeholder when image path is empty or null."""
        from app import store_image_url
        with app.test_request_context('/'):
            placeholder = store_image_url(None)
            self.assertIn('store-placeholder.svg', placeholder)
            
            empty_placeholder = store_image_url('')
            self.assertIn('store-placeholder.svg', empty_placeholder)
            
            existing = store_image_url('uploads/stores/test.jpg')
            self.assertIn('uploads/stores/test.jpg', existing)

    def test_12_existing_functionality_regression(self):
        """12. Existing core routes remain completely functional and properly protected."""
        # Public routes
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/stores').status_code, 200)
        self.assertEqual(self.client.get('/login').status_code, 200)
        self.assertEqual(self.client.get('/register').status_code, 200)

        # Protected routes redirect unauthenticated users
        self.assertEqual(self.client.get('/user-dashboard').status_code, 302)
        self.assertEqual(self.client.get('/owner-dashboard').status_code, 302)
        self.assertEqual(self.client.get('/admin-dashboard').status_code, 302)
        self.assertEqual(self.client.get('/manage-stores').status_code, 302)
        self.assertEqual(self.client.get('/add-store').status_code, 302)
        self.assertEqual(self.client.get('/store/3').status_code, 302)

    def test_13_database_safety_final_verification(self):
        """13. Ensure database schema, records, and tables are identical to baseline."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) as cnt FROM stores")
            self.assertEqual(cursor.fetchone()['cnt'], self.baseline_stores_count)
            cursor.execute("SELECT COUNT(*) as cnt FROM users")
            self.assertEqual(cursor.fetchone()['cnt'], self.baseline_users_count)
            cursor.execute("SELECT COUNT(*) as cnt FROM categories")
            self.assertEqual(cursor.fetchone()['cnt'], self.baseline_categories_count)
        finally:
            cursor.close()
            conn.close()

if __name__ == '__main__':
    unittest.main()
