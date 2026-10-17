"""
Focused automated test suite for ThriftMap Store Reviews and Ratings.
Tests:
- Store display with no reviews (clear empty state, 0 count, unrated)
- Review creation by logged-in users (1-5 star rating + written comment)
- Review display on store-detail page
- Average rating calculation and review count
- Duplicate review prevention (one review per user per store)
- Server-side validation for invalid ratings and review lengths
- Review editing by review author only
- Review deletion by review author only
- Unauthorized access prevention (preventing store owners or other users from modifying reviews)
- Unauthenticated access gating
- XSS prevention / safe HTML rendering
- Clean teardown ensuring existing baseline database records are preserved untouched.
"""
import unittest
from app import app, get_db_connection

class TestStoreReviewsAndRatings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        # Capture baseline review count and store snapshot
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews")
            cls.baseline_review_count = cursor.fetchone()['cnt']

            # Find an approved store to use for testing
            cursor.execute("SELECT store_id, store_name, owner_id FROM stores WHERE status = 'approved' ORDER BY store_id ASC LIMIT 1")
            store = cursor.fetchone()
            assert store is not None, "At least one approved store must exist in DB for testing"
            cls.test_store_id = store['store_id']
            cls.test_store_name = store['store_name']
            cls.test_store_owner_id = store['owner_id']

            # Fetch distinct users for testing
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE role = 'user' ORDER BY user_id ASC")
            users = cursor.fetchall()
            assert len(users) >= 2, "Need at least two user accounts for testing"
            cls.user1 = users[0]
            cls.user2 = users[1]

            # Fetch store owner
            cursor.execute("SELECT user_id, full_name, email, role FROM users WHERE user_id = %s", (cls.test_store_owner_id,))
            cls.owner = cursor.fetchone()

        finally:
            cursor.close()
            conn.close()

        cls.created_review_ids = []

    @classmethod
    def tearDownClass(cls):
        # Strictly preserve baseline database records: clean up all test-created reviews
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if cls.created_review_ids:
                format_strings = ','.join(['%s'] * len(cls.created_review_ids))
                cursor.execute(f"DELETE FROM reviews WHERE review_id IN ({format_strings})", tuple(cls.created_review_ids))
                conn.commit()

            # Ensure review count is back to baseline
            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews")
            final_cnt = cursor.fetchone()[0]
            assert final_cnt == cls.baseline_review_count, f"Review count mismatch: expected {cls.baseline_review_count}, got {final_cnt}"
        finally:
            cursor.close()
            conn.close()

    def setUp(self):
        self.client = app.test_client()

    def login_as(self, user):
        """Helper to simulate session login."""
        with self.client.session_transaction() as sess:
            sess['user_id'] = user['user_id']
            sess['full_name'] = user['full_name']
            sess['role'] = user['role']

    def logout(self):
        """Helper to clear session."""
        with self.client.session_transaction() as sess:
            sess.clear()

    def test_01_store_display_with_no_reviews(self):
        """Test store details page when store has no reviews."""
        self.login_as(self.user1)
        resp = self.client.get(f"/store/{self.test_store_id}")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Customer Reviews & Ratings", html)
        self.assertIn("No reviews yet", html)
        self.assertIn("write-review-container", html)
        self.assertIn("id=\"btn-submit-review\"", html)

    def test_02_create_review_success(self):
        """Test submitting a valid 1-5 star review."""
        self.login_as(self.user1)
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '5', 'comment': 'Fantastic curated vintage denim and leather jackets!'},
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Your review has been published successfully!", html)
        self.assertIn("Fantastic curated vintage denim", html)
        self.assertIn("5.0", html)  # average rating
        self.assertIn("1 Review", html)

        # Verify in database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT review_id, rating, comment FROM reviews WHERE store_id = %s AND user_id = %s",
                           (self.test_store_id, self.user1['user_id']))
            rev = cursor.fetchone()
            self.assertIsNotNone(rev)
            self.assertEqual(rev['rating'], 5)
            self.assertEqual(rev['comment'], 'Fantastic curated vintage denim and leather jackets!')
            self.__class__.created_review_ids.append(rev['review_id'])
        finally:
            cursor.close()
            conn.close()

    def test_03_duplicate_review_prevention(self):
        """Test that a user cannot submit more than one review for the same store."""
        self.login_as(self.user1)
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '4', 'comment': 'Attempting a second review on the same store.'},
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 400)
        html = resp.get_data(as_text=True)
        self.assertIn("You have already reviewed this store", html)

        # Verify DB still has only 1 review from user1
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews WHERE store_id = %s AND user_id = %s",
                           (self.test_store_id, self.user1['user_id']))
            self.assertEqual(cursor.fetchone()['cnt'], 1)
        finally:
            cursor.close()
            conn.close()

    def test_04_invalid_rating_and_comment_validation(self):
        """Test server-side validation for rating values and comment length."""
        self.login_as(self.user2)

        # 1. Rating out of range (0)
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '0', 'comment': 'Valid length comment here.'}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Rating must be an integer between 1 and 5", resp.get_data(as_text=True))

        # 2. Rating out of range (6)
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '6', 'comment': 'Valid length comment here.'}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Rating must be an integer between 1 and 5", resp.get_data(as_text=True))

        # 3. Rating non-numeric ('five')
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': 'five', 'comment': 'Valid length comment here.'}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Rating must be a valid number", resp.get_data(as_text=True))

        # 4. Comment empty
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '4', 'comment': '   '}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Review comment cannot be empty", resp.get_data(as_text=True))

        # 5. Comment too short (< 3 chars)
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '4', 'comment': 'Ok'}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("at least 3 characters", resp.get_data(as_text=True))

        # 6. Comment too long (> 1000 chars)
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '4', 'comment': 'X' * 1001}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("must not exceed 1,000 characters", resp.get_data(as_text=True))

        # Verify user2 has no reviews created
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT COUNT(*) AS cnt FROM reviews WHERE store_id = %s AND user_id = %s",
                           (self.test_store_id, self.user2['user_id']))
            self.assertEqual(cursor.fetchone()['cnt'], 0)
        finally:
            cursor.close()
            conn.close()

    def test_05_average_rating_calculation(self):
        """Test calculation of average rating with multiple reviews."""
        # User 1 already gave 5 stars
        # User 2 gives 3 stars
        self.login_as(self.user2)
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '3', 'comment': 'Decent collection, but prices were somewhat steep.'},
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Average of 5 and 3 is 4.0
        self.assertIn("4.0", html)
        self.assertIn("2 Reviews", html)

        # Record review_id for teardown
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT review_id FROM reviews WHERE store_id = %s AND user_id = %s",
                           (self.test_store_id, self.user2['user_id']))
            rev = cursor.fetchone()
            self.assertIsNotNone(rev)
            self.__class__.created_review_ids.append(rev['review_id'])
        finally:
            cursor.close()
            conn.close()

    def test_06_edit_own_review(self):
        """Test editing own review by the review author."""
        self.login_as(self.user1)
        user1_rev_id = self.__class__.created_review_ids[0]

        # Edit review from 5 stars to 4 stars and update comment
        resp = self.client.post(
            f"/review/{user1_rev_id}/edit",
            data={'rating': '4', 'comment': 'Updated review: good quality clothing overall.'},
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Your review has been updated successfully!", html)
        self.assertIn("Updated review: good quality clothing overall.", html)

        # Average of 4 and 3 is 3.5
        self.assertIn("3.5", html)

        # Verify DB updated
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT rating, comment FROM reviews WHERE review_id = %s", (user1_rev_id,))
            rev = cursor.fetchone()
            self.assertEqual(rev['rating'], 4)
            self.assertEqual(rev['comment'], 'Updated review: good quality clothing overall.')
        finally:
            cursor.close()
            conn.close()

    def test_07_unauthorized_edit_and_delete_prevention(self):
        """Test that store owners and other users CANNOT edit or delete someone else's review."""
        user1_rev_id = self.__class__.created_review_ids[0]

        # 1. User 2 tries to edit User 1's review -> 403 Forbidden
        self.login_as(self.user2)
        resp = self.client.post(
            f"/review/{user1_rev_id}/edit",
            data={'rating': '1', 'comment': 'Malicious modification of someone elses review.'}
        )
        self.assertEqual(resp.status_code, 403)

        # 2. Store Owner tries to edit User 1's review -> 403 Forbidden
        if self.owner:
            self.login_as(self.owner)
            resp = self.client.post(
                f"/review/{user1_rev_id}/edit",
                data={'rating': '5', 'comment': 'Owner inflating customer rating.'}
            )
            self.assertEqual(resp.status_code, 403)

            # 3. Store Owner tries to delete User 1's review -> 403 Forbidden
            resp = self.client.post(f"/review/{user1_rev_id}/delete")
            self.assertEqual(resp.status_code, 403)

        # 4. User 2 tries to delete User 1's review -> 403 Forbidden
        self.login_as(self.user2)
        resp = self.client.post(f"/review/{user1_rev_id}/delete")
        self.assertEqual(resp.status_code, 403)

        # Verify User 1's review is completely intact in DB
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT rating, comment FROM reviews WHERE review_id = %s", (user1_rev_id,))
            rev = cursor.fetchone()
            self.assertEqual(rev['rating'], 4)
            self.assertEqual(rev['comment'], 'Updated review: good quality clothing overall.')
        finally:
            cursor.close()
            conn.close()

    def test_08_delete_own_review(self):
        """Test deleting own review by author, and verify average rating recalculation."""
        # User 2 deletes their own review (was 3 stars)
        self.login_as(self.user2)
        user2_rev_id = self.__class__.created_review_ids[1]

        resp = self.client.post(f"/review/{user2_rev_id}/delete", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn("Your review has been deleted successfully.", html)

        # Now only User 1's 4-star review remains -> average should be 4.0
        self.assertIn("4.0", html)
        self.assertIn("1 Review", html)

        # Verify row is gone from DB
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT review_id FROM reviews WHERE review_id = %s", (user2_rev_id,))
            self.assertIsNone(cursor.fetchone())
        finally:
            cursor.close()
            conn.close()

        # Remove from created_review_ids tracking
        self.__class__.created_review_ids.remove(user2_rev_id)

    def test_09_unauthenticated_access_gating(self):
        """Test unauthenticated visitors are redirected to login."""
        self.logout()
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '5', 'comment': 'Unauthenticated review attempt.'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.headers.get('Location', ''))

    def test_10_safe_rendering_and_xss_protection(self):
        """Test that user submitted reviews safely escape HTML tags."""
        self.login_as(self.user2)
        xss_payload = '<script>alert("xss")</script><b>Bold vintage</b>'
        resp = self.client.post(
            f"/store/{self.test_store_id}/review",
            data={'rating': '5', 'comment': xss_payload},
            follow_redirects=True
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Unescaped raw script tag must NOT be in the HTML output
        self.assertNotIn('<script>alert("xss")</script>', html)
        # Escaped script tag must be present
        self.assertIn('&lt;script&gt;alert(&#34;xss&#34;)&lt;/script&gt;', html)

        # Record review_id for teardown
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT review_id FROM reviews WHERE store_id = %s AND user_id = %s",
                           (self.test_store_id, self.user2['user_id']))
            rev = cursor.fetchone()
            self.assertIsNotNone(rev)
            self.__class__.created_review_ids.append(rev['review_id'])
        finally:
            cursor.close()
            conn.close()

if __name__ == '__main__':
    unittest.main()
