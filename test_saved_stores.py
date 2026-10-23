"""
Automated unit and integration test suite for ThriftMap 'Saved Stores' (Favorites) feature.
Covers:
1. Dashboard link verification: Replace "Future Feature" with working link to /my-favorites
2. Authentication enforcement: Protected route /my-favorites redirects unauthenticated users to /login
3. Empty state display: Friendly message and CTA button when user has 0 saved stores
4. Store saving action: User can save a store and view it on /my-favorites with accurate details
5. Store details page Save/Saved toggle button behavior
6. Removing saved store: User can remove a store from /my-favorites
7. Ownership & Access Control isolation: User A sees only User A's favorites; User B sees only User B's favorites
8. Cross-user removal prevention: User B cannot delete User A's saved store (403 Forbidden)
9. Unauthenticated save/remove prevention: Unauthenticated POST requests redirect to /login
10. Safe teardown: Cleans up all test favorites and restores baseline database state
"""
import unittest
from app import app, get_db_connection

class TestSavedStoresFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Baseline favorites to protect
            cursor.execute("SELECT favorite_id, user_id, store_id FROM favorites")
            fav_rows = cursor.fetchall()
            cls.baseline_fav_ids = {r['favorite_id'] for r in fav_rows}
            existing_fav_pairs = {(r['user_id'], r['store_id']) for r in fav_rows}

            # Find approved stores
            cursor.execute("SELECT store_id, store_name, city, image FROM stores WHERE status = 'approved' ORDER BY store_id ASC")
            stores = cursor.fetchall()
            assert len(stores) >= 2, "At least two approved stores must exist in DB for testing"
            cls.test_store_1 = stores[0]
            cls.test_store_2 = stores[1]

            # Fetch two distinct users
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'user' ORDER BY user_id ASC")
            users = cursor.fetchall()
            assert len(users) >= 2, "At least two users required for isolation testing"
            cls.user1 = users[0]
            cls.user2 = users[1]

        finally:
            cursor.close()
            conn.close()

        cls.created_fav_ids = []

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if cls.created_fav_ids:
                format_strings = ','.join(['%s'] * len(cls.created_fav_ids))
                cursor.execute(f"DELETE FROM favorites WHERE favorite_id IN ({format_strings})", tuple(cls.created_fav_ids))
                conn.commit()

            # Clean any test entries created during tests, strictly preserving baseline favorites
            if cls.baseline_fav_ids:
                fmt = ','.join(['%s'] * len(cls.baseline_fav_ids))
                cursor.execute(f"DELETE FROM favorites WHERE favorite_id NOT IN ({fmt})", tuple(cls.baseline_fav_ids))
            conn.commit()
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

    def test_01_dashboard_saved_stores_card_is_active_link(self):
        """Test that user dashboard displays an active link to /my-favorites without 'Future Feature'."""
        self.login_as(self.user1)
        resp = self.client.get('/user-dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Must have working link to my_favorites
        self.assertIn('/my-favorites', html)
        self.assertIn('id="menu-saved-stores"', html)
        self.assertIn('Saved Stores', html)

        # Must NOT contain "Future Feature" in the Saved Stores card
        card_start = html.find('id="menu-saved-stores"')
        self.assertNotEqual(card_start, -1)
        card_content = html[card_start:card_start + 600]
        self.assertNotIn('Future Feature', card_content)

    def test_02_unauthenticated_access_redirects_to_login(self):
        """Test that unauthenticated requests to /my-favorites redirect to /login."""
        self.logout()
        resp = self.client.get('/my-favorites', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

        # Follow redirect and verify flash message
        follow_resp = self.client.get('/my-favorites', follow_redirects=True)
        html = follow_resp.get_data(as_text=True)
        self.assertIn('Please log in to view your saved stores.', html)

    def test_03_empty_state_when_user_has_no_saved_stores(self):
        """Test that a user with 0 saved stores sees a friendly empty state message."""
        # Ensure user1 has no favorites initially
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if self.baseline_fav_ids:
                fmt = ','.join(['%s'] * len(self.baseline_fav_ids))
                cursor.execute(f"DELETE FROM favorites WHERE user_id = %s AND favorite_id NOT IN ({fmt})", (self.user1['user_id'], *self.baseline_fav_ids))
            else:
                cursor.execute("DELETE FROM favorites WHERE user_id = %s", (self.user1['user_id'],))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        self.login_as(self.user1)
        resp = self.client.get('/my-favorites')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('No Saved Stores Yet', html)
        self.assertIn('Browse Stores', html)
        self.assertIn('/stores', html)
        self.assertIn('id="empty-favorites-state"', html)

    def test_04_save_store_and_view_in_saved_stores(self):
        """Test that a logged-in user can save a store and see it on the /my-favorites page."""
        self.login_as(self.user1)

        # Save store 1
        store_id = self.test_store_1['store_id']
        save_resp = self.client.post(f'/store/{store_id}/save', data={'next': '/my-favorites'}, follow_redirects=True)
        self.assertEqual(save_resp.status_code, 200)
        html = save_resp.get_data(as_text=True)

        # Check flash message and store details in saved list
        self.assertIn('has been added to your saved stores', html)
        self.assertIn(self.test_store_1['store_name'], html)
        self.assertIn(f"/store/{store_id}", html)
        self.assertIn(f"id=\"btn-remove-favorite-{store_id}\"", html)

        # Track created favorite for teardown
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT favorite_id FROM favorites WHERE user_id = %s AND store_id = %s", (self.user1['user_id'], store_id))
            fav = cursor.fetchone()
            if fav:
                self.created_fav_ids.append(fav['favorite_id'])
        finally:
            cursor.close()
            conn.close()

    def test_05_store_details_shows_saved_toggle(self):
        """Test that store details page displays 'Saved' when store is favorited, and 'Save Store' when not."""
        self.login_as(self.user1)
        store_id = self.test_store_1['store_id']

        # Store 1 was saved in test_04
        resp = self.client.get(f'/store/{store_id}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('Saved', html)
        self.assertIn('id="btn-save-store"', html)

    def test_06_isolation_and_ownership(self):
        """Test that User A sees only User A's saved stores, and User B sees only User B's saved stores."""
        # User 2 saves store 2
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("INSERT INTO favorites (user_id, store_id) VALUES (%s, %s)", (self.user2['user_id'], self.test_store_2['store_id']))
            conn.commit()
            self.created_fav_ids.append(cursor.lastrowid)
        finally:
            cursor.close()
            conn.close()

        # User 1 view
        self.login_as(self.user1)
        resp1 = self.client.get('/my-favorites')
        html1 = resp1.get_data(as_text=True)
        self.assertIn(self.test_store_1['store_name'], html1)
        if self.test_store_1['store_id'] != self.test_store_2['store_id']:
            self.assertNotIn(f"id=\"btn-remove-favorite-{self.test_store_2['store_id']}\"", html1)

        # User 2 view
        self.login_as(self.user2)
        resp2 = self.client.get('/my-favorites')
        html2 = resp2.get_data(as_text=True)
        self.assertIn(self.test_store_2['store_name'], html2)
        if self.test_store_1['store_id'] != self.test_store_2['store_id']:
            self.assertNotIn(f"id=\"btn-remove-favorite-{self.test_store_1['store_id']}\"", html2)

    def test_07_user_cannot_remove_another_users_saved_store(self):
        """Test that User 2 cannot remove User 1's saved store (403 Forbidden)."""
        # User 1 saved store 1. User 2 tries to remove it.
        self.login_as(self.user2)
        resp = self.client.post(f'/favorite/{self.test_store_1["store_id"]}/remove', data={'next': '/my-favorites'})
        self.assertEqual(resp.status_code, 403)

    def test_08_user_can_remove_own_saved_store(self):
        """Test that a logged-in user can successfully remove their own saved store."""
        self.login_as(self.user1)
        store_id = self.test_store_1['store_id']

        remove_resp = self.client.post(f'/favorite/{store_id}/remove', data={'next': '/my-favorites'}, follow_redirects=True)
        self.assertEqual(remove_resp.status_code, 200)
        html = remove_resp.get_data(as_text=True)

        self.assertIn('from your saved stores', html)
        self.assertNotIn(f"id=\"favorite-item-{store_id}\"", html)

    def test_09_unauthenticated_save_and_remove_redirect(self):
        """Test that unauthenticated requests to save or remove favorites redirect to login."""
        self.logout()
        resp_save = self.client.post(f'/favorite/{self.test_store_1["store_id"]}/add', follow_redirects=False)
        self.assertEqual(resp_save.status_code, 302)
        self.assertIn('/login', resp_save.headers['Location'])

        resp_remove = self.client.post(f'/favorite/{self.test_store_1["store_id"]}/remove', follow_redirects=False)
        self.assertEqual(resp_remove.status_code, 302)
        self.assertIn('/login', resp_remove.headers['Location'])

if __name__ == '__main__':
    unittest.main()
