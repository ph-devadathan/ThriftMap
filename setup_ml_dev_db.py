"""
Script to safely clone thriftmap_db schema and baseline data into thriftmap_ml_dev.
The original thriftmap_db is treated strictly as read-only.
"""
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD

SOURCE_DB = "thriftmap_db"
TARGET_DB = "thriftmap_ml_dev"
TABLES = ["categories", "users", "stores", "favorites", "reviews"]

def clone_database():
    conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD)
    cursor = conn.cursor()

    try:
        # Create target database if it does not exist
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{TARGET_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        print(f"Ensured target database '{TARGET_DB}' exists.")

        # Disable foreign key checks for clean recreation in target
        cursor.execute(f"USE `{TARGET_DB}`")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")

        # Copy table structures and baseline data
        for table in TABLES:
            # Get CREATE TABLE DDL from source
            cursor.execute(f"SHOW CREATE TABLE `{SOURCE_DB}`.`{table}`")
            create_stmt = cursor.fetchone()[1]

            # Drop and recreate in target database ONLY
            cursor.execute(f"DROP TABLE IF EXISTS `{TARGET_DB}`.`{table}`")
            cursor.execute(create_stmt)

            # Copy baseline data from source
            cursor.execute(f"INSERT INTO `{TARGET_DB}`.`{table}` SELECT * FROM `{SOURCE_DB}`.`{table}`")
            print(f"Cloned table '{table}' with {cursor.rowcount} baseline rows.")

        # Re-enable foreign key checks
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        conn.commit()

        # Add user preference columns in TARGET_DB ONLY
        cursor.execute(f"USE `{TARGET_DB}`")
        cursor.execute("SHOW COLUMNS FROM `users` LIKE 'preferred_categories'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE `users` ADD COLUMN `preferred_categories` VARCHAR(255) DEFAULT NULL AFTER `role`")
            print("Added 'preferred_categories' to users in target DB.")

        cursor.execute("SHOW COLUMNS FROM `users` LIKE 'preferred_city'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE `users` ADD COLUMN `preferred_city` VARCHAR(100) DEFAULT NULL AFTER `preferred_categories`")
            print("Added 'preferred_city' to users in target DB.")

        cursor.execute("SHOW COLUMNS FROM `users` LIKE 'preferred_lat'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE `users` ADD COLUMN `preferred_lat` DECIMAL(10,8) DEFAULT NULL AFTER `preferred_city`")
            print("Added 'preferred_lat' to users in target DB.")

        cursor.execute("SHOW COLUMNS FROM `users` LIKE 'preferred_lng'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE `users` ADD COLUMN `preferred_lng` DECIMAL(11,8) DEFAULT NULL AFTER `preferred_lat`")
            print("Added 'preferred_lng' to users in target DB.")

        conn.commit()
        print("Database cloning and preference schema setup completed successfully!")

    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    clone_database()
