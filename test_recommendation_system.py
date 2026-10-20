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
import math
from unittest.mock import MagicMock, call, patch

# app.py connects and creates the upload directory at import time.
# Isolate those side effects; integration tests below still require an explicit DB run.
with patch('mysql.connector.connect'), patch('os.makedirs'):
    from app import app, get_db_connection
from recommendation_engine import HybridRecommendationEngine, resolve_preference

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

class TestLocationPreferencesOffline(unittest.TestCase):
    """Run this class alone: all persistence is an in-memory mock."""

    def setUp(self):
        guard = patch('mysql.connector.connect', side_effect=AssertionError("Real DB access forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        self.engine = HybridRecommendationEngine()
        self.connection = MagicMock()
        self.cursor = self.connection.cursor.return_value
        self.cursor.rowcount = 1
        self.favorites = []
        self.reviews = []
        self.profile = {
            'user_id': 901, 'preferred_categories': '71',
            'preferred_city': 'Old City', 'preferred_lat': 9.59, 'preferred_lng': 76.52,
        }
        self.stores = [
            dict(store_id=sid, store_name='Vintage denim', description='Denim jackets',
                 category_id=71, category_name='Clothing', city=city,
                 latitude=lat, longitude=lng, avg_rating=0, review_count=0,
                 status='approved')
            for sid, city, lat, lng in [
                (801, 'Old City', 9.59, 76.52),
                (802, 'New City', 12.97, 77.59),
            ]
        ]
        self.cursor.execute.side_effect = self.execute_fake
        connection_patch = patch.object(self.engine, '_get_connection', return_value=self.connection)
        self.get_connection = connection_patch.start()
        self.addCleanup(connection_patch.stop)

    def execute_fake(self, query, params=None):
        """Record updates in memory and supply fabricated recommendation inputs."""
        if query.startswith('UPDATE users SET '):
            assignments = query.split(' SET ', 1)[1].split(' WHERE ', 1)[0].split(', ')
            for assignment, value in zip(assignments, params[:-1]):
                self.profile[assignment.split(' = ')[0]] = value
        elif 'FROM users WHERE' in query:
            self.cursor.fetchone.return_value = dict(self.profile)
        elif 'FROM stores s' in query:
            self.cursor.fetchall.return_value = [dict(s) for s in self.stores]
        elif 'FROM favorites' in query:
            self.cursor.fetchall.return_value = [
                dict(row) for row in self.favorites
                if params is None or row['user_id'] == params[0]]
        elif 'FROM reviews' in query:
            self.cursor.fetchall.return_value = [
                dict(row) for row in self.reviews
                if params is None or row['user_id'] == params[0]]
        else:
            self.cursor.fetchall.return_value = []

    def assert_location_cleared(self, city):
        self.assertEqual(self.profile['preferred_city'], city)
        self.assertIsNone(self.profile['preferred_lat'])
        self.assertIsNone(self.profile['preferred_lng'])
        self.cursor.execute.assert_called_once()
        query, params = self.cursor.execute.call_args.args
        self.assertIn('preferred_lat = %s, preferred_lng = %s', query)
        self.assertEqual(params[-3:], (None, None, 901))
        self.connection.commit.assert_called_once()

    def test_city_submissions_clear_coordinates_atomically(self):
        for submitted, expected in [
            (' New City ', 'New City'), ('', ''), ('   ', ''), ('Old City', 'Old City'),
        ]:
            with self.subTest(city=submitted):
                self.cursor.reset_mock()
                self.connection.commit.reset_mock()
                self.profile.update(preferred_city='Old City', preferred_lat=9.59, preferred_lng=76.52)
                self.engine.update_user_preferences(901, preferred_city=submitted)
                self.assert_location_cleared(expected)

    def test_categories_and_city_share_one_update(self):
        self.engine.update_user_preferences(
            901, preferred_categories=['72'], preferred_city='New City')
        self.assertEqual(self.profile['preferred_categories'], '72')
        self.assert_location_cleared('New City')

    def test_category_only_preserves_location(self):
        before = dict(self.profile)
        self.engine.update_user_preferences(901, preferred_categories=['72', 'invalid'])
        self.assertEqual(self.profile['preferred_categories'], '72')
        for field in ('preferred_city', 'preferred_lat', 'preferred_lng'):
            self.assertEqual(self.profile[field], before[field])
        query, params = self.cursor.execute.call_args.args
        self.assertNotIn('preferred_city', query)
        self.assertNotIn('preferred_lat', query)
        self.assertEqual(params, ('72', 901))

    def test_omitted_preferences_do_not_update(self):
        before = dict(self.profile)
        self.assertFalse(self.engine.update_user_preferences(901))
        self.assertEqual(self.profile, before)
        self.cursor.execute.assert_not_called()
        self.connection.commit.assert_not_called()

    def test_valid_coordinate_pairs(self):
        for city, lat, lng in [(None, '12.97', '77.59'), ('New City', 0, 0),
                               (None, -90, -180), (None, 90, 180)]:
            with self.subTest(city=city, lat=lat, lng=lng):
                self.connection.reset_mock()
                previous_city = self.profile['preferred_city']
                self.assertTrue(self.engine.update_user_preferences(
                    901, preferred_city=city, lat=lat, lng=lng))
                self.assertEqual(self.profile['preferred_lat'], float(lat))
                self.assertEqual(self.profile['preferred_lng'], float(lng))
                self.assertEqual(self.profile['preferred_city'],
                                 previous_city if city is None else city)
                assignments = 'preferred_lat = %s, preferred_lng = %s'
                params = (float(lat), float(lng), 901)
                if city is not None:
                    assignments = 'preferred_city = %s, ' + assignments
                    params = (city,) + params
                self.assertEqual(self.connection.mock_calls, [
                    call.cursor(),
                    call.cursor().execute(
                        f'UPDATE users SET {assignments} WHERE user_id = %s', params),
                    call.commit(),
                    call.cursor().close(),
                    call.close(),
                ])
                self.connection.rollback.assert_not_called()

    def test_invalid_coordinates_rejected_before_connection(self):
        pairs = [(1, None), (None, 1), (float('nan'), 1), (1, float('nan')),
                 (float('inf'), 1), (1, float('-inf')),
                 (90.01, 1), (-90.01, 1), (1, 180.01), (1, -180.01), ('bad', 1)]
        for lat, lng in pairs:
            with self.subTest(lat=lat, lng=lng):
                with self.assertRaises(ValueError):
                    self.engine.update_user_preferences(901, lat=lat, lng=lng)
        self.get_connection.assert_not_called()
        self.cursor.execute.assert_not_called()

    def test_blank_city_overrides_valid_coordinates(self):
        for city in ('', '  '):
            with self.subTest(city=city):
                self.cursor.reset_mock()
                self.connection.commit.reset_mock()
                self.engine.update_user_preferences(901, preferred_city=city, lat=12.97, lng=77.59)
                self.assert_location_cleared('')

    def test_blank_city_still_validates_coordinates(self):
        with self.assertRaises(ValueError):
            self.engine.update_user_preferences(901, preferred_city='', lat=float('inf'), lng=0)
        self.get_connection.assert_not_called()

    def test_city_change_moves_ranking_to_new_city(self):
        self.assertEqual(self.engine.get_recommendations(901)[0]['city'], 'Old City')
        self.engine.update_user_preferences(901, preferred_city='New City')
        recs = self.engine.get_recommendations(901)
        self.assertEqual(recs[0]['city'], 'New City')
        self.assertEqual(recs[0]['distance_km'], 0)
        self.assertGreater(recs[1]['distance_km'], 25)
        self.assertIsNone(self.profile['preferred_lat'])  # Lookup is not persisted.
        self.assertIsNone(self.profile['preferred_lng'])

    def test_clear_and_unknown_city_remove_old_ranking_advantage(self):
        for city in ('', 'Unknown City'):
            with self.subTest(city=city):
                self.profile.update(preferred_city='Old City', preferred_lat=9.59, preferred_lng=76.52)
                self.assertEqual(self.engine.get_recommendations(901)[0]['city'], 'Old City')
                self.engine.update_user_preferences(901, preferred_city=city)
                recs = self.engine.get_recommendations(901)
                self.assertEqual(recs[0]['match_score'], recs[1]['match_score'])
                for rec in recs:
                    self.assertIsNone(rec['distance_km'])
                    self.assertFalse(any('Nearby' in reason or 'preferred city' in reason
                                         for reason in rec['all_reasons']))

    def test_route_city_values(self):
        client = app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 901
        with patch('app.HybridRecommendationEngine') as engine_class:
            for data, expected in [
                ({'preferred_city': ' New City '}, 'New City'),
                ({'preferred_city': ''}, ''),
                ({'preferred_city': '  '}, ''),
                ({}, None),
            ]:
                with self.subTest(data=data):
                    engine_class.reset_mock()
                    response = client.post('/update-preferences', data=data)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response.location.endswith('/user-dashboard#recommendations-section'))
                    engine_class.return_value.update_user_preferences.assert_called_once_with(
                        901, preferred_categories=[], preferred_city=expected)

    def test_route_nonempty_categories_and_changed_city(self):
        client = app.test_client()
        with client.session_transaction() as session:
            session['user_id'] = 901
        with patch('app.HybridRecommendationEngine') as engine_class:
            response = client.post('/update-preferences', data={
                'preferred_categories': ['71', '72'],
                'preferred_city': ' New City ',
            })
            self.assertEqual(response.status_code, 302)
            engine_class.return_value.update_user_preferences.assert_called_once_with(
                901, preferred_categories=['71', '72'], preferred_city='New City')

    def assert_failure_calls(self, commit_attempted, rollback_attempted):
        expected = [
            call.cursor(),
            call.cursor().execute(
                'UPDATE users SET preferred_city = %s, preferred_lat = %s, '
                'preferred_lng = %s WHERE user_id = %s',
                ('New City', None, None, 901)),
        ]
        if commit_attempted:
            expected.append(call.commit())
        if rollback_attempted:
            expected.append(call.rollback())
        expected.extend([call.cursor().close(), call.close()])
        self.assertEqual(self.connection.mock_calls, expected)

    def test_execution_failure_rolls_back_and_closes(self):
        error = RuntimeError('mock execution failure')
        self.cursor.execute.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            self.engine.update_user_preferences(901, preferred_city='New City')
        self.assertIs(caught.exception, error)
        self.assert_failure_calls(commit_attempted=False, rollback_attempted=True)

    def test_commit_failure_rolls_back_and_closes(self):
        error = RuntimeError('mock commit failure')
        self.connection.commit.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            self.engine.update_user_preferences(901, preferred_city='New City')
        self.assertIs(caught.exception, error)
        self.assert_failure_calls(commit_attempted=True, rollback_attempted=True)

    def test_cursor_close_failure_still_closes_connection(self):
        error = RuntimeError('mock cursor close failure')
        self.cursor.close.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            self.engine.update_user_preferences(901, preferred_city='New City')
        self.assertIs(caught.exception, error)
        self.assert_failure_calls(commit_attempted=True, rollback_attempted=False)

    def test_connection_close_failure_propagates(self):
        error = RuntimeError('mock connection close failure')
        self.connection.close.side_effect = error
        with self.assertRaises(RuntimeError) as caught:
            self.engine.update_user_preferences(901, preferred_city='New City')
        self.assertIs(caught.exception, error)
        self.assert_failure_calls(commit_attempted=True, rollback_attempted=False)

    def test_both_close_failures_preserve_first_cleanup_error(self):
        error = RuntimeError('mock cursor close failure')
        self.cursor.close.side_effect = error
        self.connection.close.side_effect = RuntimeError('mock connection close failure')
        with self.assertRaises(RuntimeError) as caught:
            self.engine.update_user_preferences(901, preferred_city='New City')
        self.assertIs(caught.exception, error)
        self.assert_failure_calls(commit_attempted=True, rollback_attempted=False)

    def test_secondary_failures_preserve_operation_error_and_attempt_cleanup(self):
        for stage in ('execute', 'commit'):
            with self.subTest(stage=stage):
                self.connection.reset_mock(side_effect=True)
                error = RuntimeError('mock operation failure')
                self.cursor.execute.side_effect = error if stage == 'execute' else self.execute_fake
                self.connection.commit.side_effect = error if stage == 'commit' else None
                self.connection.rollback.side_effect = RuntimeError('mock rollback failure')
                self.cursor.close.side_effect = RuntimeError('mock cursor close failure')
                self.connection.close.side_effect = RuntimeError('mock connection close failure')
                with self.assertRaises(RuntimeError) as caught:
                    self.engine.update_user_preferences(901, preferred_city='New City')
                self.assertIs(caught.exception, error)
                self.assert_failure_calls(commit_attempted=stage == 'commit', rollback_attempted=True)

    def prepare_signal_records(self):
        """Equal candidates without location/quality differences or explicit tastes."""
        self.profile.update(preferred_categories='', preferred_city='',
                            preferred_lat=None, preferred_lng=None)
        self.stores = [
            dict(store_id=sid, store_name='Denim', description='Jackets',
                 category_id=cat, category_name='Clothing',
                 city='', latitude=None, longitude=None, avg_rating=0,
                 review_count=0, status='approved')
            for sid, cat in [(801, 71), (802, 72), (803, 73)]
        ]
        self.favorites = []
        self.reviews = []

    def add_review(self, uid, sid, rating):
        self.reviews.append(dict(user_id=uid, store_id=sid, rating=rating))

    def signal_recommendations(self):
        recs = self.engine.get_recommendations(901)
        self.assertEqual(len(recs), len(self.stores))
        return {rec['store_id']: rec for rec in recs}

    def test_signed_preference_semantics(self):
        self.assertIsNone(resolve_preference(False))
        self.assertEqual(resolve_preference(True), 0.5)
        for rating, expected in [(1, -1), (2, -0.5), (3, 0), (4, 0.5), (5, 1)]:
            for saved in (False, True):
                with self.subTest(rating=rating, saved=saved):
                    self.assertEqual(resolve_preference(saved, rating), expected)

    def test_all_ratings_override_favorites_in_content_pipeline(self):
        for rating in range(1, 6):
            for saved in (False, True):
                with self.subTest(rating=rating, saved=saved):
                    self.prepare_signal_records()
                    self.add_review(901, 801, rating)
                    if saved:
                        self.favorites.append(dict(user_id=901, store_id=801))
                    recs = self.signal_recommendations()
                    positive = rating >= 4
                    self.assertEqual(recs[801]['is_favorited'], saved)
                    self.assertEqual(
                        'Based on your interest in Clothing' in recs[801]['all_reasons'],
                        positive)
                    # All candidates have the same tokens but different categories.
                    # This also detects leaking neutral/negative name or description tokens.
                    expected_own = 0.7 * (0.75 * (0.85 if positive else 0.35)
                                          + 0.25 * (1 if positive else 0.1)) + 0.3 * 0.5
                    expected_other = 0.7 * (0.75 * 0.35
                                            + 0.25 * (1 if positive else 0.1)) + 0.3 * 0.5
                    self.assertEqual(recs[801]['match_score'], round(expected_own, 4))
                    self.assertEqual(recs[802]['match_score'], round(expected_other, 4))

    def test_favorite_only_establishes_content_interest(self):
        self.prepare_signal_records()
        self.favorites.append(dict(user_id=901, store_id=801))
        recs = self.signal_recommendations()
        self.assertIn('Based on your interest in Clothing', recs[801]['all_reasons'])
        self.assertGreater(recs[801]['match_score'], recs[802]['match_score'])

    def test_negative_review_preserves_explicit_category_and_other_positive_interest(self):
        self.prepare_signal_records()
        self.profile['preferred_categories'] = '71'
        self.add_review(901, 801, 1)
        recs = self.signal_recommendations()
        self.assertIn('Matches your taste in Clothing', recs[801]['all_reasons'])
        self.profile['preferred_categories'] = ''
        self.stores[1]['category_id'] = 71
        self.add_review(901, 802, 5)
        recs = self.signal_recommendations()
        self.assertIn('Based on your interest in Clothing', recs[801]['all_reasons'])
        self.assertIn(801, recs)  # No direct disliked-store suppression.

    def test_signed_similarity_opposition_and_insufficient_overlap(self):
        for target, peer in [
            ({801: -1}, {801: 1}),
            ({801: 1}, {801: 1}),
            ({801: 1, 802: -1}, {801: -1, 802: 1}),
            ({801: 1, 802: 0}, {801: 1, 802: 1}),
            ({801: 1, 802: 1}, {801: 1, 802: 0}),
            ({801: 1, 802: 1}, {801: 1, 803: 1}),
            ({801: 0, 802: 0}, {801: 0, 802: 0}),
            ({}, {801: 1, 802: 1}),
        ]:
            with self.subTest(target=target, peer=peer):
                self.assertEqual(self.engine._peer_similarity(target, peer), 0)

    def test_similarity_overlap_shrinkage_and_full_vector_norms(self):
        for count in (2, 3, 5):
            aligned = {sid: (-1 if sid % 2 else 0.5) for sid in range(count)}
            with self.subTest(count=count):
                self.assertAlmostEqual(
                    self.engine._peer_similarity(aligned, aligned), count / (count + 2))
        self.assertAlmostEqual(
            self.engine._peer_similarity({801: 1, 802: 1}, {801: 1, 802: 1, 803: 1}),
            (2 / math.sqrt(6)) * 0.5)
        with patch.object(self.engine, 'MIN_SHARED_PREFERENCES', 3):
            self.assertEqual(self.engine._peer_similarity({1: 1, 2: 1}, {1: 1, 2: 1}), 0)
        with patch.object(self.engine, 'SIMILARITY_SHRINKAGE', 4):
            self.assertAlmostEqual(
                self.engine._peer_similarity({1: 1, 2: 1}, {1: 1, 2: 1}), 2 / 6)

    def test_candidate_feedback_mapping_and_review_precedence(self):
        for rating, preference in [(None, None), (1, -1), (2, -0.5), (3, 0), (4, 0.5), (5, 1)]:
            for saved in (False, True):
                with self.subTest(rating=rating, saved=saved):
                    self.prepare_signal_records()
                    # Shared dislikes establish aligned peers without content interests.
                    for uid in (901, 902):
                        for sid in (801, 802):
                            self.add_review(uid, sid, 1)
                    if saved:
                        self.favorites.append(dict(user_id=902, store_id=803))
                    if rating is not None:
                        self.add_review(902, 803, rating)
                    resolved = preference if rating is not None else (0.5 if saved else None)
                    if resolved is None:
                        collaborative = 0.5
                    else:
                        similarity = (2 / math.sqrt(2 * (2 + resolved ** 2))) * 0.5
                        collaborative = (similarity * ((resolved + 1) / 2) + 0.4) / (similarity + 0.8)
                    rec = self.signal_recommendations()[803]
                    expected = 0.45 * 0.2875 + 0.4 * collaborative + 0.15 * 0.5
                    self.assertEqual(rec['match_score'], round(expected, 4))
                    self.assertEqual('Similar shoppers showed interest in this' in rec['all_reasons'],
                                     collaborative >= 0.6)
                    self.assertFalse(any('loved' in reason.lower() for reason in rec['all_reasons']))

    def test_missing_peer_feedback_does_not_dilute_candidate_score(self):
        self.prepare_signal_records()
        for uid in (901, 902, 903):
            for sid in (801, 802):
                self.add_review(uid, sid, 1)
        self.add_review(902, 803, 5)
        missing_score = self.signal_recommendations()[803]['match_score']
        similarity = 1 / math.sqrt(6)
        collaborative = (similarity + 0.4) / (similarity + 0.8)
        self.assertEqual(missing_score, round(0.45 * 0.2875 + 0.4 * collaborative + 0.075, 4))
        self.add_review(903, 803, 3)
        neutral_score = self.signal_recommendations()[803]['match_score']
        collaborative = (similarity + 0.5 * 0.5 + 0.4) / (similarity + 0.5 + 0.8)
        self.assertEqual(neutral_score, round(0.45 * 0.2875 + 0.4 * collaborative + 0.075, 4))
        self.assertLess(neutral_score, missing_score)

    def test_cold_sparse_neutral_and_opposing_histories_use_fallback(self):
        for history, peer in [
            ([], [(801, 5), (802, 5)]),
            ([(801, 1)], [(801, 1)]),
            ([(801, 3), (802, 3)], [(801, 3), (802, 3)]),
            ([(801, 1), (802, 3)], [(801, 1), (802, 1)]),
            ([(801, 1), (802, 2)], [(801, 5), (802, 4)]),
        ]:
            with self.subTest(history=history, peer=peer):
                self.prepare_signal_records()
                for sid, rating in history:
                    self.add_review(901, sid, rating)
                for sid, rating in peer:
                    self.add_review(902, sid, rating)
                self.add_review(902, 803, 5)
                for rec in self.signal_recommendations().values():
                    self.assertEqual(rec['match_score'], round(0.7 * 0.2875 + 0.3 * 0.5, 4))
                    self.assertNotIn('Similar shoppers showed interest in this', rec['all_reasons'])

    def test_positive_shared_favorites_enable_collaborative_scoring(self):
        self.prepare_signal_records()
        for uid in (901, 902):
            for sid in (801, 802):
                self.favorites.append(dict(user_id=uid, store_id=sid))
        self.add_review(902, 803, 5)
        rec = self.signal_recommendations()[803]
        similarity = (0.5 / math.sqrt(0.5 * 1.5)) * 0.5
        collaborative = (similarity + 0.4) / (similarity + 0.8)
        # Positive history supplies matching text, but candidate category is unselected.
        content = 0.75 * 0.35 + 0.25
        self.assertEqual(rec['match_score'], round(0.45 * content + 0.4 * collaborative + 0.075, 4))
        self.assertIn('Similar shoppers showed interest in this', rec['all_reasons'])

    def test_unauthenticated_route_does_not_save(self):
        with patch('app.HybridRecommendationEngine') as engine_class:
            response = app.test_client().post('/update-preferences', data={'preferred_city': ''})
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login', response.location)
            engine_class.assert_not_called()


if __name__ == '__main__':
    unittest.main()

