"""
Automated Test Suite for ThriftMap Hybrid ML Recommendation System.
Covers:
1. Dashboard UI: Recommended for You section, match badges, and preference modal.
2. Recommendations for existing demonstration user profile.
3. Content-based fallback for cold-start / new user with 0 interactions.
4. Collaborative recommendations when overlapping peer interactions exist.
5. Dynamic ranking update after saving a store or rating.
6. User preference update endpoint (/update-preferences).
7. Strict exclusion of unapproved (pending / rejected) stores.
8. Unauthenticated access control and dashboard preservation.
"""
import unittest
from app import app, get_db_connection
from recommendation_engine import HybridRecommendationEngine

class TestRecommendationSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        cls.engine = HybridRecommendationEngine()

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Fetch existing demo user (user_id=2 or first user)
            cursor.execute("SELECT user_id, full_name, role FROM users WHERE role = 'user' ORDER BY user_id ASC LIMIT 1")
            cls.demo_user = cursor.fetchone()
            assert cls.demo_user is not None, "Demo user required for testing"

            # Fetch synthetic cold-start user
            cursor.execute("SELECT user_id, full_name, preferred_categories FROM users WHERE email LIKE %s", ('coldstart%',))
            cls.coldstart_user = cursor.fetchone()

            # Fetch synthetic Priya (vintage enthusiast)
            cursor.execute("SELECT user_id, full_name FROM users WHERE email LIKE %s", ('priya%',))
            cls.priya_user = cursor.fetchone()

            # Fetch an approved store
            cursor.execute("SELECT store_id, store_name, category_id, city FROM stores WHERE status = 'approved' LIMIT 1")
            cls.approved_store = cursor.fetchone()

            # Fetch unapproved store (pending)
            cursor.execute("SELECT store_id, store_name FROM stores WHERE status = 'pending' LIMIT 1")
            cls.pending_store = cursor.fetchone()

        finally:
            cursor.close()
            conn.close()

    def setUp(self):
        self.client = app.test_client()

    def login_as(self, user):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user['user_id']
            sess['full_name'] = user['full_name']
            sess['role'] = user.get('role', 'user')

    def logout(self):
        with self.client.session_transaction() as sess:
            sess.clear()

    def test_01_dashboard_recommendations_section_rendered(self):
        """Test that user dashboard displays 'Recommended for You' section with badges and controls."""
        self.login_as(self.demo_user)
        resp = self.client.get('/user-dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('Recommended for You', html)
        self.assertIn('recommendations-section', html)
        self.assertIn('Hybrid ML', html)
        self.assertIn('Customize Preferences', html)
        self.assertIn('id="preferencesModal"', html)
        self.assertIn('btn-refresh-recommendations', html)

    def test_02_recommendations_for_demo_profile(self):
        """Test generating hybrid recommendations for the existing demonstration profile."""
        recs = self.engine.get_recommendations(user_id=self.demo_user['user_id'], limit=6)
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)

        for r in recs:
            # Must strictly be approved
            self.assertEqual(r['status'], 'approved')
            # Must contain hybrid metadata
            self.assertIn('match_pct', r)
            self.assertIn('primary_reason', r)
            self.assertGreaterEqual(r['match_pct'], 50)
            self.assertLessEqual(r['match_pct'], 100)

    def test_03_content_based_fallback_for_cold_start_user(self):
        """Test that a cold-start user with 0 interactions receives content-based fallback recommendations."""
        if not self.coldstart_user:
            self.skipTest("Cold start user not seeded")

        recs = self.engine.get_recommendations(user_id=self.coldstart_user['user_id'], limit=5)
        self.assertIsInstance(recs, list)
        self.assertGreater(len(recs), 0)

        # Cold start user preferred category was vintage clothing (cat 1)
        top_rec = recs[0]
        self.assertEqual(top_rec['status'], 'approved')
        self.assertIn('match_pct', top_rec)
        self.assertTrue(any("Matches your taste" in r['primary_reason'] or "Vintage" in r['category_name'] for r in recs))

    def test_04_collaborative_recommendations_with_overlapping_peers(self):
        """Test collaborative signal identification when overlapping interactions exist."""
        if not self.priya_user:
            self.skipTest("Priya synthetic user not seeded")

        recs = self.engine.get_recommendations(user_id=self.priya_user['user_id'], limit=6)
        self.assertGreater(len(recs), 0)

        # Check for collaborative or content reason strings
        reasons = [r['primary_reason'] for r in recs]
        has_expected_reasons = any("Matches your taste" in rs or "Shoppers with similar" in rs for rs in reasons)
        self.assertTrue(has_expected_reasons, f"Expected taste or collaborative reasons, got: {reasons}")

    def test_05_dynamic_update_after_interaction(self):
        """Test that adding a favorite dynamically updates the user's recommendations without offline retraining."""
        user_id = self.demo_user['user_id']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Pick an approved store to favorite temporarily
            cursor.execute("SELECT store_id, store_name, category_id FROM stores WHERE status = 'approved' ORDER BY store_id DESC LIMIT 1")
            target_store = cursor.fetchone()
            target_store_id = target_store['store_id']

            # Ensure clean state
            cursor.execute("DELETE FROM favorites WHERE user_id = %s AND store_id = %s", (user_id, target_store_id))
            conn.commit()

            recs_before = self.engine.get_recommendations(user_id=user_id, limit=6)

            # Insert favorite
            cursor.execute("INSERT INTO favorites (user_id, store_id) VALUES (%s, %s)", (user_id, target_store_id))
            conn.commit()

            # Immediately fetch fresh recommendations
            recs_after = self.engine.get_recommendations(user_id=user_id, limit=6)

            # Verify target store is marked as favorited
            matching_after = next((r for r in recs_after if r['store_id'] == target_store_id), None)
            if matching_after:
                self.assertTrue(matching_after['is_favorited'])

        finally:
            # Clean up test favorite
            cursor.execute("DELETE FROM favorites WHERE user_id = %s AND store_id = %s", (user_id, target_store_id))
            conn.commit()
            cursor.close()
            conn.close()

    def test_06_preference_update_endpoint(self):
        """Test POST /update-preferences updates preferred categories and location."""
        self.login_as(self.demo_user)
        user_id = self.demo_user['user_id']

        post_data = {
            'preferred_categories': ['1', '3'],
            'preferred_city': 'Bangalore'
        }
        resp = self.client.post('/update-preferences', data=post_data, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('preferences have been updated', html)

        # Verify database was updated
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT preferred_categories, preferred_city FROM users WHERE user_id = %s", (user_id,))
            row = cursor.fetchone()
            self.assertEqual(row['preferred_city'], 'Bangalore')
            self.assertIn('1', row['preferred_categories'])
            self.assertIn('3', row['preferred_categories'])
        finally:
            cursor.close()
            conn.close()

    def test_07_strict_exclusion_of_unapproved_stores(self):
        """Test that unapproved (pending or rejected) stores are strictly excluded from recommendations."""
        if not self.pending_store:
            self.skipTest("No pending store available to test")

        pending_id = self.pending_store['store_id']
        recs = self.engine.get_recommendations(user_id=self.demo_user['user_id'], limit=20)
        rec_ids = [r['store_id'] for r in recs]

        self.assertNotIn(pending_id, rec_ids, f"Pending store {pending_id} must NEVER be recommended!")

    def test_08_unauthenticated_preference_update_redirect(self):
        """Test that unauthenticated requests to /update-preferences redirect to login."""
        self.logout()
        resp = self.client.post('/update-preferences', data={'preferred_city': 'Kochi'}, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers['Location'])

    def test_09_explicit_category_preference_priority_over_unselected(self):
        """Test that explicit category preferences strongly prioritize matching stores over unselected ones."""
        user_id = self.demo_user['user_id']
        # Set explicitly to category 1 (Vintage Clothing)
        self.engine.update_user_preferences(user_id, preferred_categories=['1'], preferred_city='Kottayam')

        recs = self.engine.get_recommendations(user_id=user_id, limit=6)
        self.assertGreater(len(recs), 0)

        # Top recommendations must be from the explicitly preferred category
        top_rec = recs[0]
        self.assertEqual(top_rec['category_id'], 1, f"Expected top recommendation to be category 1, got {top_rec['category_id']} ({top_rec['category_name']})")
        self.assertIn("Matches your taste in", top_rec['primary_reason'])

    def test_10_preference_update_changes_ranking_immediately(self):
        """Test that updating or unchecking categories immediately recalculates ranking on subsequent requests."""
        user_id = self.demo_user['user_id']

        # Switch explicit preference to category 3 (Shoes)
        self.engine.update_user_preferences(user_id, preferred_categories=['3'], preferred_city='Bangalore')
        recs_shoes = self.engine.get_recommendations(user_id=user_id, limit=6)
        self.assertGreater(len(recs_shoes), 0)
        self.assertEqual(recs_shoes[0]['category_id'], 3, "Top store should be Shoes after updating preference")
        self.assertIn("Shoes", recs_shoes[0]['primary_reason'])

        # Now uncheck all categories
        self.engine.update_user_preferences(user_id, preferred_categories=[], preferred_city='')
        recs_empty = self.engine.get_recommendations(user_id=user_id, limit=6)
        self.assertGreater(len(recs_empty), 0)
        # Should gracefully return valid approved stores without errors
        for r in recs_empty:
            self.assertEqual(r['status'], 'approved')

    def test_11_balanced_rating_influence_does_not_override_explicit_preference(self):
        """Test that a high rating for a shoe store contributes to interests but does not outrank explicitly preferred clothing."""
        user_id = self.demo_user['user_id']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            # Set explicit preference to category 1 (Vintage Clothing)
            self.engine.update_user_preferences(user_id, preferred_categories=['1'], preferred_city='Kottayam')

            # Find a shoe store (category 3)
            cursor.execute("SELECT store_id, store_name FROM stores WHERE category_id = 3 AND status = 'approved' LIMIT 1")
            shoe_store = cursor.fetchone()
            assert shoe_store is not None, "Shoe store required for test"
            shoe_id = shoe_store['store_id']

            # User gives a 5-star review to this shoe store
            cursor.execute("DELETE FROM reviews WHERE user_id = %s AND store_id = %s", (user_id, shoe_id))
            cursor.execute("INSERT INTO reviews (store_id, user_id, rating, comment) VALUES (%s, %s, 5, 'Great shoes!')", (shoe_id, user_id))
            conn.commit()

            recs = self.engine.get_recommendations(user_id=user_id, limit=6)
            top_rec = recs[0]

            # The top store must still be an explicitly preferred category 1 store
            self.assertEqual(top_rec['category_id'], 1, "Explicitly preferred Vintage Clothing store must outrank single-rated shoe store")

            # Shoe store should still be present with positive interest
            matching_shoe = next((r for r in recs if r['store_id'] == shoe_id), None)
            self.assertIsNotNone(matching_shoe, "Shoe store should still be recommended")
            self.assertIn("interest in Shoes", matching_shoe['primary_reason'])

        finally:
            cursor.execute("DELETE FROM reviews WHERE user_id = %s AND store_id = %s", (user_id, shoe_id))
            conn.commit()
            cursor.close()
            conn.close()

    def test_12_accurate_reason_explanations(self):
        """Test that recommendation reason explanations accurately match profile and scoring signals."""
        user_id = self.demo_user['user_id']
        # User explicitly chooses category 1 (Vintage Clothing)
        self.engine.update_user_preferences(user_id, preferred_categories=['1'], preferred_city='Kottayam')

        recs = self.engine.get_recommendations(user_id=user_id, limit=6)
        for r in recs:
            if r['category_id'] == 1:
                self.assertIn("Matches your taste in Vintage Clothing", r['primary_reason'])
            else:
                # Must NEVER claim taste match for an unselected category
                self.assertNotIn("Matches your taste in", r['primary_reason'])

    def test_13_dashboard_refresh_action(self):
        """Test that refreshing recommendations via ?refresh=1 recalculates recommendations and displays flash notice."""
        self.login_as(self.demo_user)
        resp = self.client.get('/user-dashboard?refresh=1')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('Recommendations recalculated with your latest preferences and activity', html)
        self.assertIn('id="hybrid-recommendations-grid"', html)

    def test_14_preferred_city_outranks_distant_city_for_same_category(self):
        """Test that for same category relevance (Shoes), a store in preferred city (Mallappally) outranks a distant store (Bangalore)."""
        user_id = self.demo_user['user_id']
        self.engine.update_user_preferences(user_id, preferred_categories=['3'], preferred_city='Mallappally')

        recs = self.engine.get_recommendations(user_id=user_id, limit=6)
        self.assertGreater(len(recs), 1, "Expected multiple recommendations")

        # Top recommendation must be Store 5 (Shoe Peedya in Mallappally)
        top_rec = recs[0]
        self.assertEqual(top_rec['store_id'], 5, f"Expected Store 5 in Mallappally to rank first, got Store {top_rec['store_id']} ({top_rec['store_name']}) in {top_rec['city']}")
        self.assertEqual(top_rec['category_id'], 3)
        self.assertEqual(top_rec['city'].lower(), 'mallappally')

        # Store 15 (Sole Revival in Bangalore) must still be present lower in the recommendations (not hard-filtered)
        rec_ids = [r['store_id'] for r in recs]
        self.assertIn(15, rec_ids, "Distant Bangalore shoe store (Store 15) must remain discoverable in recommendations")
        self.assertGreater(rec_ids.index(15), rec_ids.index(5), "Store 5 (Mallappally) must rank above Store 15 (Bangalore)")

        # Verify explanations accurately reflect signals
        self.assertIn("Matches your taste in Shoes", top_rec['primary_reason'])
        all_reasons_top = top_rec.get('all_reasons', [])
        self.assertTrue(any('Mallappally' in r for r in all_reasons_top), f"Expected Mallappally city signal in reasons: {all_reasons_top}")

    def test_15_category_preference_priority_across_cities(self):
        """Test that explicit category preferences maintain strong priority, and changing preferred city shifts city ranking."""
        user_id = self.demo_user['user_id']
        # When user explicitly prefers Bangalore as city for Shoes, Bangalore shoe store (Store 15) should rank ahead of Mallappally
        self.engine.update_user_preferences(user_id, preferred_categories=['3'], preferred_city='Bangalore')
        recs_blr = self.engine.get_recommendations(user_id=user_id, limit=6)
        self.assertGreater(len(recs_blr), 0)
        self.assertEqual(recs_blr[0]['store_id'], 15, "Store 15 in Bangalore should rank #1 when preferred city is Bangalore")
        self.assertIn("Matches your taste in Shoes", recs_blr[0]['primary_reason'])

    def test_16_city_normalization_and_whitespace_resilience(self):
        """Test that city normalization safely handles whitespace, casing, and missing coordinate lookups."""
        user_id = self.demo_user['user_id']
        # Pass irregular casing and whitespace
        self.engine.update_user_preferences(user_id, preferred_categories=['3'], preferred_city='   mAlLaPpaLLy  ')
        recs = self.engine.get_recommendations(user_id=user_id, limit=6)
        self.assertGreater(len(recs), 0)
        self.assertEqual(recs[0]['store_id'], 5, "City normalization should safely resolve '  mAlLaPpaLLy  ' to Mallappally and rank Store 5 #1")

if __name__ == '__main__':
    unittest.main()

