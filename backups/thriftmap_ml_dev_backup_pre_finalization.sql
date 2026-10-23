-- MySQL dump 10.13  Distrib 5.6.16, for Win32 (x86)
--
-- Host: localhost    Database: thriftmap_ml_dev
-- ------------------------------------------------------
-- Server version	5.6.16

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Current Database: `thriftmap_ml_dev`
--

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `thriftmap_ml_dev` /*!40100 DEFAULT CHARACTER SET latin1 */;

USE `thriftmap_ml_dev`;

--
-- Table structure for table `categories`
--

DROP TABLE IF EXISTS `categories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `categories` (
  `category_id` int(11) NOT NULL AUTO_INCREMENT,
  `category_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`category_id`),
  UNIQUE KEY `category_name` (`category_name`)
) ENGINE=InnoDB AUTO_INCREMENT=7 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `categories`
--

LOCK TABLES `categories` WRITE;
/*!40000 ALTER TABLE `categories` DISABLE KEYS */;
INSERT INTO `categories` VALUES (4,'Accessories'),(5,'Bags'),(2,'Clothing'),(3,'Shoes'),(1,'Vintage Clothing'),(6,'Vintage Items');
/*!40000 ALTER TABLE `categories` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `favorites`
--

DROP TABLE IF EXISTS `favorites`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `favorites` (
  `favorite_id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `store_id` int(11) NOT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`favorite_id`),
  UNIQUE KEY `uq_user_store` (`user_id`,`store_id`),
  KEY `fk_favorites_store` (`store_id`),
  CONSTRAINT `fk_favorites_store` FOREIGN KEY (`store_id`) REFERENCES `stores` (`store_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_favorites_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=22 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `favorites`
--

LOCK TABLES `favorites` WRITE;
/*!40000 ALTER TABLE `favorites` DISABLE KEYS */;
INSERT INTO `favorites` VALUES (14,14,13,'2026-10-19 10:53:12'),(15,14,14,'2026-10-19 10:53:12'),(16,15,15,'2026-10-19 10:53:12'),(17,15,18,'2026-10-19 10:53:12'),(18,16,14,'2026-10-19 10:53:12'),(19,16,16,'2026-10-19 10:53:12'),(20,17,17,'2026-10-19 10:53:12'),(21,17,13,'2026-10-19 10:53:12');
/*!40000 ALTER TABLE `favorites` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `reviews`
--

DROP TABLE IF EXISTS `reviews`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `reviews` (
  `review_id` int(11) NOT NULL AUTO_INCREMENT,
  `store_id` int(11) NOT NULL,
  `user_id` int(11) DEFAULT NULL,
  `rating` int(11) DEFAULT NULL,
  `comment` text COLLATE utf8mb4_unicode_ci,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`review_id`),
  KEY `fk_reviews_user` (`user_id`),
  KEY `idx_reviews_store_id` (`store_id`),
  CONSTRAINT `fk_reviews_store` FOREIGN KEY (`store_id`) REFERENCES `stores` (`store_id`) ON DELETE CASCADE,
  CONSTRAINT `fk_reviews_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=59 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `reviews`
--

LOCK TABLES `reviews` WRITE;
/*!40000 ALTER TABLE `reviews` DISABLE KEYS */;
INSERT INTO `reviews` VALUES (23,4,4,4,'There is a huge denim collection with a wide variety. Clothes are very affordable..','2026-10-17 14:46:19'),(32,13,14,5,'Incredible 90s jackets and authentic vintage items! [Synthetic Review]','2026-10-19 10:53:12'),(33,14,14,4,'Great selection of vintage trousers and denim jackets. [Synthetic Review]','2026-10-19 10:53:12'),(34,15,15,5,'Best curated retro sneakers in South India! [Synthetic Review]','2026-10-19 10:53:12'),(35,18,15,5,'Rare vintage windbreakers in mint condition. [Synthetic Review]','2026-10-19 10:53:12'),(36,14,16,5,'Super friendly staff and lovely pre-loved Levi\'s. [Synthetic Review]','2026-10-19 10:53:12'),(37,16,16,4,'High quality leather totes and vintage shoulder bags. [Synthetic Review]','2026-10-19 10:53:12'),(38,17,17,5,'Found gorgeous brass accessories and retro earrings! [Synthetic Review]','2026-10-19 10:53:12'),(39,13,17,4,'Wonderful ambience and unique aesthetic pieces. [Synthetic Review]','2026-10-19 10:53:12'),(47,15,4,3,'It has so many collections. but it is expensive.','2026-10-19 11:12:32'),(58,5,4,4,'Good shop. Good collections. Affordable items','2026-10-19 11:34:39');
/*!40000 ALTER TABLE `reviews` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `stores`
--

DROP TABLE IF EXISTS `stores`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `stores` (
  `store_id` int(11) NOT NULL AUTO_INCREMENT,
  `owner_id` int(11) NOT NULL,
  `category_id` int(11) NOT NULL,
  `store_name` varchar(150) COLLATE utf8mb4_unicode_ci NOT NULL,
  `description` text COLLATE utf8mb4_unicode_ci NOT NULL,
  `address` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `city` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `contact_number` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL,
  `opening_hours` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `latitude` decimal(10,8) DEFAULT NULL,
  `longitude` decimal(11,8) DEFAULT NULL,
  `image` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` enum('pending','approved','rejected') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending',
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`store_id`),
  KEY `fk_stores_owner` (`owner_id`),
  KEY `fk_stores_category` (`category_id`),
  KEY `idx_stores_status` (`status`),
  KEY `idx_stores_city` (`city`),
  KEY `idx_stores_created_at` (`created_at`),
  CONSTRAINT `fk_stores_category` FOREIGN KEY (`category_id`) REFERENCES `categories` (`category_id`),
  CONSTRAINT `fk_stores_owner` FOREIGN KEY (`owner_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=20 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `stores`
--

LOCK TABLES `stores` WRITE;
/*!40000 ALTER TABLE `stores` DISABLE KEYS */;
INSERT INTO `stores` VALUES (3,5,1,'Vintage Hub','Grab the trending vintage clothes','142 vintage row','kottayam','1234567899','Mon - Sat 09:00am to 08:00pm',9.58915000,76.52410700,'uploads/stores/store_d1c94e5eaa01_1792171729.png','approved','2026-10-11 14:29:07'),(4,5,2,'Denim Store','Find your perfect denims','Main Road, Suite 4','Thiruvalla','1234567890','10:00 AM - 9:00 PM',9.38804900,76.57845100,'uploads/stores/store_cf7870286bae_1792171930.jpg','approved','2026-10-16 17:32:10'),(5,6,3,'Shoe Peedya','Grab your sneakers','MC Road 103','Mallappally','1122112211','Mon - Sat 09:00 am - 08:00 pm',9.44463200,76.65513700,'uploads/stores/store_308d542f11ff_1792182535.png','approved','2026-10-16 20:28:55'),(13,13,1,'Retro Vault Vintage','Curated 90s vintage clothing, oversized graphic tees, denim jackets, and rare retro flannel shirts. [Synthetic Demo Store]','Baker Junction, MG Road','Kottayam','+91 98471 23450','10:00 AM - 8:00 PM',9.59160000,76.52220000,NULL,'approved','2026-10-19 10:53:11'),(14,13,2,'Kochi Pre-Loved Denim & Co','High-grade pre-loved denim, Levi\'s classics, trucker jackets, cargo pants, and vintage workwear trousers. [Synthetic Demo Store]','Panampilly Nagar, Main Ave','Kochi','+91 98471 23451','11:00 AM - 9:00 PM',9.96740000,76.29290000,NULL,'approved','2026-10-19 10:53:11'),(15,13,3,'Sole Revival Sneakers & Boots','Restored retro sneakers, leather boots, converse, and vintage street shoes curated for sustainable style lovers. [Synthetic Demo Store]','Indiranagar 100ft Road','Bangalore','+91 98471 23452','10:30 AM - 8:30 PM',12.97160000,77.59460000,NULL,'approved','2026-10-19 10:53:11'),(16,13,5,'The Vintage Tote & Bag Co','Handcrafted leather handbags, recycled canvas totes, retro backpacks, and pre-owned luxury purses. [Synthetic Demo Store]','Fort Kochi Art District','Kochi','+91 98471 23453','10:00 AM - 7:30 PM',9.96580000,76.24410000,NULL,'approved','2026-10-19 10:53:11'),(17,13,4,'Heritage Brass & Antique Accents','Vintage belt buckles, retro eyewear, brass pins, silver trinkets, and aesthetic thrifted accessories. [Synthetic Demo Store]','Kalarickal Bazaar','Kottayam','+91 98471 23454','10:00 AM - 7:00 PM',9.58900000,76.52500000,NULL,'approved','2026-10-19 10:53:11'),(18,13,6,'Bangalore 90s Streetwear Archive','Nostalgic 90s pop culture apparel, varsity windbreakers, band tees, and collectible vintage streetwear. [Synthetic Demo Store]','Koramangala 5th Block','Bangalore','+91 98471 23455','11:00 AM - 9:30 PM',12.93520000,77.62450000,NULL,'approved','2026-10-19 10:53:11'),(19,13,1,'Pending Secret Vintage Hub','Private unapproved boutique submitted for review. Must never appear in public recommendations. [Synthetic Demo Store]','Marine Drive','Kochi','+91 98471 23456','10:00 AM - 6:00 PM',9.98160000,76.27500000,NULL,'pending','2026-10-19 10:53:11');
/*!40000 ALTER TABLE `stores` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `users` (
  `user_id` int(11) NOT NULL AUTO_INCREMENT,
  `full_name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `email` varchar(191) COLLATE utf8mb4_unicode_ci NOT NULL,
  `password` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `role` enum('user','owner','admin') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'user',
  `preferred_categories` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `preferred_city` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `preferred_lat` decimal(10,8) DEFAULT NULL,
  `preferred_lng` decimal(11,8) DEFAULT NULL,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB AUTO_INCREMENT=19 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,'Admin User','admin@thriftmap.com','adminpass','admin',NULL,NULL,NULL,NULL,'2026-10-07 18:58:59'),(2,'New User','newuser@example.com','pass123','user','3','mAlLaPpaLLy',NULL,NULL,'2026-10-07 18:58:59'),(4,'sample user','sample@mail.com','123456','user','3','mallappally',NULL,NULL,'2026-10-07 19:10:53'),(5,'sample store owner','samplestoreowner@mail.com','123456','owner',NULL,NULL,NULL,NULL,'2026-10-07 19:11:26'),(6,'Store Owner 2','storeowner2@mail.com','123456','owner',NULL,NULL,NULL,NULL,'2026-10-16 20:25:06'),(13,'[Synthetic] Demo Store Owner','owner@synthetic.thriftmap.dev','scrypt:32768:8:1$E5zRhQz1zPx4zhR5$9547b3d8c4181e8ebcdc9542df13357b95ec7b97a108ed7fd41fd5f176d8c5e2c17a9719a186abbef3894578e443061de76544047c0b797260cf8f0b663b7636','owner',NULL,'Kochi',NULL,NULL,'2026-10-19 10:53:11'),(14,'[Synthetic] Priya Vintage Fan','priya@synthetic.thriftmap.dev','scrypt:32768:8:1$otAXvkF0aK4MVuOn$49e2e1a0acfa82327581dcf5b1c402e25099f8785bc1a764db82a2f03950fdd7f17d39c12084140cad7f7d60e792c7802e70ecc60ee6620c3256f566a02163ec','user','1,2','Kottayam',9.59160000,76.52220000,'2026-10-19 10:53:12'),(15,'[Synthetic] Rahul Streetwear & Shoes','rahul@synthetic.thriftmap.dev','scrypt:32768:8:1$3sx77mCNQwp4K624$f97b0ea20b75dd3a0f11ae9882620519f5be09bbad9f646446e7331054fc08413ed1bb80e2bbf82b3173d91976632923ed2d1dd47354cd0c79db6f94dc555554','user','3,6','Bangalore',12.97160000,77.59460000,'2026-10-19 10:53:12'),(16,'[Synthetic] Maya Kochi Circular Shopper','maya@synthetic.thriftmap.dev','scrypt:32768:8:1$CujjM9rFa3jJYJfB$3820451d4a556be8a95b1ac8e82efeb5f07c0455e35f3af99c1caaa70c21bae28fa06b6b614eb01fa50d869697fb6d3e4c286e42bb9d1a63e666c4ff1a2befba','user','2,5','Kochi',9.96740000,76.29290000,'2026-10-19 10:53:12'),(17,'[Synthetic] Ananya Accessories Lover','ananya@synthetic.thriftmap.dev','scrypt:32768:8:1$mcgLEcKUr38B6pGW$0c795b0faa6dc097d624fa15f7127eda597ea3c778604c967b1fcac8095afb1eb2afda0e3cd92c836a54813c6bb62f245cc9e36f0becdb1b0171a3466cf928ea','user','4,1','Kottayam',9.58900000,76.52500000,'2026-10-19 10:53:12'),(18,'[Synthetic] ColdStart New Shopper','coldstart@synthetic.thriftmap.dev','scrypt:32768:8:1$NxIOJ7ALwUNbtDrW$d43470b1ec4ae527edeab774e39d14b70e3041ada5177ca0dae06d919fb50c55109370d91ec921d1382b85c390bddbd02053c443b9770c10f5fc962a283c4fa6','user','1','Kochi',NULL,NULL,'2026-10-19 10:53:12');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-10-20 21:16:03
