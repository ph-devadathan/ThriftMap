"""
ThriftMap Hybrid ML Recommendation Engine
==========================================
Algorithm Documentation:
This engine implements a Hybrid Recommendation System based on multi-signal similarity scoring
and adaptive fusion. It is NOT a black-box deep learning or trained neural network model;
it is a deterministic, explainable mathematical similarity engine designed for sparse, cold-start,
and production-ready circular fashion discovery.

Core Components:
1. Content-Based Similarity (S_content):
   - Computes matching between store categories and the user's explicit preference profile
     (preferred_categories) as well as implicit affinities from their interaction history.
   - Computes keyword/token overlap (Jaccard token similarity) over store descriptions, names,
     and user interaction keywords.
2. Collaborative Filtering (S_collab):
   - Constructs a sparse User-Item interaction matrix from implicit saves (favorites, weight=3.0)
     and explicit ratings (reviews, 1-5 scale).
   - Missing ratings/interactions are treated as unobserved/neutral, NEVER as negative ratings.
   - Computes vector cosine similarity between target user and peer users across co-interacted stores.
   - Aggregates peer preference scores for candidate stores.
3. Location Relevance (S_location):
   - Uses soft distance scoring via the Haversine formula based on store (latitude, longitude)
     and user preferred location.
   - Distance serves as a soft positive ranking factor: S_loc = 1 / (1 + d_km / 40.0).
   - Farther stores are NEVER filtered out; missing coordinates receive a neutral baseline (0.5).
4. Hybrid Dynamic Fusion (S_hybrid):
   - Combines S_content, S_collab, and S_location using adaptive weights.
   - Cold-start & sparse users automatically fall back to content + location signals (w_collab=0).
5. Authorization & Visibility Eligibility:
   - Strictly recommends ONLY stores with status = 'approved'.
   - Returns explainable recommendation badges (e.g., "Similar Shoppers Loved", "Category Match").
"""
import math
import re
from collections import defaultdict
import mysql.connector
from config import DB_HOST, DB_USER, DB_PASSWORD, DB_NAME

STOPWORDS = {
    'and', 'the', 'for', 'with', 'in', 'of', 'a', 'an', 'to', 'is', 'at', 'on', 'our', 'all',
    'from', 'by', 'this', 'that', 'shop', 'store', 'boutique', 'thrift', 'pre', 'loved', 'preloved'
}

def tokenize(text):
    """Normalize and extract meaningful keyword tokens from text."""
    if not text:
        return set()
    words = re.findall(r'[a-zA-Z0-9]+', text.lower())
    return {w for w in words if len(w) > 2 and w not in STOPWORDS}

def normalize_city(city_str):
    """Normalize city name for safe comparison, geocoding, and lookup."""
    if not city_str:
        return ""
    cleaned = re.sub(r'[^a-zA-Z0-9\s]', '', str(city_str)).strip().lower()
    return " ".join(cleaned.split())

