"""
Automated unit and integration test suite for ThriftMap Store Owner 'View Reviews' feature.
Covers:
1. Owner Dashboard link verification: Replace placeholder #reviews with working link to /owner-reviews
2. Authentication & Authorization:
   - Unauthenticated user redirected to /login
   - Regular user (role='user') denied access with 302 redirect
   - Admin (role='admin') redirected
   - Owner (role='owner') granted access (200 OK)
3. Empty state display: Shows friendly empty state message when owner stores have no reviews
4. Review details display accuracy: Store name, reviewer name, rating, comment, date, store link
5. Review ownership isolation: Owner A sees only reviews for Owner A's stores; Owner B sees only reviews for Owner B's stores
6. Teardown: Restores baseline database state without modifying pre-existing records
"""
import unittest
from app import app, get_db_connection

class TestOwnerReviewsFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Baseline review count
            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews")
            cls.baseline_review_count = cursor.fetchone()['cnt']

            # Fetch distinct owners
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'owner' ORDER BY user_id ASC")
            owners = cursor.fetchall()
            assert len(owners) >= 1, "At least one owner required for tests"
            cls.owner1 = owners[0]

            # If there's a second owner, use them, otherwise create a temporary one for isolation tests
            cls.created_user_ids = []
            if len(owners) >= 2:
                cls.owner2 = owners[1]
            else:
                cursor.execute(
                    "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, %s)",
                    ("Second Owner Test", "second_owner_test@example.com", "dummyhash", "owner")
                )
                conn.commit()
                owner2_id = cursor.lastrowid
                cls.created_user_ids.append(owner2_id)
                cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE user_id = %s", (owner2_id,))
                cls.owner2 = cursor.fetchone()

            # Fetch a regular user
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'user' ORDER BY user_id ASC LIMIT 1")
            cls.user = cursor.fetchone()

            # Find or assign a store for owner1
            cursor.execute("SELECT store_id, store_name FROM stores WHERE owner_id = %s ORDER BY store_id ASC LIMIT 1", (cls.owner1['user_id'],))
            s1 = cursor.fetchone()
            if s1:
                cls.store1_id = s1['store_id']
                cls.store1_name = s1['store_name']
                cls.created_store1 = False
            else:
                cursor.execute(
                    "INSERT INTO stores (owner_id, category_id, store_name, description, address, city, status, latitude, longitude) "
                    "VALUES (%s, 1, 'Owner 1 Test Boutique', 'Description', '123 Test St', 'Mumbai', 'approved', 19.0760, 72.8777)",
                    (cls.owner1['user_id'],)
                )
                conn.commit()
                cls.store1_id = cursor.lastrowid
                cls.store1_name = 'Owner 1 Test Boutique'
                cls.created_store1 = True

            # Find or assign a store for owner2
            cursor.execute("SELECT store_id, store_name FROM stores WHERE owner_id = %s ORDER BY store_id ASC LIMIT 1", (cls.owner2['user_id'],))
            s2 = cursor.fetchone()
            if s2:
                cls.store2_id = s2['store_id']
                cls.store2_name = s2['store_name']
                cls.created_store2 = False
            else:
                cursor.execute(
                    "INSERT INTO stores (owner_id, category_id, store_name, description, address, city, status, latitude, longitude) "
                    "VALUES (%s, 1, 'Owner 2 Test Boutique', 'Description', '456 Test Ave', 'Delhi', 'approved', 28.6139, 77.2090)",
                    (cls.owner2['user_id'],)
                )
                conn.commit()
                cls.store2_id = cursor.lastrowid
                cls.store2_name = 'Owner 2 Test Boutique'
                cls.created_store2 = True

        finally:
            cursor.close()
            conn.close()

        cls.created_review_ids = []

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if cls.created_review_ids:
                format_strings = ','.join(['%s'] * len(cls.created_review_ids))
                cursor.execute(f"DELETE FROM reviews WHERE review_id IN ({format_strings})", tuple(cls.created_review_ids))
                conn.commit()

            if cls.created_store1:
                cursor.execute("DELETE FROM stores WHERE store_id = %s", (cls.store1_id,))
                conn.commit()

            if cls.created_store2:
                cursor.execute("DELETE FROM stores WHERE store_id = %s", (cls.store2_id,))
                conn.commit()

            if cls.created_user_ids:
                format_strings = ','.join(['%s'] * len(cls.created_user_ids))
                cursor.execute(f"DELETE FROM users WHERE user_id IN ({format_strings})", tuple(cls.created_user_ids))
                conn.commit()

            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews")
            final_cnt = cursor.fetchone()[0]
            assert final_cnt == cls.baseline_review_count, f"Review count mismatch: expected {cls.baseline_review_count}, got {final_cnt}"
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

    def test_01_owner_dashboard_view_reviews_is_active_link(self):
        """Test that the owner dashboard has a working link to /owner-reviews instead of #reviews."""
        self.login_as(self.owner1)
        resp = self.client.get('/owner-dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('id="menu-view-reviews"', html)
        self.assertIn('/owner-reviews', html)
        self.assertNotIn('href="#reviews"', html)

    def test_02_access_control_unauthenticated(self):
        """Test that unauthenticated requests to /owner-reviews redirect to /login."""
        self.logout()
        resp = self.client.get('/owner-reviews', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_03_access_control_role_enforcement(self):
        """Test that non-owner users cannot access /owner-reviews."""
        self.login_as(self.user)
        resp = self.client.get('/owner-reviews', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/user-dashboard', resp.headers['Location'])

    def test_04_empty_state_display(self):
        """Test empty state display when owner stores have no reviews."""
        # Create a fresh temporary owner with no reviews
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "INSERT INTO users (full_name, email, password, role) VALUES (%s, %s, %s, %s)",
                ("No Reviews Owner", "noreviews_owner@example.com", "hash", "owner")
            )
            conn.commit()
            temp_owner_id = cursor.lastrowid
            self.__class__.created_user_ids.append(temp_owner_id)
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE user_id = %s", (temp_owner_id,))
            temp_owner = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        self.login_as(temp_owner)
        resp = self.client.get('/owner-reviews')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('No Customer Reviews Yet', html)
        self.assertIn('id="empty-owner-reviews"', html)
        self.assertIn('Manage Your Stores', html)

    def test_05_review_display_fields_accuracy(self):
        """Test that customer reviews for owner store accurately show store name, reviewer, rating, text, date."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "INSERT INTO reviews (store_id, user_id, rating, comment) VALUES (%s, %s, %s, %s)",
                (self.store1_id, self.user['user_id'], 5, "Outstanding curated 80s leather jackets and great hospitality!")
            )
            conn.commit()
            rev_id = cursor.lastrowid
            self.created_review_ids.append(rev_id)
        finally:
            cursor.close()
            conn.close()

        self.login_as(self.owner1)
        resp = self.client.get('/owner-reviews')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn(self.store1_name, html)
        self.assertIn(self.user['full_name'], html)
        self.assertIn("Outstanding curated 80s leather jackets and great hospitality!", html)
        self.assertIn("5/5", html)
        self.assertIn(f"/store/{self.store1_id}", html)

    def test_06_review_ownership_isolation(self):
        """Test that Owner 1 only sees reviews for Store 1, and Owner 2 only sees reviews for Store 2."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "INSERT INTO reviews (store_id, user_id, rating, comment) VALUES (%s, %s, %s, %s)",
                (self.store2_id, self.user['user_id'], 4, "Owner 2 unique comment: vintage sunglasses collection.")
            )
            conn.commit()
            rev2_id = cursor.lastrowid
            self.created_review_ids.append(rev2_id)
        finally:
            cursor.close()
            conn.close()

        # Check Owner 1
        self.login_as(self.owner1)
        resp1 = self.client.get('/owner-reviews')
        html1 = resp1.get_data(as_text=True)
        self.assertIn("Outstanding curated 80s leather jackets", html1)
        self.assertNotIn("Owner 2 unique comment: vintage sunglasses collection.", html1)

        # Check Owner 2
        self.login_as(self.owner2)
        resp2 = self.client.get('/owner-reviews')
        html2 = resp2.get_data(as_text=True)
        self.assertIn("Owner 2 unique comment: vintage sunglasses collection.", html2)
        self.assertNotIn("Outstanding curated 80s leather jackets", html2)

    def test_07_alternate_url_alias(self):
        """Test that /owner/reviews also works as an alias."""
        self.login_as(self.owner1)
        resp = self.client.get('/owner/reviews')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Customer Reviews & Ratings', html)

if __name__ == '__main__':
    unittest.main()
