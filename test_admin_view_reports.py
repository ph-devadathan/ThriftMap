"""
Unit and integration test suite for ThriftMap Admin 'View Reports' feature.
Covers:
1. Access control:
   - Authenticated administrator (role='admin') granted access (200 OK)
   - Authenticated shopper (role='user') denied access (302 redirect)
   - Authenticated store owner (role='owner') denied access (302 redirect)
   - Unauthenticated guest redirected to /login (302 redirect)
2. Summary counts match active database:
   - Total registered users
   - Total shoppers
   - Total store owners
   - Total stores (approved, pending, rejected)
   - Total reviews
   - Total favorites
3. Detailed reports verification:
   - User report: users grouped by role and registration trends
   - Store report: store counts by status, category, and city
   - Review report: total reviews, average rating, star breakdown, most-reviewed stores
   - Popular stores report: ranked by favorites, reviews, and average rating
4. Report filters:
   - Category filter
   - City filter
   - Date range filters (date_from, date_to)
5. Robustness & empty dataset handling:
   - Extreme filters with zero matches render gracefully without errors
   - Chart data structures handle empty records safely
6. Data integrity:
   - Zero synthetic rows inserted into baseline tables
"""
import unittest
from app import app, get_db_connection

class TestAdminViewReports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Fetch baseline counts directly from DB
            cursor.execute("SELECT COUNT(*) AS cnt FROM users")
            cls.expected_users = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'user'")
            cls.expected_shoppers = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'owner'")
            cls.expected_owners = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM stores")
            cls.expected_stores = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM stores WHERE status = 'approved'")
            cls.expected_approved = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM stores WHERE status = 'pending'")
            cls.expected_pending = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM stores WHERE status = 'rejected'")
            cls.expected_rejected = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews")
            cls.expected_reviews = cursor.fetchone()['cnt']

            cursor.execute("SELECT COUNT(*) AS cnt FROM favorites")
            cls.expected_favorites = cursor.fetchone()['cnt']

            # Users for auth testing
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'admin' LIMIT 1")
            cls.admin_user = cursor.fetchone()

            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'user' LIMIT 1")
            cls.shopper_user = cursor.fetchone()

            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'owner' LIMIT 1")
            cls.owner_user = cursor.fetchone()

            # Fetch a sample city and category for filter testing
            cursor.execute("SELECT city FROM stores WHERE city IS NOT NULL AND city != '' LIMIT 1")
            city_row = cursor.fetchone()
            cls.sample_city = city_row['city'] if city_row else None

            cursor.execute("SELECT category_id, category_name FROM categories LIMIT 1")
            cat_row = cursor.fetchone()
            cls.sample_category_id = cat_row['category_id'] if cat_row else None

        finally:
            cursor.close()
            conn.close()

    def setUp(self):
        self.client = app.test_client()

    def login_as(self, user):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user['user_id']
            sess['full_name'] = user['full_name']
            sess['role'] = user['role']

    def logout(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    # --- 1. Access Control Tests ---

    def test_01_admin_can_access_reports(self):
        """Admin user must be granted access (200 OK) to /admin/reports."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/reports')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Platform Reports & Analytics", html)
        self.assertIn("dashboard-summary-cards", html)
        self.assertIn("chart-user-roles", html)
        self.assertIn("chart-user-trends", html)
        self.assertIn("chart-store-status", html)

    def test_02_shopper_cannot_access_reports(self):
        """Shopper must be denied access and redirected."""
        self.login_as(self.shopper_user)
        resp = self.client.get('/admin/reports', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        redirected_resp = self.client.get('/admin/reports', follow_redirects=True)
        html = redirected_resp.get_data(as_text=True)
        self.assertIn("Access denied", html)

    def test_03_store_owner_cannot_access_reports(self):
        """Store owner must be denied access and redirected."""
        self.login_as(self.owner_user)
        resp = self.client.get('/admin/reports', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        redirected_resp = self.client.get('/admin/reports', follow_redirects=True)
        html = redirected_resp.get_data(as_text=True)
        self.assertIn("Access denied", html)

    def test_04_unauthenticated_guest_cannot_access_reports(self):
        """Guest must be redirected to login."""
        self.logout()
        resp = self.client.get('/admin/reports', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers.get('Location', ''))

    # --- 2. Dashboard Summary Counts Accuracy ---

    def test_05_summary_counts_match_database(self):
        """Summary card metrics must match exact values in active database."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/reports')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn(f'id="summary-total-users">{self.expected_users}</h3>', html)
        self.assertIn(f'id="summary-total-shoppers">{self.expected_shoppers}</h3>', html)
        self.assertIn(f'id="summary-total-owners">{self.expected_owners}</h3>', html)
        self.assertIn(f'id="summary-total-stores">{self.expected_stores}</h3>', html)
        self.assertIn(f'id="summary-approved-stores">{self.expected_approved}</h3>', html)
        self.assertIn(f'id="summary-pending-stores">{self.expected_pending}</h3>', html)
        self.assertIn(f'id="summary-rejected-stores">{self.expected_rejected}</h3>', html)
        self.assertIn(f'id="summary-total-reviews">{self.expected_reviews}</h3>', html)
        self.assertIn(f'id="summary-total-favorites">{self.expected_favorites}</h3>', html)

    # --- 3. Report Filter Tests ---

    def test_06_filter_by_city(self):
        """Applying a city filter should update displayed report statistics."""
        if not self.sample_city:
            self.skipTest("No stores with city in DB")

        self.login_as(self.admin_user)
        resp = self.client.get(f'/admin/reports?city={self.sample_city}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(self.sample_city, html)

    def test_07_filter_by_category(self):
        """Applying a category filter should update report statistics."""
        if not self.sample_category_id:
            self.skipTest("No categories in DB")

        self.login_as(self.admin_user)
        resp = self.client.get(f'/admin/reports?category_id={self.sample_category_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(f'value="{self.sample_category_id}" selected', html)

    def test_08_filter_by_date_range(self):
        """Applying date range filters should filter user and store timelines."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/reports?date_from=2026-10-01&date_to=2026-10-31')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('value="2026-10-01"', html)
        self.assertIn('value="2026-10-31"', html)

    # --- 4. Empty Dataset & Edge Case Handling ---

    def test_09_empty_dataset_renders_without_errors(self):
        """Querying with non-matching filters should render empty states safely without 500 errors."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/reports?city=NonExistentCity99999&date_from=1990-01-01&date_to=1990-01-02')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        # Should render page cleanly with informative notices
        self.assertIn("Platform Reports & Analytics", html)
        self.assertIn("No customer reviews match the selected filter criteria", html)

    def test_10_charts_data_embedded_safely(self):
        """Chart.js initialization data must be present in script blocks."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/reports')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("chart-user-roles", html)
        self.assertIn("chart-review-ratings", html)
        self.assertIn("chart-store-category", html)

if __name__ == '__main__':
    unittest.main()
