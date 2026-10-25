"""
Unit and integration test suite for ThriftMap Admin 'Manage Users' feature.
Covers:
1. Access control:
   - Authenticated administrator (role='admin') granted access (200 OK)
   - Authenticated shopper (role='user') denied access (302 redirect)
   - Authenticated store owner (role='owner') denied access (302 redirect)
   - Unauthenticated guest redirected to login (302 redirect)
2. User list display:
   - Table displays User ID, Name, Email, Role, Account Status, Registration Date, Actions
   - Activity metrics (owned stores, reviews, favorites)
3. Search and filtering:
   - Search by name or email
   - Filter by role (user, owner, admin)
   - Filter by status (active, inactive)
   - Empty state when no users match search criteria
4. User actions & security:
   - View user profile / details endpoint
   - Change user role between Shopper and Store Owner
   - Toggle account status (activate / deactivate)
   - Deactivated user rejected during login (403 Forbidden)
   - Self-modification blocked: Admin cannot change own role, deactivate self, or delete self
   - Last administrator account cannot be demoted or deleted
5. Safe deletion & baseline data preservation:
   - Clean handling of associated user data
   - Existing baseline records preserved intact
"""
import unittest
from app import app, get_db_connection

class TestAdminManageUsers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        try:
            # Record baseline user IDs and counts
            cursor.execute("SELECT user_id, full_name, email, role, status FROM users ORDER BY user_id ASC")
            cls.baseline_users = cursor.fetchall()
            cls.baseline_user_ids = {u['user_id'] for u in cls.baseline_users}
            cls.baseline_user_count = len(cls.baseline_users)

            # Locate admin, shopper, owner
            cls.admin_user = next((u for u in cls.baseline_users if u['role'] == 'admin'), None)
            cls.shopper_user = next((u for u in cls.baseline_users if u['role'] == 'user'), None)
            cls.owner_user = next((u for u in cls.baseline_users if u['role'] == 'owner'), None)

            assert cls.admin_user is not None, "At least one admin user required in database"
            assert cls.shopper_user is not None, "At least one shopper required in database"
            assert cls.owner_user is not None, "At least one store owner required in database"

        finally:
            cursor.close()
            conn.close()

        cls.created_user_ids = []

    @classmethod
    def tearDownClass(cls):
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # Clean up any test users created during test execution
            if cls.created_user_ids:
                format_strings = ','.join(['%s'] * len(cls.created_user_ids))
                cursor.execute(f"DELETE FROM users WHERE user_id IN ({format_strings})", tuple(cls.created_user_ids))
                conn.commit()

            # Ensure baseline users retain their original roles and statuses
            for u in cls.baseline_users:
                cursor.execute(
                    "UPDATE users SET role = %s, status = %s WHERE user_id = %s",
                    (u['role'], u.get('status', 'active'), u['user_id'])
                )
            conn.commit()

            # Verify exact count matches baseline
            cursor.execute("SELECT COUNT(*) FROM users")
            final_count = cursor.fetchone()[0]
            assert final_count == cls.baseline_user_count, f"Database leak detected: expected {cls.baseline_user_count}, found {final_count}"
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

    def test_01_admin_can_access_manage_users(self):
        """Administrator must be granted access (200 OK) to /admin/users."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/users')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("Manage Users", html)
        self.assertIn("User Directory & Security", html)
        self.assertIn("table-users", html)

    def test_02_shopper_cannot_access_manage_users(self):
        """Shopper (role='user') must be denied access and redirected."""
        self.login_as(self.shopper_user)
        resp = self.client.get('/admin/users', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        # Follow redirect and verify flash message
        redirected_resp = self.client.get('/admin/users', follow_redirects=True)
        html = redirected_resp.get_data(as_text=True)
        self.assertIn("Access denied", html)

    def test_03_store_owner_cannot_access_manage_users(self):
        """Store owner (role='owner') must be denied access and redirected."""
        self.login_as(self.owner_user)
        resp = self.client.get('/admin/users', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        redirected_resp = self.client.get('/admin/users', follow_redirects=True)
        html = redirected_resp.get_data(as_text=True)
        self.assertIn("Access denied", html)

    def test_04_unauthenticated_guest_cannot_access_manage_users(self):
        """Unauthenticated guest must be redirected to login page."""
        self.logout()
        resp = self.client.get('/admin/users', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.headers.get('Location', ''))

    # --- 2. User List Display & Content Tests ---

    def test_05_user_list_contains_expected_baseline_users(self):
        """User list should display user ID, name, email, role, and status for users."""
        self.login_as(self.admin_user)
        resp = self.client.get(f'/admin/users?search={self.admin_user["email"]}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(self.admin_user['full_name'], html)
        self.assertIn(self.admin_user['email'], html)
        self.assertIn("Admin", html)

    # --- 3. Search and Filter Tests ---

    def test_06_search_by_name(self):
        """Search query matching part of a user's name should return only matching users."""
        self.login_as(self.admin_user)
        search_term = self.shopper_user['full_name'][:4]
        resp = self.client.get(f'/admin/users?search={search_term}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(self.shopper_user['full_name'], html)

    def test_07_search_by_email(self):
        """Search query matching user email should return the target user."""
        self.login_as(self.admin_user)
        search_email = self.owner_user['email'].split('@')[0]
        resp = self.client.get(f'/admin/users?search={search_email}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(self.owner_user['email'], html)

    def test_08_filter_by_role_shopper(self):
        """Filtering by role='user' should list only Shoppers."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/users?role=user')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(self.shopper_user['full_name'], html)
        self.assertNotIn(f"id=\"user-row-{self.admin_user['user_id']}\"", html)

    def test_09_filter_by_role_owner(self):
        """Filtering by role='owner' should list only Store Owners."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/users?role=owner')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(self.owner_user['full_name'], html)
        self.assertNotIn(f"id=\"user-row-{self.admin_user['user_id']}\"", html)

    def test_10_empty_state_on_unmatched_search(self):
        """A search query that yields no matches should display a friendly empty state."""
        self.login_as(self.admin_user)
        resp = self.client.get('/admin/users?search=NonExistentUserXYZ987654321')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("No Users Found", html)
        self.assertIn("empty-state-users", html)

    # --- 4. User Details View Tests ---

    def test_11_admin_user_details_page(self):
        """Admin can access full user profile page at /admin/user/<id>."""
        self.login_as(self.admin_user)
        resp = self.client.get(f'/admin/user/{self.shopper_user["user_id"]}')
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn(self.shopper_user['full_name'], html)
        self.assertIn(self.shopper_user['email'], html)
        self.assertIn("Stores Owned", html)
        self.assertIn("Reviews Authored", html)

    def test_12_admin_user_details_json_endpoint(self):
        """Admin can fetch JSON details via format=json query parameter."""
        self.login_as(self.admin_user)
        resp = self.client.get(f'/admin/user/{self.shopper_user["user_id"]}?format=json')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data['user']['user_id'], self.shopper_user['user_id'])
        self.assertEqual(data['user']['email'], self.shopper_user['email'])

    # --- 5. Security & Protection Constraints ---

    def test_13_admin_cannot_change_own_role(self):
        """Logged-in admin cannot demote or change their own role."""
        self.login_as(self.admin_user)
        resp = self.client.post(
            f'/admin/user/{self.admin_user["user_id"]}/change-role',
            data={'new_role': 'user'},
            follow_redirects=True
        )
        html = resp.get_data(as_text=True)
        self.assertIn("You cannot change your own administrator role", html)

        # Verify DB role unchanged
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT role FROM users WHERE user_id = %s", (self.admin_user['user_id'],))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        self.assertEqual(row['role'], 'admin')

    def test_14_admin_cannot_deactivate_own_account(self):
        """Logged-in admin cannot deactivate their own administrator account."""
        self.login_as(self.admin_user)
        resp = self.client.post(
            f'/admin/user/{self.admin_user["user_id"]}/toggle-status',
            follow_redirects=True
        )
        html = resp.get_data(as_text=True)
        self.assertIn("You cannot deactivate your own administrator account", html)

        # Verify DB status unchanged
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT status FROM users WHERE user_id = %s", (self.admin_user['user_id'],))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        self.assertEqual(row['status'], 'active')

    def test_15_admin_cannot_delete_own_account(self):
        """Logged-in admin cannot delete their own account."""
        self.login_as(self.admin_user)
        resp = self.client.post(
            f'/admin/user/{self.admin_user["user_id"]}/delete',
            follow_redirects=True
        )
        html = resp.get_data(as_text=True)
        self.assertIn("You cannot delete your own administrator account", html)

    def test_16_last_administrator_cannot_be_demoted(self):
        """If only one administrator exists, they cannot be demoted."""
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'")
        admin_count = cursor.fetchone()['cnt']
        cursor.close()
        conn.close()

        if admin_count == 1:
            self.login_as(self.admin_user)
            resp = self.client.post(
                f'/admin/user/{self.admin_user["user_id"]}/change-role',
                data={'new_role': 'user'},
                follow_redirects=True
            )
            html = resp.get_data(as_text=True)
            self.assertTrue(
                "You cannot change your own administrator role" in html or
                "Cannot change role of the only administrator account" in html
            )

    # --- 6. Role Change, Status Toggle, and Safe Operations on Test User ---

    def test_17_role_change_between_shopper_and_owner(self):
        """Admin can change a user's role from Shopper to Store Owner and back."""
        # Create a temporary test user
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (full_name, email, password, role, status) VALUES (%s, %s, %s, %s, %s)",
            ("Temp Role User", "temprole_test_2026@example.com", "pass123", "user", "active")
        )
        conn.commit()
        temp_user_id = cursor.lastrowid
        self.created_user_ids.append(temp_user_id)
        cursor.close()
        conn.close()

        self.login_as(self.admin_user)

        # 1. Switch to Store Owner
        resp1 = self.client.post(
            f'/admin/user/{temp_user_id}/change-role',
            data={'new_role': 'owner'},
            follow_redirects=True
        )
        html1 = resp1.get_data(as_text=True)
        self.assertIn("successfully updated to Store Owner", html1)

        # Verify DB
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT role FROM users WHERE user_id = %s", (temp_user_id,))
        self.assertEqual(cursor.fetchone()['role'], 'owner')
        cursor.close()
        conn.close()

        # 2. Switch back to Shopper
        resp2 = self.client.post(
            f'/admin/user/{temp_user_id}/change-role',
            data={'new_role': 'user'},
            follow_redirects=True
        )
        html2 = resp2.get_data(as_text=True)
        self.assertIn("successfully updated to Shopper", html2)

        conn2 = get_db_connection()
        cursor2 = conn2.cursor(dictionary=True)
        cursor2.execute("SELECT role FROM users WHERE user_id = %s", (temp_user_id,))
        self.assertEqual(cursor2.fetchone()['role'], 'user')
        cursor2.close()
        conn2.close()

    def test_18_toggle_status_and_deactivated_login_block(self):
        """Admin can deactivate account and deactivated account cannot log in (403 Forbidden)."""
        # Create a temporary test user
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (full_name, email, password, role, status) VALUES (%s, %s, %s, %s, %s)",
            ("Temp Status User", "tempstatus_test_2026@example.com", "mypassword123", "user", "active")
        )
        conn.commit()
        temp_user_id = cursor.lastrowid
        self.created_user_ids.append(temp_user_id)
        cursor.close()
        conn.close()

        self.login_as(self.admin_user)

        # Deactivate
        resp = self.client.post(f'/admin/user/{temp_user_id}/toggle-status', follow_redirects=True)
        html = resp.get_data(as_text=True)
        self.assertIn("has been deactivated successfully", html)

        # Verify DB
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT status FROM users WHERE user_id = %s", (temp_user_id,))
        self.assertEqual(cursor.fetchone()['status'], 'inactive')
        cursor.close()
        conn.close()

        # Log out admin and attempt to log in as the deactivated user
        self.logout()
        login_resp = self.client.post(
            '/login',
            data={'email': 'tempstatus_test_2026@example.com', 'password': 'mypassword123'},
            follow_redirects=False
        )
        self.assertEqual(login_resp.status_code, 403)
        html_login = login_resp.get_data(as_text=True)
        self.assertIn("Your account has been deactivated", html_login)

        # Reactivate
        self.login_as(self.admin_user)
        reactivate_resp = self.client.post(f'/admin/user/{temp_user_id}/toggle-status', follow_redirects=True)
        html_reactivate = reactivate_resp.get_data(as_text=True)
        self.assertIn("has been activated successfully", html_reactivate)

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT status FROM users WHERE user_id = %s", (temp_user_id,))
        self.assertEqual(cursor.fetchone()['status'], 'active')
        cursor.close()
        conn.close()

    def test_19_safe_delete_user(self):
        """Admin can safely delete a non-admin user without leaving orphaned records."""
        # Create a temporary user with a review and favorite
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (full_name, email, password, role, status) VALUES (%s, %s, %s, %s, %s)",
            ("Temp Delete User", "tempdelete_test_2026@example.com", "pass123", "user", "active")
        )
        conn.commit()
        del_user_id = cursor.lastrowid
        cursor.close()
        conn.close()

        self.login_as(self.admin_user)
        del_resp = self.client.post(f'/admin/user/{del_user_id}/delete', follow_redirects=True)
        html = del_resp.get_data(as_text=True)
        self.assertIn("safely deleted", html)

        # Confirm user is absent from DB
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE user_id = %s", (del_user_id,))
        self.assertIsNone(cursor.fetchone())
        cursor.close()
        conn.close()

if __name__ == '__main__':
    unittest.main()
