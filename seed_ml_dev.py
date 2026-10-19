"""
Repeatable Synthetic Demo Data Seed Script for thriftmap_ml_dev ONLY.
Provides synthetic stores, simulated users, favorites, ratings, and reviews
to power and demonstrate the Hybrid ML Recommendation System.

Safety:
- Strictly checks that current DB is 'thriftmap_ml_dev'. Refuses to modify 'thriftmap_db'.
- All synthetic users and stores have explicit synthetic markers ([Synthetic Demo Data]).
- Idempotent: Can be rerun safely without creating duplicates.
"""
import mysql.connector
from werkzeug.security import generate_password_hash
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

SYNTHETIC_EMAIL_DOMAIN = "@synthetic.thriftmap.dev"

def seed_development_data():
    if DB_NAME != "thriftmap_ml_dev":
        raise RuntimeError(f"Safety Halt: seed_ml_dev.py must only run against 'thriftmap_ml_dev', current DB is '{DB_NAME}'")

    conn = mysql.connector.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
    cursor = conn.cursor(dictionary=True)

    try:
        print(f"Connected to development database: {DB_NAME}")

        # 1. Clean existing synthetic records to guarantee repeatability and prevent duplicate growth
        cursor.execute("SELECT user_id FROM users WHERE email LIKE %s", (f"%{SYNTHETIC_EMAIL_DOMAIN}",))
        synth_user_ids = [r['user_id'] for r in cursor.fetchall()]

        if synth_user_ids:
            fmt = ','.join(['%s'] * len(synth_user_ids))
            cursor.execute(f"DELETE FROM favorites WHERE user_id IN ({fmt})", tuple(synth_user_ids))
            cursor.execute(f"DELETE FROM reviews WHERE user_id IN ({fmt})", tuple(synth_user_ids))
            cursor.execute(f"DELETE FROM stores WHERE owner_id IN ({fmt})", tuple(synth_user_ids))
            cursor.execute(f"DELETE FROM users WHERE user_id IN ({fmt})", tuple(synth_user_ids))
            conn.commit()
            print(f"Cleaned previous synthetic users ({len(synth_user_ids)}) and their interactions.")

        # Also clean any stores with synthetic marker in description
        cursor.execute("DELETE FROM stores WHERE description LIKE '%[Synthetic Demo Store]%'")
        conn.commit()

        # 2. Fetch categories
        cursor.execute("SELECT category_id, category_name FROM categories")
        categories_map = {r['category_name'].lower(): r['category_id'] for r in cursor.fetchall()}
        vintage_cat = categories_map.get('vintage clothing', 1)
        clothing_cat = categories_map.get('clothing', 2)
        shoes_cat = categories_map.get('shoes', 3)
        acc_cat = categories_map.get('accessories', 4)
        bags_cat = categories_map.get('bags', 5)
        vintage_items_cat = categories_map.get('vintage items', 6)

        # 3. Create a synthetic store owner
        owner_pw = generate_password_hash("SynthOwner123!")
        cursor.execute("""
            INSERT INTO users (full_name, email, password, role, preferred_city)
            VALUES (%s, %s, %s, 'owner', 'Kochi')
        """, ("[Synthetic] Demo Store Owner", f"owner{SYNTHETIC_EMAIL_DOMAIN}", owner_pw))
        owner_id = cursor.lastrowid

        # 4. Create varied fictional stores
        synthetic_stores_data = [
            {
                "name": "Retro Vault Vintage",
                "cat": vintage_cat,
                "desc": "Curated 90s vintage clothing, oversized graphic tees, denim jackets, and rare retro flannel shirts. [Synthetic Demo Store]",
                "address": "Baker Junction, MG Road",
                "city": "Kottayam",
                "phone": "+91 98471 23450",
                "hours": "10:00 AM - 8:00 PM",
                "lat": 9.5916,
                "lng": 76.5222,
                "status": "approved"
            },
            {
                "name": "Kochi Pre-Loved Denim & Co",
                "cat": clothing_cat,
                "desc": "High-grade pre-loved denim, Levi's classics, trucker jackets, cargo pants, and vintage workwear trousers. [Synthetic Demo Store]",
                "address": "Panampilly Nagar, Main Ave",
                "city": "Kochi",
                "phone": "+91 98471 23451",
                "hours": "11:00 AM - 9:00 PM",
                "lat": 9.9674,
                "lng": 76.2929,
                "status": "approved"
            },
            {
                "name": "Sole Revival Sneakers & Boots",
                "cat": shoes_cat,
                "desc": "Restored retro sneakers, leather boots, converse, and vintage street shoes curated for sustainable style lovers. [Synthetic Demo Store]",
                "address": "Indiranagar 100ft Road",
                "city": "Bangalore",
                "phone": "+91 98471 23452",
                "hours": "10:30 AM - 8:30 PM",
                "lat": 12.9716,
                "lng": 77.5946,
                "status": "approved"
            },
            {
                "name": "The Vintage Tote & Bag Co",
                "cat": bags_cat,
                "desc": "Handcrafted leather handbags, recycled canvas totes, retro backpacks, and pre-owned luxury purses. [Synthetic Demo Store]",
                "address": "Fort Kochi Art District",
                "city": "Kochi",
                "phone": "+91 98471 23453",
                "hours": "10:00 AM - 7:30 PM",
                "lat": 9.9658,
                "lng": 76.2441,
                "status": "approved"
            },
            {
                "name": "Heritage Brass & Antique Accents",
                "cat": acc_cat,
                "desc": "Vintage belt buckles, retro eyewear, brass pins, silver trinkets, and aesthetic thrifted accessories. [Synthetic Demo Store]",
                "address": "Kalarickal Bazaar",
                "city": "Kottayam",
                "phone": "+91 98471 23454",
                "hours": "10:00 AM - 7:00 PM",
                "lat": 9.5890,
                "lng": 76.5250,
                "status": "approved"
            },
            {
                "name": "Bangalore 90s Streetwear Archive",
                "cat": vintage_items_cat,
                "desc": "Nostalgic 90s pop culture apparel, varsity windbreakers, band tees, and collectible vintage streetwear. [Synthetic Demo Store]",
                "address": "Koramangala 5th Block",
                "city": "Bangalore",
                "phone": "+91 98471 23455",
                "hours": "11:00 AM - 9:30 PM",
                "lat": 12.9352,
                "lng": 77.6245,
                "status": "approved"
            },
            {
                "name": "Pending Secret Vintage Hub",
                "cat": vintage_cat,
                "desc": "Private unapproved boutique submitted for review. Must never appear in public recommendations. [Synthetic Demo Store]",
                "address": "Marine Drive",
                "city": "Kochi",
                "phone": "+91 98471 23456",
                "hours": "10:00 AM - 6:00 PM",
                "lat": 9.9816,
                "lng": 76.2750,
                "status": "pending"  # Crucial for testing: unapproved exclusion
            }
        ]

        store_id_map = {}
        for s in synthetic_stores_data:
            cursor.execute("""
                INSERT INTO stores (owner_id, category_id, store_name, description, address, city, contact_number, opening_hours, latitude, longitude, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                owner_id, s['cat'], s['name'], s['desc'], s['address'], s['city'],
                s['phone'], s['hours'], s['lat'], s['lng'], s['status']
            ))
            store_id_map[s['name']] = cursor.lastrowid

        print(f"Created {len(store_id_map)} synthetic stores ({len([s for s in synthetic_stores_data if s['status']=='approved'])} approved, 1 pending).")

        # 5. Create simulated users with preference profiles
        sim_users = [
            {
                "name": "[Synthetic] Priya Vintage Fan",
                "email": f"priya{SYNTHETIC_EMAIL_DOMAIN}",
                "role": "user",
                "pref_cats": f"{vintage_cat},{clothing_cat}",
                "pref_city": "Kottayam",
                "lat": 9.5916,
                "lng": 76.5222
            },
            {
                "name": "[Synthetic] Rahul Streetwear & Shoes",
                "email": f"rahul{SYNTHETIC_EMAIL_DOMAIN}",
                "role": "user",
                "pref_cats": f"{shoes_cat},{vintage_items_cat}",
                "pref_city": "Bangalore",
                "lat": 12.9716,
                "lng": 77.5946
            },
            {
                "name": "[Synthetic] Maya Kochi Circular Shopper",
                "email": f"maya{SYNTHETIC_EMAIL_DOMAIN}",
                "role": "user",
                "pref_cats": f"{clothing_cat},{bags_cat}",
                "pref_city": "Kochi",
                "lat": 9.9674,
                "lng": 76.2929
            },
            {
                "name": "[Synthetic] Ananya Accessories Lover",
                "email": f"ananya{SYNTHETIC_EMAIL_DOMAIN}",
                "role": "user",
                "pref_cats": f"{acc_cat},{vintage_cat}",
                "pref_city": "Kottayam",
                "lat": 9.5890,
                "lng": 76.5250
            },
            {
                "name": "[Synthetic] ColdStart New Shopper",
                "email": f"coldstart{SYNTHETIC_EMAIL_DOMAIN}",
                "role": "user",
                "pref_cats": f"{vintage_cat}",
                "pref_city": "Kochi",
                "lat": None,
                "lng": None
            }
        ]

        user_id_map = {}
        for u in sim_users:
            pw_hash = generate_password_hash("SimUser123!")
            cursor.execute("""
                INSERT INTO users (full_name, email, password, role, preferred_categories, preferred_city, preferred_lat, preferred_lng)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (u['name'], u['email'], pw_hash, u['role'], u['pref_cats'], u['pref_city'], u['lat'], u['lng']))
            user_id_map[u['name']] = cursor.lastrowid

        print(f"Created {len(user_id_map)} simulated users with distinct preferences.")

        # 6. Create realistic favorites and ratings for collaborative signals
        retro_vault_id = store_id_map["Retro Vault Vintage"]
        denim_co_id = store_id_map["Kochi Pre-Loved Denim & Co"]
        sneakers_id = store_id_map["Sole Revival Sneakers & Boots"]
        bags_id = store_id_map["The Vintage Tote & Bag Co"]
        acc_id = store_id_map["Heritage Brass & Antique Accents"]
        streetwear_id = store_id_map["Bangalore 90s Streetwear Archive"]

        priya_id = user_id_map["[Synthetic] Priya Vintage Fan"]
        rahul_id = user_id_map["[Synthetic] Rahul Streetwear & Shoes"]
        maya_id = user_id_map["[Synthetic] Maya Kochi Circular Shopper"]
        ananya_id = user_id_map["[Synthetic] Ananya Accessories Lover"]

        # Favorites
        fav_pairs = [
            (priya_id, retro_vault_id),
            (priya_id, denim_co_id),
            (rahul_id, sneakers_id),
            (rahul_id, streetwear_id),
            (maya_id, denim_co_id),
            (maya_id, bags_id),
            (ananya_id, acc_id),
            (ananya_id, retro_vault_id),
        ]
        for uid, sid in fav_pairs:
            cursor.execute("INSERT INTO favorites (user_id, store_id) VALUES (%s, %s)", (uid, sid))

        # Reviews with ratings
        reviews_data = [
            (retro_vault_id, priya_id, 5, "Incredible 90s jackets and authentic vintage items! [Synthetic Review]"),
            (denim_co_id, priya_id, 4, "Great selection of vintage trousers and denim jackets. [Synthetic Review]"),
            (sneakers_id, rahul_id, 5, "Best curated retro sneakers in South India! [Synthetic Review]"),
            (streetwear_id, rahul_id, 5, "Rare vintage windbreakers in mint condition. [Synthetic Review]"),
            (denim_co_id, maya_id, 5, "Super friendly staff and lovely pre-loved Levi's. [Synthetic Review]"),
            (bags_id, maya_id, 4, "High quality leather totes and vintage shoulder bags. [Synthetic Review]"),
            (acc_id, ananya_id, 5, "Found gorgeous brass accessories and retro earrings! [Synthetic Review]"),
            (retro_vault_id, ananya_id, 4, "Wonderful ambience and unique aesthetic pieces. [Synthetic Review]"),
        ]
        for sid, uid, rating, comment in reviews_data:
            cursor.execute("""
                INSERT INTO reviews (store_id, user_id, rating, comment)
                VALUES (%s, %s, %s, %s)
            """, (sid, uid, rating, comment))

        conn.commit()
        print(f"Created {len(fav_pairs)} synthetic favorites and {len(reviews_data)} synthetic reviews.")
        print("Synthetic seed script completed successfully!")

    finally:
        cursor.close()
        conn.close()

if __name__ == '__main__':
    seed_development_data()
