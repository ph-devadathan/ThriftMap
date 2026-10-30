"""
Automated unit and integration test suite for ThriftMap 'Manage Profile' feature.
Covers all requirements and strict restrictions:
1. Navigation & Menu verification: Manage Profile option in user dashboard navbar and menu grid
2. Authentication enforcement: Protected route redirects unauthenticated users to /login
3. View Profile: Logged-in user can view their name, email, role, and account metrics
4. Update Name and Email: Valid updates persist to the MySQL users table and update session
5. Duplicate Email Prevention: Rejects attempts to use an email belonging to another user
6. Form Input Validation: Full name length, email format, empty fields rejection
7. Secure Password Change:
   - Requires verification of current password
   - Rejects incorrect current password
   - Enforces minimum length (6+ chars)
   - Enforces confirmation match
   - Hashes new password securely (never stores plain-text)
   - Enables subsequent authentication with new password
8. Strict Isolation & Ownership: Users cannot view or update another user's profile (403 Forbidden)
9. Safe Teardown: Restores original database state for test accounts
"""
import unittest
import re
from werkzeug.security import check_password_hash, generate_password_hash
from app import app, get_db_connection

class TestManageProfileFeature(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Create two unique, dedicated test users for this suite to avoid polluting existing data
            cls.test_email_1 = "test_profile_shopper_1@example.com"
            cls.test_email_2 = "test_profile_shopper_2@example.com"
            cls.initial_password_1 = "InitialPass123!"
            cls.initial_password_2 = "InitialPass456!"

            # Clean any stale test accounts from previous runs
            cursor.execute("DELETE FROM users WHERE email IN (%s, %s)", (cls.test_email_1, cls.test_email_2))
            conn.commit()

            # Insert User 1
            cursor.execute("""
                INSERT INTO users (full_name, email, password, role, status, preferred_city)
                VALUES (%s, %s, %s, 'user', 'active', 'Kochi')
            """, ("Test User One", cls.test_email_1, cls.initial_password_1))
            cls.user1_id = cursor.lastrowid

            # Insert User 2
            cursor.execute("""
                INSERT INTO users (full_name, email, password, role, status, preferred_city)
                VALUES (%s, %s, %s, 'user', 'active', 'Bangalore')
            """, ("Test User Two", cls.test_email_2, cls.initial_password_2))
            cls.user2_id = cursor.lastrowid

            conn.commit()

            cls.user1 = {
                'user_id': cls.user1_id,
                'full_name': "Test User One",
                'email': cls.test_email_1,
                'role': 'user'
            }
            cls.user2 = {
                'user_id': cls.user2_id,
                'full_name': "Test User Two",
                'email': cls.test_email_2,
                'role': 'user'
            }

        finally:
            cursor.close()
            conn.close()

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM users WHERE email IN (%s, %s, 'updated_shopper1@example.com')", 
                           (cls.test_email_1, cls.test_email_2))
            cursor.execute("DELETE FROM users WHERE user_id IN (%s, %s)", (cls.user1_id, cls.user2_id))
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

    # -------------------------------------------------------------
    # 1. Navigation & Menu Tests
    # -------------------------------------------------------------
    def test_01_user_navigation_contains_manage_profile(self):
        """User dashboard navbar and Discovery Menu contain active link to Manage Profile."""
        self.login_as(self.user1)
        resp = self.client.get('/user-dashboard')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        # Check navbar button
        self.assertIn('/manage-profile', html)
        self.assertIn('id="nav-btn-profile"', html)
        self.assertIn('Manage Profile', html)

        # Check menu card in dashboard
        self.assertIn('id="menu-manage-profile"', html)
        self.assertIn('Account Settings', html)

    def test_02_other_user_views_contain_profile_nav(self):
        """my_reviews and my_favorites navbars contain Manage Profile link."""
        self.login_as(self.user1)
        for path in ['/my-reviews', '/my-favorites']:
            resp = self.client.get(path)
            self.assertEqual(resp.status_code, 200)
            html = resp.get_data(as_text=True)
            self.assertIn('id="nav-btn-profile"', html)
            self.assertIn('/manage-profile', html)

    # -------------------------------------------------------------
    # 2. Authentication Enforcement Tests
    # -------------------------------------------------------------
    def test_03_unauthenticated_access_redirects_to_login(self):
        """Unauthenticated requests to /manage-profile redirect to /login."""
        self.logout()
        resp = self.client.get('/manage-profile', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers.get('Location', ''))

        # Also test POST without session
        resp_post = self.client.post('/manage-profile', data={'fullname': 'Hacker', 'email': 'h@h.com'}, follow_redirects=False)
        self.assertEqual(resp_post.status_code, 302)
        self.assertIn('/login', resp_post.headers.get('Location', ''))

    # -------------------------------------------------------------
    # 3. View Profile Tests
    # -------------------------------------------------------------
    def test_04_logged_in_user_can_view_own_profile(self):
        """Logged-in user can access /manage-profile and view their personal data."""
        self.login_as(self.user1)
        resp = self.client.get('/manage-profile')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)

        self.assertIn('Test User One', html)
        self.assertIn(self.test_email_1, html)
        self.assertIn('id="fullname"', html)
        self.assertIn('id="email"', html)
        self.assertIn('id="current_password"', html)
        self.assertIn('id="new_password"', html)
        self.assertIn('id="confirm_password"', html)
        self.assertIn('id="btn-save-profile"', html)

    # -------------------------------------------------------------
    # 4. Update Name and Email Tests
    # -------------------------------------------------------------
    def test_05_update_name_and_email_success(self):
        """User can successfully update their full name and email."""
        self.login_as(self.user1)
        updated_name = "Maya Sharma"
        updated_email = "maya_sharma_thrift@example.com"

        resp = self.client.post('/manage-profile', data={
            'fullname': updated_name,
            'email': updated_email,
            'current_password': '',
            'new_password': '',
            'confirm_password': ''
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Your profile has been successfully updated!", html)
        self.assertIn(updated_name, html)
        self.assertIn(updated_email, html)

        # Verify database record
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT full_name, email FROM users WHERE user_id = %s", (self.user1_id,))
            user = cursor.fetchone()
            self.assertEqual(user['full_name'], updated_name)
            self.assertEqual(user['email'], updated_email)
        finally:
            cursor.close()
            conn.close()

        # Update local user1 reference
        self.user1['full_name'] = updated_name
        self.user1['email'] = updated_email

    def test_06_user_can_keep_own_email_when_updating_name(self):
        """User can update name while submitting their current email without duplicate collision."""
        self.login_as(self.user1)
        new_name = "Maya S. Thrift"
        resp = self.client.post('/manage-profile', data={
            'fullname': new_name,
            'email': self.user1['email'],
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Your profile has been successfully updated!", html)
        self.assertIn(new_name, html)
        self.user1['full_name'] = new_name

    # -------------------------------------------------------------
    # 5. Duplicate Email Rejection Tests
    # -------------------------------------------------------------
    def test_07_duplicate_email_rejected(self):
        """Attempting to update email to another user's email is rejected with validation error."""
        self.login_as(self.user1)
        # Try to take user 2's email
        resp = self.client.post('/manage-profile', data={
            'fullname': self.user1['full_name'],
            'email': self.test_email_2
        }, follow_redirects=True)

        # Must return 400 or display duplicate error
        html = resp.get_data(as_text=True)
        self.assertIn("An account with this email address already exists.", html)

        # Database must still have original email for user 1
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT email FROM users WHERE user_id = %s", (self.user1_id,))
            user = cursor.fetchone()
            self.assertEqual(user['email'], self.user1['email'])
        finally:
            cursor.close()
            conn.close()

    # -------------------------------------------------------------
    # 6. Field Validation Tests
    # -------------------------------------------------------------
    def test_08_empty_and_short_fullname_rejected(self):
        """Empty full name or full name shorter than 2 characters is rejected."""
        self.login_as(self.user1)

        # Empty
        resp = self.client.post('/manage-profile', data={
            'fullname': '',
            'email': self.user1['email']
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Full Name is required.", resp.get_data(as_text=True))

        # Too short (1 char)
        resp2 = self.client.post('/manage-profile', data={
            'fullname': 'A',
            'email': self.user1['email']
        })
        self.assertEqual(resp2.status_code, 400)
        self.assertIn("Full Name must be at least 2 characters.", resp2.get_data(as_text=True))

    def test_09_invalid_email_format_rejected(self):
        """Invalid email addresses are rejected."""
        self.login_as(self.user1)
        invalid_emails = ['', 'notanemail', 'test@', 'test@domain', 'missing.dot@domain']
        for bad_email in invalid_emails:
            resp = self.client.post('/manage-profile', data={
                'fullname': self.user1['full_name'],
                'email': bad_email
            })
            self.assertEqual(resp.status_code, 400, f"Expected 400 for email: '{bad_email}'")

    # -------------------------------------------------------------
    # 7. Password Management & Hashing Tests
    # -------------------------------------------------------------
    def test_10_password_change_missing_current_password(self):
        """Changing password without providing current password is rejected."""
        self.login_as(self.user1)
        resp = self.client.post('/manage-profile', data={
            'fullname': self.user1['full_name'],
            'email': self.user1['email'],
            'current_password': '',
            'new_password': 'BrandNewPass123!',
            'confirm_password': 'BrandNewPass123!'
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Current password is required to change password.", resp.get_data(as_text=True))

    def test_11_password_change_incorrect_current_password(self):
        """Providing wrong current password is rejected and does not update password."""
        self.login_as(self.user1)
        resp = self.client.post('/manage-profile', data={
            'fullname': self.user1['full_name'],
            'email': self.user1['email'],
            'current_password': 'CompletelyWrongPassword!',
            'new_password': 'BrandNewPass123!',
            'confirm_password': 'BrandNewPass123!'
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Current password is incorrect.", resp.get_data(as_text=True))

    def test_12_password_change_mismatched_confirmation(self):
        """New password and confirmation mismatch is rejected."""
        self.login_as(self.user1)
        resp = self.client.post('/manage-profile', data={
            'fullname': self.user1['full_name'],
            'email': self.user1['email'],
            'current_password': self.initial_password_1,
            'new_password': 'BrandNewPass123!',
            'confirm_password': 'DifferentPass123!'
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("New password and confirmation do not match.", resp.get_data(as_text=True))

    def test_13_password_change_too_short(self):
        """New password shorter than 6 characters is rejected."""
        self.login_as(self.user1)
        resp = self.client.post('/manage-profile', data={
            'fullname': self.user1['full_name'],
            'email': self.user1['email'],
            'current_password': self.initial_password_1,
            'new_password': 'short',
            'confirm_password': 'short'
        })
        self.assertEqual(resp.status_code, 400)
        self.assertIn("Password must be at least 6 characters long.", resp.get_data(as_text=True))

    def test_14_password_change_success_securely_hashed_and_authenticates(self):
        """Valid password change securely hashes the new password and allows subsequent login."""
        self.login_as(self.user1)
        new_password = "SecureThriftPass2026!"

        resp = self.client.post('/manage-profile', data={
            'fullname': self.user1['full_name'],
            'email': self.user1['email'],
            'current_password': self.initial_password_1,
            'new_password': new_password,
            'confirm_password': new_password
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Your profile and password have been successfully updated!", html)

        # Inspect database record
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT password FROM users WHERE user_id = %s", (self.user1_id,))
            stored_record = cursor.fetchone()
            stored_pw = stored_record['password']

            # NEVER store plain text
            self.assertNotEqual(stored_pw, new_password, "Password must not be stored in plain text!")
            self.assertNotEqual(stored_pw, self.initial_password_1)

            # Must verify with check_password_hash
            self.assertTrue(check_password_hash(stored_pw, new_password), "Stored password must be a valid hash matching the new password")
        finally:
            cursor.close()
            conn.close()

        # Verify old password cannot log in
        self.logout()
        resp_old_login = self.client.post('/login', data={
            'email': self.user1['email'],
            'password': self.initial_password_1
        })
        self.assertEqual(resp_old_login.status_code, 400)
        self.assertIn("Incorrect password.", resp_old_login.get_data(as_text=True))

        # Verify new password DOES log in successfully
        resp_new_login = self.client.post('/login', data={
            'email': self.user1['email'],
            'password': new_password
        }, follow_redirects=False)
        self.assertEqual(resp_new_login.status_code, 302)
        self.assertIn('/user-dashboard', resp_new_login.headers.get('Location', ''))

    # -------------------------------------------------------------
    # 8. Ownership and Isolation Tests
    # -------------------------------------------------------------
    def test_15_user_cannot_update_another_user_profile_via_form_tampering(self):
        """User 1 logged in cannot tamper form user_id to modify User 2's profile (403 Forbidden)."""
        self.login_as(self.user1)

        # Send User 2's user_id in the POST request
        resp = self.client.post('/manage-profile', data={
            'user_id': self.user2_id,
            'fullname': 'Tampered Hacker Name',
            'email': 'hacked_user2@example.com'
        })
        self.assertEqual(resp.status_code, 403, "Tampering with user_id must result in 403 Forbidden")

        # Verify User 2 was not modified in the database
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT full_name, email FROM users WHERE user_id = %s", (self.user2_id,))
            user2 = cursor.fetchone()
            self.assertEqual(user2['full_name'], "Test User Two")
            self.assertEqual(user2['email'], self.test_email_2)
        finally:
            cursor.close()
            conn.close()

    def test_16_user_cannot_access_another_user_profile_by_id(self):
        """User 1 logged in cannot view or edit User 2 via /profile/<user2_id> (403 Forbidden)."""
        self.login_as(self.user1)
        resp = self.client.get(f'/profile/{self.user2_id}')
        self.assertEqual(resp.status_code, 403, "Accessing another user's profile URL must return 403 Forbidden")

        # But can access their own profile by ID
        resp_own = self.client.get(f'/profile/{self.user1_id}')
        self.assertEqual(resp_own.status_code, 200)

if __name__ == '__main__':
    unittest.main()
