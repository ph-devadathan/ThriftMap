-- =============================================================
-- ThriftMap - Complete MySQL Database Schema
-- Database Name: thriftmap_db
-- Character Set: utf8mb4
-- Collation:     utf8mb4_unicode_ci
-- Storage Engine: InnoDB
-- Compatible with: MySQL 5.7+, MySQL 8.0+, MariaDB 10.3+ (XAMPP)
-- =============================================================

-- Disable foreign key checks temporarily during schema definition
SET @OLD_FOREIGN_KEY_CHECKS = @@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS = 0;
SET @OLD_SQL_MODE = @@SQL_MODE, SQL_MODE = 'NO_AUTO_VALUE_ON_ZERO';
SET NAMES utf8mb4;

-- -------------------------------------------------------------
-- 1. Database Creation
-- -------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS `thriftmap_db`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `thriftmap_db`;

-- -------------------------------------------------------------
-- 2. Table: categories
-- Purpose: Lookup taxonomy for thrift boutique store categories.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `categories` (
  `category_id` INT(11) NOT NULL AUTO_INCREMENT,
  `category_name` VARCHAR(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`category_id`),
  UNIQUE KEY `uq_categories_name` (`category_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- 3. Table: users
-- Purpose: Registered platform members (Shoppers, Store Owners, Admins).
-- Includes authentication credentials, account status, and recommendation preferences.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
  `user_id` INT(11) NOT NULL AUTO_INCREMENT,
  `full_name` VARCHAR(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` VARCHAR(191) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` ENUM('user', 'owner', 'admin') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'user',
  `status` ENUM('active', 'inactive') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'active',
  `preferred_categories` VARCHAR(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `preferred_city` VARCHAR(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `preferred_lat` DECIMAL(10, 8) DEFAULT NULL,
  `preferred_lng` DECIMAL(11, 8) DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `uq_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- 4. Table: stores
-- Purpose: Thrift store listings managed by store owners and moderated by admins.
-- Includes geographic coordinates (lat/lng) for Leaflet map discovery and approval status.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `stores` (
  `store_id` INT(11) NOT NULL AUTO_INCREMENT,
  `owner_id` INT(11) NOT NULL,
  `category_id` INT(11) NOT NULL,
  `store_name` VARCHAR(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` TEXT COLLATE utf8mb4_unicode_ci NOT NULL,
  `address` VARCHAR(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `city` VARCHAR(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `contact_number` VARCHAR(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `opening_hours` VARCHAR(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latitude` DECIMAL(10, 8) DEFAULT NULL,
  `longitude` DECIMAL(11, 8) DEFAULT NULL,
  `image` VARCHAR(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` ENUM('pending', 'approved', 'rejected') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`store_id`),
  KEY `fk_stores_owner` (`owner_id`),
  KEY `fk_stores_category` (`category_id`),
  KEY `idx_stores_status` (`status`),
  KEY `idx_stores_city` (`city`),
  KEY `idx_stores_created_at` (`created_at`),
  CONSTRAINT `fk_stores_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_stores_category` FOREIGN KEY (`category_id`) REFERENCES `categories` (`category_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- 5. Table: favorites
-- Purpose: Bookmarked stores saved by shoppers for quick access and recommendation tuning.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `favorites` (
  `favorite_id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `store_id` INT(11) NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`favorite_id`),
  UNIQUE KEY `uq_user_store` (`user_id`, `store_id`),
  KEY `fk_favorites_user` (`user_id`),
  KEY `fk_favorites_store` (`store_id`),
  CONSTRAINT `fk_favorites_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_favorites_store` FOREIGN KEY (`store_id`) REFERENCES `stores` (`store_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- 6. Table: reviews
-- Purpose: Ratings (1-5 stars) and feedback comments authored by registered users for stores.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `reviews` (
  `review_id` INT(11) NOT NULL AUTO_INCREMENT,
  `store_id` INT(11) NOT NULL,
  `user_id` INT(11) DEFAULT NULL,
  `rating` INT(11) DEFAULT NULL,
  `comment` TEXT COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`review_id`),
  KEY `fk_reviews_user` (`user_id`),
  KEY `idx_reviews_store_id` (`store_id`),
  CONSTRAINT `fk_reviews_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_reviews_store` FOREIGN KEY (`store_id`) REFERENCES `stores` (`store_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -------------------------------------------------------------
-- 7. Standard Lookup Taxonomy: Categories
-- Predefined system categories required by store listing and filtering dropdowns.
-- -------------------------------------------------------------
INSERT INTO `categories` (`category_id`, `category_name`) VALUES
  (1, 'Vintage Clothing'),
  (2, 'Clothing'),
  (3, 'Shoes'),
  (4, 'Accessories'),
  (5, 'Bags'),
  (6, 'Vintage Items')
ON DUPLICATE KEY UPDATE `category_name` = VALUES(`category_name`);

-- Restore previous environment settings
SET FOREIGN_KEY_CHECKS = @OLD_FOREIGN_KEY_CHECKS;
SET SQL_MODE = @OLD_SQL_MODE;