def haversine_distance_km(lat1, lon1, lat2, lon2):
    """Calculate the great circle distance in kilometers between two points on Earth."""
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    except (ValueError, TypeError):
        return None

    # Earth radius in kilometers
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (math.sin(delta_phi / 2.0) ** 2 +
         math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c

class HybridRecommendationEngine:
    """Production-ready hybrid recommendation engine with content, collaborative, and location signals."""

    def __init__(self, db_config=None):
        self.db_config = db_config or {
            'host': DB_HOST,
            'user': DB_USER,
            'password': DB_PASSWORD,
            'database': DB_NAME
        }

    def _get_connection(self):
        return mysql.connector.connect(**self.db_config)

    def get_recommendations(self, user_id, limit=6, exclude_interacted=False):
        """
        Generate hybrid recommendations for the specified user.
        Returns: list of recommended store dicts with scores, match percentage, and explanation badges.
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor(dictionary=True)

            # 1. Fetch User Profile
            cursor.execute("""
                SELECT user_id, full_name, role, preferred_categories, preferred_city, preferred_lat, preferred_lng
                FROM users WHERE user_id = %s
            """, (user_id,))
            user_profile = cursor.fetchone()

            # Parse user preferred category IDs (strictly explicit preferences)
            explicit_pref_cat_ids = set()
            if user_profile and user_profile.get('preferred_categories'):
                for cid in str(user_profile['preferred_categories']).split(','):
                    cid = cid.strip()
                    if cid.isdigit():
                        explicit_pref_cat_ids.add(int(cid))

            user_city_raw = (user_profile.get('preferred_city') or '').strip() if user_profile else ''
            norm_user_city = normalize_city(user_city_raw)
            user_lat = user_profile.get('preferred_lat') if user_profile else None
            user_lng = user_profile.get('preferred_lng') if user_profile else None

            # 2. Fetch User Interactions (Favorites & Reviews)
            cursor.execute("SELECT store_id FROM favorites WHERE user_id = %s", (user_id,))
            user_favorited_store_ids = {r['store_id'] for r in cursor.fetchall()}

            cursor.execute("SELECT store_id, rating FROM reviews WHERE user_id = %s", (user_id,))
            user_reviews = {r['store_id']: r['rating'] for r in cursor.fetchall()}

            user_interacted_store_ids = user_favorited_store_ids.union(user_reviews.keys())

            # 3. Fetch All Approved Stores (Strict Authorization & Visibility)
            cursor.execute("""
                SELECT 
                    s.store_id, s.store_name, s.category_id, s.description, s.city, s.address,
                    s.latitude, s.longitude, s.image, s.status, s.created_at,
                    c.category_name,
                    COALESCE(AVG(r.rating), 0) AS avg_rating,
                    COUNT(r.review_id) AS review_count
                FROM stores s
                JOIN categories c ON s.category_id = c.category_id
                LEFT JOIN reviews r ON s.store_id = r.store_id
                WHERE s.status = 'approved'
                GROUP BY s.store_id, c.category_name
            """)
            approved_stores = cursor.fetchall()
            if not approved_stores:
                return []

            # Build city-to-coordinates lookup from approved stores to handle missing user lat/lng
            city_coords_map = {}
            for s in approved_stores:
                s_city_norm = normalize_city(s.get('city'))
                if s_city_norm and s.get('latitude') is not None and s.get('longitude') is not None:
                    if s_city_norm not in city_coords_map:
                        try:
                            city_coords_map[s_city_norm] = (float(s['latitude']), float(s['longitude']))
                        except (ValueError, TypeError):
                            pass

            if (user_lat is None or user_lng is None) and norm_user_city in city_coords_map:
                user_lat, user_lng = city_coords_map[norm_user_city]

            # 4. Fetch Full Interaction Matrix for Collaborative Filtering
            cursor.execute("SELECT user_id, store_id FROM favorites")
            all_favorites = cursor.fetchall()

            cursor.execute("SELECT user_id, store_id, rating FROM reviews WHERE rating IS NOT NULL")
            all_reviews = cursor.fetchall()

            # Build interaction matrix: user_matrix[uid][sid] = score in [1, 5]
            # Favorites given weight 3.5, reviews given their rating
            user_matrix = defaultdict(dict)
            for f in all_favorites:
                user_matrix[f['user_id']][f['store_id']] = max(user_matrix[f['user_id']].get(f['store_id'], 0), 3.5)

            for r in all_reviews:
                uid, sid, rt = r['user_id'], r['store_id'], r['rating']
                # If favorited and reviewed, combine for stronger signal
                existing = user_matrix[uid].get(sid, 0)
                user_matrix[uid][sid] = min(5.0, max(existing, float(rt)) + (0.5 if existing > 0 else 0.0))

            target_ratings = user_matrix.get(user_id, {})

            # 5. Extract Implicit User Taste from High Ratings & Favorites (WITHOUT mutating explicit preferences!)
            implicit_cat_ids = set()
            user_keywords = set()

            # Seed user keywords from explicit preferred category names
            for s in approved_stores:
                if s['category_id'] in explicit_pref_cat_ids:
                    user_keywords.update(tokenize(s.get('category_name', '')))

            for s in approved_stores:
                sid = s['store_id']
                is_fav = sid in user_favorited_store_ids
                rating_val = user_reviews.get(sid)
                # Count positive interactions (favorited or rated >= 4 stars)
                if is_fav or (rating_val is not None and rating_val >= 4):
                    implicit_cat_ids.add(s['category_id'])
                    user_keywords.update(tokenize(s['store_name']))
                    user_keywords.update(tokenize(s['description']))
                elif rating_val is not None and rating_val >= 3:
                    user_keywords.update(tokenize(s['store_name']))

            # 6. Compute Collaborative User Similarities (Cosine Similarity)
            peer_similarities = {}
            if target_ratings:
                target_norm = math.sqrt(sum(v * v for v in target_ratings.values()))
                if target_norm > 0:
                    for peer_id, peer_ratings in user_matrix.items():
                        if peer_id == user_id:
                            continue
                        common_stores = set(target_ratings.keys()).intersection(peer_ratings.keys())
                        if common_stores:
                            dot_product = sum(target_ratings[sid] * peer_ratings[sid] for sid in common_stores)
                            peer_norm = math.sqrt(sum(v * v for v in peer_ratings.values()))
                            if peer_norm > 0:
                                sim = dot_product / (target_norm * peer_norm)
                                if sim > 0:
                                    peer_similarities[peer_id] = sim

            # 7. Score Each Approved Candidate Store
            scored_candidates = []
            has_explicit_prefs = len(explicit_pref_cat_ids) > 0
            has_location_pref = bool(norm_user_city or (user_lat is not None and user_lng is not None))
            has_collaborative_signal = len(peer_similarities) > 0 and len(target_ratings) > 0

            # Dynamic weighting:
            # - Explicit categories and preferred city both receive strong priority.
            # - When both explicit category and location preferences are given, they jointly drive the primary ranking.
            # - Collaborative filtering provides personalized affinity, but is bounded so it cannot
            #   overwhelm matching category and preferred-city signals without justification.
            if has_explicit_prefs and has_location_pref:
                if has_collaborative_signal:
                    w_content = 0.50
                    w_loc = 0.35
                    w_collab = 0.15
                else:
                    w_content = 0.65
                    w_loc = 0.35
                    w_collab = 0.00
            elif has_explicit_prefs:
                if has_collaborative_signal:
                    w_content = 0.65
                    w_loc = 0.10
                    w_collab = 0.25
                else:
                    w_content = 0.85
                    w_loc = 0.15
                    w_collab = 0.00
            elif has_location_pref:
                if has_collaborative_signal:
                    w_content = 0.35
                    w_loc = 0.35
                    w_collab = 0.30
                else:
                    w_content = 0.60
                    w_loc = 0.40
                    w_collab = 0.00
            else:
                if has_collaborative_signal:
                    w_content = 0.45
                    w_collab = 0.40
                    w_loc = 0.15
                else:
                    w_content = 0.70
                    w_collab = 0.00
                    w_loc = 0.30

            for store in approved_stores:
                sid = store['store_id']

                # Optional: exclude stores already interacted with if caller requested
                if exclude_interacted and sid in user_interacted_store_ids:
                    continue

                reasons = []

                # A. Content-Based Score
                is_explicit_match = store['category_id'] in explicit_pref_cat_ids
                is_implicit_match = store['category_id'] in implicit_cat_ids

                if has_explicit_prefs:
                    if is_explicit_match:
                        cat_score = 1.0  # Top score for explicit preference
                    elif is_implicit_match:
                        cat_score = 0.38  # Positive past interaction, but distinctly lower than explicit choices
                    else:
                        cat_score = 0.12  # Unselected category: ranks lower, NOT excluded
                else:
                    if is_implicit_match:
                        cat_score = 0.85
                    else:
                        cat_score = 0.35

                # Textual keyword overlap
                store_tokens = tokenize(store['store_name']).union(tokenize(store['description']))
                if user_keywords and store_tokens:
                    token_overlap = len(user_keywords.intersection(store_tokens)) / max(1, len(user_keywords.union(store_tokens)))
                    text_score = min(1.0, token_overlap * 2.5)
                else:
                    text_score = 0.10

                content_score = (0.75 * cat_score) + (0.25 * text_score)

                # B. Collaborative Score with Bayesian Shrinkage
                # Baseline for unobserved/unrated stores is neutral (0.50), never penalized to 0.0
                collab_score = 0.50
                if has_collaborative_signal:
                    collab_weighted_sum = 0.0
                    collab_sim_sum = 0.0
                    for peer_id, sim in peer_similarities.items():
                        if sid in user_matrix[peer_id]:
                            rating_val = user_matrix[peer_id][sid]
                            collab_weighted_sum += sim * (rating_val / 5.0)
                            collab_sim_sum += sim

                    m = 0.8  # Pseudo-interaction weight for shrinkage to neutral baseline
                    collab_score = min(1.0, max(0.0, (collab_weighted_sum + (m * 0.50)) / (collab_sim_sum + m)))

                # C. Location Score (Soft continuous ranking - NEVER hard filters)
                loc_score = 0.50  # Neutral baseline
                store_lat = store.get('latitude')
                store_lng = store.get('longitude')
                store_city_norm = normalize_city(store.get('city'))

                distance_km = None
                is_nearby = False
                if user_lat is not None and user_lng is not None and store_lat is not None and store_lng is not None:
                    distance_km = haversine_distance_km(user_lat, user_lng, store_lat, store_lng)
                    if distance_km is not None:
                        # Soft decay: closer gets boost, distant stores remain reachable (>= 0.20)
                        loc_score = 0.20 + (0.80 / (1.0 + (distance_km / 40.0)))
                        if distance_km <= 25.0:
                            is_nearby = True
                elif norm_user_city and store_city_norm:
                    if norm_user_city == store_city_norm:
                        loc_score = 1.00
                        is_nearby = True
                    else:
                        loc_score = 0.28

                # D. Hybrid Aggregation
                hybrid_score = (w_content * content_score) + (w_collab * collab_score) + (w_loc * loc_score)

                # Quality prior: add small boost for high-rated stores
                avg_r = float(store.get('avg_rating') or 0.0)
                if avg_r >= 4.0:
                    hybrid_score += 0.04

                # E. Accurate, Context-Aware Reason Explanations
                if is_explicit_match:
                    reasons.append(f"Matches your taste in {store['category_name']}")
                elif is_implicit_match:
                    reasons.append(f"Based on your interest in {store['category_name']}")

                if is_nearby:
                    if distance_km is not None and distance_km <= 25.0:
                        if distance_km > 0.1:
                            reasons.append(f"Nearby boutique ({round(distance_km, 1)} km away)")
                        else:
                            reasons.append(f"Located in your preferred city ({store['city']})")
                    else:
                        reasons.append(f"Located in your preferred city ({store['city']})")

                if has_collaborative_signal and collab_score >= 0.60:
                    reasons.append("Shoppers with similar vintage taste loved this")

                if avg_r >= 4.5:
                    reasons.append(f"Highly rated boutique ({avg_r:.1f} stars)")

                if not reasons:
                    reasons.append(f"Curated {store['category_name']} collection")

                # Match percentage clamped to 50% - 98% for realistic UX
                match_pct = int(min(98, max(52, round(hybrid_score * 100))))

                candidate = dict(store)
                candidate['match_score'] = round(hybrid_score, 4)
                candidate['match_pct'] = match_pct
                candidate['primary_reason'] = reasons[0]
                candidate['all_reasons'] = reasons
                candidate['distance_km'] = round(distance_km, 1) if distance_km is not None else None
                candidate['is_favorited'] = sid in user_favorited_store_ids

                scored_candidates.append(candidate)

            # Sort by hybrid score descending, then by avg rating, then newest
            scored_candidates.sort(
                key=lambda x: (x['match_score'], float(x.get('avg_rating') or 0), x['store_id']),
                reverse=True
            )

            return scored_candidates[:limit]

        except Exception as e:
            print(f"Error generating recommendations: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

    def update_user_preferences(self, user_id, preferred_categories=None, preferred_city=None, lat=None, lng=None):
        """Update explicit user preference profile in the development database."""
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            updates = []
            params = []

            if preferred_categories is not None:
                if isinstance(preferred_categories, (list, set, tuple)):
                    cat_str = ','.join(str(c).strip() for c in preferred_categories if str(c).strip().isdigit())
                else:
                    cat_str = str(preferred_categories).strip()
                updates.append("preferred_categories = %s")
                params.append(cat_str)

            if preferred_city is not None:
                updates.append("preferred_city = %s")
                params.append(preferred_city.strip())

            if lat is not None and lng is not None:
                updates.append("preferred_lat = %s, preferred_lng = %s")
                params.extend([float(lat), float(lng)])

            if not updates:
                return False

            params.append(user_id)
            query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s"
            cursor.execute(query, tuple(params))
            conn.commit()
            return cursor.rowcount >= 0
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()
