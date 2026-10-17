"""
Automated unit and integration test suite for ThriftMap 'My Reviews' feature.
Covers:
1. Dashboard link verification: Replace "Future Feature" with working link to /my-reviews
2. Authentication enforcement: Protected route redirects unauthenticated users to /login
3. Empty state display: Friendly message and CTA button when user has 0 reviews
4. Review display accuracy: Correct store name, link to store, star rating, comment, date
5. Ownership & Access Control isolation: User A sees only User A's reviews; User B sees only User B's reviews
6. Edit functionality reuse: Edit review via existing edit_review endpoint with next redirect
7. Delete functionality reuse: Delete review via existing delete_review endpoint with next redirect
8. Unauthorized edit/delete prevention: 403 Forbidden when a user tries to modify another user's review
9. Safe teardown: Restores baseline database state without modifying existing records
"""
import unittest
from app import app, get_db_connection

class TestMyReviewsFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Baseline count
            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews")
            cls.baseline_review_count = cursor.fetchone()['cnt']

            # Find an approved store
            cursor.execute("SELECT store_id, store_name, owner_id FROM stores WHERE status = 'approved' ORDER BY store_id ASC LIMIT 1")
            store = cursor.fetchone()
            assert store is not None, "At least one approved store must exist in DB for testing"
            cls.test_store_id = store['store_id']
            cls.test_store_name = store['store_name']

            # Second approved store if available
            cursor.execute("SELECT store_id, store_name FROM stores WHERE status = 'approved' AND store_id != %s ORDER BY store_id ASC LIMIT 1", (cls.test_store_id,))
            second_store = cursor.fetchone()
            cls.test_store_2_id = second_store['store_id'] if second_store else cls.test_store_id
            cls.test_store_2_name = second_store['store_name'] if second_store else cls.test_store_name

            # Fetch two distinct users
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'user' ORDER BY user_id ASC")
            users = cursor.fetchall()
            assert len(users) >= 2, "At least two users required for isolation testing"
            cls.user1 = users[0]
            cls.user2 = users[1]

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

    def test_01_dashboard_my_reviews_card_is_active_link(self):
        """Test that user dashboard displays an active link to /my-reviews without 'Future Feature'."""
        self.login_as(self.user1)
        resp = self.client.get('/user-dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Must have working link to my_reviews
        self.assertIn('/my-reviews', html)
        self.assertIn('id="menu-my-reviews"', html)
        self.assertIn('My Reviews', html)

        # Must NOT contain "Future Feature" in the My Reviews card
        card_start = html.find('id="menu-my-reviews"')
        self.assertNotEqual(card_start, -1)
        card_content = html[card_start:card_start + 500]
        self.assertNotIn('Future Feature', card_content)

    def test_02_unauthenticated_access_redirects_to_login(self):
        """Test that unauthenticated requests to /my-reviews redirect to /login."""
        self.logout()
        resp = self.client.get('/my-reviews', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

        # Following redirect shows flash message
        follow_resp = self.client.get('/my-reviews', follow_redirects=True)
        html = follow_resp.get_data(as_text=True)
        self.assertIn('Please log in to view your reviews', html)

    def test_03_empty_state_when_user_has_no_reviews(self):
        """Test that a user with 0 reviews sees a friendly empty state message."""
        # Ensure user1 has no reviews currently
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM reviews WHERE user_id = %s", (self.user1['user_id'],))
            conn.commit()
        finally:
            cursor.close()
            conn.close()

        self.login_as(self.user1)
        resp = self.client.get('/my-reviews')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('No Reviews Written Yet', html)
        self.assertIn('Browse Stores to Review', html)
        self.assertIn('/stores', html)

    def test_04_review_display_with_store_link_rating_comment_date(self):
        """Test that user's reviews are accurately displayed with store name, rating, text, date and link."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "INSERT INTO reviews (store_id, user_id, rating, comment) VALUES (%s, %s, %s, %s)",
                (self.test_store_id, self.user1['user_id'], 5, "Remarkable vintage varsity jackets and wonderful store staff!")
            )
            conn.commit()
            review_id = cursor.lastrowid
            self.created_review_ids.append(review_id)
        finally:
            cursor.close()
            conn.close()

        self.login_as(self.user1)
        resp = self.client.get('/my-reviews')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn(self.test_store_name, html)
        self.assertIn(f"/store/{self.test_store_id}", html)
        self.assertIn("Remarkable vintage varsity jackets and wonderful store staff!", html)
        self.assertIn("5/5", html)
        self.assertIn(f"btn-toggle-edit-{review_id}", html)
        self.assertIn(f"deleteReviewModal-{review_id}", html)

    def test_05_isolation_and_ownership(self):
        """Test that User A only sees User A's reviews, and User B only sees User B's reviews."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # User 2 writes a review
            cursor.execute(
                "INSERT INTO reviews (store_id, user_id, rating, comment) VALUES (%s, %s, %s, %s)",
                (self.test_store_2_id, self.user2['user_id'], 4, "Unique user 2 comment: excellent retro vinyls.")
            )
            conn.commit()
            r2_id = cursor.lastrowid
            self.created_review_ids.append(r2_id)
        finally:
            cursor.close()
            conn.close()

        # Check User 1: sees User 1's review, NOT User 2's review
        self.login_as(self.user1)
        resp1 = self.client.get('/my-reviews')
        html1 = resp1.get_data(as_text=True)
        self.assertIn("Remarkable vintage varsity jackets", html1)
        self.assertNotIn("Unique user 2 comment: excellent retro vinyls.", html1)

        # Check User 2: sees User 2's review, NOT User 1's review
        self.login_as(self.user2)
        resp2 = self.client.get('/my-reviews')
        html2 = resp2.get_data(as_text=True)
        self.assertIn("Unique user 2 comment: excellent retro vinyls.", html2)
        self.assertNotIn("Remarkable vintage varsity jackets", html2)

    def test_06_edit_review_from_my_reviews(self):
        """Test editing a review using edit_review route with next=/my-reviews."""
        review_id = self.created_review_ids[0]  # user 1 review
        self.login_as(self.user1)

        edit_data = {
            'rating': '4',
            'comment': 'Updated review: exceptional quality and lovely ambience.',
            'next': '/my-reviews'
        }
        resp = self.client.post(f"/review/{review_id}/edit", data=edit_data, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/my-reviews')

        # Follow redirect and verify update
        get_resp = self.client.get('/my-reviews')
        html = get_resp.get_data(as_text=True)
        self.assertIn('Your review has been updated successfully!', html)
        self.assertIn('Updated review: exceptional quality and lovely ambience.', html)
        self.assertIn('4/5', html)

    def test_07_unauthorized_edit_prevented(self):
        """Test that user2 cannot edit user1's review (403 Forbidden)."""
        review_id = self.created_review_ids[0]  # user 1 review
        self.login_as(self.user2)

        malicious_data = {
            'rating': '1',
            'comment': 'Hacked review attempt',
            'next': '/my-reviews'
        }
        resp = self.client.post(f"/review/{review_id}/edit", data=malicious_data)
        self.assertEqual(resp.status_code, 403)

    def test_08_unauthorized_delete_prevented(self):
        """Test that user2 cannot delete user1's review (403 Forbidden)."""
        review_id = self.created_review_ids[0]  # user 1 review
        self.login_as(self.user2)

        resp = self.client.post(f"/review/{review_id}/delete", data={'next': '/my-reviews'})
        self.assertEqual(resp.status_code, 403)

    def test_09_delete_review_from_my_reviews(self):
        """Test deleting a review using delete_review route with next=/my-reviews."""
        review_id = self.created_review_ids[0]  # user 1 review
        self.login_as(self.user1)

        resp = self.client.post(f"/review/{review_id}/delete", data={'next': '/my-reviews'}, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers['Location'], '/my-reviews')

        # Follow redirect and verify review is gone and empty state is displayed
        get_resp = self.client.get('/my-reviews')
        html = get_resp.get_data(as_text=True)
        self.assertIn('Your review has been deleted successfully.', html)
        self.assertIn('No Reviews Written Yet', html)

        # Remove from teardown list since already deleted
        self.created_review_ids.remove(review_id)

if __name__ == '__main__':
    unittest.main()
